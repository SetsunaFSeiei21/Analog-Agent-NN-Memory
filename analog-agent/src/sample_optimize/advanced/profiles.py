from __future__ import annotations

import re
from dataclasses import dataclass

from ...circuit_ir.schema import DeviceType
from .config import grid


@dataclass(frozen=True)
class Group:
    width: str
    length: str
    reference: str
    members: tuple[str, ...]
    # A width constraint need not imply one length constraint (Wilson mirrors).
    # Entries follow members; length remains the reference transistor's length.
    member_lengths: tuple[str, ...] = ()


# Reference transistors, including the diode element of self-cascode bias stacks.
REFERENCES = {
    "5t_ota": ["XMBIAS", "XMN_INP", "XMP_DIODE"],
    "two_stage_opamp_otaf": ["XMBIAS", "XMN_INN", "XMP_DIODE", "XMP_STAGE2"],
    "two_stage_folded_opamp": ["XMP_BIAS_REF", "XMN_BIAS_REF", "XMP_PCAS_DIODE",
        "XMN_NCAS_DIODE", "XMP_INP", "XMP_FOLD_N", "XMP_CAS_N", "XMN_CAS_N", "XMP_STAGE2"],
    # "Opamp0": ["XPM7", "XNM4", "XNM5", "XPM4", "XNM1", "XPM1", "XPM2"],
    "Opamp0": [
        "XPM7",
        "XNM4",
        "XNM6",
        "XPM4",
        "XNM1",
        "XPM1",
        "XPM2",
    ],
    "Opamp1": ["XNM7", "XPM8", "XPM11", "XNM9", "XM11", "XM10", "XM9", "XM1", "XM7"],
    # One reference per independent W1..W8. Multiplicity expressions remain
    # in the netlist; XNM2 and XPM3 share widths with existing references.
    "loOpamp116": ["XNM0", "XNM1", "XNM8", "XNM3",
                  "XNM7", "XPM0", "XPM1", "XPM2"],
    # One reference per independent W1..W8; XNM1 carries IBIAS_A.
    "ltOpamp114": ["XNM1", "XPM5", "XNM2", "XNM13",
                    "XNM11", "XPM6", "XPM15", "XNM4"],
}
SIGNAL = {
    "5t_ota": ["XMTAIL", "XMN_INP", "XMN_INN", "XMP_DIODE", "XMP_OUT"],
    "two_stage_opamp_otaf": ["XMTAIL", "XMN_INP", "XMN_INN", "XMP_DIODE", "XMP_MIRROR", "XMP_STAGE2", "XMN_STAGE2"],
    "two_stage_folded_opamp": ["XMP_INPUT_TAIL", "XMP_INP", "XMP_INN", "XMP_FOLD_P", "XMP_FOLD_N",
        "XMP_CAS_P", "XMP_CAS_N", "XMN_SINK_P", "XMN_SINK_N", "XMN_CAS_P", "XMN_CAS_N", "XMP_STAGE2", "XMN_STAGE2"],
    "Opamp0": [f"XPM{i}" for i in range(7)] + [f"XNM{i}" for i in range(4)],
    "Opamp1": ["XM10", "XM15", "XM9", "XM5", "XM16", "XM14", "XM8", "XM6", "XM13", "XM7", "XM1", "XM0", "XM11", "XM12", "XNM5"],
    "loOpamp116": ["XNM6", "XNM8", "XNM9", "XNM7", "XNM5", "XPM4", "XPM1", "XPM2"],
    "ltOpamp114": ["XNM10", "XNM12", "XNM13", "XNM11", "XNM9",
                    "XPM6", "XPM16", "XPM15", "XNM8"],
}

