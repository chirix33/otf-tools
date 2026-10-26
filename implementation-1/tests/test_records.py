"""Toy tests for OTF v3 (gate G2): record matching, blinding, the step-1 probes, the forecast check, patches and
divergence replay, on two tiny hand-made documents (no PDF, no LLM). Run: python -m pytest tests
(or python tests/test_records.py)."""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from otf import records, toolgen  # noqa: E402
from otf.engine import OTFEngine  # noqa: E402


# ---------- a timed toy: level(t) = level(t-1) + amount(t), per unit ----------
def timed_nav():
    nodes, k = [], 0
    for s, amounts in (("Unit A", [3, 0, 2, 0, 4, 0, 1, 0]), ("Unit B", [1, 1, 0, 5, 0, 0, 2, 2]),
                       ("Unit C", [0, 2, 2, 0, 0, 3, 0, 1])):
        level, rows = 10, []
        for t, a in enumerate(amounts, start=1):
            level += a
            rows.append([str(t), s[-1], str(a), str(level)])
        root, log = f"n{k:04d}", f"n{k + 1:04d}"
        nodes.append({"node_id": root, "title": s, "level": 0, "parent_id": None, "kind": "text", "text": "",
                      "pages": [1, 1], "children": [log]})
        nodes.append({"node_id": log, "title": f"{s}: Log", "level": 1, "parent_id": root, "kind": "table",
                      "pages": [1, 1], "children": [], "table": {"columns": ["t", "who", "amount", "level"], "rows": rows}})
        k += 2
    return {"document_id": "toy", "source_files": [], "intro_text": "Each unit starts at level 10; every step adds "
            "the amount to the level.", "nodes": nodes}


READERS_T = r'''
def _log(doc, scope):
    return node_by_title(doc, scope + ": Log")

def entities(doc, scope):
    return [{"id": scope[-1], "description": scope}]

def recorded_end(doc, scope):
    return float(max(int(r["t"]) for _, r in table_rows(_log(doc, scope))))

def inputs(doc, scope):
    n = _log(doc, scope)
    out = [{"id": "start", "time": 0.0, "kind": "start", "entities": [scope[-1]], "fields": {"level": 10},
            "src": [[n["node_id"], 0, ["who"]]]}]
    for i, r in table_rows(n):
        out.append({"id": "a" + r["t"], "time": float(r["t"]), "kind": "amount", "entities": [r["who"]],
                    "fields": {"amount": float(r["amount"])}, "src": [[n["node_id"], i, ["t", "who", "amount"]]]})
    return out

def outcomes(doc, scope):
    n = _log(doc, scope)
    return [{"time": float(r["t"]), "kind": "level", "entities": [r["who"]], "value": float(r["level"]),
             "src": [[n["node_id"], i, ["level"]]]} for i, r in table_rows(n) if r["level"] != ""]
'''

SIM_HONEST = r'''
def simulate(doc, scope, inputs, params, start=None, horizon=None):
    start = 0.0 if start is None else start
    level = next(r["fields"]["level"] for r in inputs if r["kind"] == "start")
    for o in outcomes(doc, scope):                 # state at start from the records at or before start
        if o["time"] <= start:
            level = o["value"]
    out = []
    for r in sorted((r for r in inputs if r["kind"] == "amount"), key=lambda r: r["time"]):
        if r["time"] > start and (horizon is None or r["time"] <= horizon):
            level += r["fields"]["amount"]
            out.append({"time": r["time"], "kind": "level", "entities": r["entities"], "value": level})
    return out
'''

SIM_REPLAY = r'''
def simulate(doc, scope, inputs, params, start=None, horizon=None):
    return [o for o in outcomes(doc, scope) if start is None or o["time"] > start]
'''

SIM_DEAF = r'''
def simulate(doc, scope, inputs, params, start=None, horizon=None):
    level, out = 10.0, []
    for i, r in table_rows(node_by_title(doc, scope + ": Log")):
        if r["amount"] != "":
            level += float(r["amount"])
            if float(r["t"]) > (start or 0):
                out.append({"time": float(r["t"]), "kind": "level", "entities": [r["who"]], "value": level})
    return out
'''


