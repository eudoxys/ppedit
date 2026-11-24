# IEEE 118-bus Tracy 2021 example

Battery and renewable studies on the IEEE 118-bus network with hourly
demand, utility solar, wind and distributed solar from Tracy, California in
2021: one ppedit case per study, with every input its multistep OPF needs
(network, generators, renewables, batteries, load shedding, hourly series).

## Files in this folder

| File | Purpose |
| --- | --- |
| `9q9wtp_gen_and_load.csv` | modeled hourly Tracy, California demand, utility solar, utility wind and distributed solar (MW, UTC-08:00, 2018-2023; geohash `9q9wtp`) |
| `case118.py` | the PYPOWER IEEE 118-bus case (same as `../pypower/case118.py`): the starting point of the study cases |
| `pglib_opf_case118_ieee.m`, `LICENSE-pglib` | the PGLib-OPF v23.07 IEEE 118-bus case (CC BY 4.0), which supplies the network limits and costs |
| `case118_tracy2021_*.py` | the six 24-hour study cases (see below) |
| `build_tracy2021.py` | writes the study case files (and the annual one) from the files above |

## Study case files

`build_tracy2021.py` writes one ppedit case per study (`python3
examples/ieee118/build_tracy2021.py [STUDY ...]`, from the repository root):

| Case file | Study | Hours of 2021 (UTC-08:00) | Battery energy start → end |
| --- | --- | --- | --- |
| `case118_tracy2021_surplus.py` | large surplus | 3308-3332 (May 18 20:00 to May 19 20:00) | 50% → 50% |
| `case118_tracy2021_deficit.py` | large deficit | 1165-1189 (Feb 18 13:00 to Feb 19 13:00) | 50% → 50% |
| `case118_tracy2021_deficit_depletion.py` | deficit depletion | 1165-1189 | 60% → 25% |
| `case118_tracy2021_surplus_to_deficit.py` | surplus to deficit | 8580-8604 (Dec 27 12:00 to Dec 28 12:00) | 50% → 50% |
| `case118_tracy2021_deficit_to_surplus.py` | deficit to surplus | 2439-2463 (Apr 12 15:00 to Apr 13 15:00) | 50% → 50% |
| `case118_tracy2021_forced_shedding.py` | forced shedding: the large-deficit day with demand (P and Q) times 7.5416905141946184 | 1165-1189 | 50% → 50% |
| `case118_tracy2021_annual.py` (not in the repository: about 42 MB, write it with `build_tracy2021.py annual`) | the full year | 0-8760 | 50% → 50% |

Solve them with **Run OPF ▾ › Multistep OPF** and the `CVXOPF-1NODE`
(copper plate), `CVXOPF-DC` (lossy DC), `CVXOPF-SOCP` or `CVXOPF-AC` solver.
The DC models solve a day in a few seconds; ppedit's AC multistep OPF of a
whole day needs more memory than 7 GB.

How the cases are made: `case118.py` is the PYPOWER IEEE 118-bus case; the
study network is the PGLib-OPF version, which has the same buses, branches,
impedances, loads and generator locations, so the builder keeps
`case118.py` and takes from `pglib_opf_case118_ieee.m` only the columns
where the two differ, after checking all the others are equal: bus `Vm`,
`Va`; generator `Pg`, `Qg`, `Qmax`, `Qmin`, `Vg`, `Pmax`; branch `rateA`,
`rateB`, `rateC`, `angmin`, `angmax` and the unit `ratio` of branches
86-87 and 68-116 (0 in `case118.py`, the same thing); generator cost `c2`,
`c1`. The study inputs, with buses picked at random from a fixed seed:

- the 2021 hours of `9q9wtp_gen_and_load.csv` scaled so the peak net load
  is 6000 MW; demand shared by the 99 load buses in proportion to their case
  load (reactive load at each bus's case Q/P ratio);
- utility solar (10 units) and wind (10) at 15 buses, distributed solar at
  the 99 load buses; MVA rating 1.1 times the annual peak;
- 27 ideal batteries (4 hours of average load in all, 3 h at rated power),
  aging cost 0.01 $/MWh of throughput;
- the 19 generators with capacity scaled to 5000 MW in all, with a
  quadratic cost term `c2 = c1/(3 Pmax)`;
- load shedding allowed everywhere at 20763.594 $/MWh.

In the case files generators 1-54 are the case generators, 55-81 the
batteries' discharge (with `storage` rows 1-27), 82-200 the renewable units
(zero cost, `Pmax` following the available power, so curtailment is
`Pmax - Pg`) and 201-299 load shedding (`Pmax` following the bus demand).
The series `tracy2021` holds the hourly `bus.Pd`, `bus.Qd` of the load
buses and `gen.Pmax` of the renewable and shedding generators; the case
values are those of the first hour. Values are written with 10 significant
digits.

ppedit's DC multistep OPF of these cases is the same problem as cvxopf's
device model of the studies. In SOCP and AC it is close but not the same:
cvxopf limits batteries and renewables to a circle `P^2 + Q^2 <= S^2` (here
a box, and charging has no reactive power) and sheds reactive load with
real load (here shedding has no reactive power).
`build_tracy2021.cvxopf_inputs(case, formulation)` turns a case file into
that device model, for all four formulations:

```python
from cvxopf import build_opf_multistep, extract_results
build = build_opf_multistep(**build_tracy2021.cvxopf_inputs(case, "lossy_dc"))
build.solve(solver="CLARABEL")
```

ppedit's multistep OPF of these cases is less accurate in CLARABEL than
the device model's: with tolerances of 1e-10, one-day copper-plate windows
end up to about 1e-5 (relative) above the optimum and some do not solve,
where the device model solves them to about 1e-9 (see the rough edges in
`CLAUDE.md`).

## References

1. Meyers BE, "Network-Model Fidelity in Intertemporal Storage Dispatch: A Matched Study with CVXOPF," IEEE PES 2027 General Meeting, submitted 10 Nov 2026. 