# Interior voltage seeds for the coupled KCL solver. These are starting guesses,
# not fixed constraints or claimed OPs. Values scale with the supply span.
NODE_SEEDS = {
    "5t_ota": {"N_BIAS": .6, "NTAIL": .2, "N1": 1.2},
    "two_stage_opamp_otaf": {"VBIAS": .6, "NTAIL": .2, "N1": 1.2, "OTA_OUT": 1.1, "COMP": 1.1},
    "two_stage_folded_opamp": {"VBP1": 1.2, "VB3": .6, "VB2": .7, "VB1": 1.1,
        "N_PBIAS": 1.7, "N_NBIAS": .1, "N_INPUT_TAIL": 1.5,
        "N_FOLD_P": .1, "N_FOLD_N": .1, "N_PCAS_P": 1.7, "N_PCAS_N": 1.7,
        "N_PCAS_GATE": 1.2, "OTA_OUT": 1.1, "COMP": 1.1},
    "Opamp0": {"NET1": 1.2, "NET2": .1, "VB2": .7, "VB3": .6, "NET9": 1.5,
        "NET18": 1.2, "NET24": .1, "NET27": .1, "NET34": .6, "NET35": 1.2},
    "Opamp1": {"VB1": .7, "VB2": 1.1, "VB3": .6, "NET1": .2, "NET2": 1.2,
        "NET3": 1.7, "NET4": 1.2, "NET5": .1, "NET6": 1.2, "NET11": .6,
        "NET22": .1, "NET23": .1, "NET24": 1.7, "NET25": 1.7, "NET26": 1.7, "NET27": 1.7},
    "loOpamp116": {"VBIAS": .85, "N0": .15, "N1": .15, "N2": .45,
                 "N3": .25, "N4": .45, "N5": 1.0, "N6": .85,
                 "N7": 1.15, "N8": 1.35},
    "ltOpamp114": {"VBIAS": .5, "N0": .85, "N1": .2, "N2": .5,
                    "N3": 1.2, "N4": .4, "N5": 1.2, "N6": .4,
                    "N7": 1.2},
}


def _parameter(expression):
    text = expression.text.strip("{}'\" ")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", text):
        raise ValueError(f"gm/ID profile requires a direct shared W/L parameter, got {text}")
    return text.upper()


def make_profile(name, circuit, gmid_config):
    if name not in REFERENCES:
        raise ValueError(f"No engineering gm/ID profile for {name}; supported: {list(REFERENCES)}")
    devices = {d.name.upper(): d for d in circuit.devices}
    mos = [d for d in circuit.devices if d.device_type in (DeviceType.NMOS, DeviceType.PMOS)]
    groups = []
    for ref in REFERENCES[name]:
        if ref not in devices:
            raise ValueError(f"{name}: profile reference {ref} is missing; review changed topology")
        device = devices[ref]
        width, length = (_parameter(device.parameters[k]) for k in ("W", "L"))
        members = tuple(d.name.upper() for d in mos if _parameter(d.parameters["W"]) == width)
        member_lengths = tuple(_parameter(devices[m].parameters["L"]) for m in members)
        groups.append(Group(width, length, ref, members, member_lengths))
    if len({g.width for g in groups}) != len(groups) or set(m for g in groups for m in g.members) != set(d.name.upper() for d in mos):
        raise ValueError("Profile must cover every MOS exactly once by shared sizing group")
    if set(SIGNAL[name]) - devices.keys():
        raise ValueError("Signal-path profile no longer matches topology")
    overrides = gmid_config.get("group_gmid_overrides") or {}
    # Optional flat group overrides, or circuit -> partial group override objects.
    flat = {k.upper(): v for k, v in overrides.items() if not isinstance(v, dict)}
    unknown_circuits = {k for k, v in overrides.items() if isinstance(v, dict)} - REFERENCES.keys()
    if unknown_circuits:
        raise ValueError(f"Unknown gm/ID topology overrides: {unknown_circuits}")
    flat.update({k.upper(): v for k, v in overrides.get(name, {}).items()})
    if set(flat) - {g.width for g in groups}:
        raise ValueError(f"Unknown gm/ID groups for {name}: {set(flat) - {g.width for g in groups}}")
    targets = {g.width: grid(flat.get(g.width, gmid_config["default_range"])) for g in groups}
    if any(axis[0] <= 0 for axis in targets.values()):
        raise ValueError("gm/ID group targets must be positive")
    return tuple(groups), tuple(SIGNAL[name]), targets


