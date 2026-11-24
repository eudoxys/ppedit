# Tests

Run from the repository root:

    pip install -e . pytest
    pytest

All tests are fast (a few seconds) and need no network or credentials.

Coverage (settings in `pyproject.toml` under `[tool.coverage.*]`):

    pip install pytest-cov
    pytest --cov --cov-report=term --cov-report=html   # report in htmlcov/

The Validation workflow runs the tests with coverage on every push and pull
request to `main`, writes the per-module table to the run's job summary,
and uploads `coverage.xml` and `htmlcov/` as the `coverage-report`
artifact. The Documentation workflow republishes the latest report from
`main` at https://www.eudoxys.com/ppedit/coverage/, with `badge.json` for
the README badge. Coverage is informational: no minimum is enforced.

| File | Checks |
|---|---|
| `conftest.py` | `client` (Flask test client on `case9`) and `post` fixtures |
| `test_case.py` | format round trips for all built-in cases, `.py` parsing without execution, GLM import conventions, edit cascades, validation, PF/OPF solve |
| `test_server.py` | API guard (header, host), edits, undo/redo, rollback of bad edits, rows, solve/apply, upload, export, save |
| `test_doctest.py` | examples in the `ppedit.case` docstring |
| `test_examples.py` | every `examples/pypower/*.glm` holds the same data as its `.py`; `examples/pypower/case9_dcline.py`: its load series, PIPS OPF matches cvxopf's PYPOWER reference (`data/case9_dcline_pypower_reference.json`), and (skipped unless cvxopf is installed) the case data and `CVXOPF-AC` solution equal cvxopf's and multistep OPF over the series solves every step as the single-period case |
| `test_ieee118.py` | `examples/ieee118/case118_tracy2021_*.py`: the files are what `build_tracy2021.py` writes, their generators, storage, shedding costs and series are as documented, and (skipped unless cvxopf is installed) the large-deficit day solves with copper-plate multistep OPF at the known cost |
| `test_cvxopf.py` | `CVXOPF-*` OPF solvers: AC matches PIPS, all formulations solve case9, isolated buses, piecewise-linear and reactive costs, DC line direction (skipped unless cvxopf is installed) |
| `test_solveproc.py` | `CVXOPF-*` solves in a child process: same result as in process, progress phases and IPOPT iterations, errors, stop (stand-in child), a child killed without a result, `/api/solve/progress` and `/api/solve/stop` (solver tests skipped unless cvxopf is installed) |
| `test_cli.py` | `convert` and `check` commands and error exit codes |
| `test_areas.py` | `areas` table on `case30`: defaults rebuilt from bus areas, price reference bus, round trips, dropped on GLM output, not passed to the solver, renumber cascades, validation, per-area results (unlisted areas, isolated buses, DC line ties) |
| `test_dcline.py` | `dcline` and `dclinecost` tables: load and round trips (including `gridlabd convert` GLM style), PF and OPF against the expected values of `pypower/t/t_dcline.py`, isolated terminals, validation, edit cascades |
| `test_psse.py` | PSS/E RAW input on `data/psse_v33.raw`, `data/psse_v35.raw` and the IEEE cases: field parsing, buses, generators, branches, DC lines, read-only save guard, errors, API and CLI, `examples/wecc240/wecc240_case.raw` |
| `test_claude.py` | `ppedit.claude` and `/api/claude`: sessions with a fake API client (no key), edits with undo, tool errors rolled back, local reads confined to the root, several sessions |
| `test_geodata.py` | geodata CSV parsing and errors, `.py`/`.json`/`.glm` round trips, bus edit cascades, validation warnings, `/api/geodata`, `convert --geodata` |
| `data/` | curated inputs; see `data/README.md` |
