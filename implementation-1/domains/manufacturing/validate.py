"""Validate the manufacturing benchmark and write domains/manufacturing/VALIDATION.md.

    python -m domains.manufacturing.validate          (from implementation-1/)

Checks, on every run folder runs/mfg_*:
 1. determinism: sim.simulate run twice gives identical results, and reproduces the ledger printed in the PDF;
 2. independent re-implementation: a second, separately written policy runner (below, `ref_run`) fed only
    with the inputs parsed back from the PDF reproduces every ledger row, the events and every gold label
    (so the document alone holds everything a question needs);
 3. conservation on every printed ledger row (stock and backlog), no negative values, capacity never exceeded;
 4. printed inputs (production, orders, order book) equal the raw SupplyGraph records;
 5. counts per type / template, true-false balance, no constant-answer template, simple baselines;
 6. prompt hygiene: scope title verbatim, only products/days of that scope, no type or method words;
 7. 20 seeded random questions written out with the document excerpt and gold, for hand-checking.
"""
from __future__ import annotations

import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

import pypdfium2 as pdfium

from .data import ROOT, load
from .questions import _stmt_truth
from .scopes import all_scopes
from .sim import events, simulate

RUNS = ROOT / "runs"
OUT = Path(__file__).resolve().parent / "VALIDATION.md"
FORBIDDEN = ("descriptive", "explanatory", "predictive", "counterfactual", "simulat", "gold", "but-for",
             "intervention", "benchmark")


# ------------------------------------------------------------------ parse the PDF back
def parse_pdf(path: Path) -> dict:
    pdf = pdfium.PdfDocument(str(path))
    lines = []
    for i in range(len(pdf)):
        lines += pdf[i].get_textpage().get_text_range().replace("\r", "").split("\n")
    scopes, cur, sec = {}, None, None
    for ln in lines:
        ln = ln.strip()
        m = re.fullmatch(r"Plant (\d+), Period (\d\d)", ln)
        if m:
            cur = scopes.setdefault(ln, {"plant": m[1], "period": int(m[2]), "products": {}, "ledger": {},
                                         "events": [], "open": [], "book": {}, "capacity": None})
            sec = "head"
            continue
        m = re.fullmatch(r"(Plant \d+, Period \d\d): (Products|Daily ledger|Events|Order book)", ln)
        if m:
            cur, sec = scopes[m[1]], m[2]
            continue
        if cur is None or not ln:
            continue
        if sec == "head":
            cur["head"] = cur.get("head", "") + " " + ln
            m = re.search(r"Daily dispatch capacity: (\d+) kg\.", cur["head"])
            if m:
                cur["capacity"] = int(m[1])
        tok = ln.split()
        if sec == "Products" and len(tok) == 6 and tok[0] != "product":
            cur["products"][tok[0]] = (round(float(tok[4]) * 1000), int(tok[5]))
        elif sec == "Daily ledger" and len(tok) == 8 and tok[0].isdigit():
            cur["ledger"][(int(tok[0]), tok[2])] = dict(zip(("produced", "ordered", "shipped", "backordered",
                                                             "stock"), map(int, tok[3:])))
        elif sec == "Events":
            if ln.startswith("Day "):
                cur["events"].append(ln)
            elif cur["events"] and not ln.startswith("No events"):
                cur["events"][-1] += " " + ln
        elif sec == "Order book":
            if len(tok) == 3 and tok[1].isdigit() and tok[2].isdigit():
                cur["open"].append((tok[0], int(tok[1]), int(tok[2])))
            elif len(tok) == 5 and tok[0].isdigit() and re.fullmatch(r"\d{4}-\d\d-\d\d", tok[1]):
                cur["book"][(int(tok[0]), tok[2])] = (int(tok[3]), int(tok[4]))
    return scopes