# ---------- a timeless toy: total = a + b, per row ----------
def timeless_nav():
    nodes = []
    for k, (s, rows) in enumerate((("Sheet 1", [["x", "3", "4"], ["y", "10", "5"]]),
                                    ("Sheet 2", [["x", "1", "1"], ["z", "7", "2"]]))):
        root, tab = f"n{2 * k:04d}", f"n{2 * k + 1:04d}"
        nodes.append({"node_id": root, "title": s, "level": 0, "parent_id": None, "kind": "text", "text": "",
                      "pages": [1, 1], "children": [tab]})
        nodes.append({"node_id": tab, "title": f"{s}: Table", "level": 1, "parent_id": root, "kind": "table",
                      "pages": [1, 1], "children": [], "table": {"columns": ["label", "a", "b", "total"],
                      "rows": [r + [str(int(r[1]) + int(r[2]))] for r in rows]}})
    return {"document_id": "toy2", "source_files": [], "intro_text": "total = a + b.", "nodes": nodes}


READERS_TL = r'''
def _tab(doc, scope):
    return node_by_title(doc, scope + ": Table")

def entities(doc, scope):
    return [{"id": r["label"], "description": "row " + r["label"]} for _, r in table_rows(_tab(doc, scope))]

def recorded_end(doc, scope):
    return None

def inputs(doc, scope):
    n = _tab(doc, scope)
    return [{"id": r["label"] + c, "time": None, "kind": c, "entities": [r["label"]], "fields": {"value": float(r[c])},
             "src": [[n["node_id"], i, ["label", c]]]} for i, r in table_rows(n) for c in ("a", "b")]

def outcomes(doc, scope):
    n = _tab(doc, scope)
    return [{"time": None, "kind": "total", "entities": [r["label"]], "value": float(r["total"]),
             "src": [[n["node_id"], i, ["total"]]]} for i, r in table_rows(n) if r["total"] != ""]

def simulate(doc, scope, inputs, params, start=None, horizon=None):
    tot = {}
    for r in inputs:
        tot[r["entities"][0]] = tot.get(r["entities"][0], 0.0) + r["fields"]["value"]
    return [{"time": None, "kind": "total", "entities": [e], "value": v} for e, v in tot.items()]
'''


def _map(nav, d):
    p = Path(d) / "navmap.json"
    p.write_text(json.dumps(nav))
    return p


def test_record_f1_and_diff():
    h = [{"time": 5, "kind": "level", "entities": ["A"], "value": 100.0},
         {"time": 9, "kind": "event", "entities": ["A", "B"], "value": None}]
    p = [{"time": 5.2, "kind": "Level", "entities": ["A"], "value": 103.0},
         {"time": 30, "kind": "event", "entities": ["B", "A"], "value": None}]
    f1, missed, extra = records.record_f1(h, p, tol_t=1.0, vtol={})
    assert abs(f1 - 0.5) < 1e-9 and missed[0]["time"] == 9 and extra[0]["time"] == 30
    d = records.diff(h, [{**h[0], "value": 50.0}], 1.0, {})
    assert len(d["changed"]) == 1 and d["gone"] == [h[1]]


def test_blinding_keeps_inputs_hides_outcomes():
    nav = timed_nav()
    with tempfile.TemporaryDirectory() as d:
        r = toolgen.read_scope(READERS_T + SIM_HONEST, _map(nav, d), "Unit A")
    cut = toolgen._cut(r)
    b = records.blind(nav, "Unit A", r["inputs"], r["outcomes"], cut)
    rows = next(n for n in b["nodes"] if n["title"] == "Unit A: Log")["table"]["rows"]
    assert all(row[2] != "" for row in rows) and all(row[3] == "" for row in rows)   # amounts kept, levels hidden
    untouched = next(n for n in b["nodes"] if n["title"] == "Unit B: Log")
    assert untouched == next(n for n in nav["nodes"] if n["title"] == "Unit B: Log")


