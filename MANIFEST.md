# MANIFEST

Map of the `eudoxys/ppedit` repository. Every tracked file is covered by
one row or glob below; check with `python .github/check_manifest.py`.
Update this file in the same PR that adds, moves, or deletes a file.

## Start here

1. `CLAUDE.md` — conventions and working rules
2. `DESIGN.md` — design decisions, contracts, open questions
3. `ppedit/__init__.py` — package docs (spec, limits) and public API
4. `ppedit/case.py` — case model, formats, validation, solver
5. `ppedit/server.py` — Flask app and JSON API

## Task index

- Add or change a table column: `COLUMNS` (and `GLM_UNITS`) in `ppedit/case.py`; validation in `Case.validate`; `ppedit/_test/test_case.py`
- Change the extended (result) columns shown after a solve: `RESULT_COLUMNS` and `_extended` in `ppedit/case.py`; `extendedColumns`/`renderTable` in `ppedit/static/app.js`; export in `Editor.extended` (`ppedit/server.py`) and `dump_rows` (`ppedit/_tableio.py`); `test_solve_extended_columns` in `ppedit/_test/test_case.py`, `test_server_export_extended` in `ppedit/_test/test_tableio.py`
- Add a validation rule: `Case.validate`; test in `test_validate_finds_errors`
- Support another GLM object: `_parse_glm`/`_dump_glm` in `ppedit/case.py`; add it to `ppedit/_test/data/case3.glm` and its README
- Change area handling: `COLUMNS["areas"]`, `Case.validate` and `Case._area_summary` in `ppedit/case.py`; `areaRegions`/`convexHull`/`traceOutline`, area grouping in `layout`/`onelineLayout` in `ppedit/static/app.js`; `ppedit/_test/test_areas.py`
- Change the cvxopf solvers: `OPF_SOLVERS` and `Case.solve` in `ppedit/case.py`; `ppedit/_cvxopf.py`; `ppedit/_test/test_cvxopf.py`
- Change time series or multistep OPF: `Case.set_series`/`set_series_panel`/`series_values`/`at_step`/`_series_input` and `Case.solve` in `ppedit/case.py`; `runopf(series=...)` in `ppedit/_cvxopf.py`; `read_series`/`dump_series` in `ppedit/_tableio.py`; `/api/series*` in `ppedit/server.py`; `renderSeries`, `stepView` in `ppedit/static/app.js`; `ppedit/_test/test_series.py`
- Change storage: `COLUMNS["storage"]`, the edit methods, `_dump_glm_storage` and `_series_input` in `ppedit/case.py`; `_storage_constraints` and related helpers in `ppedit/_cvxopf.py`; `storageBlock` in `ppedit/static/app.js`; `ppedit/_test/test_storage.py`
- Change DC line handling: `COLUMNS["dcline"]`, `COST_TABLES` and `Case.solve` in `ppedit/case.py`; solver callbacks in `ppedit/_dcline.py`; `ppedit/_test/test_dcline.py`
- Change WECC 240 2020 areas (EIA-930 balancing authorities): `examples/wecc240/wecc240_ba.csv`, then `python3 examples/wecc240/wecc240_areas.py`; see `examples/wecc240/README.md`
- Change WECC 240 generator costs: `examples/wecc240/wecc240_gentypes.csv` (or rederive it with `examples/wecc240/wecc240_gentypes.py`), then `python3 examples/wecc240/build_wecc240_2018.py`; see `examples/README.md`
- Change PSS/E `.raw` input: `ppedit/_psse.py` (conversion), `INPUT_FORMATS`/`Case.load` in `ppedit/case.py`; `ppedit/_test/test_psse.py` and `ppedit/_test/data/psse_v*.raw`
- Change table data import/export: `ppedit/_tableio.py` (file formats), `Case.import_rows` in `ppedit/case.py`, `/api/table/*` in `ppedit/server.py`; `importRows`/`exportRows` in `ppedit/static/app.js`; `ppedit/_test/test_tableio.py`
- Change solve progress or the Stop button: `ppedit/_solveproc.py`; `_ipopt_progress` and `progress` of `runopf` in `ppedit/_cvxopf.py`; `job` of `Case.solve`; `/api/solve/progress`, `/api/solve/stop` in `ppedit/server.py`; `watchSolve`/`busyRefresh` in `ppedit/static/app.js`; `ppedit/_test/test_solveproc.py`
- Add an API route: `ppedit/server.py` (and its docstring API list); `ppedit/_test/test_server.py`; call it from `ppedit/static/app.js`
- Change the UI: `ppedit/static/{index.html,style.css,app.js}`
- Change geodata handling or map layers: `Case.load_geodata`/`_geo_*` helpers in `ppedit/case.py`; `geoLayout`/`renderMap` in `ppedit/static/app.js`; `ppedit/_test/test_geodata.py`
- Add a CLI command or option: `ppedit/cli.py`, `ppedit/__init__.py` Syntax section, `README.md`
- Refresh the PYPOWER example cases: `python3 examples/import_pypower_cases.py` (after upgrading `pypower`)
- Change the Agent tab sessions (tools, data sources, models, API key): `ppedit/claude.py`; `/api/claude*` routes in `ppedit/server.py`; claude section and `renderAgentSettings` of `ppedit/static/app.js`; `ppedit/_test/test_claude.py`
- Change a design decision or resolve an open question: `DESIGN.md` (never renumber decisions)
- Release: `pyproject.toml` version; see the eudoxys-package skill checklist

