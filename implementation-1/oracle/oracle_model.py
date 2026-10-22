# Hand-written process model for the CLEVRER document (the "oracle tool" upper bound in the paper).
# Same interface and sandbox as the model-generated code (entities / recorded_end / observed_events /
# simulate), so the OTF engine can run it unchanged. It reads only what the document renders.
import math
import re

_OBJ = re.compile(r"Object\s+(\d+):\s*([^()]+?)\s*(\(|$)")
_EVT = re.compile(r"Frame\s+(\d+):\s*Object\s+(\d+)\s*\([^)]*\)\s*collides with\s*Object\s+(\d+)")


def _node(doc, scope, suffix):
    for n in doc["nodes"]:
        if n["title"] == f"{scope}: {suffix}":
            return n
    return None


def entities(doc, scope):
    n = _node(doc, scope, "Objects")
    out = []
    for line in (n or {}).get("lines", []):
        m = _OBJ.match(line)
        if m:
            out.append({"id": m.group(1), "description": m.group(2).strip()})
    return out


def _rows(doc, scope):
    n = _node(doc, scope, "Motion log")
    rows = []
    for r in (n or {}).get("table", {}).get("rows", []):
        try:
            rows.append((int(r[0]), r[1].split()[0], float(r[2]), float(r[3]), float(r[4]), float(r[5])))
        except (ValueError, IndexError):
            pass
    return rows


def recorded_end(doc, scope):
    rows = _rows(doc, scope)
    return float(max(r[0] for r in rows)) if rows else 127.0


def observed_events(doc, scope):
    n = _node(doc, scope, "Events")
    out = []
    for line in (n or {}).get("lines", []):
        m = _EVT.match(line)
        if m:
            out.append({"time": float(m.group(1)), "kind": "collision", "participants": [m.group(2), m.group(3)]})
    return out


_CAL = {}


def _calibrate(doc):
    """Global constants from every scope's full records: seconds per frame, per-frame speed decay, and the
    centre distance at which recorded collisions happen."""
    if "k" in _CAL:
        return _CAL["k"]
    spf, decay, dist = [], [], []
    for top in doc["nodes"]:
        if top["level"] != 0 or not top.get("children"):
            continue
        sc = top["title"]
        rows = _rows(doc, sc)
        by = {}
        for f, oid, x, y, vx, vy in rows:
            by.setdefault(oid, []).append((f, x, y, vx, vy))
        for tr in by.values():
            for (f0, x0, y0, vx0, vy0), (f1, x1, y1, vx1, vy1) in zip(tr, tr[1:]):
                s0, s1 = math.hypot(vx0, vy0), math.hypot(vx1, vy1)
                if f1 - f0 == 8 and s0 > 0.3 and s1 > 0.3 and abs(s1 - s0) / s0 < 0.08:   # free motion
                    d = math.hypot(x1 - x0, y1 - y0)
                    spf.append(d / (0.5 * (s0 + s1) * (f1 - f0)))
                    decay.append((s1 / s0) ** (1.0 / (f1 - f0)))
        at = {}
        for f, oid, x, y, vx, vy in rows:
            at[(f, oid)] = (x, y)
        for e in observed_events(doc, sc):
            f = int(e["time"]); a, b = e["participants"]
            if (f, a) in at and (f, b) in at:
                dist.append(math.dist(at[(f, a)], at[(f, b)]))
    med = lambda v, d: sorted(v)[len(v) // 2] if v else d
    k = {"spf": med(spf, 1 / 36.0), "decay": med(decay, 0.995), "dist": med(dist, 0.43)}
    _CAL["k"] = k
    return k


def simulate(doc, scope, removed=(), horizon=None, start=0.0):
    k = _calibrate(doc)
    removed = {str(r) for r in removed}
    rows = _rows(doc, scope)
    first, at_start = {}, {}
    for f, oid, x, y, vx, vy in rows:
        if oid not in first:
            first[oid] = (f, x, y, vx, vy)
        if f <= start:
            at_start[oid] = (f, x, y, vx, vy)          # latest recorded state at or before `start`
    end = horizon if horizon is not None else recorded_end(doc, scope)
    state, events, touching = {}, [], set()
    t0 = int(start)
    for oid, (f, x, y, vx, vy) in at_start.items():
        if oid in removed:
            continue
        st = [x, y, vx, vy]
        for _ in range(t0 - f):                         # advance from the record's time to `start`
            st[0] += st[2] * k["spf"]; st[1] += st[3] * k["spf"]; st[2] *= k["decay"]; st[3] *= k["decay"]
        state[oid] = st
    for t in range(t0 + 1, int(end) + 1):
        for oid, (f, x, y, vx, vy) in first.items():
            if f == t and f > t0 and oid not in removed:
                state[oid] = [x, y, vx, vy]
        for s in state.values():
            s[0] += s[2] * k["spf"]; s[1] += s[3] * k["spf"]
            s[2] *= k["decay"]; s[3] *= k["decay"]
        ids = sorted(state)
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                a, b = state[ids[i]], state[ids[j]]
                dx, dy = b[0] - a[0], b[1] - a[1]
                d = math.hypot(dx, dy)
                pair = (ids[i], ids[j])
                if d < k["dist"]:
                    if pair not in touching:
                        nx, ny = (dx / d, dy / d) if d > 1e-9 else (1.0, 0.0)
                        rel = (a[2] - b[2]) * nx + (a[3] - b[3]) * ny
                        if rel > 0:          # approaching: equal-mass elastic exchange of normal components
                            a[2] -= rel * nx; a[3] -= rel * ny
                            b[2] += rel * nx; b[3] += rel * ny
                            events.append({"time": float(t), "kind": "collision", "participants": [ids[i], ids[j]]})
                        touching.add(pair)
                else:
                    touching.discard(pair)
    return events
