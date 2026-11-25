"""Claude assistant sessions

A `Sessions` object holds any number of conversations with Claude (the
Anthropic Messages API) that read and edit the case open in the editor.
Each session runs its own tool-use loop in a background thread; every
change Claude makes goes through the same `ppedit.case.Case` methods and
`ppedit.server.Editor.edit` as the browser, so it is checked, shows up in
the browser on its next refresh, and can be undone like any other edit.

Configuration
-------------

  - Agent: `AGENTS` lists the agent back ends a session can use (chosen in
    the editor's Settings tab, decision #64); only `claude` exists.

  - API key: given per session as `api_key` (the key text) or `api_key_file`
    (a file on the server machine whose first line is the key), or else the
    server default: the `ANTHROPIC_API_KEY` environment variable, or the
    first line of `~/.anthropic`. With no server default the Agent tab says
    so, and a session starts only when the Settings tab gives a key. A key
    is kept in server memory with its session and never returned in the
    session state.

  - Model: chosen per session from `MODELS`; the default is
    `PPEDIT_CLAUDE_MODEL` from the environment or `DEFAULT_MODEL`.

Data sources
------------

Every session can read and edit the case, validate it and run PF/OPF,
including multistep OPF over the case time series (`multistep` and
`window` of the `solve` tool, as in `/api/solve`). It can also read
(issue #162):

  - `get_series`: the time series of the case (`Case.series`) and their
    combined horizon (`Case.combined_series`), as summaries or as step
    rows, filtered by column name or prefix;

  - `get_result`: the editor's last solution (`Editor.result`), whether
    the page or the session ran it: its summary (with the result columns
    of each table), result rows (with the extended columns on request),
    the solver log, and for a multistep OPF the horizon cost and window,
    the per-step summary (as the Results tab's Steps block), the rows and
    storage of any step, and any result column of chosen rows at every
    step (`column`, `rows`);

  - `get_issues`: what the Issues tab lists: `Case.validate()` and the
    last solve's `messages` with their `detail`.

The `solve` tool refuses to run while a solve started from the page is
still running (decision #63).

Two optional data sources are chosen when a session is created:

  - `web`: Anthropic's server-side web search tool and a `fetch_url` tool
    that downloads a public `http(s)` page or data file through the
    `ppedit` server (text, at most `FETCH_LIMIT` bytes).

  - `local`: `list_files` and `read_file` tools for files under one
    folder on the server machine (`root`, default: the folder of the open
    case file, or the current folder). Paths that resolve outside `root`
    are refused.

Geodata can be loaded from either source with `load_geodata` (CSV text
or a local CSV file).

Caveats
-------

  - Sessions live in server memory and are lost when the server stops.

  - Several sessions may edit the case at the same time; each tool call is
    one undoable edit, so concurrent sessions interleave their edits.

  - Tool results sent to Claude are cut to `RESULT_LIMIT` characters.
"""

import itertools
import json
import os
import threading
import time
import urllib.error
import urllib.request

from ppedit.case import COLUMNS, TABLES, RESULT_COLUMNS, PF_SOLVERS, OPF_SOLVERS, CaseError

API_URL = "https://api.anthropic.com/v1/messages"
"""Anthropic Messages API endpoint"""

API_VERSION = "2023-06-01"
"""Value of the `anthropic-version` header"""

AGENTS = ["claude"]
"""Agent back ends sessions can use (the editor's Settings tab picks one)"""

MODELS = ["claude-sonnet-5-5","claude-opus-5-5","claude-haiku-5-5"]
"""Models offered in the editor (first is the default)"""

DEFAULT_MODEL = os.environ.get("PPEDIT_CLAUDE_MODEL",MODELS[0])
"""Model used when a session does not choose one"""

MAX_TOKENS = 8192
"""Maximum tokens per Claude response"""

MAX_STEPS = 40
"""Maximum API calls in one turn (a user message and the tool use it causes)"""

RESULT_LIMIT = 30000
"""Maximum characters of one tool result sent to Claude"""

FETCH_LIMIT = 2000000
"""Maximum bytes read by `fetch_url`"""

READ_LIMIT = 2000000
"""Maximum bytes read by `read_file`"""

def api_key() -> str|None:
    """Return the Anthropic API key from the environment or `~/.anthropic`"""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key.strip()
    try:
        with open(os.path.expanduser("~/.anthropic"),encoding="utf-8") as fh:
            return fh.readline().strip() or None
    except OSError:
        return None

def read_key_file(path:str) -> str:
    """Return the API key in the first line of a file on the server machine

    Arguments
    ---------

      - `path`: file name (`~` is expanded)

    Raises `CaseError` when the file cannot be read or its first line is
    empty. The message names the file, never its contents.
    """
    name = os.path.expanduser(str(path or "").strip())
    if not name:
        raise CaseError("no API key file given")
    try:
        with open(name,encoding="utf-8") as fh:
            key = fh.readline().strip()
    except OSError as err:
        raise CaseError(f"cannot read API key file '{path}': {err.strerror}") from err
    if not key:
        raise CaseError(f"API key file '{path}' is empty")
    return key

