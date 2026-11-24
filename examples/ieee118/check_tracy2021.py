"""Check the Tracy 2021 study cases against the paper's reproduction archive

Usage: python3 examples/ieee118/check_tracy2021.py SOURCE [--year] [--hours N] [--studies] [--year-ppedit]

SOURCE is `pes2027-reproduction-inputs.zip` or a folder holding its
`experiments/` tree. Needs cvxopf (the `CVXOPF-*` solvers of ppedit).
Exits 1 if a check fails.

Cases are solved two ways: with ppedit's multistep OPF (`Case.solve`,
`CVXOPF-1NODE` copper plate and `CVXOPF-DC` lossy DC, the case as ppedit
models it), and as the study's own cvxopf device model made from the case
file (`build_tracy2021.cvxopf_inputs`, `singlenode_dc` and `lossy_dc`),
both with the study's CLARABEL settings (`SOLVE`).

Checks, in order:

  1. inputs: the hourly loads and renewable availability that
     `build_tracy2021.py` makes from `9q9wtp_gen_and_load.csv` equal those
     recorded in the two annual (Stage C) results, as do the batteries'
     starting energies; the recorded costs follow from the recorded
     dispatch with the case costs.

  2. case files: the 24-hour case files in this folder have the windows and
     battery start and end energies of the joint (E3) study binding, and the
     network, generators, renewables, storage, demand and shedding cost of
     the study's frozen model inputs (`qualification_002/binding.json`: the
     first 3 hours of the deficit window, and the 24-hour forced-shedding
     inputs), within the 10 significant digits of the case files.

  3. windows: each 24-hour window is solved both ways in both DC models
     with the battery energies at its ends fixed to those of the annual
     solution of the same model, so its optimum is the cost of the annual
     solution over the window. Copper plate: within `COST_ABS` $ plus
     `COPPER_REL`, with the same generator outputs (within `POWER_MW`).
     Lossy DC: within `LOSSY_ABS` $ a day (the largest seen is $1.0), with
     the generator outputs within `LOSSY_MW`. Lossy DC is degenerate
     (renewable curtailment can be spread over the units in many ways that
     differ only in the small loss term), and CLARABEL stops short of its
     optimum by up to about $1 a day, in the annual solve as in window
     solves: window optima are mostly below the annual cost (their
     solutions meet the study's constraints), sometimes above it. When
     CLARABEL fails with the study's settings (insufficient progress), or
     ends `optimal_inaccurate`, the window is solved again
     with `RETRY`; still inaccurate is a failure. ppedit's multistep OPF
     is held to `PPEDIT_REL` and `PPEDIT_MW` instead (see `--year-ppedit`).

  4. `--year`: the same over the whole year with the device model, in
     consecutive windows of `--hours` hours (default 168): the window optima
     must add up to the annual objective (about half an hour).

  `--year-ppedit` (a diagnostic, not counted): ppedit's multistep OPF of
  the year in 24-hour windows, reporting how many windows it solves and how
  close it comes to the annual solution (about half an hour). ppedit's form
  of these problems is less well conditioned for CLARABEL than cvxopf's
  device model: some windows end without a solution and the others within
  about 1e-5 of the optimum.

  5. `--studies`: each 24-hour study case is solved as written (its own
     battery end energies) both ways in both DC models: ppedit's optimum
     must equal the device model's (within `PPEDIT_REL` or, lossy DC,
     `LOSSY_ABS` $ a day), and the
     forced-shedding case must shed at least the study's minimum energy not
     served.
"""

import argparse
import gzip
import io
import json
import os
import sys
import time
import zipfile

import numpy as np

sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
import build_tracy2021 as B  # pylint: disable=wrong-import-position
from ppedit.case import Case  # pylint: disable=wrong-import-position

