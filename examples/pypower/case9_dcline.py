"""
Power flow data for case9_dcline test case, with a load time series.

Imported from cvxopf (https://github.com/cvxgrp/cvxopf, file
src/cvxopf/testcases/case9_dcline.py at commit fd4d279, 2026-11-18; the
same at 8c40598), which adapts PYPOWER's DC line test case
pypower/t/t_case9_dcline.py:
https://rwl.github.io/PYPOWER/api/pypower.case9_dcline-module.html

The case data is unchanged from cvxopf. Added here is ppc["series"], a
ppedit time series of case values for multistep OPF: 24 hourly steps of the
active (bus.Pd, MW) and reactive (bus.Qd, MVAr) demand of the loaded buses
5, 7 and 9. Every step holds the base-case demand, so each step of a
multistep solve reproduces the single-period case. PYPOWER ignores the key.
"""

import numpy as np


def case9_dcline() -> dict:
    """
    Return power flow data for the case9_dcline test case.

    Returns
    -------
    ppc : dict
        MATPOWER-format case dict with keys:
        version, baseMVA, bus, gen, branch, areas, gencost, dcline, dclinecost.

    Network summary
    ---------------
    Buses      : 9
    Generators : 3
    Branches   : 9
    """
    ppc = {"version": "2"}

    ppc["baseMVA"] = 100

    # bus_i  type  Pd  Qd  Gs  Bs  area  Vm  Va  baseKV  zone  Vmax  Vmin
    ppc["bus"] = np.array(
        [
            [1, 3, 0, 0, 0, 0, 1, 1, 0, 345, 1, 1.1, 0.9],
            [2, 2, 0, 0, 0, 0, 1, 1, 0, 345, 1, 1.1, 0.9],
            [30, 2, 0, 0, 0, 0, 1, 1, 0, 345, 1, 1.1, 0.9],
            [4, 1, 0, 0, 0, 0, 1, 1, 0, 345, 1, 1.1, 0.9],
            [5, 1, 90, 30, 0, 0, 1, 1, 0, 345, 1, 1.1, 0.9],
            [6, 1, 0, 0, 0, 0, 1, 1, 0, 345, 1, 1.1, 0.9],
            [7, 1, 100, 35, 0, 0, 1, 1, 0, 345, 1, 1.1, 0.9],
            [8, 1, 0, 0, 0, 0, 1, 1, 0, 345, 1, 1.1, 0.9],
            [9, 1, 125, 50, 0, 0, 1, 1, 0, 345, 1, 1.1, 0.9],
        ]
    )

    # bus  Pg  Qg  Qmax  Qmin  Vg  mBase  status  Pmax  Pmin  ...
    ppc["gen"] = np.array(
        [
            [1, 0, 0, 300, -300, 1, 100, 1, 250, 90, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [
                2,
                163,
                0,
                300,
                -300,
                1,
                100,
                1,
                300,
                10,
                0,
                200,
                -20,
                20,
                -10,
                10,
                0,
                0,
                0,
                0,
                0,
            ],
            [
                30,
                85,
                0,
                300,
                -300,
                1,
                100,
                1,
                270,
                10,
                0,
                200,
                -30,
                30,
                -15,
                15,
                0,
                0,
                0,
                0,
                0,
            ],
        ]
    )

    # fbus  tbus  r  x  b  rateA  rateB  rateC  ratio  angle  status  angmin  angmax
    ppc["branch"] = np.array(
        [
            [1, 4, 0, 0.0576, 0, 0, 250, 250, 0, 0, 1, -360, 2.48],
            [4, 5, 0.017, 0.092, 0.158, 0, 250, 250, 0, 0, 1, -360, 360],
            [5, 6, 0.039, 0.17, 0.358, 150, 150, 150, 0, 0, 1, -360, 360],
            [30, 6, 0, 0.0586, 0, 0, 300, 300, 0, 0, 1, -360, 360],
            [6, 7, 0.0119, 0.1008, 0.209, 40, 150, 150, 0, 0, 1, -360, 360],
            [7, 8, 0.0085, 0.072, 0.149, 250, 250, 250, 0, 0, 1, -360, 360],
            [8, 2, 0, 0.0625, 0, 250, 250, 250, 0, 0, 1, -360, 360],
            [8, 9, 0.032, 0.161, 0.306, 250, 250, 250, 0, 0, 1, -360, 360],
            [9, 4, 0.01, 0.085, 0.176, 250, 250, 250, 0, 0, 1, -2, 360],
        ]
    )

    ppc["areas"] = np.array(
        [
            [1, 5],
        ]
    )

    # model  startup  shutdown  n  coefficients (highest power first) ... c0
    ppc["gencost"] = np.array(
        [
            [1, 0, 0, 4, 0, 0, 100, 2500, 200, 5500, 250, 7250],
            [2, 0, 0, 2, 24.035, -403.5, 0, 0, 0, 0, 0, 0],
            [1, 0, 0, 3, 0, 0, 200, 3000, 300, 5000, 0, 0],
        ]
    )

    # fbus  tbus  status  Pf  Pt  Qf  Qt  Vf  Vt  Pmin  Pmax  QminF  QmaxF  QminT  QmaxT  loss0  loss1
    ppc["dcline"] = np.array(
        [
            [30, 4, 1, 10, 8.9, 0, 0, 1.01, 1, 1, 10, -10, 10, -10, 10, 1, 0.01],
            [7, 9, 1, 2, 1.96, 0, 0, 1, 1, 2, 10, 0, 0, 0, 0, 0, 0],
            [5, 8, 0, 0, 0, 0, 0, 1, 1, 1, 10, -10, 10, -10, 10, 0, 0],
            [5, 9, 1, 10, 9.5, 0, 0, 1, 0.98, 0, 10, -10, 10, -10, 10, 0, 0.05],
        ]
    )

    # model  startup  shutdown  n  coefficients (highest power first) ... c0
    ppc["dclinecost"] = np.array(
        [
            [2, 0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [2, 0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [2, 0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [2, 0, 0, 2, 7.3, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        ]
    )

    ## time series of case values (multistep OPF; ppedit)
    ppc["series"] = [
        {
            "name": "load",
            "delta": 1,
            "timed": False,
            "index": ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14", "15", "16", "17", "18", "19", "20", "21", "22", "23", "24"],
            "columns": ["bus.Pd.5", "bus.Pd.7", "bus.Pd.9", "bus.Qd.5", "bus.Qd.7", "bus.Qd.9"],
            "values": [
                [90, 100, 125, 30, 35, 50],
                [90, 100, 125, 30, 35, 50],
                [90, 100, 125, 30, 35, 50],
                [90, 100, 125, 30, 35, 50],
                [90, 100, 125, 30, 35, 50],
                [90, 100, 125, 30, 35, 50],
                [90, 100, 125, 30, 35, 50],
                [90, 100, 125, 30, 35, 50],
                [90, 100, 125, 30, 35, 50],
                [90, 100, 125, 30, 35, 50],
                [90, 100, 125, 30, 35, 50],
                [90, 100, 125, 30, 35, 50],
                [90, 100, 125, 30, 35, 50],
                [90, 100, 125, 30, 35, 50],
                [90, 100, 125, 30, 35, 50],
                [90, 100, 125, 30, 35, 50],
                [90, 100, 125, 30, 35, 50],
                [90, 100, 125, 30, 35, 50],
                [90, 100, 125, 30, 35, 50],
                [90, 100, 125, 30, 35, 50],
                [90, 100, 125, 30, 35, 50],
                [90, 100, 125, 30, 35, 50],
                [90, 100, 125, 30, 35, 50],
                [90, 100, 125, 30, 35, 50]
            ],
        },
    ]

    return ppc
