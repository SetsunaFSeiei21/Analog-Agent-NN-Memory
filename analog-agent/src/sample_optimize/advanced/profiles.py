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
