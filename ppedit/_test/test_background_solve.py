"""Background solves: the page stays usable while a solve runs"""

import threading
import time

import pytest

from ppedit import Case

def _wait(client,timeout=30):
    """Poll /api/solve/progress until the solve ends; return the last report"""
    end = time.time() + timeout
    while time.time() < end:
        p = client.get("/api/solve/progress").get_json()
        if not p["running"]:
            return p
        time.sleep(0.05)
    raise AssertionError("the solve did not end")

@pytest.fixture
def slow(monkeypatch):
    """Make Case.solve wait until the returned event is set"""
    gate = threading.Event()
    real = Case.solve
    def solve(self,*args,**kwargs):
        gate.wait(10)
        return real(self,*args,**kwargs)
    monkeypatch.setattr(Case,"solve",solve)
    return gate

def test_background_result(client,post):
    """The request returns at once; the result arrives when the solve ends"""
    status,st = post("/api/solve",{"kind":"pf","background":True})
    assert status == 200 and st["solving"] and st["revision"] == 0
    p = _wait(client)
    assert p["background"] and p["outcome"] == "result" and p["kind"] == "pf"
    st = client.get("/api/state").get_json()
    assert st["result"]["success"] and st["result"]["kind"] == "pf"

def test_edit_while_solving(client,post,slow):
    """Requests go on during the solve; an edit discards the result"""
    post("/api/solve",{"kind":"pf","background":True})
    t0 = time.time()
    status,st = post("/api/cell",{"table":"bus","row":4,"column":"Pd","value":95})
    assert status == 200 and time.time() - t0 < 2 and st["case"]["tables"]["bus"][4][2] == 95
    assert client.get("/api/solve/progress").get_json()["running"]
    status,st = post("/api/solve",{"kind":"pf"})
    assert status == 409 and "already running" in st["error"]
    slow.set()
    assert _wait(client)["outcome"] == "discarded"
    assert client.get("/api/state").get_json()["result"] is None

def test_unchanged_case_keeps_result(client,post,slow):
    """Requests that do not change the case keep the result"""
    post("/api/solve",{"kind":"pf","background":True})
    assert client.get("/api/state").status_code == 200
    assert client.get("/api/table/export?table=bus&format=csv").status_code == 200
    slow.set()
    assert _wait(client)["outcome"] == "result"
    assert client.get("/api/state").get_json()["result"]["success"]

def test_background_error(client,post):
    """A solve that raises reports the error in the progress"""
    post("/api/solve",{"kind":"opf","algorithm":"NOPE","background":True})
    p = _wait(client)
    assert p["outcome"] == "error" and "OPF algorithm must be one of" in p["error"]
    assert client.get("/api/state").get_json()["result"] is None