def http_client(payload:dict,key:str|None=None) -> dict:
    """Send one Messages API request and return the response

    Arguments
    ---------

      - `payload`: request body (`model`, `system`, `messages`, `tools`, ...)

      - `key`: API key (default: `api_key()`)

    Returns
    -------

      - `dict`: the API response

    Raises `RuntimeError` with the API's error message on failure.
    """
    key = key or api_key()
    if not key:
        raise RuntimeError("no Anthropic API key (set ANTHROPIC_API_KEY or create ~/.anthropic)")
    req = urllib.request.Request(API_URL,data=json.dumps(payload).encode(),method="POST",
        headers={"x-api-key":key,"anthropic-version":API_VERSION,
            "content-type":"application/json"})
    try:
        with urllib.request.urlopen(req,timeout=600) as res:
            return json.loads(res.read())
    except urllib.error.HTTPError as err:
        try:
            msg = json.loads(err.read())["error"]["message"]
        except Exception: # pylint: disable=broad-exception-caught
            msg = str(err)
        raise RuntimeError(f"Claude API error {err.code}: {msg}") from err
    except urllib.error.URLError as err:
        raise RuntimeError(f"cannot reach the Claude API: {err.reason}") from err

# ---------------------------------------------------------------------------
# tools
# ---------------------------------------------------------------------------

_TABLE = {"type":"string","enum":TABLES}

_SERIES_ROWS = 24
"""Steps `get_series` returns when `count` is not given"""

_RESULT_ROWS = 200
"""Rows `get_result` returns when `count` is not given"""

_RESULT_TABLES = ["bus","gen","branch","dcline","areas","steps","storage"]

CASE_TOOLS = [
    {"name":"get_case","description":"Summary of the open case: name, baseMVA, "
        "version, row count of each table, geodata row count, and load notes.",
        "input_schema":{"type":"object","properties":{}}},
    {"name":"get_table","description":"Rows of one table as objects keyed by "
        "column name, with their 0-based row index. Use start/count to page "
        "through large tables.",
        "input_schema":{"type":"object","properties":{"table":_TABLE,
            "start":{"type":"integer","minimum":0},"count":{"type":"integer","minimum":1}},
            "required":["table"]}},
    {"name":"set_cell","description":"Set one cell. Renumbering a bus renumbers "
        "its references. Returns whether other cells changed as a result.",
        "input_schema":{"type":"object","properties":{"table":_TABLE,
            "row":{"type":"integer","minimum":0},"column":{"type":"string"},
            "value":{"type":["number","string"]}},"required":["table","row","column","value"]}},
    {"name":"set_cells","description":"Set several cells as one undoable edit; "
        "all are rolled back if any fails.",
        "input_schema":{"type":"object","properties":{"edits":{"type":"array","items":{
            "type":"object","properties":{"table":_TABLE,"row":{"type":"integer","minimum":0},
                "column":{"type":"string"},"value":{"type":["number","string"]}},
            "required":["table","row","column","value"]}}},"required":["edits"]}},
    {"name":"add_rows","description":"Add rows to a table as one undoable edit. "
        "Each row is an object of column values (missing columns get defaults) "
        "or a full list in column order. Adding a gen or dcline also adds its "
        "cost row when the case has costs. Returns the new row indexes.",
        "input_schema":{"type":"object","properties":{"table":_TABLE,
            "rows":{"type":"array","items":{"type":["object","array"]}},
            "after":{"type":"integer","minimum":0,"description":"insert after this row (default: append)"}},
            "required":["table","rows"]}},
    {"name":"delete_rows","description":"Delete rows by 0-based index. Deleting "
        "buses that have connections needs cascade=true (connections are deleted too).",
        "input_schema":{"type":"object","properties":{"table":_TABLE,
            "rows":{"type":"array","items":{"type":"integer","minimum":0}},
            "cascade":{"type":"boolean"}},"required":["table","rows"]}},
    {"name":"set_global","description":"Set the case name, baseMVA or version.",
        "input_schema":{"type":"object","properties":{"key":{"type":"string",
            "enum":["name","baseMVA","version"]},"value":{"type":["number","string"]}},
            "required":["key","value"]}},
    {"name":"validate","description":"Check the case; returns the list of errors and warnings.",
        "input_schema":{"type":"object","properties":{}}},
    {"name":"solve","description":"Run a PYPOWER power flow (pf) or optimal power "
        "flow (opf, needs gencost). algorithm: for pf one of "+", ".join(PF_SOLVERS)
        +" (default NR); for opf one of "+", ".join(OPF_SOLVERS)+" (default PIPS; "
        "DC-* solve the DC OPF; IPOPT, CPLEX, MOSEK and Gurobi need their Python "
        "module installed; CVXOPF-* use cvxopf if installed: AC, SOCP relaxation, "
        "lossy DC network flow, copper plate (1NODE), no prices; options for CVXOPF-* only: "
        "preparation default|recommended, solver (CVXPY solver for the convex models), verbose, "
        "solver_options {name: value}). Returns a summary with messages (solver errors and "
        "warnings; a warning's detail gives its physical meaning and the constraints and case rows "
        "involved); the full result is shown in the editor's Results tab and read with "
        "get_result. multistep=true solves the combined time series (get_series) as one "
        "multistep OPF (opf with a CVXOPF-* solver only), over the combined steps "
        "window [first, last] (counted from 0, both included; default all).",
        "input_schema":{"type":"object","properties":{"kind":{"type":"string","enum":["pf","opf"]},
            "algorithm":{"type":"string","enum":[*PF_SOLVERS,*OPF_SOLVERS]},
            "multistep":{"type":"boolean"},
            "window":{"type":"array","items":{"type":"integer","minimum":0},
                "minItems":2,"maxItems":2},
            "options":{"type":"object","properties":{
                "preparation":{"type":"string","enum":["default","recommended"]},
                "solver":{"type":"string"},"verbose":{"type":"boolean"},
                "solver_options":{"type":"object"}}}}}},
    {"name":"apply_result","description":"Copy the last solution (voltages, "
        "generator outputs) into the case; for a multistep solution, the step "
        "given by step (counted from 0 in the solved window, default 0).",
        "input_schema":{"type":"object","properties":{"step":{"type":"integer","minimum":0}}}},
    {"name":"get_series","description":"Time series of case values used by multistep "
        "OPF. Without name: the summary of every series (columns, steps, hours per step, "
        "first and last labels) and of the combined series the multistep OPF solves "
        "(or why the series cannot be combined). With name (a series name, or "
        "\"combined\"): its step rows {step (0-based), label, values {column: value}} "
        "from start, count steps (default "+str(_SERIES_ROWS)+"). Columns are "
        "table.column.key: bus.Pd.<bus_i>, bus.Qd.<bus_i>, gen.Pmin.<gen row from 1>, "
        "gen.Pmax.<n>, dcline.Pmin.<n>, dcline.Pmax.<n>; columns limits them to the "
        "names or prefixes given (e.g. [\"bus.Pd\", \"gen.Pmax.3\"]).",
        "input_schema":{"type":"object","properties":{"name":{"type":"string"},
            "start":{"type":"integer","minimum":0},"count":{"type":"integer","minimum":1},
            "columns":{"type":"array","items":{"type":"string"}}}}},
    {"name":"get_result","description":"The last solution in the editor, whether the "
        "user (Results tab) or this session ran it; edits clear it. Without table: its "
        "summary (success, solver, objective, losses, row counts, multistep horizon "
        "and window, message count). table bus|gen|branch|dcline|areas: result rows "
        "(extended=true adds prices and multipliers when the solver gives them); "
        "table steps: one summary row per step of a multistep solution; table storage: "
        "storage dispatch of a multistep step. step (counted from 0 in the solved "
        "window) picks a multistep step (default 0). For a multistep solution, "
        "table with column (a result column such as Pg, Vm, loading_pct, Pd, E, or an "
        "extended column such as lam_P; the summary lists them) gives that column "
        "of every row, or of rows (0-based), at every step: the optimization "
        "result over the horizon. start/count page the rows (the steps with column). "
        "log=true adds the end of the solver log (the step's report with step).",
        "input_schema":{"type":"object","properties":{"table":{"type":"string",
            "enum":_RESULT_TABLES},"step":{"type":"integer","minimum":0},
            "column":{"type":"string"},
            "rows":{"type":"array","items":{"type":"integer","minimum":0}},
            "start":{"type":"integer","minimum":0},"count":{"type":"integer","minimum":1},
            "extended":{"type":"boolean"},"log":{"type":"boolean"}}}},
    {"name":"get_issues","description":"Everything the editor's Issues tab lists: "
        "case issues (the same as validate) and the errors and warnings of the last "
        "solve, each warning with its detail when known (physical meaning, constraints "
        "and case rows involved).",
        "input_schema":{"type":"object","properties":{}}},
    {"name":"load_geodata","description":"Replace the case geodata (bus "
        "locations) from CSV with columns BUS_I, LAT, LON (others kept as "
        "auxiliary data), given as text or as a local file path.",
        "input_schema":{"type":"object","properties":{"text":{"type":"string"},
            "path":{"type":"string"}}}},
]

