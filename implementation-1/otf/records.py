"""Records: the common currency of OTF v3, and the deterministic code that works on them.

A scope's records split into inputs (given to the process from outside), outcomes (produced by it) and
constants (`params`). Every input and outcome points back to the cells or lines it was read from (`src`), so the
forecast check can hide exactly the outcomes and keep the inputs. Time is optional: a scope whose
`recorded_end` is None is timeless (outcomes are computed from inputs, not run forward).

    input   {"id", "time": float|None, "kind", "entities": [ids], "fields": {name: value}, "src": [loc, ...]}
    outcome {"time": float|None, "kind", "entities": [ids], "value": number|None, "src": [loc, ...]}
    loc     [node_id, row] | [node_id, row, [columns]] | [node_id, line]

What-if questions become patches (small JSON edits of inputs or constants) applied here, outside the generated
code, so the function used for what-ifs is exactly the one that passed the check.
"""
from __future__ import annotations

import copy
import json
import math
import re

INF = float("inf")


# ---------- small accessors ----------
def rtime(r: dict) -> float | None:
    t = r.get("time")
    try:
        return None if t is None or t == "" else float(t)
    except (TypeError, ValueError):
        return None


def ents(r: dict) -> frozenset:
    return frozenset(str(e) for e in (r.get("entities") or []))


def num(v) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        x = float(str(v).replace(",", ""))
        return x if math.isfinite(x) else None
    except ValueError:
        return None


def kind(r: dict) -> str:
    return str(r.get("kind", "")).strip().lower()


def strip_src(recs: list[dict]) -> list[dict]:
    return [{k: v for k, v in r.items() if k != "src"} for r in recs]


def canon(recs: list[dict]) -> list[str]:
    """Order-independent comparable form (src left out: row positions move when rows are hidden)."""
    return sorted(json.dumps(r, sort_keys=True, default=str) for r in strip_src(recs))


# ---------- matching ----------
def value_tols(outcomes: list[dict]) -> dict:
    """Per kind: 5% of the range of its recorded values in the scope."""
    by: dict = {}
    for o in outcomes:
        v = num(o.get("value"))
        if v is not None:
            by.setdefault(kind(o), []).append(v)
    return {k: 0.05 * (max(v) - min(v)) for k, v in by.items()}


def _value_close(h: dict, p: dict, vtol: dict, rel: float = 0.05) -> bool:
    vh = num(h.get("value"))
    if vh is None:
        return True
    vp = num(p.get("value"))
    return vp is not None and abs(vh - vp) <= max(vtol.get(kind(h), 0.0), rel * abs(vh), 1e-9)


def _match(h: dict, p: dict, tol_t: float, vtol: dict | None) -> bool:
    """Same kind, same entity set, close in time; and close in value unless vtol is None."""
    if kind(h) != kind(p) or ents(h) != ents(p):
        return False
    th, tp = rtime(h), rtime(p)
    if (th is None) != (tp is None) or (th is not None and abs(th - tp) > tol_t):
        return False
    return vtol is None or _value_close(h, p, vtol)


def pairs(a: list[dict], b: list[dict], tol_t: float, vtol: dict | None):
    """Greedy one-to-one matching of a against b, closest time first. Returns (pairs, unmatched a, unmatched b)."""
    used, out, missed = set(), [], []
    for h in sorted(a, key=lambda r: (rtime(r) is None, rtime(r) or 0.0)):
        cands = [j for j, p in enumerate(b) if j not in used and _match(h, p, tol_t, vtol)]
        if not cands:
            missed.append(h)
            continue
        j = min(cands, key=lambda j: abs((rtime(b[j]) or 0.0) - (rtime(h) or 0.0)))
        used.add(j)
        out.append((h, b[j]))
    return out, missed, [p for j, p in enumerate(b) if j not in used]


def record_f1(hidden: list[dict], predicted: list[dict], tol_t: float, vtol: dict | None = None):
    """F1 of the predicted records against the hidden ones. Returns (f1, missed, extra)."""
    vtol = value_tols(hidden) if vtol is None else vtol
    matched, missed, extra = pairs(hidden, predicted, tol_t, vtol)
    if not hidden and not predicted:
        return 1.0, [], []
    p = len(matched) / len(predicted) if predicted else 0.0
    r = len(matched) / len(hidden) if hidden else 0.0
    return (2 * p * r / (p + r) if p + r else 0.0), missed, extra


