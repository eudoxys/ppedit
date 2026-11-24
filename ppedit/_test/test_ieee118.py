"""Check the Tracy 2021 study cases in `examples/ieee118/` (fast; solves skipped without cvxopf)"""

import importlib.util
import os

import pytest

from ppedit import Case

FOLDER = os.path.join(os.path.dirname(__file__),"..","..","examples","ieee118")
STUDIES = ["surplus","deficit","deficit_depletion","surplus_to_deficit","deficit_to_surplus","forced_shedding"]

def _builder():
    path = os.path.join(FOLDER,"build_tracy2021.py")
    if not os.path.exists(path):
        pytest.skip("examples folder not available (installed package only)")
    pytest.importorskip("pandas")
    spec = importlib.util.spec_from_file_location("build_tracy2021",path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def test_case_files_are_current(tmp_path):
    """The committed case files are what `build_tracy2021.py` writes"""
    builder = _builder()
    assert builder.main(["--output",str(tmp_path)]) == 0
    for name in STUDIES:
        file = f"case118_tracy2021_{name}.py"
        with open(os.path.join(FOLDER,file),encoding="utf-8") as fh:
            committed = fh.read()
        with open(tmp_path/file,encoding="utf-8") as fh:
            assert fh.read() == committed,file

@pytest.mark.parametrize("name",STUDIES)
def test_case_contents(name):
    """Generators, storage and series as documented in `build_tracy2021.py`"""
    builder = _builder()
    case = Case.load(os.path.join(FOLDER,f"case118_tracy2021_{name}.py"))
    start,stop,e0,e1,demand = builder.STUDIES[name]
    size = case.size()
    assert size["bus"] == 118 and size["branch"] == 186 and size["gen"] == 299 and size["storage"] == 27
    storage = case.tables["storage"]
    assert [r[0] for r in storage] == list(range(55,82))
    for row in storage:
        assert row[2] == pytest.approx(e0*row[4],rel=1e-9) and row[10] == pytest.approx(e1*row[4],rel=1e-9)
    costs = [float(r[4].split(",")[1]) for r in case.tables["gencost"]]
    assert costs[200:] == [builder.SHEDDING_COST]*99 and costs[54:200] == [0.0]*146
    ser = case.series[0]
    assert len(ser["values"]) == stop - start and ser["delta"] == 1
    assert ser["index"][0].endswith("-08:00")
    col = {k:i for i,k in enumerate(ser["columns"])}
    for t in (0,stop - start - 1):  # shedding limited to the bus demand
        row = ser["values"][t]
        gen = case.tables["gen"]
        assert all(row[col[f"gen.Pmax.{k+1}"]] == row[col[f"bus.Pd.{gen[k][0]}"]] for k in range(200,299))
    assert sum(r[2] for r in case.tables["bus"]) == pytest.approx(
        sum(ser["values"][0][col[f"bus.Pd.{gen[k][0]}"]] for k in range(200,299)))

def test_deficit_solves():
    """Copper-plate multistep OPF of the large-deficit day (no shedding needed)"""
    pytest.importorskip("cvxopf")
    case = Case.load(os.path.join(FOLDER,"case118_tracy2021_deficit.py"))
    res = case.solve("opf","CVXOPF-1NODE",{"solver_options":{"tol_gap_abs":1e-10,"tol_gap_rel":1e-10,
        "tol_feas":1e-10,"max_iter":5000}},multistep=True)
    assert res["success"]
    assert res["horizon_objective"] == pytest.approx(1457135.41,rel=1e-6)
    shed = sum(g["Pg"] for s in res["steps"] for g in s["gen"][200:])
    assert shed == pytest.approx(0,abs=1e-6)
