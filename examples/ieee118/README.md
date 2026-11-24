# IEEE 118-bus Tracy 2021 example (IEEE PES GM 2027)

This folder holds the Case118 experiments of the IEEE PES General Meeting
2027 paper submitted by Bennet Meyers (November 2026) two ways:

- **ppedit case files**, one per study, with every input the study's
  optimization needs (network, generators, renewables, batteries, load
  shedding, hourly series), to open, edit and solve in ppedit (see
  [Study case files](#study-case-files));
- the inputs for reproducing the experiments with
  [cvxopf](https://github.com/cvxgrp/cvxopf) itself, as the paper's
  reproduction archive `pes2027-reproduction-inputs.zip` describes (the
  instructions below come from that archive; the next section says how
  the files here stand in for it).

## Files in this folder

| File | Purpose |
| --- | --- |
| `9q9wtp_gen_and_load.csv` | the external source data: modeled Tracy, California demand, utility solar, utility wind and distributed solar profiles (installed as `experiments/battery_terminal/data/9q9wtp_gen_and_load.csv`) |
| `SHA256SUMS` | SHA-256 of all ten archive files, by cvxopf clone path |
| `install_inputs.py` | installs the files into a cvxopf clone and checks them against `SHA256SUMS` |
| `case118.py` | the PYPOWER IEEE 118-bus case (same as `../pypower/case118.py`): the starting point of the study case files |
| `pglib_opf_case118_ieee.m`, `LICENSE-pglib` | the PGLib-OPF v23.07 IEEE 118-bus case the experiments use (CC BY 4.0), as pinned in cvxopf (revision `dc6be4b2`) |
| `case118_tracy2021_*.py` | the six 24-hour study cases (see below) |
| `build_tracy2021.py` | writes the study case files (and the annual one) from the files above |
| `check_tracy2021.py` | checks the study case files against the reproduction archive (see below) |

The nine earlier study records under `experiments/` (the largest three are
about 138 MB together) are **not** in this repository: the cvxopf code
checks them by hash, so they must be the original files, from
`pes2027-reproduction-inputs.zip`. Neither the study case files nor
`build_tracy2021.py` need them; `install_inputs.py` and
`check_tracy2021.py` read them from the ZIP.

## Study case files

`build_tracy2021.py` writes one ppedit case per study (`python3
examples/ieee118/build_tracy2021.py [STUDY ...]`, from the repository root):

| Case file | Study | Hours of 2021 (UTC-08:00) | Battery energy start → end |
| --- | --- | --- | --- |
| `case118_tracy2021_surplus.py` | joint (E3) large surplus | 3308-3332 (May 18 20:00 to May 19 20:00) | 50% → 50% |
| `case118_tracy2021_deficit.py` | joint (E3) large deficit | 1165-1189 (Feb 18 13:00 to Feb 19 13:00) | 50% → 50% |
| `case118_tracy2021_deficit_depletion.py` | joint (E3) deficit depletion | 1165-1189 | 60% → 25% |
| `case118_tracy2021_surplus_to_deficit.py` | joint (E3) surplus to deficit | 8580-8604 (Dec 27 12:00 to Dec 28 12:00) | 50% → 50% |
| `case118_tracy2021_deficit_to_surplus.py` | joint (E3) deficit to surplus | 2439-2463 (Apr 12 15:00 to Apr 13 15:00) | 50% → 50% |
| `case118_tracy2021_forced_shedding.py` | joint (E3+) forced shedding: the large-deficit day with demand (P and Q) times 7.5416905141946184 | 1165-1189 | 50% → 50% |
| `case118_tracy2021_annual.py` (not in the repository: about 42 MB, write it with `build_tracy2021.py annual`) | annual DC (Stage C) | 0-8760 | 50% → 50% |

Each study was solved in the paper with the copper-plate (`singlenode_dc`,
ppedit `CVXOPF-1NODE`) and lossy DC (`lossy_dc`, `CVXOPF-DC`) models, and the
24-hour studies also with SOCP and AC: run **Run OPF ▾ › Multistep OPF**
with those solvers. The fixed-power transfers and the rollouts have no case
files of their own: their battery schedules and energy targets come from
the joint solutions you compute (the rollouts solve three-hour windows of
the 24-hour cases).

How the cases are made: `case118.py` is the PYPOWER IEEE 118-bus case; the
study network is the PGLib-OPF version, which has the same buses, branches,
impedances, loads and generator locations, so the builder keeps
`case118.py` and takes from `pglib_opf_case118_ieee.m` only the columns
where the two differ, after checking all the others are equal: bus `Vm`,
`Va`; generator `Pg`, `Qg`, `Qmax`, `Qmin`, `Vg`, `Pmax`; branch `rateA`,
`rateB`, `rateC`, `angmin`, `angmax` and the unit `ratio` of branches 86-87 and 68-116 (0 in
`case118.py`, the same thing); generator cost `c2`, `c1`. The study inputs
follow cvxopf's `experiments/case118_tracy_2021/prepare.py` (cvxopf
`2edc6d3b`), with the same seeded random siting:

- the 2021 hours of `9q9wtp_gen_and_load.csv` scaled so the peak net load
  is 6000 MW; demand shared by the 99 load buses in proportion to their case
  load (reactive load at each bus's case Q/P ratio);
- utility solar (10 units) and wind (10) at 15 seeded buses, distributed
  solar at the 99 load buses; MVA rating 1.1 times the annual peak;
- 27 ideal batteries (4 hours of average load in all, 3 h at rated power)
  at seeded buses, aging cost 0.01 $/MWh of throughput;
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
digits (within 5e-11 of the study's).

ppedit's DC multistep OPF of these cases is the study's DC problem. In
SOCP and AC it is close but not the same: cvxopf limits batteries and
renewables to a circle `P^2 + Q^2 <= S^2` (here a box, and charging has no
reactive power) and sheds reactive load with real load (here shedding has
no reactive power). `build_tracy2021.cvxopf_inputs(case, formulation)`
turns a case file back into the study's own cvxopf device model, exact in
all four formulations:

```python
from cvxopf import build_opf_multistep, extract_results
build = build_opf_multistep(**build_tracy2021.cvxopf_inputs(case, "lossy_dc"))
build.solve(solver="CLARABEL")
```

### Checking the case files against the archive

```sh
python3 examples/ieee118/check_tracy2021.py /path/to/pes2027-reproduction-inputs.zip [--year] [--year-ppedit] [--studies]
```

checks that (1) the inputs made from the CSV equal those recorded in the
two annual results; (2) the case files have the windows and battery
energies of the joint study binding and the network, generators,
renewables, batteries, demand and shedding of the study's frozen model
inputs (`qualification_002/binding.json`); (3) each 24-hour window, solved
with the battery energies at its ends fixed to the annual solution's, costs
what the annual solution costs over it, with ppedit's multistep OPF and
with the device model; (4) with `--year`, the same for the whole year in
one-week windows, adding up to the annual objective (`--year-ppedit`: with
ppedit, in one-day windows); (5) with `--studies`, ppedit and the device
model give the same optimum for each 24-hour study as written, and the
forced-shedding study sheds at least the study's minimum.

Results on 2026-11-24 (Linux, Python 3.12, cvxopf 8c40598, CVXPY 1.9.3,
CLARABEL 0.11.1; all checks passed):

- inputs: the loads equal the recorded ones exactly, the renewable
  availability within 1.4e-14 MW; the case files equal the frozen model
  inputs within 4e-10 (relative);
- annual copper plate: the year in one-week windows adds up to the
  annual objective (101,159,780.379 $) within 0.005 $ (5e-11), every week's
  generator outputs within 1e-3 MW;
- annual lossy DC: within 132 $ (1.2e-6) of 109,472,954.967 $, every week
  within 1 $ a day and generator outputs within 0.05 MW (see the note on
  degeneracy in `check_tracy2021.py`: the window solutions meet the
  study's constraints at a slightly lower cost than the annual solution);
- the 24-hour studies as written: ppedit and the device model agree within
  2e-9 (copper plate) and 0.41 $ (lossy DC); forced shedding sheds
  551,625 MWh (copper plate) and 567,379 MWh (lossy DC), above the study's
  minimum of 439,253 MWh;
- ppedit's own multistep OPF over the year in one-day windows (a
  diagnostic): copper plate solves 349 of 365 days within 8e-6 of the
  annual solution (median 4e-11), lossy DC 354 of 365; the other days end
  without a solution in CLARABEL, which solves cvxopf's device model of the
  same days.

The SOCP and AC studies are not checked: the archive holds no SOCP or AC
results, and the 24-hour AC problems need more memory than the 7 GB this
check was run with.

## Installing the inputs

In step 1 below, replace the line `unzip -n "$archive" 'experiments/*'`
with (from the cvxopf clone root, `ppedit` being a clone of this
repository)

```sh
python3 /path/to/ppedit/examples/ieee118/install_inputs.py . "$archive"
```

where `$archive` is the ZIP or a directory holding the same `experiments/`
tree. Like `unzip -n`, it does not overwrite files already in the clone;
it then checks all ten files and exits 1 if one is missing or differs.
Without the second argument it installs only the CSV and lists the nine
missing study records. The rest of the steps are unchanged.

## Reproduce the Case118 PES experiments from a fresh CVXOPF clone

This ZIP supplies the inputs missing from Git. You will generate your **own**
24 joint solutions, use their battery powers in 18 fixed-schedule AC transfers,
and use their battery energies as targets in 24 three-hour AC rollouts. The ZIP
contains none of those solutions. Run the steps in order in **one fresh clone**:
the recorded code revisions change, but your ignored result directories stay in place.

### 1. Install the inputs and environment

Use a fresh clone of <https://github.com/cvxgrp/cvxopf>. The historical joint
and transfer runners require macOS, AC power, working `ps` process/RSS queries,
and CPU/GPU temperatures from `macmon`. They will not launch unchanged on Linux
or with unavailable telemetry. The study used Apple Silicon, Python 3.11.15,
CVXPY 1.9.3, CLARABEL 0.11.1 and native IPOPT 3.14.19. Install Git, `uv`,
IPOPT and its development files (`pkg-config`), and `macmon` before proceeding.
The lockfile pins Python packages, not the system IPOPT build.

From the **clone root**, in a POSIX-compatible shell, set the ZIP's absolute path.
Extract only `experiments/*` into the clone; do not replace the repository README.
Keep the default run directory names: downstream programs read those paths.

```sh
archive=/absolute/path/to/pes2027-reproduction-inputs.zip
unzip -tq "$archive"
git switch --detach 2edc6d3bbeac85bd78f5bf6d9cdc387f851eb0f0
unzip -n "$archive" 'experiments/*'  # or: python3 /path/to/ppedit/examples/ieee118/install_inputs.py . "$archive"
git status --porcelain                # must be empty
syncenv() { uv sync --frozen --python 3.11.15 --extra dev --extra notebook; }
syncenv
tracy=experiments/case118_tracy_2021
joint() { uv run --no-sync python -m experiments.case118_tracy_2021.run_e3 "$@"; }
uv run --no-sync python -m experiments.case118_tracy_2021.prepare \
  --output "$tracy/results/stage_a_active_inputs" \
  --review-output "$tracy/results/regenerated_stage_a_review"
```

This regenerates the annual inputs in the location the runners read, without
overwriting the **tracked** Stage A manifest or device tables. Stop on any failed
command or hash mismatch. Do not use an existing study directory.

#### What is in the ZIP?

The only external **source data** is
`experiments/battery_terminal/data/9q9wtp_gen_and_load.csv`
(SHA-256 `45e11f061d736741b18334aea0e9525c355c1a13068c291c1db6ed2e614b1b6f`).
These are modeled Tracy, California demand, utility solar, utility wind and
distributed solar profiles. Preparation selects the 8,760 hourly intervals of
2021 in fixed UTC−08:00 and allocates them to the PGLib IEEE 118-bus test case
in Git. Appendix A1 in the paper's repository folder describes the upstream
models and the mapping. Tracy supplies the hourly conditions, not the topology.

The other **nine files** are earlier study records the published code checks:

| Repository-relative location | Files and purpose |
| --- | --- |
| `experiments/case118_tracy_2021/results/stage_c/` | `binding.json`, `study-result.json`, `analysis.json`; and `completion.json` and `result.json.gz` in **each** of `arm-000/` and `arm-001/`. These seven files identify the annual DC runs used to select the published 24-hour windows. |
| `experiments/objective_assembly_qualification/results/qualification_002/binding.json` | Exact physical input specification for forced shedding: same deficit window and battery endpoints, with requested P and Q both multiplied by 7.5416905141946184. |
| `experiments/case118_tracy_2021/results/e3/binding.json` | Earlier study identity checked by the transfer and rollout code. It supplies no donor solution. |

### 2. Solve the 24 joint problems

The first revision solves five 24-hour scenarios under copper plate, network
flow, SOCP and full AC. The second adds the forced-shedding scenario under the
same four models. Use the **two distinct commits** below: the transfer reader
checks which commit produced each cohort. Preflights do not optimize; the
`--authorize-execution` commands start numerical work.

```sh
# Still at 2edc6d3b… from step 1
joint --prepared --commit "$(git rev-parse HEAD)" --preflight
joint --prepared --commit "$(git rev-parse HEAD)" --authorize-execution
joint --prepared --status

git switch --detach 13ad35bc5f0e9f8b5d20d54a55d2ab2cd7a26df8
syncenv
joint --plus --commit "$(git rev-parse HEAD)" --preflight
joint --plus --commit "$(git rev-parse HEAD)" --authorize-execution
joint --plus --status
```

Your joint records are now in `$tracy/results/e3_prepared/` and
`$tracy/results/e3_plus/`. Inspect the statuses, not just the process exit code.
The downstream reader requires all 20 ordinary arms to pass. For forced shedding
the published comparison also used three converged convex schedules with flagged
audits; retain the actual flags and review any qualified use for **your** run.
A missing trajectory or unconverged solve is not a donor. The published ordinary
run raised its per-attempt wall ceiling from 1,800 to 3,600 seconds during
execution; the default starts at 1,800. Record any budget revision using the
runner's protocol mechanism, not by editing a result or changing tolerances.

### 3. Run the 18 fixed-power transfers

```sh
git switch --detach 4fbd85f3bd80a573edac4da284e325804f1d77a3
syncenv
transfer() { uv run --no-sync python -m experiments.tracy_battery_transfer.run "$@"; }
transfer --preflight
transfer --authorize-execution --commit "$(git rev-parse HEAD)"
transfer --status
```

For each scenario, the runner fixes battery power to each of your three convex
joint schedules and initializes the remaining variables from your joint AC
solution. It writes `experiments/tracy_battery_transfer/results/transfer_001/`.
Keep all 18 outcomes, including rejections or timeouts. A failed transfer is
not by itself proof of infeasibility and does not disqualify its joint schedule
as a source of energy targets.

### 4. Run the 24 energy-signpost rollouts

Each rollout targets the individual battery energies from **a joint solution**,
including the joint AC control. It solves a three-hour AC window (shortened at
the end), executes its first action, and carries the realized state forward
by one hour. Your fixed transfers are used for comparison, not as targets.

The published run started at `8267dbf857872e4b6adcbf6c84dc05f002d63f60`
and continued at `b260e354d6eb63dfa559af7b13996617e9cdcd7a` after a telemetry
fix. Use the latter for a **new** run; do not replay the old interruption.
Keep your controls outside Git and review the resources before launch. These
are the historical ceilings (worker time is cumulative, not elapsed time):

```sh
git switch --detach b260e354d6eb63dfa559af7b13996617e9cdcd7a
syncenv
rollout() { uv run --no-sync python -m experiments.tracy_ac_rollout.run "$@"; }
runroot=experiments/tracy_ac_rollout/results/rollout_001
controls=$(mktemp -d)
printf '%s\n' '{"max_launches":2304,"total_worker_seconds":172800,"build_seconds":300,"post_solve_seconds":300,"poll_seconds":1}' > "$controls/budgets.json"
rollout --prepare --output "$runroot" --budgets "$controls/budgets.json"
```

Preparation includes the no-solve preflight. Inspect the generated
`binding.json`: source schedules, classifications, all 24 arms and budgets.
Only if you approve **this** binding and its resource use, create its launch
record and run. Two primary workers share one helper (up to three solver
processes); the per-worker and aggregate RSS limits are 16 and 24 GiB.

```sh
python3 - "$runroot/binding.json" "$controls/approval.json" <<'PY'
import hashlib, json, sys
from pathlib import Path
raw = Path(sys.argv[1]).read_bytes()
b = json.loads(raw)
approval = dict(schema=1, experiment="tracy_ac_rollout", execution_authorized=True,
                binding_sha256=hashlib.sha256(raw).hexdigest(), execution_commit=b["context"]["commit"],
                primary_workers=2, helper_workers=1, maximum_solver_processes=3,
                recovery_policy="causal_first_speculative_v1", recovery_revision=2, budgets=b["budgets"])
with open(sys.argv[2], "x") as f:
    json.dump(approval, f)
PY
rollout --run --output "$runroot" --authority "$controls/approval.json"
rollout --status --output "$runroot"
```

### Compare your results

Compare joint outcomes, fixed transfers and **executed** rollout actions
(not overlapping window forecasts) on device cost, energy not served,
curtailment and battery trajectories. Preserve classifications and missing
results. Expect platform-dependent timing and possible differences in local
AC solutions. The original study reported 24 joint solutions (including the
qualified results), 15 compatible transfers out of 18, and 24 completed
rollouts; these are comparisons, not targets to force.

The appendix and figure guide are available at reader commit
`3b918192e931d1cd88cd65a13d0c8caceea463b6` under `experiments/pes2027/`.
The historical figure tools are **not** general acceptance tests for a new
run: the results plot expects the original pattern of three failed transfers,
and the rollout SoC figure checks an original analysis-file hash. Use your
own run records to report a different outcome.
