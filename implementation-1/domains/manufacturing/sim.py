"""Reference simulator: the stock and dispatch policy written in every document's front matter.

One plant, one scope (a run of consecutive days). Per day, in this order:
  1. production arrives: the day's production of each product is added to its stock;
  2. orders join the queue: the day's sales order of each product (if > 0) becomes one order;
  3. dispatch: open orders are served oldest first (ties: smaller outstanding quantity first, then product
     code); each ships as many whole units as the product's stock and the plant's remaining dispatch capacity
     (kg) allow; the rest stays open (backordered);
  4. records: produced, ordered, shipped, backordered (open units at end of day) and end-of-day stock.

Deterministic: integer units and integer grams, no randomness, sorted iteration only.

Interventions (applied to the recorded inputs before the run; all others held as recorded):
  {"kind": "remove_order", "product": p, "day": d}                  the order for p placed on day d is not placed
  {"kind": "set_production", "product": p, "day": d, "value": v}    production of p on day d is v units
  {"kind": "delay_production", "product": p, "day": d, "by": k}     production of p on day d arrives on day d+k
  {"kind": "scale_capacity", "factor": f, "from_day": d}            capacity x f on every day >= d
Mechanism switches used only for the but-for test of explanatory questions:
  {"kind": "add_stock", "product": p, "day": d, "units": n}          n extra units of p arrive on day d
  {"kind": "unlimited_capacity", "day": d}                          capacity is not a limit on day d
  {"kind": "free_capacity", "product": p, "day": d}                 p's shipments on day d use no capacity
  {"kind": "skip_older", "product": p, "day": d}                    p's orders placed before d are not served on d
"""
from __future__ import annotations

from dataclasses import dataclass, field

INPUT_KINDS = ("remove_order", "set_production", "delay_production", "scale_capacity")
MECHANISM_KINDS = ("add_stock", "unlimited_capacity", "free_capacity", "skip_older")


@dataclass
class Scope:
    plant: str
    period: int
    first_day: int
    last_day: int                     # last day shown in the ledger
    horizon_day: int                  # last order-book day (last_day + 7)
    products: list[str]
    grams_per_unit: dict[str, int]
    opening_stock: dict[str, int]
    capacity_kg: int
    production: dict[int, dict[str, int]]   # first_day..horizon_day
    orders: dict[int, dict[str, int]]

    @property
    def title(self) -> str:
        return f"Plant {self.plant}, Period {self.period:02d}"

    @property
    def days(self) -> list[int]:
        return list(range(self.first_day, self.last_day + 1))

    @property
    def future_days(self) -> list[int]:
        return list(range(self.last_day + 1, self.horizon_day + 1))


@dataclass
class Order:
    product: str
    day: int
    qty: int
    outstanding: int
    shipped: dict[int, int] = field(default_factory=dict)

    @property
    def oid(self) -> str:
        return f"{self.product}@{self.day}"


@dataclass
class SimResult:
    rows: dict[tuple[int, str], dict]           # (day, product) -> ledger row
    orders: dict[str, Order]                    # oid -> order
    cap_g: dict[int, float]                     # day -> capacity in grams (inf when unlimited)
    used_g: dict[int, int]                      # day -> grams dispatched (counted toward capacity)
    cap_reached: dict[int, bool]                # day -> some order was cut by capacity
    queue_order: dict[int, list[str]]           # day -> oids in service order

    # ---- derived outcome predicates (used by question generation and validation) ----
    def stock(self, d: int, p: str) -> int:
        return self.rows[(d, p)]["stock"]

    def backlog(self, d: int, p: str) -> int:
        return self.rows[(d, p)]["backordered"]

    def stocked_out(self, d: int, p: str) -> bool:
        """End of day d: no stock on hand while units are still backordered."""
        r = self.rows[(d, p)]
        return r["stock"] == 0 and r["backordered"] > 0

    def order_short_on_day(self, p: str, d: int) -> bool:
        o = self.orders.get(f"{p}@{d}")
        return o is not None and o.shipped.get(d, 0) < o.qty

    def order_full_on_day(self, p: str, d: int) -> bool:
        o = self.orders.get(f"{p}@{d}")
        return o is not None and o.shipped.get(d, 0) == o.qty