STAGE_C = "experiments/case118_tracy_2021/results/stage_c"
E3 = "experiments/case118_tracy_2021/results/e3/binding.json"
QUALIFICATION = "experiments/objective_assembly_qualification/results/qualification_002/binding.json"
ARMS = {"arm-000":("singlenode_dc","CVXOPF-1NODE"),"arm-001":("lossy_dc","CVXOPF-DC")}
SOLVE = {"preparation":"default","solver_options":{"tol_gap_abs":1e-10,"tol_gap_rel":1e-10,
    "tol_feas":1e-10,"max_iter":5000,"max_threads":1}}
"""The study's CLARABEL settings"""
INPUT_REL = 1e-9
"""Relative tolerance of case data (case files keep 10 significant digits)"""
COST_ABS,COPPER_REL = 1e-4,1e-8
"""Copper plate: the window optimum within `COST_ABS` $ plus `COPPER_REL` of the annual cost"""
LOSSY_ABS = 1.5
"""Lossy DC: the window optimum within `LOSSY_ABS` $ a day of the annual cost (CLARABEL's accuracy
on this degenerate problem)"""
POWER_MW,LOSSY_MW = 1e-3,0.05
"""Generator outputs (rows 1-54) within these of the annual solution (copper plate, lossy DC)"""
PPEDIT_REL,PPEDIT_MW = 2e-5,0.1
"""ppedit's multistep OPF: copper-plate optimum within `PPEDIT_REL` of the reference and generator
outputs within `PPEDIT_MW` (its CLARABEL solves of these cases are less accurate than the device
model's: up to 8e-6 and 0.05 MW over the one-day windows of the year)"""
RETRY = {"equilibrate_max_iter":50}
"""CLARABEL options added when it fails with the study's settings (insufficient progress)"""
WINDOWS = {"surplus":"Large surplus","deficit":"Large deficit","deficit_depletion":"Large deficit",
    "surplus_to_deficit":"Surplus to deficit","deficit_to_surplus":"Deficit to surplus",
    "forced_shedding":"Large deficit"}
"""E3 window of each 24-hour study"""

class Source:
    """Members of the archive (ZIP file or folder), by archive path"""
    def __init__(self,path:str):
        self.zip = zipfile.ZipFile(path) if os.path.isfile(path) else None
        self.path = path
    def read(self,name:str) -> bytes:
        """Bytes of archive member `name`"""
        if self.zip:
            return self.zip.read(name)
        with open(os.path.join(self.path,name),"rb") as fh:
            return fh.read()
    def json(self,name:str):
        """Archive member `name` read as JSON (gunzipped if `.gz`)"""
        data = self.read(name)
        return json.loads(gzip.decompress(data) if name.endswith(".gz") else data)

class Report:
    """Check results: one line each, failures counted"""
    def __init__(self):
        self.failed = 0
    def check(self,ok:bool,text:str):
        """Print `text` as passed or failed"""
        self.failed += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {text}",flush=True)

def rel(a,b) -> float:
    """Largest difference relative to the largest magnitude of `b`"""
    a,b = np.asarray(a,dtype=float),np.asarray(b,dtype=float)
    return float(np.abs(a - b).max()/max(np.abs(b).max(),1e-300))

def window_cost(result:dict,inputs:dict,pglib:dict,start:int,stop:int) -> float:
    """Cost of the recorded annual solution over hours `start` to `stop`
    ($: generators, load shedding, battery throughput, lossy DC losses)"""
    pg = np.asarray(result["Pg"],dtype=float)[start:stop]
    cost = (pg**2).dot(inputs["c2"]).sum() + pg.dot(inputs["c1"]).sum() + inputs["c0"].sum()*(stop - start)
    cost += B.AGING*np.abs(np.asarray(result["b"],dtype=float)[start:stop]).sum()
    cost += B.SHEDDING_COST*np.asarray(result["p_load_shed"],dtype=float)[start:stop].sum()
    if "p_flows" in result:  # loss proxy: resistance times flow squared, per unit
        flows = np.asarray(result["p_flows"],dtype=float)[start:stop]/pglib["baseMVA"]
        cost += (pglib["branch"][:,2]*flows**2).sum()
    return float(cost)

