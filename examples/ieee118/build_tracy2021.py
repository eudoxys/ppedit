"""Build the Tracy 2021 IEEE 118-bus study cases

Usage: python3 examples/ieee118/build_tracy2021.py [STUDY ...] [--output DIR]

Writes one ppedit case file per study (see `README.md`), named `case118_tracy2021_<study>.py`, in this folder
unless `--output` is given. With no STUDY, all the 24-hour studies of
`STUDIES` are written; `annual` (the full year, about 40 MB) is written
only when named.

Each case starts from `case118.py` (the PYPOWER IEEE 118-bus case). The
study network is the PGLib-OPF v23.07 IEEE 118-bus case
(`pglib_opf_case118_ieee.m`), which has the same buses, branches,
impedances, loads and generator locations but different operating limits
and costs, so the columns where the two differ are taken from it (bus
`Vm`, `Va`; gen `Pg`, `Qg`, `Qmax`, `Qmin`, `Vg`, `Pmax`; branch `rateA`,
`rateB`, `rateC`, `ratio`, `angmin`, `angmax`; gencost `c2`, `c1`); every
other value is checked to be the same in both.

The study inputs: the 2021 hours of `9q9wtp_gen_and_load.csv` are scaled so the peak net load is 6000 MW, demand is shared among the 99
load buses in proportion to their case load, utility solar and wind go to
15 buses picked at random (seed 42, `prepare`), distributed solar to the
load buses, and 27 batteries (4 hours of average load in all, E/P = 3 h) to
buses picked at random. The 19 generators with capacity are scaled to
5000 MW in all and get a quadratic cost term `c2 = c1/(3 Pmax)`.

The cvxopf device models of the studies are written as ppedit case data:

  - generator rows 1-54: the case generators (study limits and costs)

  - rows 55-81: the 27 batteries' discharge generators (`Pmax` = `Smax`,
    zero cost), each with a `storage` row (charging as negative output at
    the same bus, ideal: efficiencies 1, no self-discharge, aging cost
    0.01 $/MWh of throughput, energy from 0 to its capacity, start and
    end energy of the study)

  - rows 82-200: the 119 renewable units (20 utility solar and wind, 99
    distributed solar) as zero-cost generators whose `Pmax` follows the
    available power (curtailment is `Pmax - Pg`); `Qmax`/`Qmin` are their
    MVA rating

  - rows 201-299: load shedding at the 99 load buses as generators costing
    20763.594 $/MWh whose `Pmax` follows the bus demand (energy not served
    is their output)

  - series `tracy2021`: hourly `bus.Pd`, `bus.Qd` of the load buses and
    `gen.Pmax` of the renewable and shedding generators; the case values
    are those of the first hour

In ppedit's DC multistep OPF (`CVXOPF-1NODE`, `CVXOPF-DC`) this is the
study's problem. In AC and SOCP it is not exactly: cvxopf limits batteries
and renewables to a circle `P^2 + Q^2 <= S^2` (here a box, and charging has
no reactive power) and sheds reactive load with real load (here shedding
has no reactive power). `cvxopf_inputs` turns a case back into the study's
own cvxopf device model, exact in all four formulations.

The CSV and the case files must be in this folder (or give `--source`).
"""

import argparse
import os
import re
import sys

import numpy as np
import pandas as pd

from ppedit.case import Case,COLUMNS

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(HERE,"9q9wtp_gen_and_load.csv")
PGLIB = os.path.join(HERE,"pglib_opf_case118_ieee.m")
CASE118 = os.path.join(HERE,"case118.py")
CHANNELS = ("load","solar","wind","dist_solar")
SHEDDING_COST = 20763.594
"""$/MWh of energy not served (100 times the largest marginal cost at zero output)"""
AGING = 0.01
"""$/MWh of battery charge and discharge throughput (cvxopf's default aging weight)"""
RHO = 1/3
"""Quadratic cost term at Pmax as a fraction of the linear term"""
FORCED_DEMAND = 7.5416905141946184
"""Demand multiplier of the forced-shedding study (P and Q)"""

