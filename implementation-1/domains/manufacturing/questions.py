"""Question generator for the four types. Every gold label comes from the reference simulator (sim.py).

descriptive     open-ended lookups/counts in the scope's ledger and events
explanatory     MC, multi-correct: causes of an order's shortfall; a cause is correct iff the but-for run
                (that cause removed or neutralised, everything else as recorded) ships the order in full
predictive      MC: what happens in the 7 order-book days after the period (continued run, real future inputs)
counterfactual  MC, multi-correct: re-run the period with one change (remove an order / zero a production /
                delay a production by 3 days / capacity -20% from a day), everything else as recorded
"""
from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass, field

from .sim import Scope, SimResult, simulate

DESC_TEMPLATES = ("stock", "backordered", "shipped", "first_stockout", "capacity_days", "stockout_products",
                  "max_backlog")
PRED_TEMPLATES = ("will_happen", "will_happen", "first_stockout")
CF_KINDS = ("remove_order", "zero_production", "delay_production", "capacity")
N_CHOICES = 4
DELAY_DAYS = 3
CAP_FACTOR = 0.8
BIG = 10 ** 7

# running tallies across one build, used to keep answers from following an exploitable pattern:
# explanatory (cause kind, truth) pairs, and descriptive max_backlog answers
_EXPL_SEEN: Counter = Counter()
_ANSWER_USED: Counter = Counter()


def reset_balance() -> None:
    _EXPL_SEEN.clear()
    _ANSWER_USED.clear()


@dataclass
class Question:
    scope: str
    qtype: str
    subtype: str
    question: str
    choices: list[str] = field(default_factory=list)
    gold_answer: str | None = None
    gold_choices: list[bool] = field(default_factory=list)
    meta: dict = field(default_factory=dict)       # intervention, per-choice baselines (for validation only)


# ---------------------------------------------------------------- statements about a run
def _stmt_text(kind: str, a: dict, mood: str) -> str:
    w = "will" if mood == "pred" else "would"
    if kind == "backlog":
        return f"{a['p']} {w} have backordered units at the end of day {a['e']}"
    if kind == "stockout":
        return f"{a['p']} {w} run out of stock on at least one day from day {a['a']} to day {a['b']}"
    if kind == "capacity":
        return f"the dispatch capacity {w} be reached on day {a['e']}"
    if kind == "full":
        return f"the order for {a['p']} placed on day {a['e']} {w} ship in full that day"
    if kind == "stock_higher":
        return f"the stock of {a['p']} at the end of day {a['e']} would be higher than the recorded {a['n']} units"
    if kind == "stock_lower":
        return f"the stock of {a['p']} at the end of day {a['e']} would be lower than the recorded {a['n']} units"
    raise ValueError(kind)


def _stmt_truth(kind: str, a: dict, r: SimResult, f: SimResult | None = None) -> bool:
    if kind == "backlog":
        return r.backlog(a["e"], a["p"]) > 0
    if kind == "stockout":
        return any(r.stocked_out(d, a["p"]) for d in range(a["a"], a["b"] + 1))
    if kind == "capacity":
        return r.cap_reached[a["e"]]
    if kind == "full":
        return r.order_full_on_day(a["p"], a["e"])
    if kind == "stock_higher":
        return r.stock(a["e"], a["p"]) > a["n"]
    if kind == "stock_lower":
        return r.stock(a["e"], a["p"]) < a["n"]
    raise ValueError(kind)


def _statements(s: Scope, f: SimResult, r: SimResult, days: list[int], mood: str, a0: int, b0: int,
                baseline) -> list[dict]:
    """All candidate statements over `days`, with truth in run r and a baseline truth (what a reader who
    copies the record / assumes persistence would answer)."""
    out = []
    for p in s.products:
        out.append(("stockout", {"p": p, "a": a0, "b": b0}))
        for e in days:
            out.append(("backlog", {"p": p, "e": e}))
            if s.orders[e][p] > 0 and f"{p}@{e}" in r.orders:
                out.append(("full", {"p": p, "e": e}))
            if mood == "cf":
                n = f.stock(e, p)
                out.append(("stock_higher", {"p": p, "e": e, "n": n}))
                if n > 0:
                    out.append(("stock_lower", {"p": p, "e": e, "n": n}))
    out += [("capacity", {"e": e}) for e in days]
    res = []
    for kind, a in out:
        t = _stmt_truth(kind, a, r)
        b = baseline(kind, a)
        res.append({"kind": kind, "args": a, "text": _stmt_text(kind, a, mood), "truth": t, "baseline": b,
                    "changed": t != b, "product": a.get("p", "")})
    return res