def test_honest_model_passes_replay_and_deaf_fail():
    nav = timed_nav()
    with tempfile.TemporaryDirectory() as d:
        mp = _map(nav, d)
        assert toolgen.check_parsers(READERS_T, nav, mp)["passed"]
        good = toolgen.check_model(READERS_T + SIM_HONEST, nav, mp)
        assert good["passed"] and good["mean_f1"] == 1.0, toolgen.short_report(good)
        replay = toolgen.check_model(READERS_T + SIM_REPLAY, nav, mp)
        assert not replay["passed"] and replay["mean_f1"] == 0.0
        deaf = toolgen.check_model(READERS_T + SIM_DEAF, nav, mp)
        assert deaf["mean_f1"] == 1.0 and not deaf["sensitive"] and not deaf["passed"]


def test_step1_probes_catch_mislabelled_readers():
    nav = timed_nav()
    with tempfile.TemporaryDirectory() as d:
        mp = _map(nav, d)
        # an input and an outcome may share the row's time and entity cells
        shared = READERS_T.replace('"src": [[n["node_id"], i, ["level"]]]', '"src": [[n["node_id"], i, ["t", "who", "level"]]]')
        assert toolgen.check_parsers(shared, nav, mp)["passed"]
        # but the outcome's own value read as an input too stays visible on the copy: the replay probe fails it
        both = READERS_T.replace('["t", "who", "amount"]', '["t", "who", "amount", "level"]')
        assert "still finds them" in toolgen.check_parsers(both, nav, mp)["error"]
        # a reader that finds nothing is told what it returned and which rows it did not read
        blind_reader = READERS_T.replace('if r["level"] != ""]', 'if r["level"] == "never"]')
        err = toolgen.check_parsers(blind_reader, nav, mp)["error"]
        assert "WHAT YOUR FUNCTIONS RETURNED" in err and "0 outcomes" in err, err
        # an input reads a cell it does not list in src: it changes once outcomes are hidden
        sneaky = READERS_T.replace('"fields": {"amount": float(r["amount"])}',
                                   '"fields": {"amount": float(r["amount"]), "lvl": r["level"]}')
        assert "reads differently" in toolgen.check_parsers(sneaky, nav, mp)["error"]
        # outcomes read from cells that are not their src are still found on the blinded copy
        leaky = READERS_T.replace('"src": [[n["node_id"], i, ["level"]]]} for i, r in table_rows(n) if r["level"] != ""',
                                  '"src": [[n["node_id"], i, ["t"]]]} for i, r in table_rows(n) if r["level"] != ""')
        rep = toolgen.check_parsers(leaky, nav, mp)
        assert not rep["passed"], rep


def test_schedule_rows_are_not_outcomes():
    """Value-less records, one per row of a table at regular times, only mark that a row exists: a reader whose
    only outcomes are such rows is rejected, and a model forecasting them cannot pass. Sparse events stay."""
    nav = timed_nav()
    idx = {n["node_id"]: n for n in nav["nodes"]}
    log = next(n for n in nav["nodes"] if n["title"] == "Unit A: Log")["node_id"]
    rows = [{"time": float(t), "kind": "row", "entities": ["A"], "value": None, "src": [[log, t - 1]]} for t in range(1, 9)]
    assert records.schedule_kinds(rows, idx) == {"row"}
    events = [{"time": 3.0, "kind": "peak", "entities": ["A"], "value": None, "src": [[log, 2]]},
              {"time": 7.0, "kind": "peak", "entities": ["A"], "value": None, "src": [[log, 6]]}]
    assert records.schedule_kinds(events + rows[:3], idx) == set()           # sparse, and too few rows
    ticks = READERS_T.split("def outcomes")[0] + r'''
def outcomes(doc, scope):
    n = _log(doc, scope)
    return [{"time": float(r["t"]), "kind": "row", "entities": [r["who"]], "value": None,
             "src": [[n["node_id"], i, ["t", "who", "level"]]]} for i, r in table_rows(n)]
'''
    with tempfile.TemporaryDirectory() as d:
        rep = toolgen.check_parsers(ticks, nav, _map(nav, d))
        assert not rep["passed"] and "regularly spaced times" in rep["error"], rep