WEB_TOOLS = [
    {"type":"web_search_20250305","name":"web_search","max_uses":10},
    {"name":"fetch_url","description":"Download a public http(s) page or data "
        "file (CSV, JSON, text, HTML) and return its text.",
        "input_schema":{"type":"object","properties":{"url":{"type":"string"}},"required":["url"]}},
]

LOCAL_TOOLS = [
    {"name":"list_files","description":"List files and folders in a folder under "
        "the local data folder (path relative to it; default: the folder itself).",
        "input_schema":{"type":"object","properties":{"path":{"type":"string"}}}},
    {"name":"read_file","description":"Read a text file under the local data folder "
        "(path relative to it). Use offset/limit (characters) for large files.",
        "input_schema":{"type":"object","properties":{"path":{"type":"string"},
            "offset":{"type":"integer","minimum":0},"limit":{"type":"integer","minimum":1}},
            "required":["path"]}},
]

def _columns_text():
    lines = []
    for table,cols in COLUMNS.items():
        lines.append(f"- {table}: " + ", ".join(
            c["name"] + (f" [{c['unit']}]" if c["unit"] else "")
            + (f" {{{', '.join(f'{k}={v}' for k,v in c['options'].items())}}}" if c["options"] else "")
            for c in cols))
    return "\n".join(lines)