def solve(case:Case,algorithm:str) -> dict:
    """ppedit multistep OPF of `case` with the study's solver settings (once
    more with `RETRY` if CLARABEL fails or is inaccurate): horizon objective,
    generator outputs (steps x gens), energy not served and `retried`"""
    def run(options):
        res = case.solve("opf",algorithm,options,multistep=True)
        inaccurate = "solver status optimal_inaccurate" in res["log"]
        return res,res["success"] and not inaccurate
    res,ok = run(SOLVE)
    retried = not ok
    if retried:
        res,ok = run(dict(SOLVE,solver_options={**SOLVE["solver_options"],**RETRY}))
    if not ok:
        return {"success":False,"retried":retried}
    pg = np.array([[g["Pg"] for g in s["gen"]] for s in res["steps"]])
    return {"success":True,"objective":res["horizon_objective"],"Pg":pg,"ens":float(pg[:,200:299].sum()),
        "retried":retried}

def solve_device(case:Case,formulation:str) -> dict:
    """The study's cvxopf device model of `case` (`build_tracy2021.cvxopf_inputs`),
    solved as `solve` does"""
    import warnings # pylint: disable=import-outside-toplevel
    from cvxopf import build_opf_multistep,extract_results,ACCEPTED_SOLVER_STATUSES # pylint: disable=import-outside-toplevel
    def run(options):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            build = build_opf_multistep(**B.cvxopf_inputs(case,formulation))
            try:
                build.solve(solver="CLARABEL",**options)
            except Exception: # pylint: disable=broad-exception-caught
                return None,False
            res = extract_results(build)
        return res,str(res["status"]) == "optimal"
    res,ok = run(SOLVE["solver_options"])
    retried = not ok
    if retried:
        res,ok = run({**SOLVE["solver_options"],**RETRY})
    if not ok or str(res["status"]) not in ACCEPTED_SOLVER_STATUSES:
        return {"success":False,"retried":retried}
    T = len(case.series[0]["values"])
    return {"success":True,"objective":float(res["objective"]),"Pg":np.asarray(res["Pg"],dtype=float).reshape(T,-1),
        "ens":float(res["energy_not_served"]),"retried":retried}

def agree(form:str,got:float,ref:float,hours:int,ppedit:bool=False) -> bool:
    """Whether optimum `got` reproduces cost `ref` (see the module docstring;
    `ppedit`: solved with ppedit's multistep OPF)"""
    diff = got - ref
    if form == "singlenode_dc":
        return abs(diff) <= COST_ABS + (PPEDIT_REL if ppedit else COPPER_REL)*abs(ref)
    return abs(diff) <= LOSSY_ABS*hours/24 + (PPEDIT_REL*abs(ref) if ppedit else 0)

def check_inputs(report,src,inputs,pglib,annual):
    """Check 1"""
    print("1. inputs")
    cap = np.array([u["capacity"] for u in inputs["batteries"]])
    for arm,(form,_) in ARMS.items():
        r = annual[arm]
        report.check(rel(r["result"]["p_load"],inputs["load_p"]) <= INPUT_REL,f"{form}: hourly loads (99 buses)")
        report.check(rel(r["renewable_available_mw"],inputs["nd"]) <= INPUT_REL,
            f"{form}: hourly renewable availability (119 units)")
        report.check(r["identities"]["renewables"] == [u["id"] for u in inputs["renewables"]]
            and r["identities"]["storage"] == [u["id"] for u in inputs["batteries"]],
            f"{form}: renewable and battery identities and order")
        report.check(rel(np.asarray(r["boundary_soc_mwh"])[0],0.5*cap) <= INPUT_REL,
            f"{form}: batteries start at half their capacity")
        named = r["named_costs"]
        total = window_cost(r["result"],inputs,pglib,0,8760)
        report.check(abs(total - float(r["result"]["objective"])) <= 1e-9*abs(total)
            and abs(total - sum(named.values())) <= 1e-9*abs(total),
            f"{form}: recorded objective {float(r['result']['objective']):.6f} $ follows from the recorded dispatch")