def _pick(cands: list[dict], rng: random.Random, min_changed: int, want_changed: int,
          focus: str | None = None, shuffle: bool = True) -> list[dict] | None:
    """N_CHOICES statements: a random number of true ones (1-3), at least `min_changed` whose truth differs
    from the baseline, at most 2 of a kind, and when `focus` is set at least one about that product."""
    k_true = rng.choice((1, 2, 2, 3))
    if shuffle:
        rng.shuffle(cands)
    chosen: list[dict] = []

    def fits(c, strict):
        if c in chosen or any(x["text"] == c["text"] for x in chosen):
            return False
        if sum(x["kind"] == c["kind"] for x in chosen) >= 2:
            return False
        if strict:
            t = sum(x["truth"] for x in chosen)
            if c["truth"] and t >= k_true:
                return False
            if not c["truth"] and len(chosen) - t >= N_CHOICES - k_true:
                return False
        return True

    order = []
    if focus:
        order.append([c for c in cands if c["product"] == focus and c["changed"]][:1] or
                     [c for c in cands if c["product"] == focus][:1])
    order.append([c for c in cands if c["changed"]])
    order.append(cands)
    for strict in (True, False):
        for i, group in enumerate(order):
            for c in group:
                if len(chosen) >= N_CHOICES:
                    break
                if group is order[-2] and sum(x["changed"] for x in chosen) >= want_changed:
                    break
                if fits(c, strict):
                    chosen.append(c)
                    if focus and i == 0:
                        break
    if len(chosen) < N_CHOICES or sum(x["changed"] for x in chosen) < min_changed:
        return None
    if all(x["truth"] for x in chosen) or not any(x["truth"] for x in chosen):
        return None
    rng.shuffle(chosen)
    return chosen


# ---------------------------------------------------------------- descriptive
def descriptive(s: Scope, f: SimResult, template: str, rng: random.Random) -> Question | None:
    T, days, prods = s.title, s.days, s.products
    pairs = [(d, p) for d in days for p in prods]
    if template in ("stock", "backordered", "shipped"):
        key = {"stock": "stock", "backordered": "backordered", "shipped": "shipped"}[template]
        nonzero = [x for x in pairs if f.rows[x][key] > 0]
        zero = [x for x in pairs if f.rows[x][key] == 0 and (f.rows[x]["ordered"] or f.rows[x]["backordered"]
                                                           or f.rows[x]["stock"])]
        pool = nonzero if (rng.random() < (0.75 if template == "backordered" else 0.85) or not zero) else zero
        if not pool:
            return None
        d, p = rng.choice(pool)
        ans = str(f.rows[(d, p)][key])
        q = {"stock": f"In {T}, how many units of {p} were in stock at the end of day {d}?",
             "backordered": f"In {T}, how many units of {p} were backordered at the end of day {d}?",
             "shipped": f"In {T}, how many units of {p} were shipped on day {d}?"}[template]
        return Question(T, "descriptive", template, q, gold_answer=ans)
    if template == "first_stockout":
        firsts = {p: next((d for d in days if f.stocked_out(d, p)), None) for p in prods}
        cand = [p for p, d in firsts.items() if d is not None]
        if not cand:
            return None
        p = rng.choice(cand)
        return Question(T, "descriptive", template,
                        f"In {T}, on which day did {p} first run out of stock? Answer with the day number.",
                        gold_answer=str(firsts[p]))
    if template == "capacity_days":
        return Question(T, "descriptive", template, f"In {T}, on how many days was the dispatch capacity reached?",
                        gold_answer=str(sum(f.cap_reached[d] for d in days)))
    if template == "stockout_products":
        n = sum(any(f.stocked_out(d, p) for d in days) for p in prods)
        return Question(T, "descriptive", template, f"In {T}, how many products ran out of stock at least once?",
                        gold_answer=str(n))
    if template == "max_backlog":
        cand = []
        for d in days:
            bl = sorted(((f.backlog(d, p), p) for p in prods), reverse=True)
            if bl[0][0] > 0 and (len(bl) == 1 or bl[0][0] > bl[1][0]):
                cand.append((d, bl[0][1]))
        if not cand:
            return None
        least = min(_ANSWER_USED[p] for _, p in cand)
        d, p = rng.choice([x for x in cand if _ANSWER_USED[x[1]] == least])
        _ANSWER_USED[p] += 1
        return Question(T, "descriptive", template,
                        f"In {T}, which product had the most units backordered at the end of day {d}? "
                        "Answer with the product code.", gold_answer=p.lower())
    raise ValueError(template)