SYSTEM = """You are working inside ppedit, a browser editor for PYPOWER power \
system cases (also Arras Energy GridLAB-D `module pypower` models). You read \
and change the case open in the editor only through the tools provided; the \
user sees every change immediately in the editor and can undo each tool call.

Tables and columns (PYPOWER caseformat; row indexes are 0-based):
{columns}

Conventions:
- gencost and dclinecost rows follow gen and dcline row by row; costs is a \
comma-separated string of coefficients (polynomial, highest order first) or \
x,y pairs (piecewise).
- areas rows are [area, price_ref_bus, name]; bus.area holds each bus's area number
  (the key); name is an optional free-text label (e.g. a balancing authority code).
- storage rows are discharged by generator row gen_i (counted from 1, unlike \
row indexes) and charge at bus bus_i, or through that generator when bus_i is \
-1; only multistep CVXOPF OPF models them (Es is the starting energy, Eend -1 \
leaves the final energy free).
- Infinite limits are the strings "Inf" and "-Inf".
- Enum columns accept the code or the keyword shown in braces.
- Multistep data: get_series reads the time series of loads and limits; the \
multistep OPF solves their combined series (solve with multistep=true). Step \
numbers in tools count from 0; the editor shows them counted from 1.
- Results and issues: get_result reads the last solution, including one the \
user ran in the editor and each step of a multistep solution; get_issues \
reads what the Issues tab shows (case issues and the last solve's messages). \
For a multistep OPF, get_result with table steps summarizes every step, and \
with table and column gives one quantity (e.g. gen Pg, bus lam_P, branch \
loading_pct, storage E) of the rows you choose across all steps. \
Read them before explaining a result or an issue, and do not solve again \
just to see a result that already exists.

Work carefully: read the tables you need before editing, prefer one \
set_cells or add_rows call for related changes, validate after editing, and \
tell the user briefly what you changed and why. When you use outside data, \
say where it came from.{sources}"""

def _system(web,local,root):
    sources = []
    if web:
        sources.append("You may search the web and fetch public data with web_search and fetch_url.")
    if local:
        sources.append(f"You may read local files under the data folder {root} with list_files and read_file.")
    if not sources:
        sources.append("No outside data sources are enabled in this session; use only the case and what the user tells you.")
    return SYSTEM.format(columns=_columns_text(),sources="\n\n"+" ".join(sources))

def _row_dict(table,row):
    return {c["name"]:v for c,v in zip(COLUMNS[table],row)}

def _page(rows,args,default):
    """Rows `start` to `start + count` (`count` default `default`) as
    `(start, rows)`"""
    start = int(args.get("start") or 0)
    count = int(args.get("count") or default)
    return start,rows[start:start+count]

def _series_tool(case,args) -> dict:
    """Result of the `get_series` tool"""
    name = args.get("name")
    if not name:
        combined = case._combined_info() # pylint: disable=protected-access
        return {"series":[{"name":s["name"],"columns":len(s["columns"]),"steps":len(s["values"]),
                "delta_h":s["delta"],"timed":s["timed"],
                "first":s["index"][0] if s["index"] else None,
                "last":s["index"][-1] if s["index"] else None} for s in case.series],
            "combined":{k:v for k,v in combined.items() if k != "index"} if combined else None,
            **({} if case.series else {"note":"the case has no time series"})}
    ser = case.get_series(name)
    if ser is None and name == "combined":
        ser = case.combined_series()
    if ser is None:
        raise CaseError(f"no series '{name}' (series: "
            + (", ".join(s["name"] for s in case.series) or "none") + "; or 'combined')")
    prefixes = [str(p).strip().lower() for p in args.get("columns") or [] if str(p).strip()]
    keep = [j for j,c in enumerate(ser["columns"]) if not prefixes
        or any(c.lower() == p or c.lower().startswith(p + ".") for p in prefixes)]
    start,steps = _page(list(range(len(ser["values"]))),args,_SERIES_ROWS)
    return {"name":name,"steps":len(ser["values"]),"delta_h":ser["delta"],"timed":ser["timed"],
        "columns":len(ser["columns"]),"columns_shown":len(keep),"start":start,
        "rows":[{"step":t,"label":ser["index"][t],
            "values":{ser["columns"][j]:ser["values"][t][j] for j in keep}} for t in steps]}

def _multistep_info(result) -> dict:
    """Multistep horizon of a result, without the full list of step labels"""
    info = result.get("multistep") or {}
    index = info.get("index") or []
    steps = result.get("steps") or []
    return {**{k:v for k,v in info.items() if k != "index"},
        "first_label":index[0] if index else None,"last_label":index[-1] if index else None,
        "horizon_objective":result.get("horizon_objective"),
        "steps_solved":sum(1 for s in steps if s.get("success"))}

def _result_summary(result) -> dict:
    """Summary of a solver result"""
    messages = result.get("messages") or []
    out = {k:result.get(k) for k in ("success","kind","algorithm","solver","dc","stopped",
        "iterations","objective","losses_MW","dcline_losses_MW","options")}
    out["rows"] = {t:len(result.get(t) or []) for t in ("bus","gen","branch","dcline","areas")}
    out["messages"] = {level:sum(1 for m in messages if m.get("level") == level)
        for level in ("error","warning")}
    if result.get("multistep"):
        out["multistep"] = _multistep_info(result)
    if result.get("success"):
        out["columns"] = _result_columns((result.get("steps") or [result])[0])
    return out