def apply_inputs(scope: Scope, interventions: list[dict]):
    prod = {d: dict(v) for d, v in scope.production.items()}
    orders = {d: dict(v) for d, v in scope.orders.items()}
    cap_factor: dict[int, float] = {}
    for iv in interventions:
        k = iv["kind"]
        if k == "remove_order":
            assert orders[iv["day"]][iv["product"]] > 0, iv
            orders[iv["day"]][iv["product"]] = 0
        elif k == "set_production":
            prod[iv["day"]][iv["product"]] = int(iv["value"])
        elif k == "delay_production":
            q = prod[iv["day"]][iv["product"]]
            prod[iv["day"]][iv["product"]] = 0
            if iv["day"] + iv["by"] in prod:          # otherwise it arrives after the run
                prod[iv["day"] + iv["by"]][iv["product"]] += q
        elif k == "add_stock":
            prod[iv["day"]][iv["product"]] += int(iv["units"])
        elif k == "scale_capacity":
            for d in prod:
                if d >= iv["from_day"]:
                    cap_factor[d] = cap_factor.get(d, 1.0) * iv["factor"]
        elif k not in MECHANISM_KINDS:
            raise ValueError(f"unknown intervention {iv}")
    return prod, orders, cap_factor


def simulate(scope: Scope, interventions: list[dict] | None = None, through: int | None = None) -> SimResult:
    """Run the policy from the scope's first day through `through` (default: the order-book horizon)."""
    interventions = interventions or []
    prod, orders_in, cap_factor = apply_inputs(scope, interventions)
    unlimited = {iv["day"] for iv in interventions if iv["kind"] == "unlimited_capacity"}
    free = {(iv["day"], iv["product"]) for iv in interventions if iv["kind"] == "free_capacity"}
    skip = {(iv["day"], iv["product"]) for iv in interventions if iv["kind"] == "skip_older"}
    g = scope.grams_per_unit
    stock = dict(scope.opening_stock)
    open_orders: list[Order] = []
    res = SimResult({}, {}, {}, {}, {}, {})
    last = scope.horizon_day if through is None else through
    for d in range(scope.first_day, last + 1):
        for p in scope.products:                                    # 1. production arrives
            stock[p] += prod[d][p]
        for p in scope.products:                                    # 2. orders join the queue
            if orders_in[d][p] > 0:
                o = Order(p, d, orders_in[d][p], orders_in[d][p])
                open_orders.append(o)
                res.orders[o.oid] = o
        cap = float("inf") if d in unlimited else round(scope.capacity_kg * 1000 * cap_factor.get(d, 1.0))
        left, used, reached = cap, 0, False
        shipped = {p: 0 for p in scope.products}
        open_orders.sort(key=lambda o: (o.day, o.outstanding, o.product))
        res.queue_order[d] = [o.oid for o in open_orders]
        for o in open_orders:                                       # 3. dispatch
            if (d, o.product) in skip and o.day < d:
                continue
            want = min(o.outstanding, stock[o.product])
            if (d, o.product) in free or left == float("inf"):
                n = want
            else:
                n = min(want, int(left // g[o.product]))
                if n < want:
                    reached = True
                left -= n * g[o.product]
                used += n * g[o.product]
            if n:
                o.outstanding -= n
                o.shipped[d] = n
                stock[o.product] -= n
                shipped[o.product] += n
        open_orders = [o for o in open_orders if o.outstanding > 0]
        res.cap_g[d], res.used_g[d], res.cap_reached[d] = cap, used, reached
        backlog = {p: 0 for p in scope.products}
        for o in open_orders:
            backlog[o.product] += o.outstanding
        for p in scope.products:                                    # 4. records
            res.rows[(d, p)] = {"day": d, "product": p, "produced": prod[d][p], "ordered": orders_in[d][p],
                                "shipped": shipped[p], "backordered": backlog[p], "stock": stock[p]}
    return res


def events(scope: Scope, res: SimResult, days: list[int] | None = None) -> list[tuple[int, int, str, str]]:
    """Time-ordered event list (day, kind order, product, text) as written in the document's Events section."""
    days = days or scope.days
    out = []
    for d in days:
        if res.cap_reached[d]:
            out.append((d, 0, "", f"dispatch capacity reached ({res.used_g[d] / 1000:.2f} of "
                                  f"{scope.capacity_kg} kg dispatched)"))
        for p in scope.products:
            prev_out = d > scope.first_day and res.stocked_out(d - 1, p)
            if res.stocked_out(d, p) and not prev_out:
                out.append((d, 1, p, f"{p} runs out of stock ({res.backlog(d, p)} units backordered)"))
            o = res.orders.get(f"{p}@{d}")
            if o is not None and o.shipped.get(d, 0) == 0:
                out.append((d, 2, p, f"order for {p} placed on day {d} fully backordered "
                                     f"({o.qty} units, none shipped)"))
            prev_bl = res.backlog(d - 1, p) if d > scope.first_day else 0
            if prev_bl > 0 and res.backlog(d, p) == 0:
                out.append((d, 3, p, f"backlog of {p} cleared"))
    out.sort(key=lambda e: (e[0], e[1], e[2]))
    return out
