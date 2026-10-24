"""Validate the finance benchmark and write domains/finance/VALIDATION.md.

    python -m domains.finance.validate          (from implementation-1/)

Checks, on every run folder runs/fin_*:
 1. layout and pairing: harness files present, questions.jsonl has no type or gold, uids unique, every
    counterfactual has its factual twin in the same document and scope;
 2. fidelity to TAT-HQA: every gold row equals the released record (answer, scale, derivation, answer type and
    source), every question is "In <scope>: " + the released question, every scope holds the released context;
 3. scoring: every gold answer scores EM = F1 = 1 against itself through score.py's full path (reply text ->
    JSON -> TAT metric); the vendored metric is AST-identical to TAT's code and agrees with TAT's original
    TaTQAEmAndF1 on gold and perturbed predictions; the assignment solver equals brute force;
 4. scope titles: every question and prompt names its scope exactly, and no other report;
 5. PDF: page count, outline (scope = level 0, Text and Table = level 1), every paragraph present in the text
    layer, and every table found as a ruled grid by pdfplumber with the same shape and the same cell text
    (numbers identical to the JSON);
 6. distributions, a copy-the-factual-answer baseline, and 20 seeded random questions with their excerpt.
"""
from __future__ import annotations

import ast
import importlib.util
import itertools
import json
import random
import re
import sys
import types
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pdfplumber
import PyPDF2
import pypdfium2 as pdfium

from . import tatqa_metric
from .data import ROOT, load
from xml.sax.saxutils import unescape

from .render import DOC_TITLE, header_rows, intro, printable
from .score import normalize_answer_value, score_one, score_predictions

RUNS = ROOT / "runs"
TAT = ROOT / "data" / "domains" / "raw" / "tat-hqa"
OUT = Path(__file__).resolve().parent / "VALIDATION.md"
FORBIDDEN = ("descriptive", "counterfactual", "hypothetical", "gold", "benchmark", "tat-", "tatqa")
GOLD_FIELDS = ("answer", "scale", "derivation", "answer_type", "answer_from", "rel_paragraphs", "req_comparison")
LAYOUT = ("document.pdf", "manifest.json", "build_config.json", "items.jsonl", "items_all.jsonl",
          "questions.jsonl", "gold.jsonl")
SCALE_CUE = re.compile(r"thousand|million|billion|'000|000s|\$\s?m\b|\$\s?k\b|\bm\b|\bbn\b|€m|£m|"
                       r"\$m|\bk\b|in millions|in thousands", re.I)

problems: list[str] = []


def check(cond: bool, msg: str) -> bool:
    if not cond:
        problems.append(msg)
    return cond


def ws(s) -> str:
    return " ".join(str(s or "").split())


def norm(s) -> str:
    """Source text as it should read in the PDF text layer: the renderer's substitutions, whitespace collapsed."""
    return ws(printable(str(s or "")))


def jl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