## Package

| Path | Purpose | Notes |
|---|---|---|
| `ppedit/__init__.py` | package docs, re-exports | pdoc landing page |
| `ppedit/cli.py` | CLI `main()`: serve, convert, check | entry point `ppedit`; tested by `_test/test_cli.py` |
| `ppedit/case.py` | `Case`: tables, `.py`/`.json`/`.glm` I/O (and `.raw` input), edits, validation, PF/OPF | tested by `_test/test_case.py` and its doctest |
| `ppedit/_psse.py` | PSS/E RAW reader (revisions 23–35), after MATPOWER `psse2mpc` | private; read only; tested by `_test/test_psse.py` |
| `ppedit/_cvxopf.py` | cvxopf OPF backend for `Case.solve` (`CVXOPF-*` solvers): case in, `runopf`-layout results out | private; optional dependency; tested by `_test/test_cvxopf.py` (skipped without cvxopf) |
| `ppedit/_solveproc.py` | runs a `CVXOPF-*` solve in a child process with progress reports and stop (`SolveJob`, `run`) | private; tested by `_test/test_solveproc.py` |
| `ppedit/_tableio.py` | table and time series data import/export with pandas (`read_rows`, `dump_rows`, `read_series`, `dump_series`, `table_formats`) | private; tested by `_test/test_tableio.py` |
| `ppedit/_dcline.py` | DC line model for the PYPOWER solver (`userfcn` callbacks, as `pypower.toggle_dcline`) | private; tested by `_test/test_dcline.py` |
| `ppedit/claude.py` | `Sessions`: Claude API conversations with tools that edit the case, web and local data sources | tested by `_test/test_claude.py` with a fake client |
| `ppedit/_branding.py` | `APP_NAME` and `APP_MARK`: the editor name the browser page shows (default `ppedit`, issue #135) | small; edit to rename the page |
| `ppedit/server.py` | `create_app()`, `Editor` (undo/redo), JSON API, `about()` package metadata | tested by `_test/test_server.py` |
| `ppedit/static/index.html` | editor page layout | |
| `ppedit/static/style.css` | editor styles | |
| `ppedit/static/vendor/plotly-basic.min.js` | Plotly basic bundle (plotly.js-basic-dist-min 4.3.0), vendored unchanged for the Results step plot (decision #2) | third-party, minified ~1.2 MB; don't read or edit |
| `ppedit/static/vendor/plotly-LICENSE.txt` | Plotly's MIT license | third-party |
| `ppedit/static/app.js` | editor logic: tables, network diagram (simple, classic and one-line styles; force and geodata layouts with map layers; labels menu), results, issues, Agent sessions, settings | checked by hand (see `CLAUDE.md`) |
| `ppedit/.gitignore` | generated-output ignores | |

## Tests

| Path | Purpose | Notes |
|---|---|---|
| `ppedit/_test/README.md` | how to run tests | |
| `ppedit/_test/conftest.py` | `client` and `post` fixtures | |
| `ppedit/_test/test_*.py` | tests | all fast, no network |
| `ppedit/_test/data/README.md` | test data provenance | |
| `ppedit/_test/data/case9_dcline.py` | PYPOWER `t_case9_dcline` from cvxopf's test cases (4 DC lines, PWL costs) | curated, written by ppedit from cvxopf; used by `test_cvxopf.py` |
| `ppedit/_test/test_ieee118.py` | the Tracy 2021 study cases are current and as documented; the deficit day solves (cvxopf) | |
| `ppedit/_test/test_examples.py` | checks `examples/pypower/` | each `.glm` matches its `.py`; `case9_dcline` results against PYPOWER and cvxopf |
| `ppedit/_test/data/case3.glm` | 3-bus GLM test model | curated, hand-written |
| `ppedit/_test/data/psse_v33.raw` | 4-bus PSS/E revision 33 test case (loads, shunts, 2- and 3-winding transformers, DC line) | curated, hand-written; used by `test_psse.py` |
| `ppedit/_test/data/psse_v35.raw` | 3-bus PSS/E revision 35 test case (system-wide data, `@!` headers, switching devices) | curated, hand-written; used by `test_psse.py` |
| `ppedit/_test/data/IEEE_*_bus.raw` | IEEE 14, 24, 30, 39, 57, 118 and 300-bus cases as PSS/E revision 33 | added by the maintainer; used by `test_psse.py`; IEEE_300 ~135 kB |
| `ppedit/_test/data/case9_dcline_pypower_reference.json` | PYPOWER OPF solution of `case9_dcline` | copied from cvxopf; used by `test_examples.py` |
| `ppedit/_test/data/case9_geodata.csv` | synthetic `case9` bus locations | curated, hand-written; used by `test_geodata.py` |

## Examples

| Path | Purpose | Notes |
|---|---|---|
| `examples/import_pypower_cases.py` | regenerates `examples/pypower/` | maintenance script |
| `examples/pypower/README.md` | provenance, conversion notes, case table | table generated by the script |
| `examples/pypower/LICENSE` | PYPOWER BSD license | copied from the `pypower` package |
| `examples/pypower/AUTHORS` | PYPOWER authors | copied from the `pypower` package |
| `examples/pypower/case*.py` | PYPOWER built-in cases, unchanged (except `case9_dcline.py`) | copied; don't edit; case300.py ~60 kB |
| `examples/pypower/case9_dcline.py` | cvxopf's `case9_dcline` with a 24-step load series (`series` key) | imported from cvxopf; kept by the script; tested by `test_examples.py` |
| `examples/pypower/LICENSE-cvxopf` | cvxopf BSD license | applies to `case9_dcline.py` |
| `examples/pypower/case*.glm` | the same cases as `module pypower` GLM models | generated; don't edit; case300.glm ~250 kB, use `head` |
| `examples/README.md` | summary of the example folders | |
| `examples/ieee118/README.md` | how to reproduce the IEEE PES GM 2027 Case118 experiments with cvxopf, and what this folder holds | instructions from the paper's reproduction archive, with a section for this folder |
| `examples/ieee118/9q9wtp_gen_and_load.csv` | modeled Tracy, CA demand, utility solar, wind and distributed solar profiles (source data of the experiments) | from the reproduction archive; ~2.8 MB, use `head`; hash in `SHA256SUMS` |
| `examples/ieee118/case118.py` | PYPOWER IEEE 118-bus case: starting point of the study cases | same as `examples/pypower/case118.py`; don't edit |
| `examples/ieee118/pglib_opf_case118_ieee.m` | PGLib-OPF v23.07 IEEE 118-bus case used by the experiments (network limits and costs) | from cvxopf (PGLib revision dc6be4b2); ~80 kB, use `head`; don't edit |
| `examples/ieee118/LICENSE-pglib` | PGLib-OPF license (data CC BY 4.0) | applies to `pglib_opf_case118_ieee.m` and the study cases |
| `examples/ieee118/build_tracy2021.py` | writes the study case files from the CSV, `case118.py` and the PGLib case; `cvxopf_inputs` turns a case back into the study's cvxopf device model | maintenance script; `annual` (~42 MB) only on request |
| `examples/ieee118/check_tracy2021.py` | checks the study cases against `pes2027-reproduction-inputs.zip` (inputs, frozen model inputs, window and year solves) | needs the archive and cvxopf; `--year` a few minutes, `--year-ppedit` ~30 min |
| `examples/ieee118/case118_tracy2021_*.py` | the six 24-hour study cases (series, storage, renewables, shedding) | written by `build_tracy2021.py`; don't edit; ~200 kB each, use `head`; tested by `_test/test_ieee118.py` |
| `examples/ieee118/SHA256SUMS` | SHA-256 of the ten reproduction input files, by cvxopf clone path | |
| `examples/ieee118/install_inputs.py` | installs the inputs into a cvxopf clone and checks their hashes | three large records read from the archive ZIP |
| `examples/ieee118/experiments/**` | six small study records the cvxopf code checks, at their cvxopf clone paths | byte copies from the archive; don't edit (hash-checked) |
| `examples/wecc240/README.md` | provenance of the WECC 240 examples | |
| `examples/wecc240/wecc240_case.raw` | WECC 240-bus case as PSS/E revision 34 (see `examples/wecc240/README.md`) | from NREL (see file header); ~220 kB, use `head`; tested by `_test/test_psse.py` |
| `examples/wecc240/wecc240_bus.csv` | WECC 240 bus index: row, PSS/E bus number, name, PYPOWER `bus_i` | from NREL |
| `examples/wecc240/wecc240_cost.csv` | per-generator cost rows (`id` = bus name + PSS/E ID; `model,startup,shutdown,cost`) | costs copied from `wecc240_gentypes.csv` by type |
| `examples/wecc240/wecc240_gentypes.csv` | polynomial costs (`c2,c1,c0`) by generator type (the PSS/E generator ID) | written by `wecc240_gentypes.py` |
| `examples/wecc240/wecc240_gentypes.py` | derives `wecc240_gentypes.csv` from NREL's WECC 240 scheduling workbook | maintenance script; needs `openpyxl` |
| `examples/wecc240/wecc240_2011.py` | the 2011 WECC 240-bus case (`wecc240_case.raw` converted by ppedit) with geodata; the Pacific DC Intertie and Intermountain HVDC lines as `dcline` rows (3.5% losses, zero `dclinecost`) | written by ppedit, DC lines edited (see `examples/README.md`); ~90 kB, use `head` |
| `examples/wecc240/wecc240_2018.py` | `wecc240_2011.py` with generator costs by type from `wecc240_gentypes.csv`, branch `rateA` from `rateB`/`rateC`, voltage fixes (`Vg` 1.08 pu at five generator buses, shunt reactors at eight buses) and `rateA` raised to a 20% margin on the 13 most loaded branches | written by `build_wecc240_2018.py`; don't edit; ~95 kB, use `head` |
| `examples/wecc240/build_wecc240_2018.py` | builds `wecc240_2018.py` from `wecc240_2011.py`, `wecc240_gentypes.csv`, `wecc240_cost.csv` (generator types) and `wecc240_bus.csv` | maintenance script |
| `examples/wecc240/wecc240_2020.py` | the 2020 WECC 240-bus case with geodata, storage (`wecc240_storage.csv`; its generators in service, `Pmax` = `Smax`) and the August 2020 series (loaded by `build_wecc240_2020.py`); areas are the EIA-930 balancing authorities (set by `wecc240_areas.py`) | written by ppedit, areas set by `wecc240_areas.py`; ~165 kB, use `head` |
| `examples/wecc240/wecc240_ba.csv` | EIA-930 balancing authority of each WECC 240 bus (`BUS_I,NAME,BA,NOTE`) | curated by hand (issue #90) |
| `examples/wecc240/wecc240_2020_real_load.csv` | series file of bus `Pd` by hour for August 2020 (`bus.Pd.N` columns), the `real_load` series of `wecc240_2020.py` | data; ~745 lines, use `head` |
| `examples/wecc240/wecc240_2020_reactive_load.csv` | series file of bus `Qd` by hour for August 2020 (`bus.Qd.N` columns), the `reactive_load` series of `wecc240_2020.py`: the real load at the case bus power factors | written by `build_wecc240_2020.py`; data; ~745 lines, use `head` |
| `examples/wecc240/wecc240_netload.csv.gz` | hourly net load by WECC 240 node geohash, 2018-2022 (113 node columns) | data; ~20 MB, don't read |
| `examples/wecc240/wecc240_generation.csv.gz` | hourly generator `Pmax` panel for 2020 for the `wecc240_2020.py` generator rows (columns are gen rows from 1; none for the storage generators; August is the case's `generation` series) | written by `build_wecc240_generation.py`; ~10 MB, don't read |
| `examples/wecc240/build_wecc240_2020.py` | writes `wecc240_2020_reactive_load.csv` from the real load at the case power factors, loads `wecc240_storage.csv` and the `real_load`, `reactive_load` and `generation` series into `wecc240_2020.py` and checks them (`--check`: checks only) | maintenance script; saves the case in place |
| `examples/wecc240/wecc240_storage.csv` | `storage` rows for the `wecc240_2020.py` generators with negative `Pmin` (43 rows: 40 batteries, 4 h; pumped hydro gen rows 3, 5, 6, 24 h; half full at start and end) | data; import into the storage table |
| `examples/wecc240/build_wecc240_generation.py` | builds `wecc240_generation.csv.gz` from the eudoxys/generation WECC 240 node files and the wecc240 county-node map | maintenance script; needs a checkout of `eudoxys/generation` `data/wecc` |
| `examples/wecc240/wecc240_areas.py` | sets the areas of a WECC 240 case (default `wecc240_2020.py`) from `wecc240_ba.csv`, in place | maintenance script |
| `examples/wecc240/wecc240_case.py` | WECC 240-bus case without geodata | written by ppedit; ~70 kB, use `head` |
| `examples/wecc240/wecc240_geodata.csv` | bus locations for the WECC 240-bus case (`BUS_I,LAT,LON` plus `GEOHASH,NAME,GEN,LOAD,BA,COUNTY`) | for `--geodata` or **Map ▸ Load CSV…** |
| `examples/wecc240/wecc240_map.py` | WECC 240-bus case with its `geodata` and `geotags` | written by ppedit; ~105 kB, use `head` |
| `examples/wecc240/wecc240_map.json` | the same case as JSON | written by ppedit; ~230 kB, use `head` |
| `examples/wecc240/wecc240_map.glm` | the same case as a `module pypower` GLM model (keeps bus latitude/longitude) | written by ppedit; ~380 kB, use `head` |

## Repository

| Path | Purpose | Notes |
|---|---|---|
| `README.md` | user overview | |
| `CLAUDE.md` | assistant guidance | |
| `DESIGN.md` | design decisions, contracts, open questions | update with any decision change |
| `MANIFEST.md` | this file | |
| `CONTRIBUTING.md` | contributor guide | approved-issue rule |
| `TODO.md` | roadmap | |
| `pyproject.toml` | packaging | version here; static files in package-data |
| `requirements.txt` | dependencies | |
| `Makefile` | `make docs`, `make test` | |
| `LICENSE` | MIT | |
| `.gitignore` | | |
| `.gitattributes` | | |
| `.github/workflows/*.yaml` | CI: tests with coverage report, docs and coverage site, approved-issue check, issue assignment | |
| `.github/check_manifest.py` | checks this file | |

## Don't read

`docs/` (generated), `.venv/`, `*.egg-info/`, `ppedit/static/vendor/` (vendored third-party JS, minified).