def compare_case(report,label,case:Case,inputs,frozen,hours):
    """Compare a case file's first `hours` steps with frozen study inputs"""
    ser = case.series[0]
    col = {k:i for i,k in enumerate(ser["columns"])}
    values = np.array(ser["values"],dtype=float)[:hours]
    gen = np.array(case.tables["gen"],dtype=float)
    cost = np.array([[float(x) for x in r[4].split(",")] for r in case.tables["gencost"]])
    storage = np.array(case.tables["storage"],dtype=float)
    loads = [int(c.split("_")[-1]) for c in frozen["df_load_p"]["columns"]]
    ok = rel(values[:,[col[f"bus.Pd.{b}"] for b in loads]],frozen["df_load_p"]["values"]) <= INPUT_REL \
        and rel(values[:,[col[f"bus.Qd.{b}"] for b in loads]],frozen["df_load_q"]["values"]) <= INPUT_REL \
        and rel(values[:,[col[f"gen.Pmax.{201+j}"] for j in range(99)]],frozen["df_load_p"]["values"]) <= INPUT_REL
    report.check(ok,f"{label}: demand and shedding limits ({hours} h)")
    nd = frozen["nondispatchable"]
    ok = [u["device_id"] for u in nd] == frozen["df_nd"]["columns"] == [u["id"] for u in inputs["renewables"]] \
        and rel(values[:,[col[f"gen.Pmax.{82+j}"] for j in range(119)]],frozen["df_nd"]["values"]) <= INPUT_REL \
        and rel(gen[81:200,0],[u["bus"] for u in nd]) == 0 \
        and rel(gen[81:200,3],[u["apparent_power_rating"] for u in nd]) <= INPUT_REL
    report.check(ok,f"{label}: renewable units (bus, rating, availability)")
    gens = frozen["generators"]
    ok = rel(gen[:54,8],[g["p_max_mw"] for g in gens]) <= INPUT_REL \
        and rel(gen[:54,9],[g["p_min_mw"] for g in gens]) == 0 \
        and rel(gen[:54,3],[g["q_max_mvar"] for g in gens]) == 0 and rel(gen[:54,4],[g["q_min_mvar"] for g in gens]) == 0 \
        and rel(cost[:54,[2,1,0]],[g["cost_coeffs"] for g in gens]) <= INPUT_REL
    report.check(ok,f"{label}: generator limits and costs")
    st = frozen["storage"]
    ok = rel(gen[storage[:,0].astype(int) - 1,0],[s["bus"] for s in st]) == 0 \
        and rel(storage[:,[2,4,5,9]],[[s["initial_soc"],s["capacity"],s["apparent_power_rating"],s["aging_weight"]]
            for s in st]) <= INPUT_REL \
        and all(s["terminal_constraint"] == "equality" for s in st) \
        and rel(storage[:,10],[s["terminal_soc"] for s in st]) <= INPUT_REL \
        and np.all(storage[:,[3,6,7,8]] == [0,1,1,0])
    report.check(ok,f"{label}: batteries (bus, capacity, rating, aging cost, start and end energy)")
    ok = all(l["shedding_cost_per_mwh"] == B.SHEDDING_COST and l["max_shed_fraction"] == 1 for l in frozen["loads"]) \
        and np.all(cost[200:299,1] == B.SHEDDING_COST) and rel(gen[200:299,0],loads) == 0
    report.check(ok,f"{label}: load shedding buses and cost")
    ppc = case.to_ppc(arrays=True)
    net = frozen["case"]
    bus = ppc["bus"].copy()
    bus[:,2:4] = np.asarray(net["bus"],dtype=float)[:,2:4]  # loads come from the series
    branch = ppc["branch"][:,:13].copy()
    ref = np.asarray(net["branch"],dtype=float)
    branch[:,8] = np.where(branch[:,8] == 0,1,branch[:,8])
    ref[:,8] = np.where(ref[:,8] == 0,1,ref[:,8])
    report.check(np.array_equal(bus,np.asarray(net["bus"],dtype=float)) and np.array_equal(branch,ref)
        and float(net["baseMVA"]) == float(ppc["baseMVA"]),f"{label}: network (buses and branches)")
    report.check(frozen["options"]["loss_weight"] == 1.0 and frozen["delta"] == 1.0,
        f"{label}: loss weight 1, one-hour steps")