def diff(before: list[dict], after: list[dict], tol_t: float, vtol: dict, rel: float = 0.05) -> dict:
    """What changes from `before` to `after`: records that no longer happen, newly happen, or change value.
    tol_t=0, vtol={}, rel=0 compares exactly (two runs of the same model)."""
    matched, gone, new = pairs(before, after, tol_t, None)
    changed = [(b, a) for b, a in matched if not _value_close(b, a, vtol, rel)]
    return {"gone": gone, "new": new, "changed": changed}


# ---------- provenance ----------
def _node_index(nav: dict) -> dict:
    return {n["node_id"]: n for n in nav["nodes"]}


def descendants(nav: dict, scope: str) -> list[dict]:
    idx = _node_index(nav)
    root = next((n for n in nav["nodes"] if n["title"] == scope and n["level"] == 0), None)
    out, todo = [], list(root.get("children", [])) if root else []
    while todo:
        n = idx.get(todo.pop(0))
        if n is None:
            continue
        out.append(n)
        todo = list(n.get("children", [])) + todo
    return out


def cells_of(loc, nav_idx: dict):
    """The (node_id, row/line, column index or None) units a loc refers to, or raises ValueError."""
    if not isinstance(loc, (list, tuple)) or len(loc) < 2:
        raise ValueError(f"loc {loc!r} is not [node_id, row] / [node_id, row, [columns]] / [node_id, line]")
    nid, k = str(loc[0]), loc[1]
    n = nav_idx.get(nid)
    if n is None:
        raise ValueError(f"loc {loc!r}: no node with id {nid!r}")
    if not isinstance(k, int) or isinstance(k, bool):
        raise ValueError(f"loc {loc!r}: row/line must be an integer index")
    if n["kind"] == "table":
        rows, cols = n["table"]["rows"], n["table"]["columns"]
        if not 0 <= k < len(rows):
            raise ValueError(f"loc {loc!r}: row {k} out of range (table has {len(rows)} rows)")
        if len(loc) >= 3 and loc[2] is not None:
            out = []
            for c in loc[2]:
                j = c if isinstance(c, int) and not isinstance(c, bool) else (cols.index(c) if c in cols else None)
                if j is None or not 0 <= j < len(cols):
                    raise ValueError(f"loc {loc!r}: no column {c!r} (columns are {cols})")
                out.append((nid, k, j))
            return out
        return [(nid, k, j) for j in range(len(cols))]
    lines = n["lines"] if n["kind"] == "list" else n.get("text", "").splitlines()
    if not 0 <= k < len(lines):
        raise ValueError(f"loc {loc!r}: line {k} out of range (node has {len(lines)} lines)")
    return [(nid, k, None)]


def units(recs: list[dict], nav_idx: dict) -> set:
    out = set()
    for r in recs:
        for loc in r.get("src") or []:
            out.update(cells_of(loc, nav_idx))
    return out


# ---------- blinding ----------
def _first_number(text: str) -> float | None:
    m = re.search(r"(?<![\w.])[-+]?\d+(?:\.\d+)?(?![\w.])", text or "")     # a standalone number, not "T17"
    return float(m.group(0)) if m else None


def first_outcome_cut(outcomes: list[dict], t0: float, end: float | None) -> float | None:
    """Just before the scope's first timed outcome (None for timeless scopes)."""
    times = [t for t in (rtime(o) for o in outcomes) if t is not None]
    if end is None or not times:
        return None
    return min(times) - 0.01 * max(end - t0, 1e-9)


