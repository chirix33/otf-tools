"""Tier B verification (plan sec. 5), against tests/mock_vllm.py instead of a GPU server.

    python -m pytest tests/test_tier_b.py -q

Needs the collaborator package (clevrer_docqa_package next to the repo, or TIERB_PACKAGE=<path>). The GraphRAG
tests build small indices with the mock model and take a few minutes.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import mock_vllm  # noqa: E402

PORT = int(os.environ.get("TIERB_TEST_PORT", "8011"))
PKG_CANDIDATES = [os.environ.get("TIERB_PACKAGE", ""), ROOT.parent.parent / "clevrer_docqa_package",
                  ROOT.parent / "clevrer_docqa_package"]
PKG = next((Path(p) for p in PKG_CANDIDATES if p and (Path(p) / "SHA256SUMS.txt").exists()), None)
pytestmark = pytest.mark.skipif(PKG is None, reason="clevrer_docqa_package not found")


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    from tierb.importer import import_all
    r = tmp_path_factory.mktemp("runs")
    import_all(PKG, r)
    return r


@pytest.fixture(scope="module", autouse=True)
def server():
    import clevrer_bench.llm as L
    log = Path(os.environ.get("TMPDIR", "/tmp")) / f"mock_requests_{os.getpid()}.jsonl"
    log.unlink(missing_ok=True)
    srv = mock_vllm.serve(PORT, "nvidia/Qwen3.6-27B-NVFP4", str(log))
    orig = L.get_model

    def get_model(alias):
        s = orig(alias)
        if s.base_url:
            s.base_url = f"http://127.0.0.1:{PORT}/v1"
        return s
    L.get_model = get_model
    yield log
    L.get_model = orig
    srv.shutdown()


@pytest.fixture
def env(monkeypatch):
    for k in list(os.environ):
        if k.startswith("MOCK_"):
            monkeypatch.delenv(k)
    return monkeypatch


def _sys(alias, runs, slot=1, **kw):
    from clevrer_bench.systems import load_system
    if alias == "recode":
        kw.setdefault("runs_root", str(runs))
    return load_system(alias, "qwen3.6-27b", slot=slot, out_name=kw.pop("out_name", f"{alias}_t{slot}"), **kw)


def _ask(system, runs, doc="pilot20", uid=None, mc=True):
    """Set the system up on `doc` and answer one question (an MC one by default)."""
    from clevrer_bench.data import load_items
    from clevrer_bench.prompts import ANSWER_INSTRUCTIONS, build_question_prompt
    from clevrer_bench.systems.base import Document
    items = load_items(runs / doc / "items.jsonl")
    it = next(i for i in items if (i.uid == uid if uid else i.is_mc == mc))
    work = runs / doc / "systems" / f"{system.name}__{system.model}" / "work"
    work.mkdir(parents=True, exist_ok=True)
    system.setup(Document(runs / doc / "document.pdf", json.loads((runs / doc / "manifest.json").read_text()), work))
    return system.answer(it.stripped(), ANSWER_INSTRUCTIONS, build_question_prompt(it.stripped())), it


# ---------------------------------------------------------------- data import
def test_import_preserves_everything(runs):
    from clevrer_bench.data import load_items
    from clevrer_bench.prompts import build_question_prompt
    from tierb.importer import E1_CORE, doc_sources, import_all
    total = 0
    for doc, src in doc_sources(PKG).items():
        q = [json.loads(l) for l in (src / "questions.jsonl").read_text().splitlines()]
        g = {r["uid"]: r for r in map(json.loads, (src / "gold.jsonl").read_text().splitlines())}
        items = load_items(runs / doc / "items.jsonl")
        assert [i.uid for i in items] == [r["uid"] for r in q]
        for it, r in zip(items, q):
            assert build_question_prompt(it.stripped()) == r["prompt"]
            assert it.choices == r["choices"]
            assert it.question_type == g[it.uid]["question_type"]
            assert it.gold_answer == g[it.uid]["gold_answer"]
            assert {str(k): v for k, v in it.gold_choices.items()} == g[it.uid]["gold_choices"]
            s = it.stripped()
            assert s.gold_answer is None and not s.gold_choices and s.question_type in ("open_ended", "multiple_choice")
        for f in ("document.pdf", "navmap.json", "manifest.json"):
            assert (runs / doc / f).read_bytes() == (src / f).read_bytes()
        total += len(items) if doc in E1_CORE else 0
    assert total == 694
    import_all(PKG, runs)                                       # idempotent
    (runs / "e1_d03" / "manifest.json").write_text("{}")
    with pytest.raises(Exception, match="refusing to overwrite"):
        import_all(PKG, runs)
    (runs / "e1_d03" / "manifest.json").write_bytes((PKG / "e1" / "e1_d03" / "manifest.json").read_bytes())


# ---------------------------------------------------------------- registry, folders, stripped items
def test_aliases_and_folders(runs, env):
    from clevrer_bench.runner import run_system
    from clevrer_bench.systems import load_system
    for alias in ("react_r", "react_c", "recode"):
        s = load_system(alias, "qwen3.6-27b", **({"runs_root": str(runs)} if alias == "recode" else {}))
        assert s.name == alias
        seen = []
        orig = s.answer

        def spy(item, ins, prompt, _o=orig):
            seen.append(item)
            return _o(item, ins, prompt)
        s.answer = spy
        out = run_system(s, runs / "e1_d03", 2, limit=2)
        assert out.name == f"{alias}__qwen3.6-27b" and (out / "setup.json").exists()
        assert all(i.gold_answer is None and not i.gold_choices and i.question_subtype is None and
                   i.question_type in ("open_ended", "multiple_choice") for i in seen)
        rows = [json.loads(l) for l in (out / "predictions.jsonl").read_text().splitlines()]
        assert len(rows) == 2 and all("error" not in r for r in rows)
    g = load_system("graphrag", "qwen3.6-27b")
    assert g.name == "graphrag"


# ---------------------------------------------------------------- ReAct
def test_react_retrieval_matches_rag(runs):
    from clevrer_bench.systems.base import Document
    from clevrer_bench.systems.rag import RAGSystem
    s = _sys("react_r", runs)
    _ask(s, runs)
    rag = RAGSystem("qwen3.6-27b")
    work = runs / "pilot20" / "systems" / "rag_probe" / "work"
    work.mkdir(parents=True, exist_ok=True)
    rag.setup(Document(runs / "pilot20" / "document.pdf", {}, work))
    for q in ("Video 10331\nQuestion: How many collisions happen?", "what enters the scene last"):
        assert s.rag.retrieve(q, 5)[0] == rag.retrieve(q, 5)[0]
        assert s.run_tool("search", {"query": q}) == rag.retrieve(q, 5)[1]


def test_react_c_sandbox_matches_otf(runs):
    from otf import sandbox
    s = _sys("react_c", runs)
    _ask(s, runs)
    out = s.run_tool("python", {"code": "n = node_by_title(doc, doc['nodes'][1]['title'])\n"
                                        "print(len(scope_nodes(doc, n['title'])), len(children(doc, n)))"})
    assert out.split() == ["3", "3"]
    assert s.run_tool("python", {"code": "import os\nprint(os.listdir('.'))"}).startswith("error: rejected")
    assert "error" in s.run_tool("python", {"code": "open('x','w')"})
    assert set(s.tools[3]["function"]["description"].split("Allowed imports: ")[1].split(".")[0].split(", ")) \
        == sandbox.ALLOWED_MODULES
    assert s.run_tool("read_section", {"node_id": "n9999"}).startswith("error: no node")
    assert s.run_tool("nonexistent", {}).startswith("error: unknown tool")


def test_react_outcomes(runs, env, server):
    s = _sys("react_c", runs)
    p, it = _ask(s, runs)                                       # normal: tools then finish
    assert p.trace["outcome"] == "finish" and p.usage.llm_calls == 6
    assert p.usage.cached_input_tokens <= p.usage.input_tokens and p.usage.reasoning_tokens <= p.usage.output_tokens
    assert [st["tool_calls"][0]["name"] for st in p.trace["steps"]][-1] == "finish"
    assert all(st["finish_reason"] for st in p.trace["steps"])

    env.setenv("MOCK_NEVER_FINISH", "1")                        # call cap exhausted -> unparseable
    p, _ = _ask(s, runs)
    assert p.trace["outcome"] == "call_cap_exhausted" and p.usage.llm_calls == 12 and p.raw_text == ""
    env.delenv("MOCK_NEVER_FINISH")

    env.setenv("MOCK_FINISH_AT", "12")                          # a valid finish on call 12 counts
    p, _ = _ask(s, runs)
    assert p.trace["outcome"] == "finish" and p.usage.llm_calls == 12 and json.loads(p.raw_text)
    env.delenv("MOCK_FINISH_AT")

    env.setenv("MOCK_BAD_ARGS", "1")                            # malformed tool JSON -> observation, continue
    p, _ = _ask(s, runs)
    assert "not valid JSON" in p.trace["steps"][0]["observations"][0]["content"] and p.trace["outcome"] == "finish"
    env.delenv("MOCK_BAD_ARGS")

    env.setenv("MOCK_LENGTH", "1")                              # truncation: completed, scored as parse error
    p, it = _ask(s, runs)
    assert p.trace["finish_reason"] == "length"
    from clevrer_bench.prompts import parse_prediction
    assert "parse_error" in parse_prediction(it, p.raw_text)
    env.delenv("MOCK_LENGTH")

    env.setenv("MOCK_NO_USAGE", "1")                            # unknown usage is flagged, not silently zero
    p, _ = _ask(s, runs)
    assert p.trace["usage_unknown_calls"] == p.usage.llm_calls > 0
    env.delenv("MOCK_NO_USAGE")


def test_infra_retries_are_ledgered(runs, env):
    from clevrer_bench.systems import metered
    env.setattr(metered.time, "sleep", lambda s: None)
    mock_vllm.STATE["requests"] = 0
    env.setenv("MOCK_FAIL_FIRST", "2")
    s = _sys("react_r", runs, out_name="react_r_infra")
    p, it = _ask(s, runs)
    rows = [json.loads(l) for l in s.ledger.path.read_text().splitlines() if json.loads(l).get("uid") == it.uid]
    assert [r["status"] for r in rows[:3]] == ["failed", "failed", "ok"] and p.trace["outcome"] == "finish"
    env.setenv("MOCK_FAIL_FIRST", "1000000")
    with pytest.raises(metered.InfraError):
        _ask(s, runs)


def test_python_tool_timeout(runs):
    s = _sys("react_c", runs)
    _ask(s, runs)
    t = time.time()
    assert "timeout" in s.run_tool("python", {"code": "while True:\n    pass"})
    assert time.time() - t < 40


# ---------------------------------------------------------------- frozen sampling
def test_frozen_sampling_and_gemma_thinking(server):
    from clevrer_bench.llm import get_model
    from clevrer_bench.systems.graphrag_system import _settings
    from clevrer_bench.systems.metered import MeteredChat
    g = MeteredChat(get_model("gemma-4-31b-think"))
    kw = g.request_kwargs(tools=[])
    assert kw["temperature"] == 1.0 and kw["top_p"] == 0.95 and kw["max_tokens"] == 16384
    assert kw["extra_body"] == {"top_k": 64, "chat_template_kwargs": {"enable_thinking": True}}
    with pytest.raises(ValueError):
        g.request_kwargs(temperature=0)
    ca = _settings(get_model("gemma-4-31b-think"), "http://x/v1", Path("p"), Path("l"))[
        "completion_models"]["default_completion_model"]["call_args"]
    assert ca["extra_body"]["chat_template_kwargs"]["enable_thinking"] is True and ca["max_tokens"] == 16384
    reqs = [json.loads(l) for l in server.read_text().splitlines()] if server.exists() else []
    assert reqs and all(r["temperature"] == 1.0 and r["top_p"] == 0.95 and r["max_tokens"] == 16384
                        and r["top_k"] == 20 for r in reqs)


# ---------------------------------------------------------------- ReCode
def test_recode_answers_through_sandbox(runs, env):
    s = _sys("recode", runs)
    p, it = _ask(s, runs)
    assert p.trace["outcome"] == "answered" and json.loads(p.raw_text)
    assert any(a["action"].startswith("list_sections") for a in p.trace["actions"])
    assert any("NeedExpansion" in b["error"] for b in p.trace["blocks"])
    assert p.usage.llm_calls == 2 and p.trace["max_depth_reached"] <= 6


def test_recode_depth_cap_and_sandbox(runs, env):
    from otf import sandbox
    s = _sys("recode", runs)
    env.setenv("MOCK_RECODE", "deep")                           # every expansion defers to a new placeholder
    p, _ = _ask(s, runs)
    assert p.trace["max_depth_reached"] == 6 and p.trace["outcome"] == "no_answer" and p.usage.llm_calls == 6
    env.setenv("MOCK_RECODE", "wide")                           # many placeholders -> 12-call cap
    p, _ = _ask(s, runs)
    assert p.trace["outcome"] == "call_cap_exhausted" and p.usage.llm_calls == 12 and p.raw_text == ""
    env.setenv("MOCK_RECODE", "os")                             # forbidden import: rejected by the OTF check
    p, _ = _ask(s, runs)
    assert any(b["error"].startswith("rejected: import of 'os'") for b in p.trace["blocks"])
    env.setattr(sandbox, "TIMEOUT_S", 2)
    env.setenv("MOCK_RECODE", "loop")                           # runaway code: killed at the sandbox time limit
    p, _ = _ask(s, runs)
    assert any(b["error"].startswith("timeout") for b in p.trace["blocks"])


def test_recode_fewshots_from_pilot_only(runs):
    from clevrer_bench.systems.recode_system import build_fewshots
    text = build_fewshots(runs / "pilot20")
    pilot_videos = set(json.loads((runs / "pilot20" / "build_config.json").read_text())["videos"])
    import re
    assert {int(v) for v in re.findall(r"Video (\d+)", text)} <= pilot_videos


# ---------------------------------------------------------------- runner durability
def test_torn_line_and_resume(runs, env):
    from clevrer_bench.runner import CorruptPredictions, load_predictions, run_system
    s = _sys("react_r", runs, out_name="react_r_resume")
    out = run_system(s, runs / "e1_d06", 2, limit=4)
    pred = out / "predictions.jsonl"
    rows = pred.read_text().splitlines()
    pred.write_text("\n".join(rows[:3]) + "\n" + rows[3][:40])          # crash mid-write of the last line
    assert len(load_predictions(pred)) == 3 and (out / "torn_lines.jsonl").exists()
    run_system(s, runs / "e1_d06", 2, limit=4)                         # re-asks only the torn question
    final = [json.loads(l) for l in pred.read_text().splitlines()]
    assert sorted(r["uid"] for r in final) == sorted(json.loads(r)["uid"] for r in rows)
    assert [r["uid"] for r in final[:3]] == [json.loads(r)["uid"] for r in rows[:3]]
    good = pred.read_text().splitlines()
    pred.write_text(good[0] + "\n{broken\n" + "\n".join(good[1:]) + "\n")
    with pytest.raises(CorruptPredictions):
        load_predictions(pred)
    pred.write_text("\n".join(good) + "\n")
    calls = len((out / "calls.jsonl").read_text().splitlines())
    run_system(s, runs / "e1_d06", 2, limit=4)                         # nothing left: no new model calls
    assert len((out / "calls.jsonl").read_text().splitlines()) == calls


def test_out_of_credits_stops_without_using_attempts(runs, env):
    from clevrer_bench.runner import run_system
    from clevrer_bench.systems.metered import OutOfCredits
    env.setenv("MOCK_CREDITS", "1")
    s = _sys("react_r", runs, out_name="react_r_credits")
    with pytest.raises(OutOfCredits):
        run_system(s, runs / "e1_d12", 2, limit=3, max_attempts=4)
    out = runs / "e1_d12" / "systems" / "react_r_credits__qwen3.6-27b"
    assert not (out / "attempts.jsonl").exists()
    assert not [l for l in (out / "predictions.jsonl").read_text().splitlines() if l.strip()] \
        if (out / "predictions.jsonl").exists() else True
    env.delenv("MOCK_CREDITS")
    run_system(s, runs / "e1_d12", 2, limit=3, max_attempts=4)        # credits back: everything is answered
    assert json.loads((out / "setup.json").read_text())["completion"]["complete"]


def test_errored_attempts_kept_and_bounded(runs, env):
    from clevrer_bench.runner import run_system
    from clevrer_bench.systems import metered
    env.setattr(metered.time, "sleep", lambda s: None)
    env.setenv("MOCK_FAIL_FIRST", "1000000")
    mock_vllm.STATE["requests"] = 0
    s = _sys("react_r", runs, out_name="react_r_attempts")
    for _ in range(3):
        out = run_system(s, runs / "e1_d09", 1, limit=1, max_attempts=2)
    hist = [json.loads(l) for l in (out / "attempts.jsonl").read_text().splitlines()]
    assert len(hist) == 2 and all("InfraError" in h["error"] for h in hist)      # bounded at 2 attempts
    env.delenv("MOCK_FAIL_FIRST")
    run_system(s, runs / "e1_d09", 1, limit=1, max_attempts=3)
    assert json.loads((out / "setup.json").read_text())["completion"]["complete"]


# ---------------------------------------------------------------- GraphRAG
@pytest.fixture(scope="module")
def graphrag_index(runs):
    s = _sys("graphrag", runs, out_name="graphrag_t1")
    p, _ = _ask(s, runs)
    return s, p


def test_graphrag_metering(graphrag_index):
    s, p = graphrag_index
    rows = s.index_ledger.rows()
    ok = [r for r in rows if r["status"] == "ok" and r["phase"] == "setup"]
    u, unknown = s.index_ledger.setup_usage()
    assert len(ok) == u.llm_calls > 0 and unknown == 0
    assert u.input_tokens == sum(r["usage"]["input_tokens"] for r in ok)
    assert p.usage.llm_calls == 1 and p.usage.input_tokens > 0 and json.loads(p.raw_text.splitlines()[-1])
    ex = json.loads((s.root / "index_complete.json").read_text())["extraction"]
    assert ex["chunks"] > 0 and ex["failed_chunks"] == 0


def test_graphrag_empty_extractions_and_extra_report_keys(runs, env):
    """A properly completed reply listing no entity is a valid empty extraction (not a failure), and a community
    report with an extra key is still accepted (hosted endpoints do not enforce the JSON schema)."""
    env.setenv("MOCK_EXTRACT_EMPTY", "1")
    env.setenv("MOCK_REPORT_EXTRA", "1")
    s = _sys("graphrag", runs, out_name="graphrag_t1")
    p, _ = _ask(s, runs, doc="e1_d09")
    ex = json.loads((s.root / "index_complete.json").read_text())["extraction"]
    assert ex["failed_chunks"] == 0 and ex["empty_but_completed_chunks"] > 0 and ex["meter_version"] == 2
    import pandas as pd
    assert len(pd.read_parquet(s.root / "output" / "community_reports.parquet")) > 0
    assert p.usage.llm_calls == 1


def test_graphrag_never_switches_method_itself(runs, env, graphrag_index):
    from clevrer_bench.systems.graphrag_system import IndexBuildError
    env.setenv("MOCK_EXTRACT_FAIL", "1")
    s = _sys("graphrag", runs, out_name="graphrag_t1")
    with pytest.raises(IndexBuildError) as e:
        _ask(s, runs, doc="e1_d12")
    assert s.index_method == "standard" and e.value.extraction["failed_fraction"] == 1.0


def test_graphrag_interrupted_index_resumes_with_costs(runs, env, tmp_path, server):
    """Kill an index build midway, build again: completed calls come from GraphRAG's cache, and the setup cost is
    the sum of both attempts."""
    from clevrer_bench.systems.metered import Ledger
    script = tmp_path / "build.py"
    script.write_text(f"""