def test_unread_trajectory_is_blinded():
    """Post-freeze bug fix 9: a timed table no record is read from (here a track mirroring the levels) is hidden
    after the cut too, so a simulator cannot forecast by reading it; tables without a time axis stay."""
    nav = timed_nav()
    for n in list(nav["nodes"]):
        if n["kind"] == "table":
            k = len(nav["nodes"])
            track = {"node_id": f"t{k:04d}", "title": n["title"].replace("Log", "Track"), "level": 1,
                     "parent_id": n["parent_id"], "kind": "table", "pages": [1, 1], "children": [],
                     "table": {"columns": ["step", "reading"], "rows": [[r[0], r[3]] for r in n["table"]["rows"]]}}
            static = {"node_id": f"s{k:04d}", "title": n["title"].replace("Log", "Spec"), "level": 1,
                      "parent_id": n["parent_id"], "kind": "table", "pages": [1, 1], "children": [],
                      "table": {"columns": ["part", "size"], "rows": [["p", "4"], ["q", "2"], ["r", "9"]]}}
            nav["nodes"] += [track, static]
            next(m for m in nav["nodes"] if m["node_id"] == n["parent_id"])["children"] += [track["node_id"],
                                                                                          static["node_id"]]
    peek = r'''
def simulate(doc, scope, inputs, params, start=None, horizon=None):
    return [{"time": float(r["step"]), "kind": "level", "entities": [scope[-1]], "value": float(r["reading"])}
            for _, r in table_rows(node_by_title(doc, scope + ": Track")) if float(r["step"]) > (start or 0)]
'''
    with tempfile.TemporaryDirectory() as d:
        mp = _map(nav, d)
        r = toolgen.read_scope(READERS_T + SIM_HONEST, mp, "Unit A")
        cut = toolgen._cut(r)
        b = records.blind(nav, "Unit A", r["inputs"], r["outcomes"], cut, (r["t0"], r["end"]))
        track = next(n for n in b["nodes"] if n["title"] == "Unit A: Track")["table"]["rows"]
        assert len(track) < 8 and all(float(row[0]) <= cut for row in track)
        assert next(n for n in b["nodes"] if n["title"] == "Unit A: Spec")["table"]["rows"] == [["p", "4"], ["q", "2"], ["r", "9"]]
        assert toolgen.check_model(READERS_T + SIM_HONEST, nav, mp)["passed"]
        assert toolgen.check_model(READERS_T + peek, nav, mp)["mean_f1"] == 0.0


def test_paired_delta_cancels_model_error():
    """v3.4: a what-if applies the difference between the model run without and with the change to the record. A
    value the model gets wrong in both runs keeps its recorded value; an outcome the model reproduces late is still
    recognised; one it never reproduces is judged by the changed run alone (as before v3.4)."""
    rec = [{"time": 5.0, "kind": "hit", "entities": ["A", "B"], "value": None},
           {"time": 7.0, "kind": "hit", "entities": ["B", "C"], "value": None},
           {"time": 9.0, "kind": "level", "entities": ["C"], "value": 10.0},
           {"time": 9.0, "kind": "stock", "entities": ["D"], "value": 500.0}]
    base = [{"time": 6.5, "kind": "hit", "entities": ["A", "B"], "value": None},       # reproduced late
            {"time": 9.0, "kind": "level", "entities": ["C"], "value": 10.0},
            {"time": 9.0, "kind": "stock", "entities": ["D"], "value": 0.0}]           # wrong in both runs
    new = [{"time": 9.0, "kind": "level", "entities": ["C"], "value": 12.0},            # A-B gone, level changes
           {"time": 9.0, "kind": "stock", "entities": ["D"], "value": 0.0},
           {"time": 8.0, "kind": "hit", "entities": ["A", "C"], "value": None}]
    out = records.apply_delta(rec, base, new, 0.5, {}, None, 4.0, 10.0)
    kinds = {(o["time"], o["kind"], tuple(o["entities"])): o.get("value") for o in out}
    assert (5.0, "hit", ("A", "B")) not in kinds                                     # removed by the change
    assert kinds[(9.0, "stock", ("D",))] == 500.0                                    # model error cancels out
    assert (7.0, "hit", ("B", "C")) not in kinds                                     # never reproduced, not in new run
    assert kinds[(9.0, "level", ("C",))] == 12.0 and (8.0, "hit", ("A", "C")) in kinds


