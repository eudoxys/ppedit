# PYPOWER example cases

The standard test cases distributed with PYPOWER, and the cvxopf DC line
test case `case9_dcline` (see [case9_dcline](#case9_dcline)), each in two
forms:

  - `<case>.py`: the original PYPOWER case file, unchanged.
  - `<case>.glm`: the same case as an Arras Energy GridLAB-D model using
    `module pypower` (`bus`, `gen`, `branch`, `gencost` objects), written by
    `ppedit`.

Open either form in the editor, for example:

    ppedit serve examples/pypower/case14.glm

or use the GLM in a GridLAB-D model (`#include "case14.glm"`).

## Source

  - Source: the `pypower` package on PyPI (https://pypi.org/project/PYPOWER/,
    https://github.com/rwl/PYPOWER), files `pypower/case*.py`.
  - License: BSD 3-clause, Copyright (c) 1996-2015 Power System Engineering
    Research Center (PSERC) and contributors. The license and author list
    are reproduced in `LICENSE` and `AUTHORS` in this folder and apply to
    the `.py` files and to the case data in the `.glm` files.
  - Regenerate with `python3 examples/import_pypower_cases.py` (copies the
    `.py` files, writes the `.glm` files, the license files, and the table
    below). Do not edit these files by hand. The script keeps
    `case9_dcline.py` and rewrites only `case9_dcline.glm`.

## Conversion notes

  - GLM buses are named `pp_bus_<bus number>`, generators `pp_gen_<n>`,
    branches `pp_branch_<n>`, and cost curves `pp_gencost_<n>`; each
    generator's `parent` is its bus and each cost curve's `parent` its
    generator. See `ppedit.case` for details.
  - `case4gs` numbers its buses from 0. GridLAB-D reads bus number 0 as
    "unset", so renumber that case before using its GLM in GridLAB-D.
  - PYPOWER result columns, `areas` and `dcline` data, if present in a case
    file, are not carried into the GLM.
  - "OPF converges" is "no" for the cases with piecewise-linear or reactive
    power costs (`case9Q`, `case30Q`, `case30pwl`): PYPOWER's own OPF fails
    on them with current numpy. `case9target` is a target case for
    PYPOWER's continuation power flow, and its base case does not converge.

## Cases

<!-- cases -->
Imported from `pypower` 5.1.21 on 2026-11-13.

| Case | Buses | Generators | Branches | Cost rows | Load (MW) | PF converges | OPF converges |
|---|--:|--:|--:|--:|--:|:-:|:-:|
| `case4gs` | 4 | 2 | 4 | 0 | 500.0 | yes | — |
| `case6ww` | 6 | 3 | 11 | 3 | 210.0 | yes | yes |
| `case9` | 9 | 3 | 9 | 3 | 315.0 | yes | yes |
| `case9Q` | 9 | 3 | 9 | 6 | 315.0 | yes | no |
| `case9target` | 9 | 3 | 9 | 3 | 755.1 | no | no |
| `case14` | 14 | 5 | 20 | 5 | 259.0 | yes | yes |
| `case24_ieee_rts` | 24 | 33 | 38 | 33 | 2,850.0 | yes | yes |
| `case30` | 30 | 6 | 41 | 6 | 189.2 | yes | yes |
| `case30Q` | 30 | 6 | 41 | 12 | 189.2 | yes | no |
| `case30pwl` | 30 | 6 | 41 | 6 | 189.2 | yes | no |
| `case39` | 39 | 10 | 46 | 10 | 6,254.2 | yes | yes |
| `case57` | 57 | 7 | 80 | 7 | 1,250.8 | yes | yes |
| `case118` | 118 | 54 | 186 | 54 | 4,242.0 | yes | yes |
| `case300` | 300 | 69 | 411 | 69 | 23,525.8 | yes | yes |
<!-- /cases -->

## case9_dcline

PYPOWER's 9-bus DC line test case (`pypower/t/t_case9_dcline.py`: four DC
lines, one out of service, with DC line costs), with a load time series
for multistep OPF.

  - Source: cvxopf (https://github.com/cvxgrp/cvxopf), file
    `src/cvxopf/testcases/case9_dcline.py` at commit `fd4d279`
    (2026-11-18; unchanged at `8c40598`, the commit CI installs), imported
    2026-11-23. The case data is unchanged.
  - License: BSD 2-clause, Copyright (c) 2026 Alliance for Sustainable
    Energy, LLC, reproduced in `LICENSE-cvxopf`; the case data itself is
    PYPOWER's (`LICENSE`, `AUTHORS`).
  - Added: `ppc["series"]`, one ppedit time series named `load` (see
    `ppedit.case`): 24 hourly steps (`delta` 1 h, steps labeled 1 to 24)
    of `bus.Pd` (MW) and `bus.Qd` (MVAr) for the loaded buses 5, 7 and 9.
    Every step holds the base-case demand. With cvxopf installed, **Run
    OPF ▾ › Multistep OPF** solves all steps at once. PYPOWER
    ignores the key; GLM cannot hold it, so `case9_dcline.glm` has no
    series.
  - Checked by `ppedit/_test/test_examples.py`:
      - PIPS OPF (PYPOWER with ppedit's DC line model), with the DC line
        costs removed as in PYPOWER's `t_dcline.py`, matches cvxopf's
        PYPOWER reference solution
        (`tests/fixtures/case9_dcline_pypower_reference.json`, copied to
        `ppedit/_test/data/`): objective 6446.05 $/h, generator and DC line
        terminal dispatch, voltages and branch flows to within 1e-6.
      - When cvxopf is installed: the case data equals cvxopf's
        `case9_dcline()`; `CVXOPF-AC` gives cvxopf's own AC `build_opf`
        solution (6443.51 $/h with the DC line costs); and a multistep OPF
        over the series costs 24 times the single-period OPF for every
        `CVXOPF-*` model, with every AC step matching the single-period
        dispatch, voltages, branch and DC line flows to within 1e-6.