import sys, json; sys.path.insert(0, {str(ROOT)!r}); sys.path.insert(0, {str(ROOT / 'tests')!r})
import clevrer_bench.llm as L
orig = L.get_model
def gm(a):
    s = orig(a); s.base_url = "http://127.0.0.1:{PORT}/v1"; return s
L.get_model = gm
from test_tier_b import _ask, _sys
from pathlib import Path
_ask(_sys("graphrag", Path({str(runs)!r}), out_name="graphrag_t1"), Path({str(runs)!r}), doc="e1_d15")
""")
    p = subprocess.Popen([sys.executable, str(script)], cwd=ROOT)
    led = None
    for _ in range(600):
        hits = list((runs / "tier_b" / "graphrag_index").glob("e1_d15__*/index_calls.jsonl"))
        if hits and len(hits[0].read_text().splitlines()) >= 15:
            led = hits[0]
            break
        time.sleep(0.5)
    p.kill()
    p.wait()
    assert led is not None
    first = len([r for r in Ledger(led).rows() if r["status"] == "ok"])
    assert not (led.parent / "index_complete.json").exists()
    s = _sys("graphrag", runs, out_name="graphrag_t1")
    _ask(s, runs, doc="e1_d15")
    u, _ = s.index_ledger.setup_usage()
    total = len([r for r in Ledger(led).rows() if r["status"] == "ok"])
    assert u.llm_calls == total >= first > 0


# ---------------------------------------------------------------- pipeline gates
def _pipe(runs, *extra):
    from tierb.pipeline import Pipeline, main  # noqa: F401
    import argparse
    a = argparse.Namespace(package=str(PKG), deadline="2099-01-01T00:00:00+00:00", workers=2,
                           models=["qwen3.6-27b", "gemma-4-31b-think"], systems=["react_r"], runs=str(runs),
                           mock_server=True, dev_limit=None, e1_limit=None, smoke_per_type=1, status=False)
    for k, v in zip(extra[::2], extra[1::2]):
        setattr(a, k, v)
    a.plan = [(m, list(a.systems)) for m in a.models]
    return Pipeline(a)


def test_e1_requires_matching_freeze(runs):
    from tierb.pipeline import StageError
    pipe = _pipe(runs)
    with pytest.raises(StageError, match="no freeze manifest"):
        pipe.e1("qwen3.6-27b", "react_r")
    s = _sys("react_r", runs)
    p = pipe.freeze_path("react_r", "qwen3.6-27b")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"kwargs": {"slot": 1}, "config_hash": s.config_hash()}))
    pipe.frozen_system("react_r", "qwen3.6-27b")                   # matches
    p.write_text(json.dumps({"kwargs": {"slot": 2}, "config_hash": s.config_hash()}))
    with pytest.raises(StageError, match="differs from its freeze manifest"):
        pipe.frozen_system("react_r", "qwen3.6-27b")
    p.unlink()


def test_gemma_gated_on_complete_qwen(runs):
    pipe = _pipe(runs)
    assert pipe.admitted(1) is False                                 # Qwen has no E1 outputs here


def test_plan_parsing():
    import tierb.pipeline as P
    seen = {}
    orig = P.Pipeline
    P.Pipeline = lambda a: seen.setdefault("a", a) and (_ for _ in ()).throw(SystemExit(0))
    try:
        with pytest.raises(SystemExit):
            P.main(["--models", "qwen3.6-27b:react_c", "or-qwen3.6-27b:react_r,graphrag", "gemma-4-31b-think"])
    finally:
        P.Pipeline = orig
    assert seen["a"].plan == [("qwen3.6-27b", ["react_c"]), ("or-qwen3.6-27b", ["react_r", "graphrag"]),
                              ("gemma-4-31b-think", P.SYSTEMS)]
    with pytest.raises(SystemExit):
        P.main(["--models", "qwen3.6-27b:nope"])


def test_deadline_gives_explicit_partial_delivery(tmp_path):
    from tierb.pipeline import main
    runs = tmp_path / "runs"
    rc = main(["--package", str(PKG), "--runs", str(runs), "--mock-server", "--systems", "react_r",
               "--models", "qwen3.6-27b", "gemma-4-31b-think",
               "--deadline", "2000-01-01T00:00:00+00:00"])
    assert rc == 0
    m = json.loads((runs / "tier_b" / "delivery_manifest.json").read_text())
    assert m["status"] == "partial" and m["partial_reason"] == "deadline reached"
    assert m["actual_predictions"] == 0 and len(m["missing_jobs"]) == 10
    assert not list(runs.glob("e1_d*/systems/*/predictions.jsonl"))         # nothing invented


# ---------------------------------------------------------------- serving rules (no WSL needed)
def test_serving_ownership_rules(tmp_path, monkeypatch):
    from tierb import serving
    srv = serving.WSLServer(tmp_path, log=lambda m: None)
    calls = []
    monkeypatch.setattr(srv, "start", lambda m: calls.append(("start", m)))
    monkeypatch.setattr(srv, "stop", lambda: calls.append(("stop",)))
    monkeypatch.setattr(srv, "wsl", lambda *a, **k: calls.append(("wsl", a)) or "")
    served = {"ids": ["nvidia/Qwen3.6-27B-NVFP4"]}
    monkeypatch.setattr(serving, "served_models", lambda url: served["ids"])
    srv.ensure("qwen3.6-27b")                         # someone else's server with the right model: reuse it
    assert srv.external and calls == []
    srv.stop = serving.WSLServer.stop.__get__(srv)     # the real stop must not touch an external server
    srv.stop()
    assert not any(c[0] == "wsl" for c in calls)
    srv2 = serving.WSLServer(tmp_path, log=lambda m: None)
    monkeypatch.setattr(srv2, "stop", lambda: calls.append(("stop2",)))
    served["ids"] = ["some/other-model"]               # someone else's server with another model: leave it alone
    with pytest.raises(serving.ServingError, match="did not start"):
        srv2.ensure("qwen3.6-27b")
    assert ("stop2",) not in calls
    srv3 = serving.WSLServer(tmp_path, log=lambda m: None)
    srv3.pid, srv3.proc, srv3.model = 42, type("P", (), {"poll": lambda self: None})(), "qwen3.6-27b"
    monkeypatch.setattr(srv3, "stop", lambda: calls.append(("stop3",)))
    monkeypatch.setattr(srv3, "start", lambda m: calls.append(("start3", m)))
    srv3.ensure("gemma-4-31b-think")                   # our own Qwen server: stopped, then Gemma started
    assert calls[-2:] == [("stop3",), ("start3", "gemma-4-31b-think")]


def test_wsl_helpers():
    from pathlib import PureWindowsPath
    from tierb import serving
    assert serving._q("a'b") == "'a'\"'\"'b'"
    s = serving.WSLServer(Path("."), log=lambda m: None)
    raw = "Ubuntu-24.04\r\ndocker-desktop\r\n".encode("utf-16-le")
    import types
    orig = serving.subprocess.run
    serving.subprocess.run = lambda *a, **k: types.SimpleNamespace(stdout=raw, returncode=0)
    try:
        assert s.distros() == ["Ubuntu-24.04", "docker-desktop"]
    finally:
        serving.subprocess.run = orig
    p = str(PureWindowsPath(r"C:\Users\x y\OTF\scripts\serve.sh"))
    assert ("/mnt/" + p[0].lower() + p[2:].replace("\\", "/")) == "/mnt/c/Users/x y/OTF/scripts/serve.sh"
