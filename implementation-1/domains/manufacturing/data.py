"""Load the real SupplyGraph records (production, sales orders, plant/storage assignment, unit weights).

Raw data: data/domains/raw/supplygraph/Raw Dataset/Homogenoeus/ (LGPL-2.1, Wasi et al., arXiv 2401.15299).
Only the recorded Production and Sales Order series are used, in units; the weight files give kg per unit.
The Delivery and Factory Issue series are not used (they follow the company's own, unknown policy).

Decisions (also in docs/domains/manufacturing.md):
- The node list contains the code POP001L12P twice (NodeIndex 12 and 20); the temporal files call the second
  column `POP001L12P.1`. The two columns are different series (they agree on only 47 of 221 production days,
  mostly days where both are 0) with the same group and weight, so they are two distinct nodes sharing a code.
  We keep both, named POP001L12P-A (index 12) and POP001L12P-B (index 20).
- Weights are recorded in tonnes; kg per unit = 1000 * weight / units. It is constant per product (checked).
- Quantities are rounded half-up to whole units (a few order cells carry float noise, e.g. 342.0000000000001).
- The records are company-wide per product, while the node file lists every plant that stores a product. Each
  product is assigned to one dispatch plant: of the four plants DISPATCH_PLANTS (the two plants with the most
  storage records in each plant-code series, 21xx and 19xx; 1912 and 1915 tie and the lower code is taken), the
  one where the product has the most storage records (ties: lower plant code). Products with no storage record
  at any of the four plants, or with no recorded production in the whole series, are left out.
"""
from __future__ import annotations

import csv
import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "domains" / "raw" / "supplygraph" / "Raw Dataset" / "Homogenoeus"
DISPATCH_PLANTS = ("1912", "1914", "2103", "2114")
DUP_CODE = "POP001L12P"
DUP_NAMES = (DUP_CODE + "-A", DUP_CODE + "-B")
FIRST_DATE = date(2023, 1, 1)


@dataclass
class Product:
    code: str
    group: str
    subgroup: str
    plant: str
    storage: str
    kg_per_unit: float
    grams_per_unit: int          # exact integer weight used by the simulator


@dataclass
class Records:
    """Day d (1-based, day 1 = 2023-01-01) -> {product: units}."""
    n_days: int
    products: dict[str, Product]
    production: dict[int, dict[str, int]]
    orders: dict[int, dict[str, int]]
    weight_check: dict[str, float] = field(default_factory=dict)   # max relative spread of kg/unit
    dropped: dict[str, str] = field(default_factory=dict)          # product -> reason

    def date_of(self, day: int) -> str:
        return (FIRST_DATE + timedelta(days=day - 1)).isoformat()

    def plant_products(self, plant: str) -> list[str]:
        return sorted(p for p, v in self.products.items() if v.plant == plant)


def _round(x: float) -> int:
    return int(math.floor(x + 0.5))


def _read_series(path: Path) -> tuple[list[str], list[list[float]]]:
    with path.open(newline="") as f:
        rows = list(csv.reader(f))
    header = rows[0][1:]
    names = [DUP_NAMES[1] if h == DUP_CODE + ".1" else DUP_NAMES[0] if h == DUP_CODE else h for h in header]
    return names, [[float(x) for x in r[1:]] for r in rows[1:]]


def load(raw: Path = RAW) -> Records:
    td = raw / "Temporal Data"
    names, prod_u = _read_series(td / "Unit" / "Production .csv")
    n2, ord_u = _read_series(td / "Unit" / "Sales Order.csv")
    n3, prod_w = _read_series(td / "Weight" / "Production .csv")
    n4, ord_w = _read_series(td / "Weight" / "Sales Order .csv")
    assert names == n2 == n3 == n4 and len(prod_u) == len(ord_u) == len(prod_w) == len(ord_w)
    n_days = len(prod_u)

    # group / sub-group (the duplicated code has one row per occurrence; both are P / POP)
    groups = {}
    with (raw / "Nodes" / "Node Types (Product Group and Subgroup).csv").open(newline="") as f:
        for r in csv.DictReader(f):
            groups[r["Node"]] = (r["Group"], r["Sub-Group"])

    # storage records per (code, plant) and the storage location used there
    rec_count: Counter = Counter()
    storage: dict[tuple[str, str], Counter] = {}
    with (raw / "Nodes" / "Nodes Type (Plant & Storage).csv").open(newline="") as f:
        for r in csv.DictReader(f):
            key = (r["Node"], r["Plant"])
            rec_count[key] += 1
            if r["Storage Location"]:
                storage.setdefault(key, Counter())[str(int(float(r["Storage Location"])))] += 1

    products, dropped, wcheck = {}, {}, {}
    for j, name in enumerate(names):
        code = DUP_CODE if name in DUP_NAMES else name
        if sum(row[j] for row in prod_u) <= 0:
            dropped[name] = "no recorded production in the whole series"
            continue
        plant = max(DISPATCH_PLANTS, key=lambda p: (rec_count[(code, p)], -int(p)))
        if rec_count[(code, plant)] == 0:
            dropped[name] = "no storage record at any of the four dispatch plants"
            continue
        ratios = [1000 * w[j] / u[j] for u, w in ((prod_u[i], prod_w[i]) for i in range(n_days)) if u[j] > 0]
        ratios += [1000 * w[j] / u[j] for u, w in ((ord_u[i], ord_w[i]) for i in range(n_days)) if u[j] > 0]
        ratios.sort()
        kg = ratios[len(ratios) // 2]
        wcheck[name] = (ratios[-1] - ratios[0]) / kg
        grams = _round(kg * 1000)
        g, sg = groups[code]
        products[name] = Product(name, g, sg, plant, storage[(code, plant)].most_common(1)[0][0],
                                 grams / 1000, grams)

    production = {d + 1: {p: _round(prod_u[d][names.index(p)]) for p in products} for d in range(n_days)}
    orders = {d + 1: {p: _round(ord_u[d][names.index(p)]) for p in products} for d in range(n_days)}
    return Records(n_days, products, production, orders, wcheck, dropped)
