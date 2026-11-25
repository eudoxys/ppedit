"""Set the branch ratings of the WECC 240 2020 case from its multistep SOCP OPF

Syntax: python3 examples/wecc240/wecc240_ratings.py [CASE] [--flows CSV] [--margin M] [--check]

Solves the multistep OPF of `CASE` (default `examples/wecc240/wecc240_2020.py`)
over all the steps of its time series (the 744 hours of August 2020) with the
SOCP relaxation (`CVXOPF-SOCP`, default preparation and solver options), and
writes the largest apparent power flow of each branch over those hours to
`wecc240_2020_maxflow.csv` (`row,fbus,tbus,status,rateA_old,maxflow_MVA,hour`:
the branch row from 1, its larger end flow `max(|PF + jQF|, |PT + jQT|)` in
MVA, and the step label of the hour it occurs). Then each in-service
branch gets `rateA` = `maxflow_MVA * (1 + M)` (default `M` = 0.1, a 10%
margin) rounded up to whole MVA, and its `rateB` and `rateC` raised to the
new `rateA` where they are lower, and the case is saved in place. This lowers
`rateA` on branches whose flows stay below their old rating, raises it on
branches that reached it, and rates branches that were unrated (0) before.
Out-of-service branches keep their ratings.

`--flows CSV` reads the maximum flows from a file written earlier instead of
solving (the solve takes about 8 minutes and more than 5 GB of memory);
`--check` reports the changes without saving.
"""

import argparse
import csv
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0,os.path.dirname(os.path.dirname(HERE)))
from ppedit import Case # pylint: disable=wrong-import-position

FLOWS = "wecc240_2020_maxflow.csv"
"""Maximum branch flow file written in `examples/wecc240/`"""

MARGIN = 0.1
"""Margin of `rateA` over the maximum flow (10%)"""

FIELDS = ["row","fbus","tbus","status","rateA_old","maxflow_MVA","hour"]

def max_flows(case:Case) -> list[dict]:
    """Return one row per branch with its largest flow (MVA) over the
    multistep SOCP OPF of all steps of the case series"""
    result = case.solve("opf",algorithm="CVXOPF-SOCP",multistep=True)
    for msg in result["messages"]:
        print(f"{msg['level']}: {msg['message']}",file=sys.stderr)
    if not result["success"]:
        raise ValueError("multistep SOCP OPF failed")
    steps = result["steps"]
    if not all(s["success"] for s in steps):
        raise ValueError("some steps of the multistep SOCP OPF failed")
    print(f"solved {len(steps)} steps ({steps[0]['label']} to {steps[-1]['label']}), "
        f"horizon objective {result['horizon_objective']:,.0f} $",file=sys.stderr)
    rows = []
    for n,branch in enumerate(case.tables["branch"]):
        best,hour = 0.0,""
        for step in steps:
            flow = step["branch"][n]
            smax = max(math.hypot(flow["PF"],flow["QF"]),math.hypot(flow["PT"],flow["QT"]))
            if smax > best:
                best,hour = smax,step["label"]
        rows.append({"row":n+1,"fbus":branch[0],"tbus":branch[1],"status":branch[10],
            "rateA_old":branch[5],"maxflow_MVA":round(best,3),"hour":hour})
    return rows

def read_flows(path:str) -> list[dict]:
    """Return the rows of a maximum flow file"""
    with open(path,newline="",encoding="utf-8") as fh:
        return list(csv.DictReader(fh))

def main() -> int:
    """Set the branch ratings of the case from its maximum multistep flows"""
    parser = argparse.ArgumentParser(description=__doc__.split("\n",1)[0])
    parser.add_argument("case",nargs="?",default=os.path.join(HERE,"wecc240_2020.py"))
    parser.add_argument("--flows",help="read the maximum flows from this file instead of solving")
    parser.add_argument("--margin",type=float,default=MARGIN,help="margin over the maximum flow")
    parser.add_argument("--check",action="store_true",help="report the changes without saving")
    args = parser.parse_args()
    case = Case.load(args.case)
    if args.flows:
        flows = read_flows(args.flows)
    else:
        flows = max_flows(case)
        with open(os.path.join(HERE,FLOWS),"w",newline="",encoding="utf-8") as fh:
            writer = csv.DictWriter(fh,FIELDS,lineterminator="\n")
            writer.writeheader()
            writer.writerows(flows)
    branches = case.tables["branch"]
    if len(flows) != len(branches):
        raise ValueError(f"{len(flows)} flows for {len(branches)} branches")
    counts = {"raised":0,"lowered":0,"rated":0,"same":0,"out":0}
    for n,(branch,flow) in enumerate(zip(branches,flows)):
        if (int(flow["fbus"]),int(flow["tbus"])) != (branch[0],branch[1]):
            raise ValueError(f"branch row {n+1} is {branch[0]}-{branch[1]}, "
                f"not {flow['fbus']}-{flow['tbus']} as the flows say")
        if branch[10] != 1:
            counts["out"] += 1
            continue
        rate = float(math.ceil(float(flow["maxflow_MVA"])*(1+args.margin)))
        old = branch[5]
        counts["same" if rate == old else "rated" if old == 0 else
            "raised" if rate > old else "lowered"] += 1
        branch[5] = rate
        branch[6] = max(branch[6],rate)
        branch[7] = max(branch[7],rate)
    errors = [x["message"] for x in case.validate() if x["level"] == "error"]
    if errors:
        raise ValueError("; ".join(errors))
    print(f"rateA raised on {counts['raised']}, lowered on {counts['lowered']}, "
        f"set on {counts['rated']} unrated, unchanged on {counts['same']} branches; "
        f"{counts['out']} out of service unchanged")
    if not args.check:
        case.save(args.case)
        print(f"saved {args.case}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
