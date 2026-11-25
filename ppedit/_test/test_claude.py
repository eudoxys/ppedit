"""Tests for `ppedit.claude` and the `/api/claude` routes (fast, no network)

A fake API client replays scripted responses, so no API key is needed.
"""

import copy
import importlib.util

import pytest

from ppedit import Case, create_app

def _client(*responses):
    """Fake Messages API: returns `responses` in turn and records requests"""
    calls = []
    def client(payload):
        calls.append(copy.deepcopy(payload))
        return responses[min(len(calls),len(responses))-1]
    client.calls = calls
    return client

def _tool(name,args,tid="t1"):
    return {"content":[{"type":"tool_use","id":tid,"name":name,"input":args}],
        "stop_reason":"tool_use","usage":{"input_tokens":10,"output_tokens":5}}

def _text(text):
    return {"content":[{"type":"text","text":text}],"stop_reason":"end_turn",
        "usage":{"input_tokens":3,"output_tokens":2}}

def _app(client):
    app = create_app(Case.builtin("case9"),claude_client=client)
    app.config["TESTING"] = True
    test = app.test_client()
    def post(path,body=None):
        res = test.post(path,json=body or {},headers={"X-PPEdit":"1"})
        return res.status_code,res.get_json()
    return app,test,post

def _wait(app,sid):
    app.config["CLAUDE"].get(sid).wait(10)

def test_session_edits_case_and_undo():
    client = _client(_tool("set_cells",{"edits":[{"table":"bus","row":4,"column":"Pd","value":95}]}),
        _text("Raised the load at bus 5 to 95 MW."))
    app,test,post = _app(client)
    status,st = post("/api/claude/new",{"title":"loads"})
    assert status == 200 and st["claude"]["sessions"][0]["title"] == "loads"
    rev = st["revision"]
    _,st = post("/api/claude/send",{"id":1,"text":"raise bus 5 load to 95 MW"})
    _wait(app,1)
    data = test.get("/api/claude").get_json()["claude"]
    s = data["sessions"][0]
    assert s["status"] == "idle" and s["edits"] == 1 and data["revision"] == rev + 1
    assert [t["kind"] for t in s["transcript"]] == ["user","tool","assistant"]
    state = test.get("/api/state").get_json()
    assert state["case"]["tables"]["bus"][4][2] == 95 and state["can_undo"]
    _,state = post("/api/undo")
    assert state["case"]["tables"]["bus"][4][2] == 90
    # the tool result went back to the API with the system prompt and tools
    last = client.calls[-1]
    assert last["messages"][-1]["content"][0]["type"] == "tool_result"
    assert any(t["name"] == "get_table" for t in last["tools"])
    assert not any(t["name"] in ("fetch_url","read_file") for t in last["tools"])

def test_tool_error_is_reported_and_rolled_back():
    client = _client(_tool("set_cells",{"edits":[{"table":"bus","row":4,"column":"Pd","value":95},
        {"table":"bus","row":0,"column":"Pd","value":"x"}]}),_text("That failed."))
    app,test,post = _app(client)
    post("/api/claude/new")
    post("/api/claude/send",{"id":1,"text":"go"})
    _wait(app,1)
    result = client.calls[-1]["messages"][-1]["content"][0]
    assert result["is_error"] and "not a number" in result["content"]
    state = test.get("/api/state").get_json()
    assert state["case"]["tables"]["bus"][4][2] == 90 and not state["can_undo"]

def test_local_files_stay_in_root(tmp_path):
    (tmp_path/"loads.csv").write_text("bus,Pd\n5,95\n")
    app,_,post = _app(_client(_text("ok")))
    status,_ = post("/api/claude/new",{"local":True,"root":str(tmp_path)})
    assert status == 200
    session = app.config["CLAUDE"].get(1)
    assert session.run_tool("list_files",{})[0] == ["loads.csv"]
    assert "5,95" in session.run_tool("read_file",{"path":"loads.csv"})[0]["text"]
    with pytest.raises(ValueError,match="outside"):
        session.run_tool("read_file",{"path":"../x"})
    with pytest.raises(ValueError,match="not available"):
        session.run_tool("fetch_url",{"url":"https://example.com"})