def _result_step(result,step):
    """The result of multistep step `step` (counted from 0), or the result
    itself when it is not multistep and `step` is 0 or `None`"""
    if not result:
        raise CaseError("no solution: the case has not been solved since the last edit")
    steps = result.get("steps")
    if not steps:
        if step not in (None,0):
            raise CaseError("the last solution is not a multistep solution")
        return result
    step = int(step or 0)
    if not 0 <= step < len(steps):
        raise CaseError(f"the multistep solution has steps 0 to {len(steps)-1}")
    return steps[step]

def _result_columns(step) -> dict:
    """Column names of each result table of one (step) result, extended
    columns included"""
    out = {}
    for table in ("bus","gen","branch","dcline","areas","storage"):
        rows = step.get(table) or []
        if rows:
            out[table] = list(rows[0]) + [c["name"] for c in RESULT_COLUMNS.get(table,[])
                if (step.get("extended") or {}).get(table)]
    return out

def _value(step,table,column,n):
    """Value of `column` in row `n` of `table` of one (step) result, from
    the result rows or the extended columns"""
    rows = step.get(table) or []
    if n >= len(rows):
        return None
    if column in rows[n]:
        return rows[n][column]
    names = [c["name"] for c in RESULT_COLUMNS.get(table,[])]
    ext = (step.get("extended") or {}).get(table)
    if column in names and ext and n < len(ext):
        return ext[n][names.index(column)]
    raise CaseError(f"result table '{table}' has no column '{column}' (columns: "
        + ", ".join(_result_columns(step).get(table,[])) + ")")

def _trajectory(result,table,args) -> dict:
    """`get_result` with `column`: one result column of the chosen rows at
    every step of a multistep solution (one value per row and step)"""
    steps = result.get("steps")
    if not steps:
        raise CaseError("column needs a multistep solution (read one step's rows with table)")
    if table not in ("bus","gen","branch","dcline","areas","storage"):
        raise CaseError("column needs table bus, gen, branch, dcline, areas or storage")
    column = args["column"]
    total = len(steps[0].get(table) or [])
    rows = [int(n) for n in args.get("rows") or range(total)]
    bad = [n for n in rows if not 0 <= n < total]
    if bad:
        raise CaseError(f"result table '{table}' has rows 0 to {total-1}, not {bad}")
    start,picked = _page(list(range(len(steps))),args,_RESULT_ROWS)
    values = [[_value(steps[t],table,column,n) for n in rows] for t in picked]
    keys = {"bus":"bus_i","areas":"area"}.get(table)
    return {"table":table,"column":column,"rows":rows,
        **({keys:[(steps[0][table][n] or {}).get(keys) for n in rows]} if keys else {}),
        "steps":len(steps),"start":start,
        "values":[{"step":t,"label":steps[t].get("label"),"values":v} for t,v in zip(picked,values)]}

def _result_tool(result,args) -> dict:
    """Result of the `get_result` tool"""
    if not result:
        return {"solution":None,"note":"no solution: the case has not been solved since the "
            "last edit (edits, undo and opening a case clear it)"}
    table,step = args.get("table"),args.get("step")
    if args.get("column"):
        return _trajectory(result,table,args)
    if table == "steps":
        if not result.get("steps"):
            raise CaseError("the last solution is not a multistep solution")
        rows = [{"step":t,"label":s.get("label"),"success":s.get("success"),
                "objective":s.get("objective"),"losses_MW":s.get("losses_MW"),
                "dcline_losses_MW":s.get("dcline_losses_MW"),
                "Pg_MW":sum(g.get("Pg") or 0 for g in s.get("gen") or []),
                "Pd_MW":sum(a.get("Pd") or 0 for a in s.get("areas") or []),
                **({"storage_MW":sum((x.get("Pdis") or 0) - (x.get("Pch") or 0)
                        for x in s["storage"] if x.get("solved")),
                    "stored_MWh":sum(x.get("E") or 0 for x in s["storage"] if x.get("solved"))}
                    if any(x.get("solved") for x in s.get("storage") or []) else {})}
            for t,s in enumerate(result["steps"])]
        start,rows = _page(rows,args,_RESULT_ROWS)
        return {"table":"steps","total":len(result["steps"]),"start":start,"rows":rows}
    target = _result_step(result,step)
    if table is None:
        out = _result_summary(result)
        if result.get("steps"):
            out["step"] = {"step":int(step or 0),**{k:target.get(k) for k in ("label","success",
                "objective","losses_MW","dcline_losses_MW","areas")}}
    else:
        if table not in _RESULT_TABLES:
            raise CaseError(f"unknown result table '{table}'")
        rows = target.get(table) or []
        ext = target.get("extended",{}).get(table) if args.get("extended") else None
        names = [c["name"] for c in RESULT_COLUMNS.get(table,[])]
        out_rows = []
        for n,row in enumerate(rows):
            item = {"row":n,**row}
            if ext and n < len(ext):
                item.update({k:v for k,v in zip(names,ext[n]) if v is not None})
            out_rows.append(item)
        start,out_rows = _page(out_rows,args,_RESULT_ROWS)
        out = {"table":table,"total":len(rows),"start":start,"rows":out_rows}
        if result.get("steps"):
            out |= {"step":int(step or 0),"label":target.get("label")}
    if args.get("log"):
        out["log"] = (target.get("log") or "")[-6000:]
    return out

def _clip(text):
    if len(text) <= RESULT_LIMIT:
        return text
    return text[:RESULT_LIMIT] + f"\n... [cut: {len(text)-RESULT_LIMIT} more characters]"

