"""Load the storage table and time series of the WECC 240 2020 case

Syntax: python3 examples/wecc240/build_wecc240_2020.py [CASE] [--check]

First writes `wecc240_2020_reactive_load.csv` from
`wecc240_2020_real_load.csv` at the power factor of each bus in the case
bus table: `Qd(t) = Pd(t) * Qd / Pd` (0 where the case `Pd` is 0), rounded
to 4 decimals like the real load. Then rebuilds, in `CASE` (default
`examples/wecc240/wecc240_2020.py`), the data that comes from the other `examples/wecc240/`
files, and saves the case in place:

  1. `storage`: the rows of `wecc240_storage.csv` (replacing any); each
     storage generator (`gen_i`) is put in service with `Pmax` = `Smax`.
  2. Time series (replacing all series), aligned on the hours of
     `wecc240_2020_real_load.csv`:
       - `real_load`: bus `Pd` by hour (`wecc240_2020_real_load.csv`);
       - `reactive_load`: bus `Qd` by hour (`wecc240_2020_reactive_load.csv`);
       - `generation`: generator `Pmax` by hour, the same hours of the
         panel `wecc240_generation.csv.gz` (columns are gen rows; the
         storage generators have none and keep their case `Pmax`; see
         `build_wecc240_generation.py`).

Then it checks that the reactive load follows the real load at the case
power factors, that every series reads back unchanged from its file, that
the three combine by time into one horizon with no column given twice, and
that the case validates without errors. `--check` runs only the checks,
without changing or saving the case.

The network, costs, geodata and areas (`wecc240_areas.py`) are not changed.
"""

import argparse
import csv
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0,os.path.dirname(os.path.dirname(HERE)))
from ppedit import Case # pylint: disable=wrong-import-position
from ppedit._tableio import read_series # pylint: disable=wrong-import-position

STORAGE = "wecc240_storage.csv"
SERIES = [
    ("real_load","wecc240_2020_real_load.csv"),
    ("reactive_load","wecc240_2020_reactive_load.csv"),
]
PANEL = ("generation","wecc240_generation.csv.gz","gen","Pmax")

def _read(name):
    """Return the step labels, columns and rows of a series file in `examples/wecc240/`"""
    with open(os.path.join(HERE,name),"rb") as fh:
        return read_series(name,fh.read())

def reactive_ratios(case,columns):
    """Return the case `Qd/Pd` of the buses of the real load `columns` (0 where `Pd` is 0)"""
    bus = {r[0]:r for r in case.tables["bus"]}
    out = []
    for col in columns:
        row = bus[int(col.split(".")[2])]
        out.append(row[3]/row[2] if row[2] else 0.0)
    return out

def write_reactive(case):
    """Write `wecc240_2020_reactive_load.csv` from the real load at the case power factors"""
    index,columns,rows = _read(SERIES[0][1])
    ratio = reactive_ratios(case,columns)
    with open(os.path.join(HERE,SERIES[1][1]),"w",newline="",encoding="utf-8") as fh:
        out = csv.writer(fh,lineterminator="\n")
        out.writerow(["time"] + [c.replace(".Pd.",".Qd.") for c in columns])
        for label,row in zip(index,rows):
            out.writerow([label] + [repr(round(p*k,4) + 0.0) for p,k in zip(row,ratio)])

