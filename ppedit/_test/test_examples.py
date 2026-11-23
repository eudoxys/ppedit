"""Check the cases in `examples/pypower/` (fast, no network; cvxopf tests skipped without it)"""

import glob
import os

import pytest

from ppedit import Case

EXAMPLES = os.path.join(os.path.dirname(__file__),"..","..","examples","pypower")
CASES = sorted(os.path.splitext(os.path.basename(x))[0]
    for x in glob.glob(os.path.join(EXAMPLES,"case*.py")))

def test_examples_present():
    """Every case has both forms, and the license is kept with them"""
    if not os.path.isdir(EXAMPLES):
        pytest.skip("examples folder not available (installed package only)")
    assert len(CASES) >= 14
    for name in CASES:
        assert os.path.exists(os.path.join(EXAMPLES,f"{name}.glm")),name
    assert os.path.exists(os.path.join(EXAMPLES,"LICENSE"))

@pytest.mark.parametrize("name",CASES)
def test_glm_matches_py(name):
    """The GLM form of each example holds the same case data as its .py file"""
    py = Case.load(os.path.join(EXAMPLES,f"{name}.py"))
    glm = Case.load(os.path.join(EXAMPLES,f"{name}.glm"))
    # module pypower has no areas objects: rebuilt from the bus areas on reading
    assert [r[0] for r in glm.tables["areas"]] == [r[0] for r in py.tables["areas"]]
    assert {k:v for k,v in glm.tables.items() if k != "areas"} \
        == {k:v for k,v in py.tables.items() if k != "areas"}
    assert glm.baseMVA == py.baseMVA
    assert glm.notes == []

# ----- case9_dcline (from cvxopf, with a load time series) -----

DCLINE_CASE = os.path.join(EXAMPLES,"case9_dcline.py")
DCLINE_REFERENCE = os.path.join(os.path.dirname(__file__),"data","case9_dcline_pypower_reference.json")

def _dcline_case():
    if not os.path.exists(DCLINE_CASE):
        pytest.skip("examples folder not available (installed package only)")
    return Case.load(DCLINE_CASE)

def test_case9_dcline_series():
    """24 hourly steps of Pd and Qd at the loaded buses, every step at the base-case demand"""
    case = _dcline_case()
    assert case.notes == [] and case.validate() == []
    assert len(case.series) == 1
    ser = case.series[0]
    assert ser["name"] == "load" and ser["delta"] == 1 and len(ser["values"]) == 24
    assert ser["columns"] == ["bus.Pd.5","bus.Pd.7","bus.Pd.9","bus.Qd.5","bus.Qd.7","bus.Qd.9"]
    bus = {row[0]:row for row in case.tables["bus"]}
    base = [bus[int(c.split(".")[2])][2 if ".Pd." in c else 3] for c in ser["columns"]]
    assert all(row == base for row in ser["values"])

def test_case9_dcline_matches_pypower_reference():
    """ppedit's OPF matches the PYPOWER solution used by cvxopf's case9_dcline tests

    cvxopf's reference (like PYPOWER's `t_dcline.py`) is solved without DC
    line costs; its `Pg`/`Qg` list the generators, then each in-service DC
    line's from end (`-Pf`, `Qf`), then its to end (`Pt`, `Qt`).
    """
    import json # pylint: disable=import-outside-toplevel
    case = _dcline_case()
    with open(DCLINE_REFERENCE,encoding="utf-8") as fh:
        ref = json.load(fh)
    case.tables["dclinecost"] = [[2,0,0,1,"0"] for _ in case.tables["dcline"]]
    res = case.solve("opf","PIPS")
    assert res["success"]
    live = [d for d in res["dcline"] if d["solved"]]
    got = {
        "objective":[res["objective"]],
        "Pg":[g["Pg"] for g in res["gen"]]+[-d["Pf"] for d in live]+[d["Pt"] for d in live],
        "Qg":[g["Qg"] for g in res["gen"]]+[d["Qf"] for d in live]+[d["Qt"] for d in live],
        "Vm":[b["Vm"] for b in res["bus"]],
        "Va_deg":[b["Va"] for b in res["bus"]],
    } | {k:[b[k] for b in res["branch"]] for k in ("PF","QF","PT","QT")}
    for key,values in got.items():
        expected = [ref[key]] if key == "objective" else ref[key]
        assert values == pytest.approx(expected,abs=1e-6),key

def test_case9_dcline_cvxopf():
    """The case data is cvxopf's, and CVXOPF-AC gives cvxopf's own single-period solution"""
    np = pytest.importorskip("numpy")
    pytest.importorskip("cvxopf")
    from cvxopf.testcases.case9_dcline import case9_dcline # pylint: disable=import-outside-toplevel,import-error
    from cvxopf.problem import build_opf # pylint: disable=import-outside-toplevel,import-error
    from cvxopf.hvdc import hvdc_from_dcline # pylint: disable=import-outside-toplevel,import-error
    from cvxopf.results import extract_results # pylint: disable=import-outside-toplevel,import-error
    from ppedit.case import _parse_py # pylint: disable=import-outside-toplevel
    import warnings # pylint: disable=import-outside-toplevel
    case = _dcline_case()
    original = case9_dcline()
    with open(DCLINE_CASE,encoding="utf-8") as fh:
        ppc = _parse_py(fh.read(),"case9_dcline")
    assert set(ppc) == set(original) | {"series"}
    for key,value in original.items():
        assert np.array_equal(np.asarray(ppc[key]),np.asarray(value)),key
    with warnings.catch_warnings():
        warnings.simplefilter("ignore",UserWarning) # converter terms cvxopf does not model
        build = build_opf(original,formulation="ac",
            hvdc=hvdc_from_dcline(original["dcline"],original["dclinecost"]))
    build.solve()
    ref = extract_results(build)
    res = case.solve("opf","CVXOPF-AC")
    assert ref["status"] == "optimal" and res["success"]
    assert res["objective"] == pytest.approx(ref["objective"],rel=1e-6)
    assert [g["Pg"] for g in res["gen"]] == pytest.approx(list(ref["Pg"]),abs=1e-4)
    assert [b["Vm"] for b in res["bus"]] == pytest.approx(list(ref["Vm"]),abs=1e-6)

@pytest.mark.parametrize("algorithm",["CVXOPF-AC","CVXOPF-SOCP","CVXOPF-DC","CVXOPF-1NODE"])
def test_case9_dcline_multistep(algorithm):
    """Multistep OPF over the series: every step solves as the single-period case

    The horizon cost is 24 times the single-period cost for every model;
    for AC the dispatch, voltages and flows of every step match too (the
    convex models may pick another of several optimal dispatches).
    """
    pytest.importorskip("cvxopf")
    case = _dcline_case()
    one = case.solve("opf",algorithm)
    many = case.solve("opf",algorithm,multistep=True)
    assert one["success"] and many["success"]
    assert many["multistep"]["steps"] == len(many["steps"]) == 24
    assert many["horizon_objective"] == pytest.approx(24*one["objective"],rel=1e-6)
    if algorithm != "CVXOPF-AC":
        return
    keys = {"gen":("Pg","Qg"),"bus":("Vm","Va"),"branch":("PF","QF","PT","QT"),"dcline":("Pf","Pt")}
    for step in many["steps"]:
        assert step["objective"] == pytest.approx(one["objective"],rel=1e-8)
        for table,names in keys.items():
            for name in names:
                assert [r[name] for r in step[table]] == pytest.approx(
                    [r[name] for r in one[table]],abs=1e-6),(table,name)