# ------------------------------------------------------------------ independent policy runner
def ref_run(ps: dict, ivs: list[dict], through: int) -> dict:
    """Written from the front-matter prose, separately from sim.py. Inputs come only from the parsed PDF."""
    days = sorted({d for d, _ in ps["ledger"]})
    prods = sorted(ps["products"])
    prod_in, ord_in = {}, {}
    for (d, p), r in ps["ledger"].items():
        prod_in[d, p], ord_in[d, p] = r["produced"], r["ordered"]
    for (d, p), (pp, oo) in ps["book"].items():
        prod_in[d, p], ord_in[d, p] = pp, oo
    cap = {d: ps["capacity"] * 1000 for d in range(days[0], through + 1)}
    unlimited, free, skip = set(), set(), set()
    for iv in ivs:
        k = iv["kind"]
        if k == "remove_order":
            ord_in[iv["day"], iv["product"]] = 0
        elif k == "set_production":
            prod_in[iv["day"], iv["product"]] = iv["value"]
        elif k == "add_stock":
            prod_in[iv["day"], iv["product"]] += iv["units"]
        elif k == "delay_production":
            q = prod_in[iv["day"], iv["product"]]
            prod_in[iv["day"], iv["product"]] = 0
            if (iv["day"] + iv["by"], iv["product"]) in prod_in:
                prod_in[iv["day"] + iv["by"], iv["product"]] += q
        elif k == "scale_capacity":
            for d in cap:
                if d >= iv["from_day"]:
                    cap[d] = round(cap[d] * iv["factor"])
        elif k == "unlimited_capacity":
            unlimited.add(iv["day"])
        elif k == "free_capacity":
            free.add((iv["day"], iv["product"]))
        elif k == "skip_older":
            skip.add((iv["day"], iv["product"]))
    stock = {p: ps["products"][p][1] for p in prods}
    queue = []                     # [day placed, product, remaining, qty, {day: shipped}]
    rows, capr, orders = {}, {}, {}
    for d in range(days[0], through + 1):
        for p in prods:
            stock[p] += prod_in[d, p]
        for p in prods:
            if ord_in[d, p] > 0:
                o = [d, p, ord_in[d, p], ord_in[d, p], {}]
                queue.append(o)
                orders[p, d] = o
        room = None if d in unlimited else cap[d]
        hit = False
        ship = Counter()
        for o in sorted(queue, key=lambda o: (o[0], o[2], o[1])):
            if (d, o[1]) in skip and o[0] < d:
                continue
            g = ps["products"][o[1]][0]
            n = min(o[2], stock[o[1]])
            if room is not None and (d, o[1]) not in free:
                fit = room // g
                if fit < n:
                    hit, n = True, fit
                room -= n * g
            o[2] -= n
            stock[o[1]] -= n
            ship[o[1]] += n
            if n:
                o[4][d] = n
        queue = [o for o in queue if o[2] > 0]
        capr[d] = hit
        for p in prods:
            rows[d, p] = {"produced": prod_in[d, p], "ordered": ord_in[d, p], "shipped": ship[p],
                          "backordered": sum(o[2] for o in queue if o[1] == p), "stock": stock[p]}
    return {"rows": rows, "cap": capr, "orders": orders}


class RefView:
    """Adapter so the statement predicates in questions.py can read a ref_run result."""
    def __init__(self, r):
        self.r = r
        self.cap_reached = r["cap"]

    def stock(self, d, p):
        return self.r["rows"][d, p]["stock"]

    def backlog(self, d, p):
        return self.r["rows"][d, p]["backordered"]

    def stocked_out(self, d, p):
        x = self.r["rows"][d, p]
        return x["stock"] == 0 and x["backordered"] > 0

    def order_full_on_day(self, p, d):
        o = self.r["orders"].get((p, d))
        return o is not None and o[4].get(d, 0) == o[3]

    def order_short_on_day(self, p, d):
        o = self.r["orders"].get((p, d))
        return o is not None and o[4].get(d, 0) < o[3]