# ---------------------------------------------------------------- explanatory
def _shortfall_fixed(s: Scope, p: str, d: int, ivs: list[dict]) -> bool:
    return simulate(s, ivs, through=d).order_full_on_day(p, d)


def explanatory(s: Scope, f: SimResult, rng: random.Random) -> Question | None:
    T = s.title
    targets = [(p, d) for d in s.days for p in s.products if f.order_short_on_day(p, d)]
    rng.shuffle(targets)
    best = None
    for p, d in targets[:15]:
        o = f.orders[f"{p}@{d}"]
        pool = [(f"there was not enough {p} in stock on day {d}", [{"kind": "add_stock", "product": p, "day": d,
                                                                    "units": BIG}], "stock"),
                (f"the dispatch capacity was reached on day {d}", [{"kind": "unlimited_capacity", "day": d}],
                 "capacity")]
        for q in s.products:
            if q != p and (f.rows[(d, q)]["shipped"] > 0 or f.rows[(d, q)]["backordered"] > 0):
                pool.append((f"orders for {q} used dispatch capacity on day {d}",
                             [{"kind": "free_capacity", "product": q, "day": d}], "other_product"))
        older = any(x.product == p and x.day < d and x.qty > sum(n for dd, n in x.shipped.items() if dd < d)
                    for x in f.orders.values())
        if older or rng.random() < 0.3:
            pool.append((f"older backorders of {p} were served before this order on day {d}",
                         [{"kind": "skip_older", "product": p, "day": d}], "older_backorder"))
        for d2 in (d - 1, d):
            if d2 >= s.first_day and s.production[d2][p] < s.orders[d2][p]:
                pool.append((f"the production of {p} on day {d2} ({s.production[d2][p]} units) was lower than "
                             f"its order that day ({s.orders[d2][p]} units)",
                             [{"kind": "set_production", "product": p, "day": d2, "value": s.orders[d2][p]}],
                             "low_production"))
        cands = [{"text": t, "truth": _shortfall_fixed(s, p, d, iv), "kind": k, "iv": iv, "changed": True,
                  "product": ""} for t, iv, k in pool]
        if not any(c["truth"] for c in cands) or all(c["truth"] for c in cands):
            continue
        # put first the (cause kind, truth) pairs that move each kind's running true share toward one half
        def helps(c):
            t, f_ = _EXPL_SEEN[(c["kind"], True)], _EXPL_SEEN[(c["kind"], False)]
            return (c["truth"] and t <= f_) or (not c["truth"] and f_ < t)
        cands.sort(key=lambda c: (not helps(c), rng.random()))
        chosen = _pick(cands, rng, 0, 0, shuffle=False)
        if chosen is None:
            continue
        score = sum(helps(c) for c in chosen)
        if best is not None and score <= best[0]:
            continue
        best = (score, Question(T, "explanatory", "shortfall_cause",
                        f"In {T}, the order for {p} placed on day {d} ({o.qty} units) did not ship in full on day "
                        f"{d}. Which of the following are responsible for that? A condition is responsible if, "
                        f"without it and with everything else as recorded, the order would have shipped in full "
                        f"on day {d}.",
                        choices=[c["text"] for c in chosen], gold_choices=[c["truth"] for c in chosen],
                        meta={"target": [p, d], "kinds": [c["kind"] for c in chosen],
                              "interventions": [c["iv"] for c in chosen]}))
    if best is None:
        return None
    q = best[1]
    for k, g in zip(q.meta["kinds"], q.gold_choices):
        _EXPL_SEEN[(k, g)] += 1
    return q