# Opamp2: seven shared width groups; XNM7 is the unit-current bias device.
REFERENCES["Opamp2"] = [
    "XPM6", "XNM7", "XNM5", "XNM0", "XNM3", "XPM3", "XPM1",
]
SIGNAL["Opamp2"] = [
    "XNM4", "XNM0", "XNM1", "XNM3", "XNM2",
    "XPM3", "XPM0", "XPM1", "XPM2",
]
NODE_SEEDS["Opamp2"] = {
    "NET6": 1.25, "VB1": 0.8, "NET5": 0.1, "NET3": 0.5,
    "NET1": 0.15, "NET16": 0.3, "NET18": 0.3,
    "NET4": 0.8, "NET19": 1.3, "NET2": 1.3,
}

# Opamp3: complementary-input revision.
# One reference transistor per independent W1..W8 group.
REFERENCES["Opamp3"] = [
    "XPM11",         # W1/L1: XPM11, XPM10
    "XNM7",          # W2/L2: XNM7, XNM5
    "XPM2",          # W3/L3: XPM2, XPM3
    "XPM0",          # W4/L4: XPM0, XPM1
    "XNM12",         # W5/L5: XNM12, XNM13
    "XNM14",         # W6/L6: XNM14, XNM15
    "XPM8",          # W7/L7: XPM8, XPM7
    "XNM_BIAS1_REF",  # W8/L8: XNM_BIAS1_REF, XNM_BIAS1_OUT
]

# Both reference branches are input-driven.
SIGNAL["Opamp3"] = [
    "XPM11", "XPM10", "XNM7", "XNM5",
    "XPM2", "XPM3", "XPM0", "XPM1",
    "XNM12", "XNM13", "XNM14", "XNM15",
    "XPM8", "XPM7", "XNM_BIAS1_REF", "XNM_BIAS1_OUT",
]

# Initial voltage guesses at 1.8 V, scaled by the solver.
# These are not fixed voltages or verified operating points.
NODE_SEEDS["Opamp3"] = {
    "IB1": 1.70,
    "IB2": 0.10,
    "NET1": 1.10,
    "NET2": 1.10,
    "NET16": 0.30,
    "NET17": 0.85,
    "NET23": 1.25,
    "NET24": 0.70,
    "NET34": 0.45,
    "NET42": 0.45,
    "NET44": 0.30,
    "NET45": 1.25,
}

# Opamp4: one reference per independent W1..W6 group.
REFERENCES["Opamp4"] = [
    "XPM0",   # W1/L1: XPM0, XPM1, XPM3
    "XNM7",   # W2/L2: XNM7, XNM8
    "XNM5",   # W3/L3: XNM5, XNM6
    "XPM9",   # W4/L4: XPM9, XPM10
    "XPM4",   # W5/L5: XPM4, XPM5
    "XNM11",  # W6/L6: XNM11
]

# Devices subject to signal-path operating-region checks.
SIGNAL["Opamp4"] = [
    "XNM8",            # Tail-current source
    "XNM5", "XNM6",    # Input differential pair
    "XPM9", "XPM10",   # PMOS current-mirror load
    "XPM4", "XPM5",    # Additional PMOS current sources
    "XNM11", "XPM3",   # Output stage
]

# Initial voltage guesses at 1.8 V, relative to VSS.
# The solver scales these values with the supply span.
# These are not fixed voltages or verified DC operating points.
NODE_SEEDS["Opamp4"] = {
    "IB1": 1.20,
    "NET11": 0.50,
    "NET21": 0.20,
    "NET22": 1.10,
    "NET29": 1.10,
    "NET1": 1.10,
}