def blind(nav: dict, scope: str, inputs: list[dict], outcomes: list[dict], cut: float | None) -> dict:
    """A copy of the map in which `scope` keeps what a forward model may use. Kept: every cell or line an
    input was read from. Hidden: cells and lines of outcomes after `cut` (all outcomes if timeless), and, in
    tables or lists that timed records were read from, rows and lines whose time is after `cut`. Text nodes
    are emptied. Other scopes and the front matter are untouched."""
    blinded = copy.deepcopy(nav)
    idx = _node_index(blinded)
    keep = units(inputs, idx)
    hide = units([o for o in outcomes if cut is None or rtime(o) is None or rtime(o) > cut], idx)
    timed = [r for r in inputs + outcomes if rtime(r) is not None]
    row_t: dict = {}                                    # (node, row) -> time, from the records read from it
    for r in timed:
        for loc in r.get("src") or []:
            for nid, k, _ in cells_of(loc, idx):
                row_t[(nid, k)] = min(row_t.get((nid, k), INF), rtime(r))
    timed_nodes = {nid for nid, _ in row_t}
    for n in descendants(blinded, scope):
        nid = n["node_id"]
        if n["kind"] == "text":
            n["text"] = ""
            continue
        if n["kind"] == "list":
            kept = []
            for k, line in enumerate(n["lines"]):
                t = row_t.get((nid, k), _first_number(line) if nid in timed_nodes else None)
                hidden = (nid, k, None) not in keep and ((nid, k, None) in hide or (
                    cut is not None and t is not None and t > cut))
                if not hidden:
                    kept.append(line)
            n["lines"] = kept
            continue
        rows, cols = n["table"]["rows"], n["table"]["columns"]
        tcol = None
        if nid in timed_nodes:                          # the column whose cells equal the records' times
            refs = [(k, t) for (m, k), t in row_t.items() if m == nid]
            for j in range(len(cols)):
                if refs and all(k < len(rows) and j < len(rows[k]) and num(rows[k][j]) is not None
                                and abs(num(rows[k][j]) - t) < 1e-6 for k, t in refs):
                    tcol = j
                    break
        new_rows = []
        for k, row in enumerate(rows):
            t = row_t.get((nid, k))
            if t is None and nid in timed_nodes:
                t = num(row[tcol]) if tcol is not None and tcol < len(row) else next(
                    (num(c) for c in row if num(c) is not None), None)
            late = cut is not None and t is not None and t > cut
            out = [c if (nid, k, j) in keep or not ((nid, k, j) in hide or late) else "" for j, c in enumerate(row)]
            if any((nid, k, j) in keep or not ((nid, k, j) in hide or late) for j in range(len(row))):
                new_rows.append(out)
        n["table"]["rows"] = new_rows
    return blinded


# ---------- patches ----------
def _id_of(x, names: dict) -> str | None:
    """An entity id from an id or a description (case-insensitive)."""
    s = str(x)
    if s in names:
        return s
    low = s.strip().lower()
    hit = [i for i, d in names.items() if str(d).strip().lower() == low]
    return hit[0] if len(hit) == 1 else None


def select(recs: list[dict], sel: dict, names: dict) -> list[int]:
    """Indices of the records a selector picks: {"entity", "kind"?, "time"?, "from"?, "to"?}."""
    sel = sel or {}
    eid = _id_of(sel["entity"], names) if sel.get("entity") is not None else None
    if sel.get("entity") is not None and eid is None:
        return []
    out = []
    for i, r in enumerate(recs):
        if eid is not None and eid not in ents(r):
            continue
        if sel.get("kind") and kind(r) != str(sel["kind"]).strip().lower():
            continue
        t = rtime(r)
        if sel.get("time") is not None and (t is None or num(sel["time"]) is None or abs(t - num(sel["time"])) > 1e-6):
            continue
        if sel.get("from") is not None and (t is None or t < (num(sel["from"]) or -INF)):
            continue
        if sel.get("to") is not None and (t is None or t > (num(sel["to"]) if num(sel["to"]) is not None else INF)):
            continue
        out.append(i)
    return out


def _numeric_field(fields: dict, field) -> str | None:
    if field is not None:
        return str(field) if str(field) in fields else None
    nums = [k for k, v in fields.items() if num(v) is not None]
    return nums[0] if len(nums) == 1 else None