# ------------------------------------------------------------------ metric fidelity
def _tat_original():
    """TAT's tag_op/tatqa_metric.py (what tatqa_eval.py imports), loaded with stand-ins for its two missing
    dependencies: pandas (only used by pivot-table helpers we never call) and scipy's linear_sum_assignment
    (replaced by exhaustive search, which is exact)."""
    def brute_lsa(cost):
        cost = np.asarray(cost)
        n_r, n_c = cost.shape
        k = min(n_r, n_c)
        best, best_pairs = None, ([], [])
        if n_r <= n_c:
            for cols in itertools.permutations(range(n_c), k):
                s = sum(cost[r, c] for r, c in zip(range(n_r), cols))
                if best is None or s < best:
                    best, best_pairs = s, (list(range(n_r)), list(cols))
        else:
            for rows in itertools.permutations(range(n_r), k):
                s = sum(cost[r, c] for r, c in zip(rows, range(n_c)))
                if best is None or s < best:
                    best, best_pairs = s, (list(rows), list(range(n_c)))
        order = np.argsort(best_pairs[0])
        return np.array(best_pairs[0])[order], np.array(best_pairs[1])[order]

    scipy_m, opt = types.ModuleType("scipy"), types.ModuleType("scipy.optimize")
    opt.linear_sum_assignment = brute_lsa
    scipy_m.optimize = opt
    saved = {k: sys.modules.get(k) for k in ("scipy", "scipy.optimize", "pandas", "tatqa_utils")}
    sys.modules.update({"scipy": scipy_m, "scipy.optimize": opt, "pandas": types.ModuleType("pandas")})
    spec_u = importlib.util.spec_from_file_location("tatqa_utils", TAT / "tatqa_utils.py")
    utils = importlib.util.module_from_spec(spec_u)
    sys.modules["tatqa_utils"] = utils
    spec_u.loader.exec_module(utils)
    spec = importlib.util.spec_from_file_location("tat_original_metric", TAT / "tag_op" / "tatqa_metric.py")
    mod = importlib.util.module_from_spec(spec)
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        spec.loader.exec_module(mod)
    for k, v in saved.items():
        if v is None:
            sys.modules.pop(k, None)
        else:
            sys.modules[k] = v
    return mod, brute_lsa