# Six independent shared W/L groups.
REFERENCES["Leung_NMCNR"] = [
    "XPM0",   # W1/L1: PMOS bias and first-stage mirror, 9 devices
    "XPM9",   # W2/L2: PMOS input pair, 2 devices
    "XPM10",  # W3/L3: second-stage PMOS, 1 device
    "XNM14",  # W4/L4: NMOS bias and folded network, 9 devices
    "XNM21",  # W5/L5: second-stage NMOS mirror, 2 devices
    "XNM23",  # W6/L6: output-stage NMOS, 1 device
]

SIGNAL["Leung_NMCNR"] = [
    "XPM4", "XPM8", "XPM9",
    "XNM19", "XNM20", "XNM15", "XNM16",
    "XPM5", "XPM6",
    "XPM10", "XNM21", "XNM22", "XPM7",
    "XNM23", "XPM11",
]

# Initial guesses near the checked nominal point at 1.8 V.
# These are solver starting values, not fixed voltage constraints.
NODE_SEEDS["Leung_NMCNR"] = {
    "NET13": 1.288,
    "VB3":   0.568,
    "VB4":   0.510,
    "NET54": 0.061,
    "NET56": 0.061,
    "DM_1":  0.510,
    "NET31": 1.123,
    "DM_2":  0.097,
    "NET63": 0.100,
    "VOUTN": 1.324,
    "NET50": 1.443,
    "NET43": 0.482,
    "NET49": 0.443,
    "NET44": 0.721,
}

# Fan_SMC: seven independent shared W/L groups.
REFERENCES["Fan_SMC"] = [
    "XPM0",   # W1/L1: PMOS bias and first-stage mirror, 8 devices
    "XPM9",   # W2/L2: PMOS input pair, 2 devices
    "XPM10",  # W3/L3: second-stage PMOS, 1 device
    "XNM14",  # W4/L4: NMOS bias and folded network, 9 devices
    "XNM21",  # W5/L5: second-stage NMOS mirror, 2 devices
    "XNM23",  # W6/L6: output-stage NMOS, 1 device
    "XPM11",  # W7/L7: feedforward PMOS, 1 device
]

SIGNAL["Fan_SMC"] = [
    "XPM4", "XPM8", "XPM9",
    "XNM19", "XNM20", "XNM15", "XNM16",
    "XPM5", "XPM6",
    "XPM10", "XNM21", "XNM22", "XPM7",
    "XNM23", "XPM11",
]

# Initial guesses near the checked nominal point at 1.8 V.
# These are solver starting values, not fixed voltage constraints.
NODE_SEEDS["Fan_SMC"] = {
    "NET13": 1.288,
    "VB3":   0.568,
    "VB4":   0.510,
    "NET54": 0.061,
    "NET56": 0.061,
    "DM_1":  0.510,
    "NET31": 1.123,
    "DM_2":  0.097,
    "NET63": 0.100,
    "VOUTN": 1.324,
    "NET50": 1.443,
    "NET43": 0.482,
    "NET49": 0.440,
}

# 每个独立宽度 W1..W8 选一只代表管，顺序对应 W1..W8。
REFERENCES["Opamp5"] = [
    "XPM0", "XNM5", "XNM4", "XNM7",
    "XPM4", "XPM1", "XPM3", "XPM_GMID_AUX",
]

# 主电路中需要检查工作区的器件，不含辅助参考管。
SIGNAL["Opamp5"] = [
    "XNM9", "XNM7", "XNM8", "XPM4", "XPM5",
    "XPM1", "XPM2", "XPM3", "XNM11",
]

# gm/ID 求解器的节点电压初值，单位 V。
NODE_SEEDS["Opamp5"] = {
    "NET1": 1.18, "NET8": 0.55, "NET9": 1.19, "NET18": 0.20,
    "NET19": 1.16, "NET20": 0.96, "NET21": 1.17, "NET32": 0.92,
    "VOUT": 0.72,
}