def check_cases(report,src,inputs,folder):
    """Check 2"""
    print("2. case files")
    e3 = src.json(E3)["study"]
    qual = src.json(QUALIFICATION)["rows"]
    for name,(start,stop,_,_,demand) in B.STUDIES.items():
        if name == "annual":
            continue
        path = os.path.join(folder,f"case118_tracy2021_{name}.py")
        case = Case.load(path)
        st = np.array(case.tables["storage"],dtype=float)
        leg = "deficit_depletion" if name == "deficit_depletion" else "energy_neutral"
        arms = [a for a in e3["arms"] if a["window"] == WINDOWS[name] and a["leg"] == leg]
        ok = len(arms) == 4 and all(a["start"] == start and a["stop"] == stop
            and rel(st[:,2],a["initial_soc_mwh"]) <= INPUT_REL and rel(st[:,10],a["terminal_soc_mwh"]) <= INPUT_REL
            and a["rho"] == B.RHO and a["throughput"] == B.AGING for a in arms) \
            and e3["storage_device_ids"] == [u["id"] for u in inputs["batteries"]]
        ser = case.series[0]
        ok = ok and len(ser["values"]) == stop - start \
            and ser["index"][0] == inputs["index"][start].isoformat()
        report.check(ok,f"{name}: hours {start}-{stop} and battery energies of the E3 binding "
            f"({', '.join(a['formulation'] for a in arms)})")
        if name in ("deficit","deficit_depletion"):
            row = [r for r in qual if r["arm"]["T"] == 3 and not r["arm"]["forced_shedding"]
                and r["arm"]["start"] == start][0]
            frozen = json.loads(json.dumps(row["frozen"]["mathematical_inputs"]))
            if name == "deficit_depletion":  # the frozen inputs are the 50%-50% leg
                for s,a,b in zip(frozen["storage"],st[:,2],st[:,10]):
                    s["initial_soc"],s["terminal_soc"] = a,b
            else:
                for s,b in zip(frozen["storage"],st[:,10]):  # 3-hour fixture: same start, its own end
                    s["terminal_soc"] = b
            compare_case(report,name,case,inputs,frozen,3)
        if name == "forced_shedding":
            rows = [r for r in qual if r["arm"]["T"] == 24 and r["arm"]["forced_shedding"]]
            frozen = rows[0]["frozen"]["mathematical_inputs"]
            same = all(r["frozen"]["mathematical_inputs"]["df_load_p"] == frozen["df_load_p"] for r in rows)
            report.check(same and len(rows) == 8,"forced_shedding: the 8 frozen 24-hour rows share their demand")
            stress = rows[0]["stress"]
            report.check(stress["demand_multiplier"] == demand,
                f"forced_shedding: demand multiplier {stress['demand_multiplier']!r}")
            compare_case(report,name,case,inputs,frozen,24)

def boundary(case:Case,soc,start,stop) -> Case:
    """`case` with its battery start and end energies set to `soc[start]`, `soc[stop]`"""
    for n,row in enumerate(case.tables["storage"]):
        row[2],row[10] = float(soc[start,n]),float(soc[stop,n])
    return case

