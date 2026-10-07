from __future__ import annotations

import numpy as np
from scipy.optimize import least_squares, lsq_linear

from ...circuit_ir import resolve_circuit
from ...circuit_ir.schema import DeviceType
from .profiles import NODE_SEEDS, SIGNAL


class GmidSampler:
    """Sample gm/ID grids and size shared widths from current-density tables.

    Coupled KCL refinement is an optional strict proposal mode.

    This is a proposal model, not a substitute for the subsequent BSIM OP.
    L/M/I/passives come from the same physical grid as the other methods.
    """
    def __init__(self, circuit, domain, groups, targets, lut, condition, config):
        self.circuit, self.domain = circuit, domain
        self.groups, self.targets, self.lut = groups, targets, lut
        self.condition, self.config = condition, config
        self.mos = [d for d in circuit.devices if d.device_type in (DeviceType.NMOS, DeviceType.PMOS)]
        self.nets = sorted({p.upper() for d in circuit.devices for p in d.pins} - {"VINP", "VINN", "VDD", "VSS", "0"})
        self.width_group = {m: i for i, g in enumerate(groups) for m in g.members}
        self.reference_index = [next(i for i, d in enumerate(self.mos) if d.name.upper() == g.reference) for g in groups]
        self._initial_curves = {}
        self._length_tables = {}

    def _initial_curve(self, kind, length, diode, supply):
        key = (kind, float(length), diode, min(.9, supply))
        if key not in self._initial_curves:
            vg = self.lut.axes[2]
            values = self.lut.lookup(kind, length, 0., vg, vg if diode else min(.9, supply))
            ratio = values[:, 1] / np.maximum(values[:, 0], 1e-30)
            values.setflags(write=False)
            ratio.setflags(write=False)
            self._initial_curves[key] = values, ratio
        return self._initial_curves[key]

    def _length_table(self, kind, parameter, supply):
        key = (kind, parameter, min(.9, supply))
        if key not in self._length_tables:
            axis = self.domain.axes[self.domain.names.index(parameter)]
            vg = self.lut.axes[2]
            values = self.lut.lookup(kind, axis[:, None], 0., vg[None, :], min(.9, supply))
            ratio = values[..., 1] / np.maximum(values[..., 0], 1e-30)
            values.setflags(write=False)
            ratio.setflags(write=False)
            self._length_tables[key] = values, ratio
        return self._length_tables[key]

    def propose(self, rng):
        design = self.domain.random(rng, 1)[0]
        chosen = {g.width: float(rng.choice(self.targets[g.width])) for g in self.groups}
        params = dict(zip(self.domain.names, design))
        resolved = resolve_circuit(self.circuit, params)
        device_params = {d.name.upper(): {k: e.value for k, e in d.parameters.items()} for d in resolved.devices}
        supply = float(self.condition["VDD"]) - float(self.condition["VSS"])
        vss = float(self.condition["VSS"])
        vcm = float(self.condition["VCM"]) - vss
        current_scale = max(abs(float(params["IBIAS_A"])), 1e-12)
        length = np.array([device_params[d.name.upper()]["L"] for d in self.mos])
        multiplicity = np.array([device_params[d.name.upper()]["M"] for d in self.mos])
        width_indices = np.array([self.width_group[d.name.upper()] for d in self.mos])
        signs = np.array([1 if d.device_type == DeviceType.NMOS else -1 for d in self.mos])
        types = {kind: np.array([i for i, d in enumerate(self.mos) if d.device_type.value == kind]) for kind in ("NMOS", "PMOS")}
        densities, reference_flags = [], []
        for group, reference in zip(self.groups, self.reference_index):
            reference_device = self.mos[reference]
            kind = self.mos[reference].device_type.value
            vg = self.lut.axes[2]
            direct_diode = (reference_device.pins[0] == reference_device.pins[1] and
                            reference_device.pins[2].upper() in {"VDD", "VSS"} and
                            reference_device.pins[2] == reference_device.pins[3])
            bias_net = reference_device.pins[0].upper()
            # Only an isolated reference diode carrying the ideal IBIAS can be
            # rejected cheaply using its exact LUT current. Other branch ratios
            # remain unknowns of the coupled KCL solve.
            bias_reference = direct_diode and any(
                d.device_type == DeviceType.CURRENT_SOURCE and bias_net in {p.upper() for p in d.pins}
                for d in self.circuit.devices)
            values, ratio = self._initial_curve(kind, length[reference], bias_reference, supply)
            roots = []
            target = chosen[group.width]
            for i in range(len(vg)-1):
                if ratio[i] >= target >= ratio[i+1] and ratio[i] > ratio[i+1] and values[i, 0] > 0:
                    fraction = (ratio[i] - target) / (ratio[i] - ratio[i+1])
                    density = values[i, 0] + fraction * (values[i+1, 0] - values[i, 0])
                    roots.append(density)
            if not roots:
                return None, {"rejection": "unreachable_gmid", "gmid_targets": chosen}
            densities.append(roots[-1])
            reference_flags.append(bias_reference)
        # Engineering sizing conditions IBIAS on the W limits; it remains on
        # the original I grid. Non-reference branches use a generous factor-two
        # interval because their actual VDS/VBS comes from the coupled solve.
        lower_current, upper_current = 0., np.inf
        conditioned_lengths = self.config["condition_lengths_on_width"]
        selected_groups = list(zip(self.groups, densities, reference_flags))
        if conditioned_lengths:
            if not reference_flags[0]:
                raise ValueError("Conditional sizing requires the first group to be the ideal bias reference")
            selected_groups = selected_groups[:1]
        for group, density, exact in selected_groups:
            axis = self.domain.axes[self.domain.names.index(group.width)]
            factor = 1. if exact else 2.
            lower_current = max(lower_current, axis[0]*1e-6*density/factor)
            upper_current = min(upper_current, axis[-1]*1e-6*density*factor)
        current_index = self.domain.names.index("IBIAS_A")
        current_axis = self.domain.axes[current_index]
        eligible = current_axis[(current_axis >= lower_current) & (current_axis <= upper_current)]
        if not len(eligible):
            return None, {"rejection": "no_bias_grid_for_lut_sizing", "gmid_targets": chosen}
        current_scale = float(rng.choice(eligible))
        design[current_index] = current_scale
        params["IBIAS_A"] = current_scale
        if conditioned_lengths:
            for group_index, (group, reference) in enumerate(zip(self.groups[1:], self.reference_index[1:]), 1):
                axis = self.domain.axes[self.domain.names.index(group.length)]
                kind = self.mos[reference].device_type.value
                # These zero-body/fixed-VDS curves depend only on the frozen
                # domain and LUT, not on a proposal's current or gm/ID target.
                values, ratio = self._length_table(kind, group.length, supply)
                target = chosen[group.width]
                crossing = (ratio[:, :-1] >= target) & (ratio[:, 1:] <= target) & (ratio[:, :-1] > ratio[:, 1:]) & (values[:, :-1, 0] > 0)
                valid = crossing.any(axis=1)
                indices = crossing.shape[1]-1-np.argmax(crossing[:, ::-1], axis=1)
                rows = np.arange(len(axis))
                fraction = np.divide(ratio[rows, indices]-target,
                                     ratio[rows, indices]-ratio[rows, indices+1],
                                     out=np.zeros(len(axis)), where=valid)
                density = values[rows, indices, 0] + fraction * (values[rows, indices+1, 0]-values[rows, indices, 0])
                widths = current_scale / np.maximum(density, 1e-30) * 1e6
                width_axis = self.domain.axes[self.domain.names.index(group.width)]
                eligible_lengths = np.flatnonzero(valid & (widths >= width_axis[0]/2.) & (widths <= width_axis[-1]*2.))
                if not len(eligible_lengths):
                    return None, {"rejection": "no_length_grid_for_lut_sizing", "gmid_targets": chosen}
                index = int(rng.choice(eligible_lengths))
                params[group.length] = float(axis[index])
                design[self.domain.names.index(group.length)] = axis[index]
                densities[group_index] = float(density[index])
        resolved = resolve_circuit(self.circuit, params)
        device_params = {d.name.upper(): {k: e.value for k, e in d.parameters.items()} for d in resolved.devices}
        length = np.array([device_params[d.name.upper()]["L"] for d in self.mos])
        guesses = [current_scale / density * 1e6 for density in densities]
        node_guess = np.full(len(self.nets), vcm)
        seeds = NODE_SEEDS[self.circuit.source_path.stem]
        for i, net in enumerate(self.nets):
            if net in seeds:
                node_guess[i] = seeds[net] * supply / 1.8
            if net == "NTAIL" or (net == "NET1" and self.circuit.source_path.stem == "Opamp1"):
                node_guess[i] = max(0.05, vcm - 0.6)
            elif net in {"N_INPUT_TAIL", "NET9"}:
                node_guess[i] = min(supply-0.05, vcm+0.6)
        # Initialize voltage differences from inverse gm/ID, including body
        # effect. Starting every cascode around VCM can leave it switched off,
        # where its gm/ID residual has no useful local derivative.
        node_indices = {net: i for i, net in enumerate(self.nets)}
        active = [i for i, d in enumerate(self.mos) if i in self.reference_index or d.name.upper() in SIGNAL[self.circuit.source_path.stem]]
        voltage_equations = []
        fixed_terms = []
        fixed = {"VDD": supply, "VSS": 0., "0": -vss, "VINP": vcm}
        for i in active:
            coefficients = np.zeros(len(self.nets))
            constant = 0.
            for pin, direction in ((self.mos[i].pins[1], signs[i]), (self.mos[i].pins[2], -signs[i])):
                pin = pin.upper()
                pin = "VOUT" if pin == "VINN" else pin
                if pin in node_indices:
                    coefficients[node_indices[pin]] += direction
                else:
                    constant += direction*fixed[pin]
            voltage_equations.append(coefficients)
            fixed_terms.append(constant)
        matrix = np.asarray(voltage_equations)
        original_seed = node_guess.copy()
        for _ in range(3):
            voltage = dict(zip(self.nets, node_guess))
            voltage.update(fixed)
            voltage["VINN"] = voltage["VOUT"]
            predictions = []
            reference_densities = {}
            for i in active:
                device = self.mos[i]
                drain, gate, source, bulk = (voltage[p.upper()] for p in device.pins)
                body = np.clip(signs[i]*(source-bulk), 0., supply)
                vd = np.clip(abs(drain-source), .05, supply)
                vg = self.lut.axes[2]
                values = self.lut.lookup(device.device_type.value, length[i], body, vg, vd)
                ratio = values[:, 1]/np.maximum(values[:, 0], 1e-30)
                target = chosen[self.groups[width_indices[i]].width]
                crossing = np.flatnonzero((ratio[:-1] >= target) & (ratio[1:] <= target) & (ratio[:-1] > ratio[1:]) & (values[:-1, 0] > 0))
                if len(crossing):
                    j = crossing[-1]
                    fraction = (ratio[j]-target)/(ratio[j]-ratio[j+1])
                    predictions.append(vg[j]+fraction*(vg[j+1]-vg[j]))
                    if i in self.reference_index:
                        reference_densities[i] = values[j, 0]+fraction*(values[j+1, 0]-values[j, 0])
                else:
                    predictions.append(np.clip(signs[i]*(gate-source), .1, supply))
            node_guess = lsq_linear(np.vstack([matrix, .03*np.eye(len(self.nets))]),
                                    np.r_[np.asarray(predictions)-fixed_terms, .03*original_seed],
                                    bounds=(0., supply), tol=1e-5).x
        if self.config["sizing_mode"] == "nominal_lut":
            # All five engineering profiles have nominal ID/M=IBIAS at their
            # reference transistors. Actual branch currents are observed later;
            # bad OPs remain useful dataset labels rather than being discarded.
            metadata = {"gmid_targets": chosen, "sizing_mode": "nominal_lut",
                        "lut_solver_error": None, "nominal_reference_current_a": current_scale,
                        "conditioned_lengths": conditioned_lengths,
                        "lut_predicted_nodes_v": dict(zip(self.nets, (node_guess+vss).tolist()))}
            if len(reference_densities) != len(self.groups):
                return None, {**metadata, "rejection": "unreachable_bias_gmid"}
            try:
                for group, reference in zip(self.groups, self.reference_index):
                    width = current_scale/reference_densities[reference]*1e6
                    design[self.domain.names.index(group.width)] = self.domain.quantize_width(group.width, width)
            except ValueError:
                return None, {**metadata, "rejection": "width_out_of_range"}
            return design, metadata
        # Wide solver bounds expose out-of-domain solutions instead of clipping them.
        initial = np.r_[node_guess, np.log(np.clip(guesses, 1e-3, 1e4))]
        lower = np.r_[np.zeros(len(self.nets)), np.full(len(self.groups), np.log(1e-3))]
        upper = np.r_[np.full(len(self.nets), supply), np.full(len(self.groups), np.log(1e4))]

        def residual(x):
            voltages = dict(zip(self.nets, x[:len(self.nets)]))
            voltages.update({"VDD": supply, "VSS": 0., "0": -vss, "VINP": vcm, "VINN": voltages["VOUT"]})
            pins = np.array([[voltages[p.upper()] for p in d.pins] for d in self.mos])
            drain, gate, source, bulk = pins.T
            forward = signs * (drain-source)
            # Current is evaluated in the correct D/S orientation, even during solving.
            actual_source = np.where(forward >= 0, source, drain)
            vg = np.maximum(signs * (gate-actual_source), 0.)
            vd = abs(drain-source)
            body = np.maximum(signs * (actual_source-bulk), 0.)
            values = np.empty((len(self.mos), 3))
            for kind, ix in types.items():
                if len(ix):
                    values[ix] = self.lut.lookup(kind, length[ix], body[ix], vg[ix], vd[ix])
            if not np.isfinite(values).all():
                return np.full(len(x), 1e6)
            widths = np.exp(x[len(self.nets):])[width_indices] * 1e-6
            currents = signs * np.where(forward >= 0, 1, -1) * values[:, 0] * widths * multiplicity
            kcl = np.zeros(len(self.nets))
            for d, current in zip(self.mos, currents):
                for pin, polarity in ((d.pins[0], 1), (d.pins[2], -1)):
                    if pin.upper() in node_indices:
                        kcl[node_indices[pin.upper()]] += polarity * current
            for device in self.circuit.devices:
                p = device_params[device.name.upper()]
                if device.device_type == DeviceType.CURRENT_SOURCE:
                    current = p["I"]
                elif device.device_type == DeviceType.RESISTOR:
                    current = (voltages[device.pins[0].upper()] - voltages[device.pins[1].upper()]) / p["R"]
                else:
                    continue
                for pin, polarity in zip(device.pins, (1, -1)):
                    if pin.upper() in node_indices:
                        kcl[node_indices[pin.upper()]] += polarity * current
            # Scale KCL by each node's incident current; never suppress an off solution.
            scale = np.full(len(self.nets), current_scale)
            for d, current in zip(self.mos, currents):
                for pin in (d.pins[0], d.pins[2]):
                    if pin.upper() in node_indices:
                        scale[node_indices[pin.upper()]] += abs(current)
            ratio = values[:, 1] / np.maximum(values[:, 0], 1e-30)
            constraints = [(ratio[i] - chosen[g.width]) / chosen[g.width] for g, i in zip(self.groups, self.reference_index)]
            return np.r_[kcl / scale, constraints]

        result = least_squares(residual, np.minimum(np.maximum(initial, lower+1e-9), upper-1e-9),
                               bounds=(lower, upper), max_nfev=self.config["max_solver_evaluations"],
                               x_scale="jac", diff_step=1e-4, ftol=1e-5, xtol=1e-5, gtol=1e-5)
        error = float(np.max(abs(residual(result.x))))
        metadata = {"gmid_targets": chosen, "lut_solver_error": error,
                    "sizing_mode": "coupled_lut",
                    "solver_evaluations": int(result.nfev),
                    "bias_sampling": "lut_width_intersection", "nominal_reference_current_a": current_scale,
                    "conditioned_lengths": conditioned_lengths,
                    "lut_predicted_nodes_v": dict(zip(self.nets, (result.x[:len(self.nets)] + vss).tolist()))}
        if error > self.config["solver_tolerance"]:
            return None, {**metadata, "rejection": "lut_kcl_or_gmid_residual"}
        try:
            for group, width in zip(self.groups, np.exp(result.x[len(self.nets):])):
                design[self.domain.names.index(group.width)] = self.domain.quantize_width(group.width, width)
        except ValueError:
            return None, {**metadata, "rejection": "width_out_of_range"}
        return design, metadata