STUDIES = {
    # name: (first hour, end hour, initial and terminal energy as fractions of capacity, demand multiplier)
    "surplus":(3308,3332,0.5,0.5,1.0),
    "deficit":(1165,1189,0.5,0.5,1.0),
    "deficit_depletion":(1165,1189,0.6,0.25,1.0),
    "surplus_to_deficit":(8580,8604,0.5,0.5,1.0),
    "deficit_to_surplus":(2439,2463,0.5,0.5,1.0),
    "forced_shedding":(1165,1189,0.5,0.5,FORCED_DEMAND),
    "annual":(0,8760,0.5,0.5,1.0),
}
"""The studies: hours counted from 2021-01-01 00:00 UTC-08:00 (end excluded)"""

TITLES = {
    "surplus":"Large surplus, 2021-05-18 20:00 to 2021-05-19 20:00, storage 50% to 50%",
    "deficit":"Large deficit, 2021-02-18 13:00 to 2021-02-19 13:00, storage 50% to 50%",
    "deficit_depletion":"Large deficit, 2021-02-18 13:00 to 2021-02-19 13:00, storage 60% to 25%",
    "surplus_to_deficit":"Surplus to deficit, 2021-12-27 12:00 to 2021-12-28 12:00, storage 50% to 50%",
    "deficit_to_surplus":"Deficit to surplus, 2021-04-12 15:00 to 2021-04-13 15:00, storage 50% to 50%",
    "forced_shedding":"Forced shedding: the large-deficit window with demand times 7.5416905141946184, storage 50% to 50%",
    "annual":"Full year 2021, storage 50% to 50%",
}

def read_source(path:str=SOURCE) -> pd.DataFrame:
    """The 8760 hours of 2021 of the four Tracy channels (MW), UTC-08:00"""
    frame = pd.read_csv(path)
    index = pd.DatetimeIndex(pd.to_datetime(frame.pop("time")))
    frame.index = index
    frame = frame.loc[frame.index.year == 2021]
    expected = pd.date_range("2021-01-01",periods=8760,freq="h",tz="Etc/GMT+8")
    if not np.array_equal(frame.index.asi8,expected.asi8):
        raise ValueError("the 2021 rows must be complete, ordered and hourly")
    frame = frame[[f"9q9wtp_{c}" for c in CHANNELS]].copy()
    frame.columns = list(CHANNELS)
    if not np.isfinite(frame.to_numpy()).all() or (frame.to_numpy() < 0).any():
        raise ValueError("source values must be finite and nonnegative")
    return frame

def read_pglib(path:str=PGLIB) -> dict:
    """The `bus`, `gen`, `gencost` and `branch` arrays of a MATPOWER case file"""
    with open(path,encoding="utf-8") as fh:
        text = fh.read()
    out = {}
    for m in re.finditer(r"mpc\.(bus|gen|gencost|branch)\s*=\s*\[(.*?)\n\s*\];",text,re.DOTALL):
        rows = []
        for line in m.group(2).splitlines():
            data = line.split("%",1)[0].strip().rstrip(";").split()
            if data:
                rows.append([float(x) for x in data])
        out[m.group(1)] = np.array(rows)
    out["baseMVA"] = float(re.search(r"mpc\.baseMVA\s*=\s*([\d.]+)",text).group(1))
    return out