# ---------------------------------------------------------------------------
# sessions
# ---------------------------------------------------------------------------

class Session:
    """One conversation with Claude about the open case

    Arguments
    ---------

      - `sid`: session id

      - `editor`: the `ppedit.server.Editor` being edited

      - `client`: function sending one API request (see `http_client`)

      - `title`: display title

      - `model`: Claude model name

      - `web`: enable the web data source

      - `local`: enable the local files data source

      - `root`: local data folder

      - `key`: API key for this session (default: the client's own)
    """

    def __init__(self,sid,editor,client,title="",model=None,web=False,local=False,root=None,
            key=None):
        self.id = sid
        self.editor = editor
        self.client = client
        self.title = title or f"Session {sid}"
        self.model = model or DEFAULT_MODEL
        self.web = bool(web)
        self.local = bool(local)
        self.root = os.path.realpath(os.path.expanduser(root)) if root else None
        if self.local and (not self.root or not os.path.isdir(self.root)):
            raise CaseError(f"local data folder '{root}' not found")
        self.messages = []
        """Conversation sent to the API"""
        self.transcript = []
        """Items shown in the editor: `{"kind": "user"|"assistant"|"tool"|"error", ...}`"""
        self.status = "idle"
        """`idle`, `running`, or `stopping`"""
        self.edits = 0
        """Number of tool calls that changed the case"""
        self.usage = {"input_tokens":0,"output_tokens":0}
        self.created = time.time()
        self.agent = "claude"
        """Agent back end (see `AGENTS`)"""
        self._key = key or None
        self._stop = False
        self._thread = None
        self._lock = threading.Lock()

    def summary(self) -> dict:
        """Return the session for the browser"""
        with self._lock:
            return {"id":self.id,"title":self.title,"agent":self.agent,"model":self.model,
                "web":self.web,"local":self.local,"root":self.root,
                "status":self.status,"edits":self.edits,"usage":dict(self.usage),
                "transcript":list(self.transcript)}

    def _add(self,**item):
        with self._lock:
            item["time"] = time.time()
            self.transcript.append(item)

    def send(self,text:str):
        """Add a user message and start working on it in the background"""
        text = (text or "").strip()
        if not text:
            raise CaseError("empty message")
        with self._lock:
            if self.status != "idle":
                raise CaseError("this session is still working")
            self.status = "running"
            self._stop = False
        self.messages.append({"role":"user","content":[{"type":"text","text":text}]})
        self._add(kind="user",text=text)
        self._thread = threading.Thread(target=self._run,daemon=True)
        self._thread.start()

    def stop(self):
        """Ask the session to stop after the current step"""
        with self._lock:
            if self.status == "running":
                self.status = "stopping"
                self._stop = True

    def wait(self,timeout:float|None=None):
        """Wait for the background work to finish (for tests and scripts)"""
        if self._thread:
            self._thread.join(timeout)

    def _tools(self):
        return CASE_TOOLS + (WEB_TOOLS if self.web else []) + (LOCAL_TOOLS if self.local else [])

    def _run(self):
        try:
            for _ in range(MAX_STEPS):
                if self._stop:
                    self._add(kind="error",text="stopped")
                    break
                payload = {"model":self.model,"max_tokens":MAX_TOKENS,
                    "system":[{"type":"text","text":_system(self.web,self.local,self.root),
                        "cache_control":{"type":"ephemeral"}}],
                    "tools":self._tools(),"messages":self.messages}
                res = self.client(payload,key=self._key) if self._key else self.client(payload)
                usage = res.get("usage") or {}
                with self._lock:
                    for k in self.usage:
                        self.usage[k] += int(usage.get(k) or 0)
                content = res.get("content") or []
                self.messages.append({"role":"assistant","content":content})
                results = []
                for block in content:
                    kind = block.get("type")
                    if kind == "text" and block.get("text","").strip():
                        self._add(kind="assistant",text=block["text"])
                    elif kind == "server_tool_use":
                        self._add(kind="tool",name=block.get("name"),input=block.get("input"),
                            result="(searched by Claude)",ok=True)
                    elif kind == "tool_use":
                        results.append(self._call(block))
                stop = res.get("stop_reason")
                if results:
                    self.messages.append({"role":"user","content":results})
                    continue
                if stop == "pause_turn":
                    continue
                if stop == "max_tokens":
                    self._add(kind="error",text="response cut off (max_tokens)")
                break
            else:
                self._add(kind="error",text=f"stopped after {MAX_STEPS} steps")
        except Exception as err: # pylint: disable=broad-exception-caught
            self._add(kind="error",text=str(err))
            # keep the conversation valid for the next message
            if self.messages and self.messages[-1]["role"] == "user" \
                    and any(b.get("type") == "tool_result" for b in self.messages[-1]["content"]):
                self.messages.append({"role":"assistant","content":[{"type":"text","text":"(interrupted)"}]})
        finally:
            if self.messages and self.messages[-1]["role"] == "assistant" \
                    and any(b.get("type") == "tool_use" for b in self.messages[-1]["content"]):
                # stopped before the tool results were sent
                self.messages.append({"role":"user","content":[{"type":"tool_result",
                    "tool_use_id":b["id"],"content":"not run (stopped)","is_error":True}
                    for b in self.messages[-1]["content"] if b.get("type") == "tool_use"]})
                self.messages.append({"role":"assistant","content":[{"type":"text","text":"(stopped)"}]})
            with self._lock:
                self.status = "idle"

    def _call(self,block):
        name,args = block.get("name"),block.get("input") or {}
        try:
            out,changed = self.run_tool(name,args)
            ok = True
        except Exception as err: # pylint: disable=broad-exception-caught
            out,changed,ok = f"error: {err}",False,False
        text = out if isinstance(out,str) else json.dumps(out,default=str)
        if changed:
            with self._lock:
                self.edits += 1
        self._add(kind="tool",name=name,input=args,result=_clip(text)[:2000],ok=ok,changed=changed)
        return {"type":"tool_result","tool_use_id":block["id"],"content":_clip(text),
            **({} if ok else {"is_error":True})}

    def _edit(self,func):
        editor = self.editor
        with editor.lock:
            before = editor.revision
            out = editor.edit(func)
            return out,editor.revision != before

    def run_tool(self,name:str,args:dict):
        """Run one tool call; return `(result, changed)`"""
        # pylint: disable=too-many-return-statements,too-many-branches,too-many-locals,too-many-statements
        editor = self.editor
        if name == "get_case":
            with editor.lock:
                case = editor.case
                combined = case._combined_info() # pylint: disable=protected-access
                return {"name":case.name,"baseMVA":case.baseMVA,"version":case.version,
                    "rows":{t:len(r) for t,r in case.tables.items()},
                    "geodata_rows":len(case.geodata),"notes":case.notes,
                    "file":editor.path,"unsaved_changes":editor.dirty,
                    "series":[s["name"] for s in case.series],
                    "combined_series":{k:v for k,v in combined.items() if k != "index"}
                        if combined else None,
                    "issues":len(case.validate()),
                    "solution":_result_summary(editor.result) if editor.result else None},False
        if name == "get_table":
            table = args["table"]
            if table not in COLUMNS:
                raise CaseError(f"unknown table '{table}'")
            start = int(args.get("start") or 0)
            count = int(args.get("count") or 200)
            with editor.lock:
                rows = editor.case.tables[table]
                return {"table":table,"total":len(rows),"start":start,
                    "rows":[{"row":i,**_row_dict(table,r)}
                        for i,r in enumerate(rows[start:start+count],start)]},False
        if name == "set_cell":
            cascade,changed = self._edit(lambda: editor.case.set_value(
                args["table"],int(args["row"]),args["column"],args["value"]))
            return {"ok":True,"other_cells_changed":bool(cascade)},changed
        if name == "set_cells":
            def apply():
                for e in args["edits"]:
                    editor.case.set_value(e["table"],int(e["row"]),e["column"],e["value"])
                return len(args["edits"])
            n,changed = self._edit(apply)
            return {"ok":True,"cells":n},changed
        if name == "add_rows":
            def add():
                after = args.get("after")
                out = []
                for values in args["rows"]:
                    out.append(editor.case.add_row(args["table"],values,after))
                    if after is not None:
                        after = out[-1]
                return out
            rows,changed = self._edit(add)
            return {"ok":True,"rows":rows},changed
        if name == "delete_rows":
            removed,changed = self._edit(lambda: editor.case.delete_rows(args["table"],
                [int(x) for x in args["rows"]],bool(args.get("cascade"))))
            return {"ok":True,"removed":removed},changed
        if name == "set_global":
            _,changed = self._edit(lambda: editor.case.set_global(args["key"],args["value"]))
            return {"ok":True},changed
        if name == "validate":
            with editor.lock:
                issues = editor.case.validate()
            return {"issues":issues} if issues else "no issues found",False
        if name == "solve":
            with editor.lock:
                job = getattr(editor,"job",None)
                if job is not None and not job.done:
                    raise CaseError("a solve started in the editor is still running: "
                        "wait for it to end, then read it with get_result")
                result = editor.case.solve(args.get("kind","pf"),args.get("algorithm"),
                    args.get("options"),bool(args.get("multistep")),window=args.get("window"))
                editor.result = result
            out = {k:result.get(k) for k in ("success","kind","algorithm","iterations","objective",
                "losses_MW","areas","messages")}
            if result.get("multistep"):
                out["multistep"] = _multistep_info(result)
                out["note"] = ("areas and objective are those of step 0; "
                    "read every step with get_result")
            return out | {"log":(result.get("log") or "")[-6000:]},False
        if name == "apply_result":
            def apply_result():
                result = _result_step(editor.result,args.get("step"))
                editor.case.apply_result(result)
            _,changed = self._edit(apply_result)
            return {"ok":True},changed
        if name == "get_series":
            with editor.lock:
                return _series_tool(editor.case,args),False
        if name == "get_result":
            with editor.lock:
                return _result_tool(editor.result,args),False
        if name == "get_issues":
            with editor.lock:
                issues = editor.case.validate()
                result = editor.result
            last = None
            if result:
                last = {"kind":result.get("kind"),"algorithm":result.get("algorithm"),
                    "success":result.get("success"),"messages":result.get("messages") or []}
            note = {} if result else {"note":"no solution since the last edit, "
                "so no solve messages"}
            return {"case":issues,"last_solve":last,**note},False
        if name == "load_geodata":
            if args.get("text"):
                n,changed = self._edit(lambda: editor.case.load_geodata("geodata.csv",args["text"]))
            elif args.get("path"):
                path = self._local(args["path"])
                n,changed = self._edit(lambda: editor.case.load_geodata(path))
            else:
                raise CaseError("give text or path")
            return {"ok":True,"rows":n},changed
        if name == "fetch_url" and self.web:
            return _fetch(args["url"]),False
        if name == "list_files" and self.local:
            path = self._local(args.get("path") or ".")
            return [e.name + ("/" if e.is_dir() else "") for e in sorted(os.scandir(path),
                key=lambda e: e.name) if not e.name.startswith(".")][:1000],False
        if name == "read_file" and self.local:
            path = self._local(args["path"])
            with open(path,encoding="utf-8",errors="replace") as fh:
                text = fh.read(READ_LIMIT)
            offset = int(args.get("offset") or 0)
            limit = int(args.get("limit") or RESULT_LIMIT)
            return {"path":args["path"],"size":len(text),"offset":offset,
                "text":text[offset:offset+limit]},False
        raise CaseError(f"tool '{name}' is not available in this session")

    def _local(self,path):
        """Resolve a path under the local data folder"""
        if not self.local:
            raise CaseError("local files are not enabled in this session")
        full = os.path.realpath(os.path.join(self.root,os.path.expanduser(path)))
        if os.path.commonpath([full,self.root]) != self.root:
            raise CaseError(f"'{path}' is outside the local data folder")
        if not os.path.exists(full):
            raise CaseError(f"'{path}' not found")
        return full