def test_case_tools():
    app,_,post = _app(_client(_text("ok")))
    post("/api/claude/new",{"web":True})
    session = app.config["CLAUDE"].get(1)
    assert session.run_tool("get_case",{})[0]["rows"]["bus"] == 9
    rows = session.run_tool("get_table",{"table":"gen","start":1,"count":1})[0]["rows"]
    assert rows == [{"row":1,**{k:v for k,v in rows[0].items() if k != "row"}}] and rows[0]["bus"] == 2
    out,changed = session.run_tool("add_rows",{"table":"bus","rows":[{"bus_i":20,"Pd":5}]})
    assert changed and out["rows"] == [9]
    assert session.run_tool("solve",{"kind":"pf"})[0]["success"]
    assert app.config["EDITOR"].result["success"]
    assert any(t.get("name") == "web_search" for t in session._tools()) # pylint: disable=protected-access

def test_two_sessions_and_delete():
    app,test,post = _app(_client(_text("hello")))
    post("/api/claude/new",{"title":"a"})
    _,st = post("/api/claude/new",{"title":"b","model":"claude-haiku-5-5"})
    assert [s["title"] for s in st["claude"]["sessions"]] == ["a","b"]
    post("/api/claude/send",{"id":2,"text":"hi"})
    _wait(app,2)
    status,st = post("/api/claude/send",{"id":2,"text":" "})
    assert status == 400
    _,st = post("/api/claude/delete",{"id":1})
    assert [s["id"] for s in st["claude"]["sessions"]] == [2]
    assert test.get("/api/claude").get_json()["claude"]["sessions"][0]["transcript"][-1]["text"] == "hello"
    status,_ = post("/api/claude/send",{"id":1,"text":"hi"})
    assert status == 400

