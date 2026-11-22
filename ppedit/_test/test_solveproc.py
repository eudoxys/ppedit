"""Tests for solving in a child process that can be stopped
(`ppedit._solveproc`, `job` of `Case.solve`, `/api/solve/progress`,
`/api/solve/stop`; issue #130). The stop and crash tests replace the
child's code with a stand-in; tests that go through `Case.solve` are
skipped without cvxopf. Fast (a few seconds: each solve starts a Python
process)."""

import importlib.util
import io
import threading
import time

import pytest

from ppedit import Case
from ppedit import _solveproc
from ppedit._solveproc import SolveJob, describe

HAS_CVXOPF = importlib.util.find_spec("cvxopf") is not None
needs_cvxopf = pytest.mark.skipif(not HAS_CVXOPF,reason="cvxopf is not installed")

# stand-in child: one IPOPT-like progress report, then wait to be killed
SLOW_CHILD = ("import pickle,sys,time; sys.stdin.buffer.read(); "
    "pickle.dump(('progress',{'phase':'iterate','text':'IPOPT iteration 7','iteration':7,"
    "'max_iter':50,'inf_pr':0.5}),sys.stdout.buffer); sys.stdout.buffer.flush(); time.sleep(60)")

class Recorder(SolveJob):
    """A job that keeps every progress report"""
    def __init__(self):
        super().__init__()
        self.reports = []
    def report(self,progress):
        self.reports.append(dict(progress))
        super().report(progress)

def _stop_when(job,cond,timeout=30):
    """Thread: call `job.stop()` once `cond(job.status())` holds"""
    def run():
        end = time.time() + timeout
        while time.time() < end and not job.done:
            if cond(job.status()):
                job.stop()
                return
            time.sleep(0.05)
    t = threading.Thread(target=run,daemon=True)
    t.start()
    return t

def test_describe():
    """Progress reports read as one line"""
    assert describe({"phase":"build","text":"building the ac model"}) == "building the ac model"
    assert describe({"phase":"iterate","iteration":12,"max_iter":3000,"inf_pr":3.2e-4}) \
        == "IPOPT iteration 12 of at most 3000, primal infeasibility 3.20e-04"
    assert describe({}) == ""

def test_job_status():
    """A new job is running, not stoppable until its child starts, and stop() says so"""
    job = SolveJob()
    s = job.status()
    assert s["running"] and not s["stoppable"] and not s["stopping"] and s["elapsed"] >= 0
    assert job.stop() is False and job.status()["stopping"]
    job.done = True
    assert not job.status()["running"]

@needs_cvxopf
def test_child_solve_matches_in_process():
    """A CVXOPF-AC solve run with a job gives the in-process result and reports its phases"""
    case = Case.builtin("case9")
    job = Recorder()
    a,b = case.solve("opf","CVXOPF-AC",job=job),case.solve("opf","CVXOPF-AC")
    assert a["success"] and not a.get("stopped")
    assert a["objective"] == pytest.approx(b["objective"],rel=1e-8)
    phases = [r["phase"] for r in job.reports]
    assert phases[0] == "start" and phases[-1] == "results"
    assert {"build","solve","derivatives","iterate"} <= set(phases)
    assert any(r.get("iteration") is not None and r.get("max_iter") == 3000 for r in job.reports)
    assert not job.stoppable

@needs_cvxopf
def test_child_solve_convex_and_max_iter():
    """Convex models report the solver; an IPOPT max_iter option is shown as the limit"""
    case = Case.builtin("case9")
    job = Recorder()
    assert case.solve("opf","CVXOPF-DC",job=job)["success"]
    assert {"text":"solving with CLARABEL","phase":"solve"} in job.reports
    job = Recorder()
    case.solve("opf","CVXOPF-AC",{"solver_options":{"max_iter":200}},job=job)
    assert any(r.get("max_iter") == 200 for r in job.reports)

@needs_cvxopf
def test_child_solve_error():
    """An error raised in the child is a solver failure with its message"""
    res = Case.builtin("case9").solve("opf","CVXOPF-SOCP",{"solver":"OSQP"},job=SolveJob())
    assert not res["success"] and not res["stopped"]
    assert any(m["level"] == "error" and "OSQP cannot solve" in m["message"] for m in res["messages"])

def test_stop(monkeypatch):
    """stop() kills the child; the solve fails as stopped, naming the last progress"""
    monkeypatch.setattr(_solveproc,"_CHILD",SLOW_CHILD)
    job = SolveJob()
    _stop_when(job,lambda s: s.get("iteration") == 7 and s["stoppable"])
    log = io.StringIO()
    start = time.time()
    with pytest.raises(_solveproc.SolveStopped,match="IPOPT iteration 7 of at most 50"):
        _solveproc.run(job,{},"ac",log)
    assert time.time() - start < 20
    assert "Solve stopped by the user" in log.getvalue()
    assert not job.stoppable

@needs_cvxopf
def test_stopped_result(monkeypatch):
    """Case.solve returns a failure with `stopped` true and no rows"""
    monkeypatch.setattr(_solveproc,"_CHILD",SLOW_CHILD)
    job = SolveJob()
    _stop_when(job,lambda s: s["stoppable"])
    res = Case.builtin("case9").solve("opf","CVXOPF-AC",job=job)
    assert res["stopped"] and not res["success"] and res["bus"] == []
    assert any("stopped by the user" in m["message"] for m in res["messages"])

def test_child_killed(monkeypatch):
    """A child killed without a result (as for lack of memory) is reported, not fatal"""
    monkeypatch.setattr(_solveproc,"_CHILD",
        "import os,signal,sys; sys.stdin.buffer.read(); os.kill(os.getpid(),getattr(signal,'SIGKILL',9))")
    with pytest.raises(_solveproc.SolverProcessError,match="ended without a result"):
        _solveproc.run(SolveJob(),{},"ac",io.StringIO())

@needs_cvxopf
def test_server_progress_and_stop(monkeypatch):
    """/api/solve/progress and /api/solve/stop work while /api/solve waits"""
    from ppedit import create_app # pylint: disable=import-outside-toplevel
    monkeypatch.setattr(_solveproc,"_CHILD",SLOW_CHILD)
    app = create_app(Case.builtin("case9"))
    client = app.test_client()
    assert client.get("/api/solve/progress").get_json() == {"running":False}
    assert client.post("/api/solve/stop",json={},headers={"X-PPEdit":"1"}).get_json() \
        == {"running":False,"stopping":False}
    out = {}
    def solve():
        out["r"] = app.test_client().post("/api/solve",json={"kind":"opf","algorithm":"CVXOPF-AC"},
            headers={"X-PPEdit":"1"}).get_json()
    t = threading.Thread(target=solve)
    t.start()
    end,p = time.time() + 30,{}
    while time.time() < end:
        p = client.get("/api/solve/progress").get_json()
        if p.get("iteration") == 7:
            break
        time.sleep(0.05)
    assert p["running"] and p["stoppable"] and p["text"].startswith("IPOPT iteration 7")
    assert client.post("/api/solve/stop",json={},headers={"X-PPEdit":"1"}).get_json() \
        == {"running":True,"stopping":True}
    t.join(20)
    r = out["r"]["result"]
    assert r["stopped"] and not r["success"]
    assert client.get("/api/solve/progress").get_json()["running"] is False