def _fetch(url):
    if not url.lower().startswith(("http://","https://")):
        raise CaseError("only http and https URLs can be fetched")
    req = urllib.request.Request(url,headers={"User-Agent":"ppedit"})
    try:
        with urllib.request.urlopen(req,timeout=60) as res:
            data = res.read(FETCH_LIMIT+1)
            ctype = res.headers.get("Content-Type","")
    except urllib.error.HTTPError as err:
        raise CaseError(f"HTTP {err.code} from {url}") from err
    except urllib.error.URLError as err:
        raise CaseError(f"cannot fetch {url}: {err.reason}") from err
    cut = len(data) > FETCH_LIMIT
    text = data[:FETCH_LIMIT].decode("utf-8",errors="replace")
    return {"url":url,"content_type":ctype,"truncated":cut,"text":text}

class Sessions:
    """All Claude sessions of one editor

    Arguments
    ---------

      - `editor`: the `ppedit.server.Editor` the sessions edit

      - `client`: function sending one API request (default `http_client`);
        tests pass a fake
    """

    def __init__(self,editor,client=None):
        self.editor = editor
        self.client = client or http_client
        self.items = {}
        self._ids = itertools.count(1)
        self.lock = threading.Lock()

    def available(self) -> bool:
        """Whether sessions can reach Claude without a key from the Settings tab
        (a server default key is set, or a test client)"""
        return self.client is not http_client or bool(api_key())

    def default_root(self) -> str:
        """Default local data folder: the open case's folder, else the current folder"""
        return os.path.dirname(self.editor.path) if self.editor.path else os.getcwd()

    def create(self,**options) -> Session:
        """Start a new session

        Arguments
        ---------

          - `agent`: agent back end, one of `AGENTS` (default `claude`)

          - `api_key`: API key text for this session

          - `api_key_file`: file on the server machine whose first line is
            the API key (used when `api_key` is not given)

          - `title`, `model`, `web`, `local`, `root`: see `Session`

        Without `api_key` or `api_key_file` the server default key is used
        (see `api_key`). Raises `CaseError` for an unknown agent, an
        unreadable key file, or when there is no key at all.
        """
        agent = options.get("agent") or "claude"
        if agent not in AGENTS:
            raise CaseError(f"unknown agent '{agent}' (available: {', '.join(AGENTS)})")
        key = str(options.get("api_key") or "").strip() or None
        if not key and options.get("api_key_file"):
            key = read_key_file(options["api_key_file"])
        if not key and not self.available():
            raise CaseError("no Anthropic API key (set ANTHROPIC_API_KEY, create ~/.anthropic, "
                "or give a key in the Settings tab)")
        model = options.get("model") or DEFAULT_MODEL
        if options.get("local") and not options.get("root"):
            options["root"] = self.default_root()
        with self.lock:
            sid = next(self._ids)
            session = Session(sid,self.editor,self.client,options.get("title",""),model,
                options.get("web"),options.get("local"),options.get("root"),key)
            self.items[sid] = session
        return session

    def get(self,sid) -> Session:
        """Return a session by id"""
        try:
            return self.items[int(sid)]
        except (KeyError,TypeError,ValueError) as err:
            raise CaseError(f"no Claude session {sid}") from err

    def delete(self,sid):
        """Stop and forget a session"""
        session = self.get(sid)
        session.stop()
        with self.lock:
            del self.items[session.id]

    def to_dict(self) -> dict:
        """Return all sessions for the browser"""
        with self.lock:
            items = list(self.items.values())
        return {"available":self.available(),"agents":AGENTS,"models":MODELS,"default_model":DEFAULT_MODEL,
            "default_root":self.default_root(),"revision":self.editor.revision,
            "sessions":[s.summary() for s in items]}