# ------------------------------------------------------------------ gold re-derivation from the PDF alone
def rederive(item: dict, meta: dict, ps: dict) -> str | list[bool]:
    days = sorted({d for d, _ in ps["ledger"]})
    L, H = days[-1], max(d for d, _ in ps["book"])
    f = RefView(ref_run(ps, [], H))
    t, q = item["question_subtype"], item["question"]
    if item["question_type"] == "descriptive":
        if t in ("stock", "backordered", "shipped"):
            p, d = re.search(r"units of (\S+) were .* day (\d+)\?", q).groups()
            return str(ps["ledger"][int(d), p][t])
        if t == "first_stockout":
            p = re.search(r"did (\S+) first", q)[1]
            return str(next(d for d in days if f.stocked_out(d, p)))
        if t == "capacity_days":
            return str(sum(f.cap_reached[d] for d in days))
        if t == "stockout_products":
            return str(sum(any(f.stocked_out(d, p) for d in days) for p in ps["products"]))
        if t == "max_backlog":
            d = int(re.search(r"end of day (\d+)", q)[1])
            return max(ps["products"], key=lambda p: ps["ledger"][d, p]["backordered"]).lower()
    if item["question_type"] == "explanatory":
        p, d = meta["target"]
        return [RefView(ref_run(ps, ivs, d)).order_full_on_day(p, d) for ivs in meta["interventions"]]
    if item["question_type"] == "predictive":
        if t == "first_stockout":
            fut = range(L + 1, H + 1)
            first = {c["choice"]: next((d for d in fut if f.stocked_out(d, c["choice"])), None)
                     for c in item["choices"]}
            e = min(v for v in first.values() if v is not None)
            return [first[c["choice"]] == e for c in item["choices"]]
        return [_stmt_truth(k, a, f) for k, a in zip(meta["kinds"], meta["args"])]
    if item["question_type"] == "counterfactual":
        r = RefView(ref_run(ps, [meta["intervention"]], L))
        return [_stmt_truth(k, a, r) for k, a in zip(meta["kinds"], meta["args"])]
    raise ValueError(t)


# ------------------------------------------------------------------ excerpt for hand-checking
def excerpt(item: dict, meta: dict, ps: dict) -> list[str]:
    text = item["question"] + " " + " ".join(c["choice"] for c in item["choices"])
    prods = [p for p in sorted(ps["products"]) if re.search(rf"\b{re.escape(p)}\b", text)]
    days = sorted({int(x) for x in re.findall(r"day (\d+)", text)})
    led_days = sorted({d for d, _ in ps["ledger"]})
    L = led_days[-1]
    out = [f"capacity {ps['capacity']} kg/day; products: " +
           ", ".join(f"{p} ({ps['products'][p][0] / 1000:g} kg/unit, opening {ps['products'][p][1]})"
                     for p in sorted(ps["products"]))]
    show = sorted({x for d in days for x in (d - 1, d) if x in led_days})
    if item["question_type"] in ("descriptive",) and item["question_subtype"] in ("capacity_days",
                                                                                  "stockout_products"):
        show = []
    rows_p = prods or sorted(ps["products"])
    if show:
        out.append("ledger (day product produced ordered shipped backordered stock):")
        for d in show:
            for p in sorted(ps["products"]) if item["question_type"] == "explanatory" else rows_p:
                r = ps["ledger"][d, p]
                out.append(f"  {d} {p} {r['produced']} {r['ordered']} {r['shipped']} {r['backordered']} {r['stock']}")
    ev = [e for e in ps["events"] if not days or int(re.match(r"Day (\d+)", e)[1]) in set(days) | set(show)]
    if item["question_subtype"] in ("capacity_days", "stockout_products", "first_stockout"):
        ev = [e for e in ps["events"] if ("capacity" in e if item["question_subtype"] == "capacity_days"
                                          else "runs out of stock" in e)]
    out += ["events:"] + [f"  {e}" for e in ev] if ev else ["events: (none on these days)"]
    if item["question_type"] == "predictive":
        out.append(f"open orders at end of day {L}: " + (", ".join(f"{p}@{d}:{u}" for p, d, u in ps["open"]) or "none"))
        out.append("order book (day product planned_production ordered):")
        for (d, p), (pp, oo) in sorted(ps["book"].items()):
            if p in rows_p:
                out.append(f"  {d} {p} {pp} {oo}")
    if item["question_type"] == "counterfactual":
        iv = meta["intervention"]
        H = L
        f, r = RefView(ref_run(ps, [], H)), RefView(ref_run(ps, [iv], H))
        out.append(f"change: {json.dumps(iv)}")
        for k, a in zip(meta["kinds"], meta["args"]):
            out.append(f"  {k} {json.dumps(a)}: recorded={_stmt_truth(k, a, f)} with change={_stmt_truth(k, a, r)}")
    if item["question_type"] == "explanatory":
        out.append("but-for runs: " + "; ".join(f"{k} -> order ships in full={g}"
                                                for k, g in zip(meta["kinds"], rederive(item, meta, ps))))
    return out