# Append to src/sample_optimize/advanced/profiles.py.
# One reference per width, in W1..W9 order. XNM7_BIAS carries IBIAS_A.
REFERENCES["Opamp6"] = [
    "XNM7_BIAS", "XPM7_BIAS", "XNM9_BIAS", "XPM5_BIAS", "XNM8",
    "XPM2", "XNM14", "XNM12", "XPM6",
]

SIGNAL["Opamp6"] = [
    "XNM9", "XNM7", "XNM8", "XPM1", "XPM2", "XPM0",
    "XNM14", "XNM13", "XNM12", "XPM3", "XPM6",
]

# Nominal follower, TT, VDD=1.8 V, VCM=0.72 V. Solver initial guesses only.
NODE_SEEDS["Opamp6"] = {
    "VB1": 0.52, "NET3": 1.22, "NET4": 0.07, "NET26": 0.64,
    "NET1": 1.67, "NET35": 1.14, "NET17": 0.20, "NET11": 1.28,
    "NET21": 1.26, "NET8": 0.54, "NET38": 0.12, "NET40": 1.64,
    "VOUT": 0.71,
}

# ltOpamp114: one reference per independent W1..W9.
# XNM1 carries IBIAS_A.
REFERENCES["ltOpamp114"] = [
    "XNM1",         # W1: NMOS reference mirror
    "XPM5",         # W2: PMOS reference mirror
    "XNM2",         # W3: tail reference, tail, output sink
    "XNM13",        # W4: input differential pair
    "XNM11",        # W5: input cascode pair
    "XPM6",         # W6: first-stage PMOS mirror
    "XPM15",        # W7: second-stage PMOS
    "XNM11_BIAS",   # W8: upper cascode-bias diode
    "XNM12_BIAS",   # W9: lower cascode-bias pair
]

SIGNAL["ltOpamp114"] = [
    "XNM10",
    "XNM12",
    "XNM13",
    "XNM11",
    "XNM9",
    "XPM6",
    "XPM16",
    "XPM15",
    "XNM8",
]

# Initial voltage guesses at 1.8 V, not fixed voltage constraints.
# N1/NET1 and N2/NET2 are distinct nodes.
NODE_SEEDS["ltOpamp114"] = {
    "VBIAS": 0.52,
    "N0": 1.26,
    "N1": 0.53,
    "N2": 1.27,
    "N3": 0.70,
    "N4": 1.32,
    "N5": 0.70,
    "N6": 0.23,
    "N7": 1.27,
    "NET1": 0.57,
    "NET2": 0.04,
}

# Opamp7: one reference per independent W1..W9 group.
# Multiplicity expressions are read directly from the netlist.

REFERENCES["Opamp7"] = [
    "XNM_BIAS_REF",        # W1/L1
    "XPM_BIAS_VB1",        # W2/L2
    "XPM_BIAS_CAS_DIODE",  # W3/L3
    "XPM19",              # W4/L4
    "XNM17",              # W5/L5
    "XNM13",              # W6/L6
    "XNM0",               # W7/L7
    "XNM10",              # W8/L8
    "XPM_BIAS_REF",        # W9/L9
]

SIGNAL["Opamp7"] = [
    "XNM4", "XNM0", "XNM3",
    "XPM16", "XPM18", "XPM6", "XPM5",
    "XNM8", "XNM7", "XNM10", "XNM9",
]

# Solver starting guesses at 1.8 V.
# These are not fixed node voltages.
NODE_SEEDS["Opamp7"] = {
    "NET4": 0.61,
    "VB1": 1.13,
    "VB2": 0.92,
    "NET5": 1.67,
    "NET2": 1.13,
    "VB3": 0.57,
    "NET6": 1.11,
    "NET1": 0.52,
    "NET3": 1.17,
    "NET10": 0.18,
    "NET26": 1.56,
    "NET32": 1.56,
    "NET12": 0.75,
    "NET27": 0.53,
    "NET21": 0.53,
    "VOUT": 0.72,
}