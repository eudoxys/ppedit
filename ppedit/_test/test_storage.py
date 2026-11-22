"""Tests of the storage table and its multistep cvxopf model (issue #128)"""

import importlib.util

import pytest

from ppedit import Case, CaseError

needs_cvxopf = pytest.mark.skipif(importlib.util.find_spec("cvxopf") is None,
    reason="cvxopf is not installed")

LOADS = [0.6,0.6,1.3,1.3]
"""Load factors of the four steps: two cheap, two expensive"""

def _case(storage=None,gen_status=1):
    """case9 with a zero-cost generator 4 at bus 5 (Pmin 0, Pmax 50) that
    discharges a storage row, and a four-step load series"""
    case = Case.builtin("case9")
    case.add_row("gen",{"bus":5,"Pmax":50,"Pmin":0,"Qmax":0,"Qmin":0,"status":gen_status})
    case.set_value("gencost",3,"costs","0,0,0")
    if storage is not None:
        case.add_row("storage",{"gen_i":4,"Emax":100,"Smax":50,**storage})
    base = [90,100,125]
    case.set_series(["bus.Pd.5","bus.Pd.7","bus.Pd.9"],[[b*f for b in base] for f in LOADS],
        ["a","b","c","d"],name="load")
    return case

def test_storage_table_edits():
    """References follow generator inserts and deletes and bus renumbering"""
    case = Case.builtin("case9")
    case.add_row("storage",{"gen_i":2,"bus_i":5})
    case.add_row("storage",{"gen_i":3})
    assert case.size()["storage"] == 2
    case.add_row("gen",None,after=0)
    assert [r[:2] for r in case.tables["storage"]] == [[3,5],[4,-1]]
    assert case.set_value("bus",4,"bus_i",50)
    assert case.tables["storage"][0][1] == 50
    removed = case.delete_rows("gen",[2])
    assert removed["storage"] == 1 and [r[:2] for r in case.tables["storage"]] == [[3,-1]]
    case.add_row("storage",{"gen_i":1,"bus_i":50})
    with pytest.raises(CaseError,match="1 storage row"):
        case.delete_rows("bus",[4])
    assert case.delete_rows("bus",[4],cascade=True)["storage"] == 1
    with pytest.raises(CaseError,match="does not exist"):
        case.set_value("storage",0,"bus_i",999)
    with pytest.raises(CaseError,match="generator row 9"):
        case.set_value("storage",0,"gen_i",9)

def test_storage_validate():
    """Bad energy limits, ratings and efficiencies are errors"""
    case = Case.builtin("case9")
    case.add_row("storage",{"gen_i":1,"Es":200,"Emax":100,"Smax":0,"eta_ch":1.5,"Eend":150})
    case.add_row("storage",{"gen_i":1})
    found = {(x["row"],x["column"]) for x in case.validate() if x["table"] == "storage" and x["level"] == "error"}
    assert {(0,"Es"),(0,"Smax"),(0,"eta_ch"),(0,"Eend"),(1,"gen_i")} <= found
    warned = [x["message"] for x in case.validate() if x["level"] == "warning"]
    assert any("Pmin 10 > 0" in w for w in warned)

@pytest.mark.parametrize("ext",["py","json","glm"])
def test_storage_save_load(tmp_path,ext):
    """Storage rows are saved and read back in every case format"""
    case = Case.builtin("case9")
    case.add_row("storage",{"gen_i":2,"bus_i":5,"Es":20,"Emax":80,"eta_ch":0.9,"Eend":40,"status":0})
    path = tmp_path / f"c.{ext}"
    case.save(str(path))
    assert Case.load(str(path)).tables["storage"] == case.tables["storage"]
    if ext == "glm":
        assert 'object pp_storage' in path.read_text()

@needs_cvxopf
@pytest.mark.parametrize("algorithm",["CVXOPF-AC","CVXOPF-SOCP","CVXOPF-DC","CVXOPF-1NODE"])
@pytest.mark.parametrize("assembly",["vectorized","stepwise"])
def test_storage_arbitrage(algorithm,assembly):
    """Storage charges in the cheap steps and discharges in the expensive ones"""
    case = _case({"Eend":0})
    r = case.solve("opf",algorithm,{"multistep":{"temporal_assembly":assembly}},multistep=True)
    assert r["success"]
    st = [s["storage"][0] for s in r["steps"]]
    assert [round(x["Pch"],1) for x in st] == [50,50,0,0]
    assert [round(x["Pdis"],1) for x in st] == [0,0,50,50]
    assert [round(x["E"],1) + 0.0 for x in st] == [50,100,50,0]
    assert [round(s["gen"][3]["Pg"],1) for s in r["steps"]] == [0,0,50,50]
    assert r["storage"] == r["steps"][0]["storage"]

@needs_cvxopf
def test_storage_saves_cost():
    """Shifting energy costs less than no storage (generator 4 out of service)"""
    with_storage = _case({"Eend":0}).solve("opf","CVXOPF-1NODE",multistep=True)
    without = _case(gen_status=0).solve("opf","CVXOPF-1NODE",multistep=True)
    assert with_storage["horizon_objective"] < without["horizon_objective"] - 100

@needs_cvxopf
def test_storage_charge_bus_losses():
    """Charging at another bus, with efficiencies, self-discharge and a free end"""
    case = _case({"bus_i":7,"Es":10,"eta_ch":0.9,"eta_dis":0.8,"self_discharge":0.5,"aging":1})
    r = case.solve("opf","CVXOPF-DC",multistep=True)
    assert r["success"]
    keep = 0.5**(1/730)
    e,prev = [],10
    for s in r["steps"]:
        x = s["storage"][0]
        prev = keep*prev + 0.9*x["Pch"] - x["Pdis"]/0.8
        assert x["E"] == pytest.approx(prev,abs=1e-3)
        e.append(x["E"])
    assert e[-1] == pytest.approx(0,abs=1e-3)  # free end: nothing left over
    assert r["steps"][0]["storage"][0]["Pch"] > 1

@needs_cvxopf
def test_storage_end_energy_and_limits():
    """Eend and Emin hold; out-of-service rows are not modeled"""
    case = _case({"Es":30,"Emin":20,"Eend":60})
    r = case.solve("opf","CVXOPF-DC",multistep=True)
    e = [s["storage"][0]["E"] for s in r["steps"]]
    assert min(e) >= 20 - 1e-4 and e[-1] == pytest.approx(60,abs=1e-4)
    case.set_value("storage",0,"status",0)
    r = case.solve("opf","CVXOPF-DC",multistep=True)
    assert r["steps"][0]["storage"][0]["solved"] is False

@needs_cvxopf
def test_storage_needs_multistep_and_default_preparation():
    """Single-step solves warn; the recommended preparation is refused"""
    case = _case({"Eend":0})
    r = case.solve("opf","CVXOPF-DC")
    assert any("not modeled" in m["message"] for m in r["messages"])
    with pytest.raises(CaseError,match="default cvxopf preparation"):
        case.solve("opf","CVXOPF-DC",{"preparation":"recommended"},multistep=True)
