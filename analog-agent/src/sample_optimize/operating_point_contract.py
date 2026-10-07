"""Stable, SI-unit columns for one DC snapshot of every MOS instance.

The observation DTO keeps the original feasibility fields.  SQL and CSV use
explicit units and signed terminal voltages; model-normalized BSIM voltages
and the original polarity-normalized voltages have separate columns.
"""
from __future__ import annotations

import math


OP_SCHEMA_VERSION = 2
CAPACITANCE_FIELDS = (
    "cgg", "cgs", "cgd", "cgb", "cdg", "cdd", "cds", "cdb",
    "csg", "csd", "css", "csb", "cbg", "cbd", "cbs", "cbb",
    "capbd", "capbs",
)
NATIVE_FIELDS = ("id", "gm", "gds", "gmbs", "vth", "vdsat", "vgs", "vds", "vbs") + CAPACITANCE_FIELDS
DEVICE_FIELD_SOURCES = (
    ("id_a", "id"), ("gm_s", "gm"), ("gds_s", "gds"), ("gmbs_s", "gmbs"),
    ("vth_v", "vth"), ("vdsat_v", "vdsat"),
    ("vd_v", "vd_v"), ("vg_v", "vg_v"), ("vs_v", "vs_v"), ("vb_v", "vb_v"),
    ("vgs_v", "vgs_raw_v"), ("vds_v", "vds_raw_v"), ("vbs_v", "vbs_raw_v"),
    ("model_vgs_v", "model_vgs_v"), ("model_vds_v", "model_vds_v"), ("model_vbs_v", "model_vbs_v"),
    ("vgs_normalized_v", "vgs_v"), ("vds_normalized_v", "vds_v"),
    ("vbs_normalized_v", "vbs_normalized_v"), ("reverse_body_bias_v", "reverse_body_bias_v"),
    ("gmid_v_inv", "gmid_v_inv"), ("intrinsic_gain_v_v", "intrinsic_gain_v_v"),
    ("saturation_margin_v", "saturation_margin_v"),
    ("w_um", "w_um"), ("l_um", "l_um"), ("multiplicity", "multiplicity"),
) + tuple((f"{name}_f", name) for name in CAPACITANCE_FIELDS)
DEVICE_FIELDS = tuple(column for column, _ in DEVICE_FIELD_SOURCES)


def finite_or_none(value):
    if value is None:
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def device_values(fields):
    """Never manufacture missing historical values or discard a negative cap."""
    return tuple(finite_or_none(fields.get(source)) for _, source in DEVICE_FIELD_SOURCES)