def prepare(source:pd.DataFrame,pglib:dict) -> dict:
    """The study inputs: per-device hourly arrays and device tables (see the
    module docstring)"""
    net = source.load - source.solar - source.wind - source.dist_solar
    scaled = source*(6000.0/float(net.max()))
    bus,gen,cost = pglib["bus"],pglib["gen"],pglib["gencost"]
    bus = bus[np.argsort(bus[:,0])]
    active = (gen[:,7] > 0) & (gen[:,8] > 0)
    if active.sum() != 19 or gen[active,8].sum() != 6515 or bus[:,2].sum() != 4242:
        raise ValueError("unexpected PGLib generator or load totals")
    ids = bus[:,0].astype(int)
    has_load = bus[:,2] > 0
    has_gen = np.isin(ids,gen[active,0])
    categories = {"load_only":ids[has_load & ~has_gen],"load_generation":ids[has_load & has_gen],
        "generation_no_load":ids[~has_load & has_gen],"neither":ids[~has_load & ~has_gen]}
    rng = np.random.Generator(np.random.PCG64(42))  # seeded siting: keep the calls and their order
    selected = {k:np.sort(rng.choice(categories[k],5,replace=False)).tolist()
        for k in ("load_generation","generation_no_load","neither")}
    utility = sorted(v for group in selected.values() for v in group)
    kinds = dict(zip(utility,rng.choice(["wind_only","solar_only","both"],15),strict=True))
    renew = []
    for channel in ("solar","wind"):
        hosts = [b for b in utility if kinds[b] in (f"{channel}_only","both")]
        mult = rng.uniform(0.8,1.2,len(hosts))
        renew += [dict(id=f"{channel}_bus_{b}",bus=b,channel=channel,share=float(s))
            for b,s in zip(hosts,mult/mult.sum(),strict=True)]
    renew += [dict(id=f"dist_solar_bus_{int(r[0])}",bus=int(r[0]),channel="dist_solar",
        share=float(r[2]/4242)) for r in bus[has_load]]
    nd = np.column_stack([scaled[r["channel"]].to_numpy()*r["share"] for r in renew])
    for j,r in enumerate(renew):
        r["S"] = 1.1*float(nd[:,j].max())
        r["energy"] = float(nd[:,j].sum())
    load_bus = bus[has_load]
    load_p = scaled.load.to_numpy()[:,None]*(load_bus[:,2]/4242)[None,:]
    load_q = load_p*(load_bus[:,3]/load_bus[:,2])[None,:]
    no_load = sorted(b for b in utility if b not in categories["load_generation"])
    with_load = sorted(b for b in utility if b in categories["load_generation"])
    sites = {"load_side":np.sort(rng.choice(categories["load_only"],22,replace=False)).tolist(),
        "renewable_no_load":np.sort(rng.choice(no_load,3,replace=False)).tolist(),
        "renewable_with_load":np.sort(rng.choice(with_load,2,replace=False)).tolist()}
    energy = float(4*scaled.load.mean())
    batteries = []
    for pool,hosts in (("load_side",sites["load_side"]),
            ("renewable_side",sorted(sites["renewable_no_load"] + sites["renewable_with_load"]))):
        weights = np.array([float(bus[ids == b,2][0]) if pool == "load_side"
            else sum(r["energy"] for r in renew if r["bus"] == b and r["channel"] != "dist_solar")
            for b in hosts])
        for b,share in zip(hosts,weights/weights.sum(),strict=True):
            cap = energy/2*float(share)
            batteries.append(dict(id=f"storage_bus_{b}",bus=b,capacity=cap,S=cap/3))
    batteries.sort(key=lambda r:r["bus"])
    pmax = np.where(active,gen[:,8]*5000/6515,gen[:,8])
    c2 = np.where(active,cost[:,5]/(3*np.where(active,pmax,1)),cost[:,4])
    return dict(index=source.index,load_bus=load_bus[:,0].astype(int),load_p=load_p,load_q=load_q,
        renewables=renew,nd=nd,batteries=batteries,pmax=pmax,c2=c2,c1=cost[:,5],c0=cost[:,6])

def base_case(pglib:dict) -> dict:
    """`case118.py` with the PGLib values where the two differ (checked)"""
    case = Case.load(CASE118)
    ppc = case.to_ppc(arrays=True)
    out = {"version":"2","baseMVA":pglib["baseMVA"]}
    same = {"bus":[0,1,2,3,4,5,6,9,10,11,12],"gen":[0,6,7,9],"branch":[0,1,2,3,4,9,10],
        "gencost":[0,1,2,3,6]}
    take = {"bus":[7,8],"gen":[1,2,3,4,5,8],"branch":[5,6,7,8,11,12],"gencost":[4,5]}
    for table in ("bus","gen","branch","gencost"):
        a,b = np.array(ppc[table],dtype=float),pglib[table]
        if a.shape[0] != b.shape[0] or not np.array_equal(a[:,same[table]],b[:,same[table]]):
            raise ValueError(f"case118.py and the PGLib case differ in {table} beyond the expected columns")
        a[:,take[table]] = b[:,take[table]]
        if table == "branch":  # tap 0 (line) and 1 (unit ratio) are the same in PYPOWER
            if not np.array_equal(np.where(ppc["branch"][:,8] == 0,1,ppc["branch"][:,8]),
                    np.where(b[:,8] == 0,1,b[:,8])):
                raise ValueError("branch tap ratios differ")
        out[table] = a
    return out

def build(name:str,inputs:dict,pglib:dict) -> Case:
    """The case of study `name` (see `STUDIES`)"""
    start,stop,e0,e1,demand = STUDIES[name]
    cap = np.array([u["capacity"] for u in inputs["batteries"]])
    return build_window(inputs,pglib,start,stop,e0*cap,e1*cap,demand,f"case118_tracy2021_{name}")