def load_storage(case):
    """Replace the storage rows with `wecc240_storage.csv`; put their generators in service"""
    with open(os.path.join(HERE,STORAGE),newline="",encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    if case.tables["storage"]:
        case.delete_rows("storage",list(range(len(case.tables["storage"]))))
    case.import_rows("storage",rows[0],[[float(x) for x in r] for r in rows[1:]])
    for gen_i,smax in ((int(r[0]),r[5]) for r in case.tables["storage"]):
        case.set_value("gen",gen_i-1,"status",1)
        case.set_value("gen",gen_i-1,"Pmax",smax)
    return len(case.tables["storage"])

def load_series(case):
    """Replace all series with the load series and the generation panel's hours"""
    for ser in list(case.series):
        case.set_series(None,name=ser["name"])
    hours = None
    for name,filename in SERIES:
        index,columns,rows = _read(filename)
        if hours is None:
            hours = index
        elif index != hours:
            raise ValueError(f"{filename} has other hours than {SERIES[0][1]}")
        case.set_series(columns,rows,index,1.0,name=name)
    name,filename,table,column = PANEL
    index,columns,rows = read_series(filename,open(os.path.join(HERE,filename),"rb").read(),
        start=hours[0],end=hours[-1])
    if index != hours:
        raise ValueError(f"{filename} does not hold the hours {hours[0]} to {hours[-1]}")
    case.set_series_panel(table,column,columns,rows,index,1.0,keys_are="row",merge=False,name=name)

def check(case):
    """Return a list of problems with the storage, series and validation of `case`"""
    problems = []
    def same(a,b):
        return len(a) == len(b) and all(math.isclose(x,y,rel_tol=1e-9,abs_tol=1e-9) for x,y in zip(a,b))
    real,reactive = case.get_series(SERIES[0][0]),case.get_series(SERIES[1][0])
    if real and reactive:
        ratio = reactive_ratios(case,real["columns"])
        if reactive["columns"] != [c.replace(".Pd.",".Qd.") for c in real["columns"]] \
                or reactive["index"] != real["index"] \
                or not all(math.isclose(q,p*k,abs_tol=1e-4) for rp,rq in zip(real["values"],reactive["values"])
                    for p,q,k in zip(rp,rq,ratio)):
            problems.append("reactive_load does not follow real_load at the case power factors")
    names = [s["name"] for s in case.series]
    if names != [n for n,_ in SERIES] + [PANEL[0]]:
        problems.append(f"series are {names}")
    for name,filename in SERIES:
        ser = case.get_series(name)
        index,columns,rows = _read(filename)
        if ser is None or ser["index"] != index or ser["columns"] != columns \
                or not all(same(a,b) for a,b in zip(ser["values"],rows)) or not ser["timed"]:
            problems.append(f"series {name} differs from {filename}")
    ser = case.get_series(PANEL[0])
    hours = case.get_series(SERIES[0][0])["index"]
    index,columns,rows = read_series(PANEL[1],open(os.path.join(HERE,PANEL[1]),"rb").read(),
        start=hours[0],end=hours[-1])
    want = {f"{PANEL[2]}.{PANEL[3]}.{c}":[r[j] for r in rows] for j,c in enumerate(columns)}
    got = {c:[r[j] for r in ser["values"]] for j,c in enumerate(ser["columns"])} if ser else {}
    if not ser or ser["index"] != index or set(got) != set(want) \
            or not all(same(got[c],want[c]) for c in want):
        problems.append(f"series {PANEL[0]} differs from {PANEL[1]}")
    stores = {int(r[0]) for r in case.tables["storage"]}
    if any(int(c.split(".")[2]) in stores for c in got):
        problems.append(f"series {PANEL[0]} has columns for storage generators")
    combined = case._combined_info() # pylint: disable=protected-access
    if "error" in combined:
        problems.append(f"series do not combine: {combined['error']}")
    elif combined.get("aligned") != "time" or combined.get("steps") != len(hours) or combined.get("summed"):
        problems.append(f"series combine unexpectedly: {combined}")
    with open(os.path.join(HERE,STORAGE),newline="",encoding="utf-8") as fh:
        rows = list(csv.reader(fh))[1:]
    if not all(same(a,[float(x) for x in b]) for a,b in zip(case.tables["storage"],rows)) \
            or len(rows) != len(case.tables["storage"]):
        problems.append(f"storage differs from {STORAGE}")
    for gen_i,smax in ((int(r[0]),r[5]) for r in case.tables["storage"]):
        gen = case.tables["gen"][gen_i-1]
        if gen[7] != 1 or gen[8] != smax:
            problems.append(f"storage generator {gen_i} is not in service with Pmax = Smax")
    problems += [f"{x['table']}: {x['message']}" for x in case.validate() if x["level"] == "error"]
    return problems

def main(argv=None):
    """Command line entry point"""
    parser = argparse.ArgumentParser(description=__doc__.split("\n",1)[0])
    parser.add_argument("case",nargs="?",default=os.path.join(HERE,"wecc240_2020.py"))
    parser.add_argument("--check",action="store_true",help="only check the case")
    args = parser.parse_args(argv)
    case = Case.load(args.case)
    if not args.check:
        write_reactive(case)
        print(f"wrote {SERIES[1][1]}")
        print(f"storage: {load_storage(case)} rows")
        load_series(case)
    for ser in case.series:
        print(f"series {ser['name']}: {len(ser['values'])} steps, {len(ser['columns'])} columns")
    info = case._combined_info() # pylint: disable=protected-access
    print("combined:",info.get("error") or f"{info['steps']} steps by {info['aligned']}, "
        f"{info['columns']} columns, {info['first']} to {info['last']}")
    problems = check(case)
    for text in problems:
        print("problem:",text)
    if problems:
        return 1
    if not args.check:
        case.save(args.case)
        print(f"saved {args.case}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