def compare_window(report,label,form,got,ref_cost,ref_pg,ppedit=False):
    """Check one window optimum against the annual solution (`ppedit`: solved
    with ppedit's multistep OPF)"""
    if not got["success"]:
        report.check(False,f"{label} {form}: solve failed or inaccurate")
        return 0.0
    diff = got["objective"] - ref_cost
    dpg = float(np.abs(got["Pg"][:,:54] - ref_pg).max())
    note = f"{got['objective']:.6f} $ vs annual {ref_cost:.6f} $ ({diff:+.2g} $); generators within {dpg:.1g} MW" \
        + (" (CLARABEL retried with " + ", ".join(f"{k}={v}" for k,v in RETRY.items()) + ")" if got["retried"] else "")
    limit = PPEDIT_MW if ppedit else POWER_MW if form == "singlenode_dc" else LOSSY_MW
    ok = agree(form,got["objective"],ref_cost,len(ref_pg),ppedit) and dpg <= limit
    report.check(ok,f"{label} {form}: {note}")
    return got["objective"]

def check_windows(report,inputs,pglib,annual,folder):
    """Check 3"""
    print("3. 24-hour windows with the annual battery energies at their ends")
    done = set()
    for name,(start,stop,_,_,demand) in B.STUDIES.items():
        if name == "annual" or demand != 1 or (start,stop) in done:
            continue
        done.add((start,stop))
        for arm,(form,algorithm) in ARMS.items():
            r = annual[arm]
            ref = window_cost(r["result"],inputs,pglib,start,stop)
            pg = np.asarray(r["result"]["Pg"])[start:stop]
            case = boundary(Case.load(os.path.join(folder,f"case118_tracy2021_{name}.py")),
                np.asarray(r["boundary_soc_mwh"]),start,stop)
            compare_window(report,f"hours {start}-{stop} ppedit",form,solve(case,algorithm),ref,pg,ppedit=True)
            compare_window(report,f"hours {start}-{stop} device",form,solve_device(case,form),ref,pg)