# ------------------------------------------------------------------ main
def main() -> None:
    rec = load()
    scopes = {s.title: s for s in all_scopes(rec)}
    run_dirs = sorted(p for p in RUNS.glob("mfg_*") if (p / "items.jsonl").exists())
    report = ["# Manufacturing benchmark: validation report", "",
              "Generated by `python -m domains.manufacturing.validate`. Every number below is recomputed "
              "from the files in `runs/mfg_*`; nothing is hand-entered. Design decisions and deviations from "
              "the draft spec: `docs/domains/manufacturing.md`, section \"As built\".", ""]
    problems: list[str] = []
    totals = Counter()
    all_items = []
    doc_rows = []
    for rd in run_dirs:
        parsed = parse_pdf(rd / "document.pdf")
        cfg = json.loads((rd / "build_config.json").read_text())
        man = json.loads((rd / "manifest.json").read_text())
        items = [json.loads(l) for l in (rd / "items.jsonl").read_text().splitlines()]
        metas = {m["uid"]: m for m in map(json.loads, (rd / "gold_meta.jsonl").read_text().splitlines())}
        qs = {q["uid"]: q for q in map(json.loads, (rd / "questions.jsonl").read_text().splitlines())}
        golds = {g["uid"]: g for g in map(json.loads, (rd / "gold.jsonl").read_text().splitlines())}
        n_rows = 0
        if [s["title"] for s in man["scopes"]] != cfg["scopes"] or set(parsed) != set(cfg["scopes"]):
            problems.append(f"{rd.name}: scope list differs between manifest, config and PDF")
        for title in cfg["scopes"]:
            s, ps = scopes[title], parsed[title]
            a, b = simulate(s), simulate(s)
            if a.rows != b.rows or a.cap_reached != b.cap_reached or a.used_g != b.used_g:
                problems.append(f"{title}: simulate is not deterministic")
            # 1. simulator reproduces the printed ledger
            for d in s.days:
                for p in s.products:
                    n_rows += 1
                    pr = ps["ledger"].get((d, p))
                    sr = {k: v for k, v in a.rows[(d, p)].items() if k not in ("day", "product")}
                    if pr != sr:
                        problems.append(f"{title} day {d} {p}: printed {pr} vs simulated {sr}")
            # events printed == events regenerated
            ev = [f"Day {d} ({rec.date_of(d)}): {t}." for d, _, _, t in events(s, a)]
            if ev != ps["events"]:
                problems.append(f"{title}: printed events differ from the simulator's")
            # 2. independent runner on PDF inputs
            rr = ref_run(ps, [], s.horizon_day)
            for (d, p), row in ps["ledger"].items():
                if rr["rows"][d, p] != row:
                    problems.append(f"{title} day {d} {p}: independent runner {rr['rows'][d, p]} vs printed {row}")
            for d in s.days + s.future_days:
                if rr["cap"][d] != a.cap_reached[d] or any(rr["rows"][d, p]["backordered"] != a.backlog(d, p)
                                                           or rr["rows"][d, p]["stock"] != a.stock(d, p)
                                                           for p in s.products):
                    problems.append(f"{title} day {d}: independent runner differs from sim.py (incl. order book days)")
            # open orders table == simulator
            opn = sorted((o.product, o.day, o.qty - sum(n for dd, n in o.shipped.items() if dd <= s.last_day))
                         for o in a.orders.values() if o.day <= s.last_day)
            if sorted(x for x in opn if x[2] > 0) != sorted(ps["open"]):
                problems.append(f"{title}: open-orders table differs from the simulator")
            # 3. conservation, non-negativity, capacity
            for p in s.products:
                st, bl = ps["products"][p][1], 0
                for d in s.days:
                    r = ps["ledger"][d, p]
                    if r["stock"] != st + r["produced"] - r["shipped"] or \
                            r["backordered"] != bl + r["ordered"] - r["shipped"] or \
                            min(r.values()) < 0:
                        problems.append(f"{title} day {d} {p}: conservation/non-negativity fails: {r}")
                    st, bl = r["stock"], r["backordered"]
            for d in s.days:
                used = sum(ps["ledger"][d, p]["shipped"] * ps["products"][p][0] for p in s.products)
                if used > ps["capacity"] * 1000:
                    problems.append(f"{title} day {d}: capacity exceeded ({used / 1000} kg)")
            # 4. inputs equal raw records
            for d in s.days:
                for p in s.products:
                    if (ps["ledger"][d, p]["produced"], ps["ledger"][d, p]["ordered"]) != \
                            (rec.production[d][p], rec.orders[d][p]):
                        problems.append(f"{title} day {d} {p}: printed inputs differ from raw records")
            for d in s.future_days:
                for p in s.products:
                    if ps["book"].get((d, p)) != (rec.production[d][p], rec.orders[d][p]):
                        problems.append(f"{title} day {d} {p}: order book differs from raw records")
            if (ps["capacity"], {p: v[1] for p, v in ps["products"].items()}) != (s.capacity_kg, s.opening_stock):
                problems.append(f"{title}: printed constants differ")
        # gold re-derivation + hygiene
        n_gold_ok = 0
        for it in items:
            ps = parsed[it["scene_index"]]
            meta = metas[it["uid"]]
            got = rederive(it, meta, ps)
            want = it["gold_answer"] if it["question_type"] == "descriptive" else \
                [it["gold_choices"][str(i)] for i in range(len(it["choices"]))]
            if got != want:
                problems.append(f"{it['uid']}: gold {want} but re-derived {got}")
            else:
                n_gold_ok += 1
            q, g = qs[it["uid"]], golds[it["uid"]]
            if it["scene_index"] not in q["prompt"] or it["scene_index"] not in it["question"]:
                problems.append(f"{it['uid']}: scope title missing from prompt")
            if any(w in q["prompt"].lower() for w in FORBIDDEN) or "question_type" in q or "gold" in str(q):
                problems.append(f"{it['uid']}: prompt leaks type/method words")
            for code in re.findall(r"\b[A-Z][A-Z0-9]{4,}(?:-[AB])?\b", q["prompt"]):
                if code not in ps["products"]:
                    problems.append(f"{it['uid']}: mentions {code}, not a product of its scope")
            s = scopes[it["scene_index"]]
            for d in map(int, re.findall(r"day (\d+)", q["prompt"])):
                if not s.first_day <= d <= s.horizon_day:
                    problems.append(f"{it['uid']}: mentions day {d} outside its scope")
            if g["gold_answer"] != it["gold_answer"] or g["question_type"] != it["question_type"]:
                problems.append(f"{it['uid']}: gold.jsonl differs from items.jsonl")
            all_items.append((rd.name, it, meta, ps))
        cnt = Counter(it["question_type"] for it in items)
        totals.update(cnt)
        pages = man["scopes"][-1]["end_page"]
        doc_rows.append(f"| {rd.name} | {cfg.get('role', 'test')} | {len(cfg['scopes'])} | {pages} | {n_rows} | "
                        f"{cnt['descriptive']} | {cnt['explanatory']} | {cnt['predictive']} | "
                        f"{cnt['counterfactual']} | {len(items)} | {n_gold_ok}/{len(items)} |")

    test = [(n, it, m, ps) for n, it, m, ps in all_items if n != "mfg_dev"]
    report += ["## Result", ""]
    result_at = len(report)
    report += [""]
    report += ["Checks run on every run folder (all scopes, all ledger rows, all questions):", "",
               "1. **Determinism.** `sim.simulate` run twice on each scope gives identical ledgers, capacity "
               "flags and dispatched weights, and reproduces the ledger printed in the PDF exactly (text "
               "extracted from the PDF with pypdfium2). The Events section and the open-orders table printed in "
               "the PDF equal the simulator's.",
               "2. **Independent re-implementation.** `ref_run` in `validate.py` is a second policy runner written "
               "from the front-matter prose, fed only with numbers parsed back out of the PDF (capacity, kg per "
               "unit, opening stock, produced, ordered, order book). It reproduces every printed ledger row, "
               "agrees with `sim.py` on the 7 order-book days, and re-derives every gold label (descriptive "
               "answers, but-for runs for explanatory, continued runs for predictive, re-runs with the change "
               "for counterfactual). So each question is answerable from its document alone.",
               "3. **Conservation** on every printed row: stock = previous stock + produced - shipped; "
               "backordered = previous backordered + ordered - shipped (previous = opening stock and 0 on the "
               "first day); no negative values; shipped weight never exceeds the day's capacity.",
               "4. **Real inputs.** Printed produced/ordered values and every order-book value equal the raw "
               "SupplyGraph records (rounded to whole units); printed capacity and opening stock equal the "
               "constants.",
               "5. **Prompt hygiene.** Every prompt and question contains its scope title verbatim; every product "
               "code mentioned belongs to that scope; every day mentioned lies in the scope's period or its "
               "order-book days; no prompt contains the words " + ", ".join(f"'{w}'" for w in FORBIDDEN) +
               "; questions.jsonl carries no type or gold.", ""]
    report += ["## Documents", "",
               "| run | role | scopes | pages | ledger rows | descriptive | explanatory | predictive | "
               "counterfactual | total | gold re-derived |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    report += doc_rows
    report += ["", f"Test total: {sum(1 for _ in test)} questions; per type: " +
               ", ".join(f"{t} {sum(it['question_type'] == t for _, it, _, _ in test)}"
                         for t in ("descriptive", "explanatory", "predictive", "counterfactual")) + ".", ""]

    # balance tables (test documents)
    report += ["## Templates and true/false balance (test documents)", "",
               "| type | template | questions | choices | true share | true per question (min-max) | "
               "distinct answers |", "|---|---|---|---|---|---|---|"]
    by = defaultdict(list)
    for _, it, m, _ in test:
        by[(it["question_type"], it["question_subtype"])].append(it)
    constant = []
    for (t, st), its in sorted(by.items()):
        if t == "descriptive":
            answers = Counter(it["gold_answer"] for it in its)
            if len(answers) < 2:
                constant.append(f"{t}/{st}")
            report.append(f"| {t} | {st} | {len(its)} | - | - | - | {len(answers)} "
                          f"(most common '{answers.most_common(1)[0][0]}' x{answers.most_common(1)[0][1]}) |")
        else:
            g = [v for it in its for v in it["gold_choices"].values()]
            per = [sum(it["gold_choices"].values()) for it in its]
            if all(g) or not any(g):
                constant.append(f"{t}/{st}")
            report.append(f"| {t} | {st} | {len(its)} | {len(g)} | {sum(g) / len(g):.2f} | {min(per)}-{max(per)} | - |")
    for t in ("explanatory", "predictive", "counterfactual"):
        g = [v for _, it, _, _ in test if it["question_type"] == t for v in it["gold_choices"].values()]
        k = Counter(sum(it["gold_choices"].values()) for _, it, _, _ in test if it["question_type"] == t)
        report.append(f"| {t} | **all** | {sum(k.values())} | {len(g)} | {sum(g) / len(g):.2f} | "
                      f"{dict(sorted(k.items()))} (true choices: questions) | - |")
    report += ["", "Constant-answer templates: " + (", ".join(constant) if constant else "none") + ".", ""]
    if constant:
        problems.append("constant-answer templates: " + ", ".join(constant))

    # explanatory cause kinds
    ek = defaultdict(list)
    for _, it, m, _ in test:
        if it["question_type"] == "explanatory":
            for k, i in zip(m["kinds"], range(len(it["choices"]))):
                ek[k].append(it["gold_choices"][str(i)])
    report += ["Explanatory choices by cause kind (test): " +
               "; ".join(f"{k}: {len(v)} choices, {sum(v) / len(v):.2f} true" for k, v in sorted(ek.items())) + ".",
               ""]

    # baselines
    def mc_scores(rows, pred):
        q_ok = o_ok = o_n = 0
        for it, p in zip(rows, pred):
            g = [it["gold_choices"][str(i)] for i in range(len(it["choices"]))]
            o_ok += sum(a == b for a, b in zip(g, p))
            o_n += len(g)
            q_ok += g == p
        return q_ok / len(rows), o_ok / o_n
    report += ["## Simple baselines (test documents)", "",
               "Shortcut answers a system could give without running the policy. Low question accuracy here "
               "means the questions are not solved by copying the record.", "",
               "| type | baseline | question accuracy | option accuracy |", "|---|---|---|---|"]
    for t in ("explanatory", "predictive", "counterfactual"):
        rows = [(it, m) for _, it, m, _ in test if it["question_type"] == t]
        its = [it for it, _ in rows]
        for name, pred in (("all false", [[False] * len(it["choices"]) for it in its]),
                           ("all true", [[True] * len(it["choices"]) for it in its])):
            qa, oa = mc_scores(its, pred)
            report.append(f"| {t} | {name} | {qa:.2f} | {oa:.2f} |")
        if t == "counterfactual":
            qa, oa = mc_scores(its, [m["baseline"] for _, m in rows])
            report.append(f"| {t} | copy the recorded outcome (ignore the change) | {qa:.2f} | {oa:.2f} |")
        if t == "predictive":
            rr = [(it, m) for it, m in rows if "baseline" in m]
            qa, oa = mc_scores([it for it, _ in rr], [m["baseline"] for _, m in rr])
            report.append(f"| {t} (will_happen only, n={len(rr)}) | state at end of period persists | "
                          f"{qa:.2f} | {oa:.2f} |")
    cfk = Counter(m["intervention"]["kind"] for _, it, m, _ in test if it["question_type"] == "counterfactual")
    report += ["", "Counterfactual change kinds (test): " + ", ".join(f"{k} {v}" for k, v in sorted(cfk.items())) +
               " (`set_production` = production set to zero, a line stoppage; `scale_capacity` = capacity 20% "
               "lower from a day on).", ""]

    # 20 hand-check samples
    rng = random.Random(7)
    sample = rng.sample(test, 20)
    report += ["## 20 random test questions for hand-checking", "",
               "Each shows the prompt, the gold, and an excerpt of the document (parsed back from the PDF). For "
               "explanatory and counterfactual questions the excerpt also gives the result of the independent "
               "runner's but-for / changed run, so the gold can be traced.", ""]
    for i, (name, it, m, ps) in enumerate(sample, 1):
        q = next(json.loads(l) for l in (RUNS / name / "questions.jsonl").read_text().splitlines()
                 if json.loads(l)["uid"] == it["uid"])
        gold = it["gold_answer"] if it["question_type"] == "descriptive" else \
            ", ".join(f"{i}: {'true' if v else 'false'}" for i, v in it["gold_choices"].items())
        report += [f"### {i}. `{it['uid']}` ({name}, {it['question_type']} / {it['question_subtype']})", "",
                   "```text", q["prompt"], "```", "", f"**Gold:** {gold}", "", "Excerpt:", "", "```text"]
        report += excerpt(it, m, ps)
        report += ["```", ""]
    head = [f"**{'PASS' if not problems else 'FAIL'}**: {len(problems)} problem(s) found.", ""]
    if problems:
        head += ["```"] + problems[:200] + ["```", ""]
    report[result_at:result_at + 1] = head
    OUT.write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"{'PASS' if not problems else 'FAIL'}: {len(problems)} problems; totals {dict(totals)}; wrote {OUT}")
    for p in problems[:20]:
        print("  ", p)


if __name__ == "__main__":
    main()