def apply_patches(inputs: list[dict], params: dict, outcomes: list[dict], patches: list[dict], names: dict,
                  t0: float = 0.0) -> dict:
    """Apply what-if patches. Returns {inputs, params, overrides, t_c, touched, errors}. `t_c` is the earliest
    time the change can take effect (None: timeless; t0 for a change without a time); `touched` the entities
    whose inputs changed; `overrides` edits of outcomes that are not computed from any input."""
    ins, prm = copy.deepcopy(inputs), dict(params or {})
    overrides, errors, touched, times = [], [], set(), []
    for p in patches or []:
        op = str(p.get("op", "")).lower()
        try:
            if p.get("param") is not None and op in ("set", "scale"):
                name = str(p["param"])
                if name not in prm or num(prm[name]) is None:
                    errors.append(f"no constant named {name!r} (constants: {sorted(prm)})")
                    continue
                prm[name] = num(p["value"]) if op == "set" else num(prm[name]) * num(p["factor"])
                times.append(num(p.get("from")) if p.get("from") is not None else t0)
                continue
            if op == "add":
                rec = dict(p.get("record") or {})
                rec.setdefault("id", f"added-{len(ins)}")
                rec.setdefault("fields", {})
                rec["entities"] = [(_id_of(e, names) or str(e)) for e in rec.get("entities", [])]
                ins.append(rec)
                touched |= ents(rec)
                times.append(rtime(rec) if rtime(rec) is not None else t0)
                continue
            hit = select(ins, p.get("select"), names)
            if not hit:
                ohit = select(outcomes, p.get("select"), names)
                if ohit and op in ("remove", "set", "scale"):
                    overrides.append({"op": op, "idx": ohit, "value": p.get("value"), "factor": p.get("factor")})
                    continue
                errors.append(f"patch {json.dumps(p)} selects no input")
                continue
            for i in hit:
                r = ins[i]
                touched |= ents(r)
                t = rtime(r)
                times.append(t if t is not None else t0)
                if op == "remove":
                    r["_removed"] = True
                elif op in ("set", "scale"):
                    f = _numeric_field(r.setdefault("fields", {}), p.get("field"))
                    if f is None:
                        errors.append(f"patch {json.dumps(p)}: input has no field {p.get('field')!r} "
                                      f"(fields: {sorted(r['fields'])})")
                        continue
                    r["fields"][f] = (p["value"] if op == "set" else num(r["fields"][f]) * num(p["factor"]))
                elif op == "shift":
                    if t is None:
                        errors.append(f"patch {json.dumps(p)}: input has no time")
                        continue
                    r["time"] = t + num(p["by"])
                    times.append(r["time"])
                else:
                    errors.append(f"unknown op {op!r}")
        except (KeyError, TypeError, ValueError) as e:
            errors.append(f"patch {json.dumps(p, default=str)}: {type(e).__name__}: {e}")
    ins = [r for r in ins if not r.pop("_removed", False)]
    timed = [t for t in times if t is not None]
    return {"inputs": ins, "params": prm, "overrides": overrides, "errors": errors, "touched": touched,
            "t_c": min(timed) if timed else None}


def apply_overrides(outcomes: list[dict], overrides: list[dict]) -> list[dict]:
    out = copy.deepcopy(outcomes)
    drop = set()
    for ov in overrides:
        for i in ov["idx"]:
            if i >= len(out):
                continue
            if ov["op"] == "remove":
                drop.add(i)
            elif ov["op"] == "set":
                out[i]["value"] = ov["value"]
            elif num(out[i].get("value")) is not None:
                out[i]["value"] = num(out[i]["value"]) * num(ov["factor"])
    return [o for i, o in enumerate(out) if i not in drop]


# ---------- presentation ----------
def focus(recs: list[dict], focus_ids: set, cap: int = 150) -> list[dict]:
    """At most `cap` records: those involving the focus entities first, then the earliest others."""
    if len(recs) <= cap:
        return sorted(recs, key=lambda r: (rtime(r) is None, rtime(r) or 0.0))
    first = [r for r in recs if ents(r) & focus_ids]
    rest = sorted((r for r in recs if not ents(r) & focus_ids), key=lambda r: rtime(r) or 0.0)
    return sorted((first + rest)[:cap], key=lambda r: (rtime(r) is None, rtime(r) or 0.0))


def fmt(r: dict, names: dict) -> str:
    who = ", ".join(f"{names.get(e, e)} (id {e})" for e in sorted(ents(r)))
    t = rtime(r)
    head = f"time {t:g}: " if t is not None else ""
    val = r.get("value") if "value" in r else None
    fields = r.get("fields")
    tail = f" = {val}" if val is not None else (f" {json.dumps(fields)}" if fields else "")
    return f"{head}{r.get('kind', 'record')} - {who or '(no entity)'}{tail}"


def fmt_list(recs: list[dict], names: dict) -> str:
    return "\n".join(fmt(r, names) for r in recs) if recs else "(none)"