def test_no_api_key(monkeypatch,tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY",raising=False)
    monkeypatch.setenv("HOME",str(tmp_path))
    app = create_app(Case.builtin("case9"))
    test = app.test_client()
    assert not test.get("/api/claude").get_json()["claude"]["available"]
    res = test.post("/api/claude/new",json={},headers={"X-PPEdit":"1"})
    assert res.status_code == 400 and "API key" in res.get_json()["error"]

def _keyed_client(*responses):
    """Fake Messages API that also records the API key of each request"""
    keys = []
    inner = _client(*responses)
    def client(payload,key=None):
        keys.append(key)
        return inner(payload)
    client.calls,client.keys = inner.calls,keys
    return client

def test_api_key_text_and_file(monkeypatch,tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY",raising=False)
    monkeypatch.setenv("HOME",str(tmp_path))
    client = _keyed_client(_text("ok"))
    app = create_app(Case.builtin("case9"))
    sessions = app.config["CLAUDE"]
    sessions.client = client
    sessions.available = lambda: False  # no server default key
    test = app.test_client()
    def post(path,body=None):
        res = test.post(path,json=body or {},headers={"X-PPEdit":"1"})
        return res.status_code,res.get_json()
    status,st = post("/api/claude/new")
    assert status == 400 and "API key" in st["error"]
    status,st = post("/api/claude/new",{"agent":"claude","api_key":"sk-text"})
    assert status == 200 and st["claude"]["agents"] == ["claude"]
    session = st["claude"]["sessions"][0]
    assert session["agent"] == "claude" and "sk-text" not in str(st)
    (tmp_path/"key.txt").write_text("sk-file\nignored\n")
    status,st = post("/api/claude/new",{"api_key_file":"~/key.txt"})
    assert status == 200 and "sk-file" not in str(st)
    for sid in (1,2):
        post("/api/claude/send",{"id":sid,"text":"hi"})
        app.config["CLAUDE"].get(sid).wait(10)
    assert client.keys == ["sk-text","sk-file"]

def test_api_key_file_errors_and_unknown_agent(tmp_path):
    _,_,post = _app(_client(_text("ok")))
    status,st = post("/api/claude/new",{"api_key_file":str(tmp_path/"missing")})
    assert status == 400 and "cannot read API key file" in st["error"]
    (tmp_path/"empty").write_text("\n")
    status,st = post("/api/claude/new",{"api_key_file":str(tmp_path/"empty")})
    assert status == 400 and "is empty" in st["error"]
    status,st = post("/api/claude/new",{"agent":"other"})
    assert status == 400 and "unknown agent" in st["error"]

HAS_CVXOPF = importlib.util.find_spec("cvxopf") is not None

def _session(case=None):
    app = create_app(case or Case.builtin("case9"),claude_client=_client(_text("ok")))
    app.config["TESTING"] = True
    app.config["CLAUDE"].create()
    return app,app.config["EDITOR"],app.config["CLAUDE"].get(1)

def _multistep_case():
    case = Case.builtin("case9")
    case.set_series(["bus.Pd.5","bus.Pd.7","gen.Pmax.1"],[[80,90,250],[100,110,200],[120,130,150]],
        ["00:00","01:00","02:00"],name="loads")
    return case

def test_get_series():
    _,_,session = _session(_multistep_case())
    out = session.run_tool("get_series",{})[0]
    assert out["series"] == [{"name":"loads","columns":3,"steps":3,"delta_h":1.0,"timed":True,
        "first":"00:00","last":"02:00"}]
    assert out["combined"]["steps"] == 3 and "index" not in out["combined"]
    out = session.run_tool("get_series",{"name":"loads","start":1,"count":1,"columns":["bus.pd"]})[0]
    assert out["columns"] == 3 and out["columns_shown"] == 2
    assert out["rows"] == [{"step":1,"label":"01:00","values":{"bus.Pd.5":100,"bus.Pd.7":110}}]
    out = session.run_tool("get_series",{"name":"combined","columns":["gen.Pmax.1"]})[0]
    assert [r["values"] for r in out["rows"]] == [{"gen.Pmax.1":250},{"gen.Pmax.1":200},{"gen.Pmax.1":150}]
    with pytest.raises(ValueError,match="no series 'x'"):
        session.run_tool("get_series",{"name":"x"})
    _,_,session = _session()
    assert session.run_tool("get_series",{})[0]["note"] == "the case has no time series"
    assert session.run_tool("get_case",{})[0]["combined_series"] is None

def test_get_result_and_issues_after_page_solve():
    app,editor,session = _session()
    assert session.run_tool("get_result",{})[0]["solution"] is None
    assert session.run_tool("get_issues",{})[0]["last_solve"] is None
    test = app.test_client()
    res = test.post("/api/solve",json={"kind":"opf","algorithm":"PIPS"},headers={"X-PPEdit":"1"})
    assert res.status_code == 200
    out = session.run_tool("get_result",{})[0]
    assert out["success"] and out["kind"] == "opf" and out["rows"]["gen"] == 3
    assert "multistep" not in out
    assert session.run_tool("get_case",{})[0]["solution"]["algorithm"] == "PIPS"
    out = session.run_tool("get_result",{"table":"gen","start":1,"count":1,"extended":True,"log":True})[0]
    assert out["total"] == 3 and out["rows"][0]["row"] == 1 and "mu_Pmax" in out["rows"][0]
    assert out["log"]
    assert "mu_Pmax" not in session.run_tool("get_result",{"table":"gen"})[0]["rows"][0]
    with pytest.raises(ValueError,match="not a multistep"):
        session.run_tool("get_result",{"table":"steps"})
    with pytest.raises(ValueError,match="not a multistep"):
        session.run_tool("get_result",{"table":"bus","step":2})
    # solver messages reach get_issues as the Issues tab shows them
    warning = {"level":"warning","message":"bus 5 isolated","detail":{"explain":"no branch"}}
    editor.result["messages"] = [warning]
    out = session.run_tool("get_issues",{})[0]
    assert out["case"] == editor.case.validate() and out["last_solve"]["messages"] == [warning]
    # an edit clears the result
    session.run_tool("set_cell",{"table":"bus","row":4,"column":"Pd","value":95})
    assert session.run_tool("get_result",{})[0]["solution"] is None

def _fake_multistep(editor):
    """A multistep result in the layout of `Case.solve` (cvxopf may not be installed)"""
    base = editor.case.solve("opf","DC-PIPS")
    steps = []
    for t,label in enumerate(["00:00","01:00"]):
        step = copy.deepcopy(base)
        step |= {"label":label,"objective":1000.0 + t,"log":f"step {t} report",
            "storage":[{"row":0,"solved":True,"Pdis":5.0,"Pch":1.0,"E":10.0,"cost":0.1}]}
        steps.append(step)
    editor.result = base | {"multistep":{"steps":2,"delta":1.0,"index":["00:00","01:00"],
        "series":["loads"],"window":[3,4],"total":10},"horizon_objective":2001.0,"steps":steps}

def test_get_result_multistep():
    _,editor,session = _session()
    _fake_multistep(editor)
    out = session.run_tool("get_result",{})[0]
    assert out["multistep"] == {"steps":2,"delta":1.0,"series":["loads"],"window":[3,4],"total":10,
        "first_label":"00:00","last_label":"01:00","horizon_objective":2001.0,"steps_solved":2}
    assert out["step"]["step"] == 0 and out["step"]["label"] == "00:00"
    rows = session.run_tool("get_result",{"table":"steps"})[0]["rows"]
    assert [(r["step"],r["label"],r["objective"],r["storage_MW"]) for r in rows] \
        == [(0,"00:00",1000.0,4.0),(1,"01:00",1001.0,4.0)]
    assert rows[0]["Pd_MW"] == pytest.approx(315)
    out = session.run_tool("get_result",{"table":"storage","step":1,"log":True})[0]
    assert out["label"] == "01:00" and out["rows"][0]["Pdis"] == 5.0 and out["log"] == "step 1 report"
    with pytest.raises(ValueError,match="steps 0 to 1"):
        session.run_tool("get_result",{"table":"bus","step":2})
    assert rows[0]["stored_MWh"] == 10.0
    # one result column of chosen rows over the horizon
    editor.result["steps"][1]["gen"][0]["Pg"] = 123.0
    out = session.run_tool("get_result",{"table":"gen","column":"Pg","rows":[0,2]})[0]
    assert out["rows"] == [0,2] and out["steps"] == 2
    assert [v["label"] for v in out["values"]] == ["00:00","01:00"]
    assert out["values"][1]["values"][0] == 123.0
    assert out["values"][0]["values"][1] == editor.result["steps"][0]["gen"][2]["Pg"]
    out = session.run_tool("get_result",{"table":"bus","column":"lam_P","start":1})[0]
    assert out["bus_i"] == [r[0] for r in editor.case.tables["bus"]] and out["start"] == 1
    assert len(out["values"]) == 1 and len(out["values"][0]["values"]) == 9
    assert out["values"][0]["values"][0] > 0
    out = session.run_tool("get_result",{"table":"storage","column":"E"})[0]
    assert [v["values"] for v in out["values"]] == [[10.0],[10.0]]
    assert "lam_P" in session.run_tool("get_result",{})[0]["columns"]["bus"]
    with pytest.raises(ValueError,match="no column 'x'"):
        session.run_tool("get_result",{"table":"gen","column":"x"})
    with pytest.raises(ValueError,match="rows 0 to 2"):
        session.run_tool("get_result",{"table":"gen","column":"Pg","rows":[3]})
    # apply_result copies the chosen step
    _,changed = session.run_tool("apply_result",{"step":1})
    assert changed and editor.case.tables["gen"][0][1] == 123.0

def test_column_needs_multistep():
    _,editor,session = _session()
    editor.result = editor.case.solve("pf")
    with pytest.raises(ValueError,match="multistep"):
        session.run_tool("get_result",{"table":"gen","column":"Pg"})

def test_solve_waits_for_page_solve():
    _,editor,session = _session()
    class Running: # pylint: disable=too-few-public-methods
        done = False
    editor.job = Running()
    with pytest.raises(ValueError,match="still running"):
        session.run_tool("solve",{"kind":"pf"})
    editor.job.done = True
    assert session.run_tool("solve",{"kind":"pf"})[0]["success"]

def test_solve_multistep_needs_cvxopf_solver():
    _,_,session = _session(_multistep_case())
    with pytest.raises(ValueError,match="CVXOPF"):
        session.run_tool("solve",{"kind":"opf","algorithm":"PIPS","multistep":True})

@pytest.mark.skipif(not HAS_CVXOPF,reason="cvxopf is not installed")
def test_solve_multistep_window():
    _,_,session = _session(_multistep_case())
    out = session.run_tool("solve",{"kind":"opf","algorithm":"CVXOPF-DC","multistep":True,"window":[1,2]})[0]
    assert out["success"] and out["multistep"]["window"] == [1,2] and out["multistep"]["steps"] == 2
    assert out["multistep"]["first_label"] == "01:00" and "index" not in out["multistep"]
    rows = session.run_tool("get_result",{"table":"steps"})[0]["rows"]
    assert [r["label"] for r in rows] == ["01:00","02:00"] and all(r["success"] for r in rows)
    assert rows[1]["Pd_MW"] == pytest.approx(120 + 130 + 125)
    out = session.run_tool("get_result",{"table":"gen","column":"Pg"})[0]
    assert [sum(v["values"]) for v in out["values"]] == pytest.approx([r["Pg_MW"] for r in rows])