def build_window(inputs:dict,pglib:dict,start:int,stop:int,initial,terminal,demand:float=1.0,
        name:str="case118_tracy2021") -> Case:
    """The case of hours `start` to `stop` (end excluded) with battery
    energies `initial` at the start and `terminal` at the end (MWh, one per
    battery) and demand times `demand`"""
    data = base_case(pglib)
    bus,gen,gencost = data["bus"],data["gen"],data["gencost"]
    ngen = len(COLUMNS["gen"])
    load_p = inputs["load_p"][start:stop]*demand
    load_q = inputs["load_q"][start:stop]*demand
    nd = inputs["nd"][start:stop]
    row = {int(b):n for n,b in enumerate(bus[:,0])}
    for j,b in enumerate(inputs["load_bus"]):
        bus[row[b],2],bus[row[b],3] = load_p[0,j],load_q[0,j]
    gen[:,8] = inputs["pmax"]
    gencost[:,4],gencost[:,5],gencost[:,6] = inputs["c2"],inputs["c1"],inputs["c0"]
    gen = np.hstack([gen,np.zeros((len(gen),ngen - gen.shape[1]))]) if gen.shape[1] < ngen else gen
    rows,costs = [],[]
    def add(b,pmax,qmax,qmin,c1=0.0):
        r = np.zeros(ngen)
        r[0],r[3],r[4],r[5],r[6],r[7],r[8] = b,qmax,qmin,1.0,data["baseMVA"],1,pmax
        rows.append(r)
        costs.append([2,0,0,3,0,c1,0])
    storage = []
    for u,e0,e1 in zip(inputs["batteries"],initial,terminal,strict=True):
        add(u["bus"],u["S"],u["S"],-u["S"])
        storage.append([len(gen) + len(rows),-1,float(e0),0.0,u["capacity"],u["S"],
            1.0,1.0,0.0,AGING,float(e1),1])
    first_nd = len(gen) + len(rows) + 1
    for j,u in enumerate(inputs["renewables"]):
        add(u["bus"],nd[0,j],u["S"],-u["S"])
    first_shed = len(gen) + len(rows) + 1
    for j,b in enumerate(inputs["load_bus"]):
        add(int(b),load_p[0,j],0.0,0.0,SHEDDING_COST)
    data["gen"] = np.vstack([gen] + rows)
    data["gencost"] = np.vstack([gencost,np.array(costs)])
    data["storage"] = storage
    index = [t.isoformat() for t in inputs["index"][start:stop]]
    columns = [f"bus.Pd.{b}" for b in inputs["load_bus"]] + [f"bus.Qd.{b}" for b in inputs["load_bus"]] \
        + [f"gen.Pmax.{first_nd + j}" for j in range(nd.shape[1])] \
        + [f"gen.Pmax.{first_shed + j}" for j in range(load_p.shape[1])]
    values = np.hstack([load_p,load_q,nd,load_p])
    data["series"] = [{"name":"tracy2021","index":index,"timed":True,"delta":1.0,
        "columns":columns,"values":values.tolist()}]
    return Case(data,name)