# ---------------------------------------------------------------- predictive
def predictive(s: Scope, f: SimResult, template: str, rng: random.Random) -> Question | None:
    T, L, H = s.title, s.last_day, s.horizon_day
    fut = s.future_days
    lead = (f"In {T}, using the order book for days {L + 1} to {H} and the same policy (continuing from the "
            f"state at the end of day {L}), ")
    if template == "will_happen":
        def persist(kind, a):       # a reader who assumes the end-of-period state persists
            if kind == "backlog":
                return f.backlog(L, a["p"]) > 0
            if kind == "stockout":
                return f.stocked_out(L, a["p"])
            if kind == "capacity":
                return f.cap_reached[L]
            if kind == "full":
                return f.backlog(L, a["p"]) == 0
            raise ValueError(kind)
        cands = _statements(s, f, f, fut, "pred", L + 1, H, persist)
        chosen = _pick(cands, rng, 1, 2)
        if chosen is None:
            return None
        return Question(T, "predictive", template, lead + "which of the following will happen?",
                        choices=[c["text"] for c in chosen], gold_choices=[c["truth"] for c in chosen],
                        meta={"baseline": [c["baseline"] for c in chosen], "kinds": [c["kind"] for c in chosen],
                              "args": [c["args"] for c in chosen]})
    if template == "first_stockout":
        ok = [p for p in s.products if not f.stocked_out(L, p)]
        first = {p: next((d for d in fut if f.stocked_out(d, p)), None) for p in ok}
        outs = [p for p in ok if first[p] is not None]
        if not outs:
            return None
        rng.shuffle(outs)
        rest = [p for p in ok if p not in outs[:1]]
        rng.shuffle(rest)
        picked = outs[:1] + rest[:N_CHOICES - 1]
        if len(picked) < 3:
            return None
        earliest = min(first[p] for p in picked if first[p] is not None)
        gold = [first[p] == earliest for p in picked]
        if all(gold):
            return None
        rng.shuffle(picked)
        gold = [first[p] == earliest for p in picked]
        return Question(T, "predictive", template,
                        lead + "which of these products will be the first to run out of stock during those days? "
                        "If several run out first on the same day, each of them is correct.",
                        choices=picked, gold_choices=gold,
                        meta={"first_day": {p: first[p] for p in picked}})
    raise ValueError(template)


# ---------------------------------------------------------------- counterfactual
def _cf_candidates(s: Scope, kind: str) -> list[tuple[dict, str]]:
    days, L = s.days, s.last_day
    out = []
    if kind == "remove_order":
        for d in days:
            for p in s.products:
                if s.orders[d][p] > 0:
                    out.append(({"kind": "remove_order", "product": p, "day": d},
                                f"the order for {p} placed on day {d} ({s.orders[d][p]} units) had not been placed"))
    elif kind == "zero_production":
        for d in days:
            for p in s.products:
                if s.production[d][p] > 0:
                    out.append(({"kind": "set_production", "product": p, "day": d, "value": 0},
                                f"no {p} had been produced on day {d} (a line stoppage; {s.production[d][p]} "
                                f"units were recorded)"))
    elif kind == "delay_production":
        for d in days:
            if d + DELAY_DAYS > L:
                continue
            for p in s.products:
                if s.production[d][p] > 0:
                    out.append(({"kind": "delay_production", "product": p, "day": d, "by": DELAY_DAYS},
                                f"the {s.production[d][p]} units of {p} produced on day {d} had arrived "
                                f"{DELAY_DAYS} days later, on day {d + DELAY_DAYS}"))
    elif kind == "capacity":
        lower = int(round(s.capacity_kg * CAP_FACTOR))
        for d in days:
            out.append(({"kind": "scale_capacity", "factor": CAP_FACTOR, "from_day": d},
                        f"the dispatch capacity had been 20% lower ({lower} kg per day instead of "
                        f"{s.capacity_kg} kg) from day {d} onward"))
    return out


def counterfactual(s: Scope, f: SimResult, kind: str, rng: random.Random) -> Question | None:
    T, L = s.title, s.last_day
    cands = _cf_candidates(s, kind)
    rng.shuffle(cands)
    for iv, clause in cands[:25]:
        r = simulate(s, [iv], through=L)
        d0 = iv.get("day", iv.get("from_day"))
        days = list(range(d0, L + 1))
        if not any(r.rows[(d, p)] != f.rows[(d, p)] for d in days for p in s.products) and \
                not any(r.cap_reached[d] != f.cap_reached[d] for d in days):
            continue                                    # the change has no visible consequence
        stm = _statements(s, f, r, days, "cf", d0, L, lambda k, a: _stmt_truth(k, a, f))
        # the changed product's own stock on the day of the change is a direct, one-step consequence: leave out
        stm = [c for c in stm if not (c["kind"].startswith("stock_") and c["product"] == iv.get("product")
                                      and c["args"]["e"] == d0)]
        chosen = _pick(stm, rng, 1, 2, focus=iv.get("product"))
        if chosen is None:
            continue
        return Question(T, "counterfactual", kind,
                        f"In {T}, suppose {clause}, with everything else as recorded. Which of the following "
                        f"would have happened?",
                        choices=[c["text"] for c in chosen],
                        gold_choices=[c["truth"] for c in chosen],
                        meta={"intervention": iv, "baseline": [c["baseline"] for c in chosen],
                              "kinds": [c["kind"] for c in chosen], "args": [c["args"] for c in chosen]})
    return None