def test_timeless_check():
    nav = timeless_nav()
    with tempfile.TemporaryDirectory() as d:
        mp = _map(nav, d)
        assert toolgen.check_parsers(READERS_TL, nav, mp)["passed"]
        rep = toolgen.check_model(READERS_TL, nav, mp)
        assert rep["passed"] and rep["mean_f1"] == 1.0 and rep["sensitive"], toolgen.short_report(rep)
        copy = READERS_TL.split("def simulate")[0] + SIM_REPLAY
        assert not toolgen.check_model(copy, nav, mp)["passed"]


def test_patch_ops():
    ins = [{"id": "s", "time": None, "kind": "start", "entities": ["A"], "fields": {"level": 10}},
           {"id": "a1", "time": 1.0, "kind": "amount", "entities": ["A"], "fields": {"amount": 3.0}},
           {"id": "a2", "time": 2.0, "kind": "amount", "entities": ["A"], "fields": {"amount": 5.0}},
           {"id": "b1", "time": 4.0, "kind": "amount", "entities": ["B"], "fields": {"amount": 1.0}}]
    outs = [{"time": None, "kind": "total", "entities": ["T"], "value": 9.0}]
    names = {"A": "unit a", "B": "unit b", "T": "the total"}
    ap = records.apply_patches(ins, {"cap": 8.0}, outs, [{"op": "remove", "select": {"entity": "unit b"}}], names)
    assert [r["id"] for r in ap["inputs"]] == ["s", "a1", "a2"] and ap["t_c"] == 4.0 and ap["touched"] == {"B"}
    ap = records.apply_patches(ins, {}, outs, [{"op": "set", "select": {"entity": "A", "kind": "amount", "time": 2},
                                                "field": "amount", "value": 0}], names)
    assert ap["inputs"][2]["fields"]["amount"] == 0 and ap["t_c"] == 2.0
    ap = records.apply_patches(ins, {}, outs, [{"op": "scale", "select": {"entity": "A", "from": 1, "to": 2},
                                                "factor": 2}], names)
    assert [r["fields"]["amount"] for r in ap["inputs"][1:3]] == [6.0, 10.0]
    ap = records.apply_patches(ins, {}, outs, [{"op": "shift", "select": {"entity": "A", "time": 1}, "by": 3}], names)
    assert ap["inputs"][1]["time"] == 4.0 and ap["t_c"] == 1.0
    ap = records.apply_patches(ins, {"cap": 8.0}, outs, [{"op": "scale", "param": "cap", "factor": 0.5, "from": 3}], names)
    assert ap["params"]["cap"] == 4.0 and ap["t_c"] == 3.0 and not ap["touched"]
    ap = records.apply_patches(ins, {}, outs, [{"op": "add", "record": {"time": 3, "kind": "amount",
                                                "entities": ["unit a"], "fields": {"amount": 1}}}], names)
    assert ap["inputs"][-1]["entities"] == ["A"] and ap["t_c"] == 3
    ap = records.apply_patches(ins, {}, outs, [{"op": "scale", "select": {"entity": "T"}, "factor": 0.8}], names)
    assert ap["overrides"] and records.apply_overrides(outs, ap["overrides"])[0]["value"] == 9.0 * 0.8
    ap = records.apply_patches(ins, {}, outs, [{"op": "remove", "select": {"entity": "nobody"}}], names)
    assert ap["errors"]


def test_divergence_replay():
    nav = timed_nav()
    with tempfile.TemporaryDirectory() as d:
        e = OTFEngine(lambda m: "", Path(d))
        e.nav, e.map_path = nav, _map(nav, d)
        e.scopes, e.model = toolgen.scopes(nav), {"code": READERS_T + SIM_HONEST, "passed": True}
        r = e._records("Unit A")
        w = e._what_if("Unit A", r, [{"op": "set", "select": {"entity": "A", "kind": "amount", "time": 5},
                                      "field": "amount", "value": 0}])
        assert abs(w["t_star"] - 5.0) < 1e-9                       # recorded until the change can first matter
        lv = {o["time"]: o["value"] for o in w["trace"]}
        assert lv[4.0] == 15.0 and lv[5.0] == 15.0 and lv[8.0] == 16.0
        w = e._what_if("Unit A", r, [{"op": "remove", "select": {"entity": "A", "time": 8}}])
        assert {o["time"] for o in w["trace"]} == {1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0}


if __name__ == "__main__":
    for name, f in list(globals().items()):
        if name.startswith("test_"):
            f()
            print("ok", name)