def cvxopf_inputs(case:Case,formulation:str) -> dict:
    """Keyword arguments of `cvxopf.build_opf_multistep` for the study's own
    device model of a case written by this script (generator rows as in the
    module docstring): `formulation` is `singlenode_dc`, `lossy_dc`,
    `socp` or `ac`. Unlike ppedit's own multistep OPF, this is the study's
    model in AC and SOCP too (circular battery and renewable ratings,
    reactive load shed with real load). Solve it with
    `build.solve(solver=...)` and read it with `cvxopf.extract_results`."""
    # pylint: disable=import-outside-toplevel
    from cvxopf import Load,NondispatchableUnit,StorageUnitIdeal,gen_from_matpower,OPFOptions
    ppc = case.to_ppc(arrays=True)
    gen,cost = ppc["gen"],ppc["gencost"]
    storage = np.array(case.tables["storage"],dtype=float)
    if len(gen) != 299 or len(storage) != 27 or not np.array_equal(storage[:,0],np.arange(55,82)):
        raise ValueError("not a case written by build_tracy2021.py")
    if np.any(storage[:,[3,6,7,8]] != [0,1,1,0]) or np.any(storage[:,1] != -1):
        raise ValueError("cvxopf's ideal storage needs Emin 0, efficiencies 1, no self-discharge")
    ser = case.series[0]
    col = {k:i for i,k in enumerate(ser["columns"])}
    values = np.array(ser["values"],dtype=float)
    T = len(values)
    index = pd.RangeIndex(T)
    shed = range(200,299)
    loads = [Load(bus=int(gen[k,0]),p_load_mw=float(values[0,col[f"bus.Pd.{int(gen[k,0])}"]]),
        q_load_mvar=float(values[0,col[f"bus.Qd.{int(gen[k,0])}"]]),device_id=f"load_bus_{int(gen[k,0])}",
        shedding_cost_per_mwh=float(cost[k,5]),max_shed_fraction=1.0) for k in shed]
    renew = [NondispatchableUnit(bus=int(gen[k,0]),p_available=float(values[0,col[f"gen.Pmax.{k+1}"]]),
        apparent_power_rating=float(gen[k,3]),device_id=f"renewable_{k+1}") for k in range(81,200)]
    units = [StorageUnitIdeal(bus=int(gen[int(r[0])-1,0]),capacity=float(r[4]),initial_soc=float(r[2]),
        apparent_power_rating=float(r[5]),aging_weight=float(r[9]),
        terminal_soc=None if r[10] < 0 else float(r[10]),
        terminal_constraint=None if r[10] < 0 else "equality",device_id=f"storage_{n+1}")
        for n,r in enumerate(storage)]
    net = {"version":"2","baseMVA":float(ppc["baseMVA"]),"bus":ppc["bus"],"gen":gen[:54],
        "branch":ppc["branch"][:,:13],"gencost":cost[:54]}
    frame = lambda keys,ids: pd.DataFrame(values[:,[col[k] for k in keys]],index=index,columns=ids)
    buses = [int(gen[k,0]) for k in shed]
    return dict(case=net,T=T,delta=float(ser["delta"]),temporal_assembly="vectorized",
        generators=gen_from_matpower(gen[:54],cost[:54]),loads=loads,nondispatchable=renew,storage=units,
        df_load_p=frame([f"bus.Pd.{b}" for b in buses],[x.device_id for x in loads]),
        df_load_q=frame([f"bus.Qd.{b}" for b in buses],[x.device_id for x in loads]),
        df_nd=frame([f"gen.Pmax.{k+1}" for k in range(81,200)],[x.device_id for x in renew]),
        formulation=formulation,options=OPFOptions(loss_weight=1.0))

def header(name:str) -> str:
    """Comment block written at the top of a case file"""
    start,stop,e0,e1,demand = STUDIES[name]
    return "\n".join([
        f"# Tracy 2021 IEEE 118-bus study case: {TITLES[name]}",
        f"# Hours {start} to {stop} of 2021 (UTC-08:00); demand multiplier {demand!r}",
        "# Written by examples/ieee118/build_tracy2021.py from 9q9wtp_gen_and_load.csv; don't edit.",
        "# Generators 1-54: case generators; 55-81: battery discharge (storage rows 1-27);",
        "# 82-200: renewables (Pmax = available power); 201-299: load shedding at 20763.594 $/MWh.",
        "# Network data: PGLib-OPF v23.07 pglib_opf_case118_ieee (CC BY 4.0, see LICENSE-pglib).",
        ""])

def main(argv:list[str]|None=None) -> int:
    """Write the case files"""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("studies",nargs="*",choices=[[]] + list(STUDIES),metavar="STUDY",
        help=f"one or more of {', '.join(STUDIES)} (default: all but annual)")
    parser.add_argument("--output",default=HERE,help="folder for the case files")
    parser.add_argument("--source",default=SOURCE,help="the Tracy CSV file")
    args = parser.parse_args(argv)
    names = args.studies or [n for n in STUDIES if n != "annual"]
    pglib = read_pglib()
    inputs = prepare(read_source(args.source),pglib)
    for name in names:
        case = build(name,inputs,pglib)
        path = os.path.join(args.output,f"case118_tracy2021_{name}.py")
        text = case.dumps("py")
        with open(path,"w",encoding="utf-8") as fh:
            fh.write(header(name) + text)
        print(f"wrote {path} ({os.path.getsize(path)/1e6:.1f} MB)")
    return 0

if __name__ == "__main__":
    sys.exit(main())