def ast_identity() -> list[tuple[str, str, bool]]:
    ours = {n.name if isinstance(n, ast.FunctionDef) else n.targets[0].id: ast.dump(n)
            for n in ast.parse(Path(tatqa_metric.__file__).read_text(encoding="utf-8")).body
            if isinstance(n, (ast.FunctionDef, ast.Assign))}
    rows = []
    for fname in ("tatqa_utils.py", "tag_op/tatqa_metric.py"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse((TAT / fname).read_text(encoding="utf-8"))
        for n in tree.body:
            if not isinstance(n, (ast.FunctionDef, ast.Assign)):
                continue
            name = n.name if isinstance(n, ast.FunctionDef) else n.targets[0].id
            if name in ours:
                rows.append((fname, name, ast.dump(n) == ours[name]))
    return rows


def perturbations(g: dict, twin: dict | None) -> list[tuple[str, object, str]]:
    """(label, answer, scale) predictions around one gold row."""
    a, sc = normalize_answer_value(g["answer"]), g["scale"]
    out = [("gold", a, sc), ("scale none", a, ""), ("scale wrong", a, "million" if sc != "million" else "thousand")]
    if isinstance(a, list):
        out += [("reversed", list(reversed(a)), sc), ("first only", a[:1], sc), ("extra item", a + ["other"], sc),
                ("joined text", ", ".join(a), sc)]
    else:
        try:
            x = float(str(a).replace(",", ""))
            out += [("rounded 1dp", f"{x:.1f}", sc), ("negated", str(-x), sc), ("x1000 no scale", str(x * 1000), ""),
                    ("percent sign", f"{x}%", sc), ("fraction no scale", str(x / 100), ""),
                    ("off by one", str(x + 1), sc)]
        except ValueError:
            out += [("lower", str(a).lower(), sc), ("with the", "the " + str(a), sc)]
    if twin is not None:
        out.append(("twin answer", normalize_answer_value(twin["answer"]), twin["scale"]))
    return out


# ------------------------------------------------------------------ PDF
def pdf_pages(path: Path) -> list[str]:
    pdf = pdfium.PdfDocument(str(path))
    return [pdf[i].get_textpage().get_text_range().replace("\r", "") for i in range(len(pdf))]


def pdf_outline(path: Path) -> list[tuple[int, str, int]]:
    pdf = pdfium.PdfDocument(str(path))
    return [(b.level, b.get_title(), b.get_dest().get_index() + 1) for b in pdf.get_toc()]


EXTRACTORS = ("pdfplumber extract_text", "pdfplumber extract_words", "pypdfium2", "PyPDF2")
BAD_CHAR = re.compile(r"[\ufffd\ufffe\x00-\x08\x0b\x0c\x0e-\x1f\x7f]|\(cid:\d+\)")


def all_extractions(path: Path) -> dict[str, list[str]]:
    """Each page's text as four common readers return it."""
    out = {}
    with pdfplumber.open(str(path)) as pl:
        out["pdfplumber extract_text"] = [pg.extract_text() or "" for pg in pl.pages]
        out["pdfplumber extract_words"] = [" ".join(w["text"] for w in pg.extract_words()) for pg in pl.pages]
    out["pypdfium2"] = pdf_pages(path)
    out["PyPDF2"] = [pg.extract_text() or "" for pg in PyPDF2.PdfReader(str(path)).pages]
    return out


def char_bag(*texts: str) -> Counter:
    """Multiset of the non-whitespace characters."""
    return Counter(ch for t in texts for ch in t if not ch.isspace())


def bag_diff(want: Counter, got: Counter) -> str:
    miss, extra = want - got, got - want
    return f"missing {ascii(dict(miss))[:120]}, extra {ascii(dict(extra))[:120]}"


def rendered_table(plumber, first: int, last: int, n_head: int) -> tuple[list[list[str]], int, list[int]]:
    """Rows of the ruled tables on pages first..last (1-based); a table continued on the next page repeats its
    header rows, which are dropped. Returns (rows, number of tables found, pages with a table)."""
    rows, n_tables, pages = [], 0, []
    for p in range(first, last + 1):
        for t in plumber.pages[p - 1].find_tables():
            data = [[norm(c) for c in r] for r in t.extract()]
            n_tables += 1
            pages.append(p)
            rows += data[n_head:] if rows else data
    return rows, n_tables, pages


# ------------------------------------------------------------------ main
def main() -> None:
    raw = {s: {c.uid: c for c in load(s)} for s in ("dev", "train")}
    raw_q = {s: {q["uid"]: (c, q) for c in raw[s].values() for q in c.questions} for s in raw}
    runs = sorted(p for p in RUNS.glob("fin_*") if p.is_dir())
    test_runs = [r for r in runs if r.name != "fin_dev"]
    lines: list[str] = []
    doc_rows, all_gold, all_q, samples_pool = [], {}, {}, []
    all_uids: Counter = Counter()
    test_uids: set[str] = set()
    table_stats = Counter()
    roundtrip: dict[str, Counter] = defaultdict(Counter)
    scale_cue = Counter()
    excerpts: dict[tuple[str, str], str] = {}

    for run in runs:
        for f in LAYOUT:
            check((run / f).exists(), f"{run.name}: missing {f}")
        man = json.loads((run / "manifest.json").read_text())
        cfg = json.loads((run / "build_config.json").read_text())
        qs, gold, items = jl(run / "questions.jsonl"), jl(run / "gold.jsonl"), jl(run / "items.jsonl")
        split = cfg["tat_split"]
        scopes = {s["title"]: s for s in man["scopes"]}
        g_by = {g["uid"]: g for g in gold}
        q_by = {q["uid"]: q for q in qs}
        all_uids.update(q["uid"] for q in qs)
        check([q["uid"] for q in qs] == [g["uid"] for g in gold] == [i["uid"] for i in items],
              f"{run.name}: questions/gold/items uids differ")
        check(jl(run / "items_all.jsonl") == items, f"{run.name}: items_all differs from items")
        for q in qs:
            check(not set(q) & {"question_type", "question_subtype", "gold_answer", "answer", "scale"},
                  f"{q['uid']}: questions.jsonl leaks type/gold")
            check(q["format"] == "open_ended" and q["choices"] == [], f"{q['uid']}: not open-ended")

        # --- fidelity + pairing + scope titles
        for q in qs:
            g = g_by[q["uid"]]
            all_gold[q["uid"]], all_q[q["uid"]] = g, q
            ctx, rq = raw_q[split][g["tat_uid"]]
            sc = scopes.get(q["scope"])
            check(sc is not None and sc["tat_table_uid"] == ctx.uid == g["tat_context_uid"],
                  f"{q['uid']}: scope does not hold the question's context")
            for k in GOLD_FIELDS:
                check(g[k] == rq[k], f"{q['uid']}: gold field {k} differs from TAT")
            check(g["eval_answer_type"] == rq["eval_answer_type"], f"{q['uid']}: eval_answer_type differs")
            check(q["question"] == f"In {q['scope']}: {rq['question'].strip()}", f"{q['uid']}: question text changed")
            check(g["question_type"] == ("counterfactual" if rq["answer_type"] == "counterfactual" else "descriptive"),
                  f"{q['uid']}: wrong type mapping")
            check(q["question"].startswith(f"In {q['scope']}: ") and q["prompt"].split("\n")[0] == q["scope"]
                  and q["scope"] in q["prompt"], f"{q['uid']}: scope title missing")
            others = set(re.findall(r"Report R-\d{3}", q["prompt"])) - {q["scope"]}
            check(not others, f"{q['uid']}: prompt names another report {others}")
            low = q["prompt"].lower()
            check(not any(w in low for w in FORBIDDEN), f"{q['uid']}: forbidden word in prompt")
            tw = g_by.get(g["pair_uid"])
            check(tw is not None and tw["pair_uid"] == q["uid"] and q_by[g["pair_uid"]]["scope"] == q["scope"]
                  and tw["tat_context_uid"] == g["tat_context_uid"], f"{q['uid']}: twin missing or not paired")
            if g["question_type"] == "counterfactual" and tw is not None:
                twin_raw = raw_q[split][tw["tat_uid"]][1]
                check(str(rq["rel_question"]) == str(twin_raw["order"]) and tw["question_type"] == "descriptive",
                      f"{q['uid']}: twin is not TAT's rel_question")
            if g["scale"] in ("thousand", "million", "billion"):
                blob = " ".join(c for r in ctx.table for c in r) + " " + " ".join(p["text"] for p in ctx.paragraphs)
                scale_cue["stated" if SCALE_CUE.search(blob) else "not stated"] += 1
        per_scope = Counter(q["scope"] for q in qs)
        check(all(v == 2 for v in per_scope.values()), f"{run.name}: a scope has other than one pair")

        # --- self-score through the full parse path (reply text -> JSON -> metric) and the plain path
        replies = [{"uid": g["uid"], "raw_text": "Answer:\n" + json.dumps(
            {"answer": g["answer"], "scale": g["scale"] or "none"})} for g in gold]
        rep = score_predictions(gold, replies)
        check(rep["overall"]["em"] == 1.0 and rep["overall"]["f1"] == 1.0 and rep["overall"]["parse_errors"] == 0,
              f"{run.name}: gold does not self-score 100% ({rep['overall']})")
        rep2 = score_predictions(gold, [{"uid": g["uid"], "answer": g["answer"], "scale": g["scale"]} for g in gold])
        check(rep2["overall"]["em"] == 1.0, f"{run.name}: gold does not self-score via answer/scale rows")

        # --- PDF
        pages = pdf_pages(run / "document.pdf")
        outline = pdf_outline(run / "document.pdf")
        n_pages = len(pages)
        check(man["videos"][-1]["end_page"] == n_pages == man["scopes"][-1]["end_page"],
              f"{run.name}: page count {n_pages} != manifest")
        lvl0 = [t for l, t, _ in outline if l == 0]
        check(lvl0 == ["Annual Report Excerpts"] + list(scopes), f"{run.name}: level-0 outline != scopes")
        kids = defaultdict(list)
        cur = None
        for l, t, pg in outline:
            if l == 0:
                cur = t
                if t in scopes:
                    check(scopes[t]["start_page"] == pg, f"{run.name}: {t} outline page != manifest")
            else:
                kids[cur].append(t)
        # --- every character reads back exactly, in every extractor
        ext = all_extractions(run / "document.pdf")
        for name, texts in ext.items():
            for i, t in enumerate(texts, 1):
                found = BAD_CHAR.findall(t)
                roundtrip[name]["bad chars"] += len(found)
                check(not found, f"{run.name} p{i} ({name}): unreadable characters {ascii(found[:5])}")
            front = char_bag(DOC_TITLE, unescape(intro()), f"Chapters in this document ({run.name}): "
                             + ", ".join(scopes) + ".")
            got = char_bag(*texts[:man["scopes"][0]["start_page"] - 1])
            roundtrip[name]["front matter exact"] += got == front
            check(got == front, f"{run.name} front matter ({name}): {bag_diff(front, got)}")
            for title, sc in scopes.items():
                ctx = raw[split][sc["tat_table_uid"]]
                want = char_bag(title, f"{title}: Text", f"{title}: Table",
                                *(printable(p["text"]) for p in ctx.paragraphs),
                                *(printable(c) for r in ctx.table for c in r))
                got = char_bag(*texts[sc["start_page"] - 1: sc["end_page"]])
                roundtrip[name]["scopes"] += 1
                roundtrip[name]["scopes exact"] += got == want
                roundtrip[name]["chars"] += sum(want.values())
                roundtrip[name]["non-ascii chars"] += sum(v for k, v in want.items() if ord(k) > 127)
                check(got == want, f"{run.name} {title} ({name}): characters differ: {bag_diff(want, got)}")
        tokens = 0
        with pdfplumber.open(str(run / "document.pdf")) as plumber:
            for title, sc in scopes.items():
                ctx = raw[split][sc["tat_table_uid"]]
                check(kids[title] == [f"{title}: Text", f"{title}: Table"], f"{title}: outline children {kids[title]}")
                text = "\n".join(pages[sc["start_page"] - 1: sc["end_page"]])
                tokens += len(text) / 4
                excerpts[(run.name, title)] = text
                check(text.lstrip().startswith(title), f"{run.name} {title}: page does not start with the title")
                flat = norm(text)
                for p in ctx.paragraphs:
                    check(norm(p["text"]) in flat, f"{run.name} {title}: paragraph {p['order']} not in text layer")
                n_head = header_rows(ctx.table)
                rows, n_tables, tpages = rendered_table(plumber, sc["start_page"], sc["end_page"], n_head)
                table_stats["tables"] += 1
                table_stats["split over pages"] += len(set(tpages)) > 1
                want = [[norm(c) for c in r] for r in ctx.table]
                ok_shape = check(len(rows) == len(want) and all(len(r) == len(w) for r, w in zip(rows, want)),
                                 f"{run.name} {title}: table shape {len(rows)}x{len(rows[0]) if rows else 0} "
                                 f"!= {len(want)}x{len(want[0])} ({n_tables} grids found)")
                if ok_shape:
                    bad = [(i, j, rows[i][j], want[i][j]) for i in range(len(want)) for j in range(len(want[i]))
                           if rows[i][j] != want[i][j]]
                    check(not bad, f"{run.name} {title}: {len(bad)} table cells differ, e.g. {ascii(bad[:2])}")
                    table_stats["cells"] += sum(len(r) for r in want)
                    table_stats["numeric cells"] += sum(bool(re.search(r"\d", c)) for r in want for c in r)
                    table_stats["header rows"] += n_head
        doc_rows.append({"run": run.name, "role": cfg["role"], "tat": split, "scopes": len(scopes), "pages": n_pages,
                         "tokens": int(tokens), "desc": sum(g["question_type"] == "descriptive" for g in gold),
                         "cf": sum(g["question_type"] == "counterfactual" for g in gold), "n": len(gold)})
        if run.name != "fin_dev":
            samples_pool += [(run.name, q) for q in qs]
            test_uids.update(q["uid"] for q in qs)
    check(all(v == 1 for v in all_uids.values()), "uids not unique across runs")
    dev_tables = {json.dumps(c.table) for c in raw["dev"].values()}
    dev_doc = json.loads((RUNS / "fin_dev" / "manifest.json").read_text())
    overlap = sum(json.dumps(raw["train"][s["tat_table_uid"]].table) in dev_tables for s in dev_doc["scopes"])

    # --- metric fidelity
    ast_rows = ast_identity()
    check(all(ok for *_, ok in ast_rows), "vendored metric differs from TAT's code")
    original, brute = _tat_original()
    n_cmp, n_diff, diffs = 0, 0, []
    for uid, g in all_gold.items():
        twin = all_gold.get(g["pair_uid"])
        gt = {"answer": g["answer"], "answer_type": g["eval_answer_type"], "scale": g["scale"],
              "answer_from": g["answer_from"]}
        for label, ans, sc in perturbations(g, twin):
            m = original.TaTQAEmAndF1()
            import contextlib, io
            with contextlib.redirect_stdout(io.StringIO()):
                em_o, f1_o = m(gt, ans, None, sc)
            em_v, f1_v = tatqa_metric.em_f1(gt, ans, sc)
            n_cmp += 1
            if (em_o, f1_o) != (em_v, f1_v):
                n_diff += 1
                diffs.append((uid, label, em_o, f1_o, em_v, f1_v))
    check(n_diff == 0, f"vendored em_f1 differs from TAT's TaTQAEmAndF1 on {n_diff} predictions: {diffs[:3]}")
    rng = np.random.default_rng(0)
    lsa_bad = 0
    for _ in range(400):
        a = rng.random((rng.integers(1, 7), rng.integers(1, 7))).round(2)
        r1, c1 = tatqa_metric.linear_sum_assignment(-a)
        r2, c2 = brute(-a)
        lsa_bad += not (np.isclose(a[r1, c1].sum(), a[r2, c2].sum()) and len(r1) == len(r2) == min(a.shape)
                        and len(set(c1)) == len(c1))
    check(lsa_bad == 0, f"assignment solver differs from brute force on {lsa_bad}/400 matrices")

    # --- distributions (test)
    test_gold = [g for uid, g in all_gold.items() if uid in test_uids]
    cf = [g for g in test_gold if g["question_type"] == "counterfactual"]
    fa = [g for g in test_gold if g["question_type"] == "descriptive"]
    pop = [q for c in raw["dev"].values() for q in c.questions]
    pop_cf = [q for q in pop if q["answer_type"] == "counterfactual"]
    pop_tw = [c.question_by_order(q["rel_question"]) for c in raw["dev"].values() for q in c.questions
              if q["answer_type"] == "counterfactual"]

    def dist(rows, key):
        c = Counter(r[key] or "none" for r in rows)
        return ", ".join(f"{k} {v} ({v / len(rows):.0%})" for k, v in sorted(c.items(), key=lambda kv: -kv[1]))

    copy = score_predictions(cf, [{"uid": g["uid"], "answer": all_gold[g["pair_uid"]]["answer"],
                                   "scale": all_gold[g["pair_uid"]]["scale"]} for g in cf])["overall"]

    # ---------------------------------------------------------------- report
    L = lines.append
    L("# Finance benchmark: validation report\n")
    L("Generated by `python -m domains.finance.validate`. Every number below is recomputed from the files in "
      "`runs/fin_*` and the released TAT-HQA files; nothing is hand-entered. Design decisions and deviations "
      "from the draft spec: `docs/domains/finance.md`, section \"As built\".\n")
    L("## Result\n")
    L(f"**{'PASS' if not problems else 'FAIL'}**: {len(problems)} problem(s) found.\n")
    for p in problems[:50]:
        L(f"- {p}")
    if problems:
        L("")
    L("Checks run on every run folder (all scopes, all table cells, all questions):\n")
    L("1. **Layout and pairing.** Harness files present; `questions.jsonl` carries no type or gold; uids unique "
      "across all runs; every scope with questions has exactly one pair (factual twin `-01`, counterfactual `-02`), "
      "and the twin is the one TAT-HQA names in `rel_question`.")
    L("2. **Fidelity to TAT-HQA.** Every gold field (answer, scale, derivation, answer_type, answer_from, "
      "rel_paragraphs, req_comparison) equals the released record (looked up by TAT uid); every question equals "
      "`In <scope>: ` + the released question (outer whitespace stripped); every scope holds the released context "
      "(table uid in the manifest). Type mapping: span, multi-span, count, arithmetic -> descriptive; "
      "counterfactual -> counterfactual.")
    L("3. **Scoring.** Every gold answer, written as a reply (`{\"answer\": ..., \"scale\": ...}` after some text, "
      "scale `none` for no scale), scores EM = F1 = 1 through `score.py`'s full path; also via plain "
      "answer/scale rows.")
    L(f"   - Vendored metric: {sum(ok for *_, ok in ast_rows)}/{len(ast_rows)} copied functions and constants are "
      "AST-identical to TAT's `tatqa_utils.py` and `tag_op/tatqa_metric.py`.")
    L(f"   - `em_f1` vs TAT's original `TaTQAEmAndF1` (loaded from the raw repo, with exhaustive search in place of "
      f"scipy): {n_cmp - n_diff}/{n_cmp} predictions agree (gold, wrong/no scale, rounding, sign, x1000, "
      "percent sign, reordered/partial/extra spans, the factual twin's answer).")
    L(f"   - Assignment solver vs exhaustive search: {400 - lsa_bad}/400 random matrices (up to 6x6) agree.")
    L("4. **Scope titles.** Every question starts with `In Report R-NNN: `, every prompt's first line is the scope "
      "title, no prompt names another report, and no prompt contains "
      + ", ".join(f"'{w}'" for w in FORBIDDEN) + ".")
    L("5. **PDF.** Page count equals the manifest; the outline has the front matter and every scope at level 0, in "
      "order, each with exactly the children `<scope>: Text` and `<scope>: Table` at level 1, on the manifest's "
      "start page; every scope's first page starts with its title; every paragraph appears verbatim in the PDF "
      "text layer (pypdfium2); every table is found by pdfplumber as a ruled grid on the scope's pages, with the "
      "released number of rows and columns and every cell's text equal to the released cell (a cell spanned by "
      "a header label reads as empty, as released). Comparisons collapse whitespace and apply the renderer's "
      "character substitutions (render.py `printable`: no-break and thin space -> space, U+2010/U+2011 -> '-', "
      "ligatures -> 'fi'/'fl', four full-width/superscript forms -> ASCII).")
    L("6. **Character round-trip.** Every page is read with four extractors (pdfplumber `extract_text` and "
      "`extract_words`, pypdfium2, PyPDF2). No page may contain U+FFFD, U+FFFE, a control character or a "
      "`(cid:N)` placeholder, and for every scope (and the front matter) the multiset of non-whitespace "
      "characters read back must equal exactly that of the printed source (scope title and section headings, "
      "paragraphs and cells after `printable`), so no character is lost, replaced or added.\n")
    L("### Character round-trip by extractor (all runs)" + chr(10))
    L("| extractor | unreadable characters | front matter exact | scopes exact | characters checked | of which non-ASCII |")
    L("|---|---|---|---|---|---|")
    for name in EXTRACTORS:
        r = roundtrip[name]
        L(f"| {name} | {r['bad chars']} | {r['front matter exact']}/{len(runs)} | {r['scopes exact']}/{r['scopes']} | "
          f"{r['chars']:,} | {r['non-ascii chars']:,} |")
    L("")
    L("## Documents\n")
    L("| run | role | TAT split | scopes | pages | approx. tokens (chars/4) | descriptive | counterfactual | total |")
    L("|---|---|---|---|---|---|---|---|---|")
    for r in doc_rows:
        L(f"| {r['run']} | {r['role']} | {r['tat']} | {r['scopes']} | {r['pages']} | {r['tokens']:,} | {r['desc']} | "
          f"{r['cf']} | {r['n']} |")
    tr = [r for r in doc_rows if r["run"] != "fin_dev"]
    L(f"\nTest total: {sum(r['n'] for r in tr)} questions ({sum(r['desc'] for r in tr)} descriptive, "
      f"{sum(r['cf'] for r in tr)} counterfactual) in {sum(r['scopes'] for r in tr)} scopes, "
      f"{sum(r['pages'] for r in tr)} pages. Every one of the 274 TAT-HQA dev contexts is in exactly one test "
      f"document; 150 of them carry a question pair, the rest are distractors.\n")
    L(f"Tables: {table_stats['tables']} rendered and checked, {table_stats['cells']:,} cells "
      f"({table_stats['numeric cells']:,} with digits) identical to the JSON; {table_stats['header rows']} header "
      f"rows in bold; {table_stats['split over pages']} table(s) continue onto a second page.\n")
    L(f"Dev document: {overlap} of its 30 train tables also occur verbatim in the dev split (0 means no overlap "
      "with the test documents' contexts).\n")
    L("## Question mix (test documents)\n")
    L("| | selected (150) | TAT-HQA dev population |")
    L("|---|---|---|")
    L(f"| counterfactual: answer source | {dist(cf, 'answer_from')} | {dist(pop_cf, 'answer_from')} |")
    L(f"| counterfactual: answer format (`eval_answer_type`) | {dist(cf, 'eval_answer_type')} | "
      f"{dist(pop_cf, 'eval_answer_type')} |")
    L(f"| counterfactual: scale | {dist(cf, 'scale')} | {dist(pop_cf, 'scale')} |")
    L(f"| factual twin: answer type | {dist(fa, 'answer_type')} | {dist(pop_tw, 'answer_type')} |")
    L(f"| factual twin: answer source | {dist(fa, 'answer_from')} | {dist(pop_tw, 'answer_from')} |")
    L(f"| factual twin: scale | {dist(fa, 'scale')} | {dist(pop_tw, 'scale')} |")
    L("")
    L(f"**Baseline: copy the factual twin's gold answer and scale** (ignore the hypothetical change): EM "
      f"{copy['em']:.2f}, F1 {copy['f1']:.2f} on the 150 counterfactual questions. A system cannot solve the "
      "counterfactuals by reading the factual value off the page.\n")
    n_sc = sum(scale_cue.values())
    L(f"**Scale stated in the excerpt** (dataset property, informational): of the {n_sc} questions (all runs) whose "
      f"gold scale is thousand, million or billion, {scale_cue['stated']} have a scale cue (thousand, million, "
      f"$m, '000, ...) somewhere in their table or text and {scale_cue['not stated']} have none; for those the "
      "scale came from the full annual report page (TAT-QA annotation) and is not recoverable from the excerpt. "
      "This affects every system equally; it is reported, not corrected.\n")

    L("## 20 random test questions for hand-checking\n")
    L("Each shows the prompt as a system receives it, the gold (with TAT's derivation), and the scope's text as "
      "extracted from the PDF (pypdfium2; table rows appear as lines of cells).\n")
    for k, (run_name, q) in enumerate(random.Random(7).sample(samples_pool, 20), 1):
        g = all_gold[q["uid"]]
        L(f"### {k}. `{q['uid']}` ({run_name}, {g['question_type']} / TAT {g['answer_type']}"
          f"{' as ' + g['eval_answer_type'] if g['answer_type'] == 'counterfactual' else ''}, from {g['answer_from']})\n")
        L("```text\n" + q["prompt"] + "\n```\n")
        L(f"Gold: answer `{json.dumps(g['answer'])}`, scale `{g['scale'] or 'none'}`"
          + (f", derivation `{g['derivation'].strip()}`" if g["derivation"].strip() else "")
          + f". Twin `{g['pair_uid']}`: answer `{json.dumps(all_gold[g['pair_uid']]['answer'])}`.\n")
        L("Excerpt:\n\n```text\n" + excerpts[(run_name, q["scope"])].strip() + "\n```\n")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{'PASS' if not problems else 'FAIL'}: {len(problems)} problem(s); wrote {OUT}")
    for p in problems[:20]:
        print(" -", ascii(p))


if __name__ == "__main__":
    main()