def check_year(report,inputs,pglib,annual,hours):
    """Check 4 (device model)"""
    print(f"4. the year in {hours}-hour windows (device model)")
    for arm,(form,_) in ARMS.items():
        r = annual[arm]
        soc = np.asarray(r["boundary_soc_mwh"])
        total,t0 = 0.0,time.time()
        for start in range(0,8760,hours):
            stop = min(start + hours,8760)
            case = B.build_window(inputs,pglib,start,stop,soc[start],soc[stop])
            total += compare_window(report,f"hours {start}-{stop}",form,solve_device(case,form),
                window_cost(r["result"],inputs,pglib,start,stop),np.asarray(r["result"]["Pg"])[start:stop])
        ref = float(r["result"]["objective"])
        diff = total - ref
        windows = -(-8760//hours)
        ok = abs(diff) <= windows*COST_ABS + COPPER_REL*abs(ref) if form == "singlenode_dc" \
            else abs(diff) <= LOSSY_ABS*365
        report.check(ok,f"{form} year: sum of window optima {total:.6f} $ vs annual objective {ref:.6f} $ "
            f"({diff:+.3g} $, {diff/ref:+.1e}; {time.time() - t0:.0f} s)")

def ppedit_accuracy(inputs,pglib,annual,hours=24,last=8760):
    """`--year-ppedit` (a diagnostic, not a check): ppedit's multistep OPF
    of the year in `hours`-hour windows with the annual battery energies at
    their ends, against the annual solution (up to hour `last`)"""
    print(f"ppedit's multistep OPF of the year in {hours}-hour windows (diagnostic, not counted)")
    for arm,(form,algorithm) in ARMS.items():
        r = annual[arm]
        soc = np.asarray(r["boundary_soc_mwh"])
        failed,retried,rels,mws,t0 = [],0,[],[],time.time()
        for start in range(0,last,hours):
            stop = min(start + hours,last)
            got = solve(B.build_window(inputs,pglib,start,stop,soc[start],soc[stop]),algorithm)
            retried += got["retried"]
            if not got["success"]:
                failed.append(f"{start}-{stop}")
                continue
            ref = window_cost(r["result"],inputs,pglib,start,stop)
            rels.append((got["objective"] - ref)/max(abs(ref),1.0))
            mws.append(float(np.abs(got["Pg"][:,:54] - np.asarray(r["result"]["Pg"])[start:stop]).max()))
        rels = np.array(rels)
        print(f"  {form}: {len(rels)} of {len(rels) + len(failed)} windows solved ({retried} retried with "
            + ", ".join(f"{k}={v}" for k,v in RETRY.items()) + f"); cost vs annual {rels.min():+.1e} to "
            f"{rels.max():+.1e} (relative, median {np.median(rels):+.1e}); generators within {max(mws):.2g} MW; "
            f"{time.time() - t0:.0f} s" + (f"; not solved: hours {', '.join(failed)}" if failed else ""),flush=True)

def check_studies(report,src,folder):
    """Check 5"""
    print("5. the 24-hour studies as written")
    stress = src.json(QUALIFICATION)["rows"]
    minimum = [r for r in stress if r["arm"]["T"] == 24 and r["arm"]["forced_shedding"]][0]["stress"]["modified"]
    for name in B.STUDIES:
        if name == "annual":
            continue
        for form,algorithm in ARMS.values():
            case = Case.load(os.path.join(folder,f"case118_tracy2021_{name}.py"))
            got,dev = solve(case,algorithm),solve_device(case,form)
            if not got["success"] or not dev["success"]:
                report.check(False,f"{name} {form}: solve failed (ppedit {got['success']}, device {dev['success']})")
                continue
            ok = agree(form,got["objective"],dev["objective"],24,ppedit=True)
            text = f"{name} {form}: ppedit {got['objective']:.6f} $, device model {dev['objective']:.6f} $; " \
                f"energy not served {got['ens']:.3f} / {dev['ens']:.3f} MWh"
            if name == "forced_shedding":
                ok = ok and min(got["ens"],dev["ens"]) >= minimum["minimum_ens_mwh"] - 1e-4
                text += f" (at least {minimum['minimum_ens_mwh']:.3f} MWh)"
            report.check(ok,text)

def main(argv:list[str]|None=None) -> int:
    """Run the checks"""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("source",help="pes2027-reproduction-inputs.zip or a folder with its experiments/ tree")
    parser.add_argument("--year",action="store_true",help="check the whole year in windows (device model)")
    parser.add_argument("--year-ppedit",action="store_true",
        help="report the accuracy of ppedit's multistep OPF over the year in 24-hour windows (slow; not a check)")
    parser.add_argument("--hours",type=int,default=168,help="window length for --year (hours)")
    parser.add_argument("--studies",action="store_true",help="solve the 24-hour studies as written")
    parser.add_argument("--cases",default=B.HERE,help="folder of the case files")
    args = parser.parse_args(argv)
    src = Source(args.source)
    pglib = B.read_pglib()
    csv = io.BytesIO(src.read("experiments/battery_terminal/data/9q9wtp_gen_and_load.csv"))
    inputs = B.prepare(B.read_source(csv),pglib)
    annual = {arm:src.json(f"{STAGE_C}/{arm}/result.json.gz") for arm in ARMS}
    report = Report()
    check_inputs(report,src,inputs,pglib,annual)
    check_cases(report,src,inputs,args.cases)
    check_windows(report,inputs,pglib,annual,args.cases)
    if args.year:
        check_year(report,inputs,pglib,annual,args.hours)
    if args.year_ppedit:
        ppedit_accuracy(inputs,pglib,annual)
    if args.studies:
        check_studies(report,src,args.cases)
    print("all checks passed" if not report.failed else f"{report.failed} check(s) failed")
    return 1 if report.failed else 0

if __name__ == "__main__":
    sys.exit(main())
