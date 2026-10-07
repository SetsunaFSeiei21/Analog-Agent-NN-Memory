from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import subprocess
import os
from contextlib import closing
from pathlib import Path

from ..operating_point_contract import OP_SCHEMA_VERSION

# Version 1's verified collector. Its bias deck and feasibility definitions
# are preserved by the version-2 field-only upgrade.
LEGACY_OP_IMPLEMENTATION = "04e33a61ef7d0beeef60db54707cd783f08a21c4755603e830f4d7aa2fadb1d3"

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def source_identity(directory, name):
    directory = Path(directory)
    files = [directory / f"{name}.sp", directory / f"{name}_params.sp"]
    if (directory / ".spiceinit").exists():
        files.append(directory / ".spiceinit")
    visited, values = set(), {}
    def visit(path):
        path = path.resolve()
        if path in visited:
            return
        visited.add(path)
        data = path.read_bytes()
        key = str(path.relative_to(directory.resolve())) if path.is_relative_to(directory.resolve()) else str(path)
        values[key] = hashlib.sha256(data).hexdigest()
        for match in re.finditer(r'(?im)^\s*\.(?:include|inc)\s+(?:"([^"]+)"|\x27([^\x27]+)\x27|(\S+))', data.decode(errors="replace")):
            target = next(v for v in match.groups() if v is not None)
            visit(path.parent / target)
    for path in files:
        visit(path)
    return values


def model_identity(paths):
    """Hash the recursive model include closure, including nested .lib files."""
    visited, hashes = set(), {}
    def visit(path):
        path = Path(path).resolve()
        if path in visited:
            return
        visited.add(path)
        if not path.is_file():
            raise FileNotFoundError(f"PDK include does not exist: {path}")
        data = path.read_bytes()
        hashes[str(path)] = hashlib.sha256(data).hexdigest()
        for line in data.decode(errors="replace").splitlines():
            match = re.match(r'^\s*\.(?:include|inc|lib)\s+(?:"([^"]+)"|\x27([^\x27]+)\x27|(\S+))', line, re.I)
            if not match:
                continue
            target = next(x for x in match.groups() if x is not None)
            # .lib tt starts a section; .lib path tt loads a file.
            if re.match(r'^\s*\.lib\s+\S+\s*$', line, re.I) and not any(c in target for c in '/.\\'):
                continue
            visit(path.parent / target)
    for path in paths:
        visit(path)
    return hashes


def resolve_mos_primitives(models, required_models=("sky130_fd_pr__nfet_01v8", "sky130_fd_pr__pfet_01v8")):
    primitives = {}
    required = set(required_models)
    for file in models:
        content = Path(file).read_text(errors="replace")
        for model in required:
            match = re.search(rf"(?ims)^\s*\.subckt\s+{re.escape(model)}\s+.*?\n(.*?)^\s*\.ends\b", content)
            if match:
                instance = re.search(r"(?im)^\s*(m\w+)\s+", match[1])
                if instance:
                    found = instance[1].lower()
                    if model in primitives and primitives[model] != found:
                        raise ValueError(f"Ambiguous primitive instance for {model}")
                    primitives[model] = found
    if set(primitives) != required:
        raise ValueError("Cannot resolve Sky130 MOS primitive names from the PDK include closure")
    return primitives


def simulation_context(source, name, simulator):
    conditions, templates = {}, {}
    for bench in simulator._get_testbench_name_lst():
        conditions[bench] = json.loads((simulator.simulate_condition_path / f"{bench}_condition.json").read_text())
        templates[bench] = hashlib.sha256((simulator.circuit_testbench_path / f"tb_{bench}.cir").read_bytes()).hexdigest()
    if "power" not in conditions:
        raise ValueError("Five-method dataset sampling requires all nine metrics, including POWER")
    anchor = conditions["power"]
    # One OP/LUT context must describe the operating conditions of the measured circuit.
    for bench, condition in conditions.items():
        for key in ("PDK_PATH", "CORNER", "VDD", "VSS", "VCM", "TEMP"):
            if condition.get(key) != anchor.get(key):
                raise ValueError(f"{bench} has a different {key}; use consistent conditions for the dataset")
    version = subprocess.run([simulator.ngspice_command, "--version"], capture_output=True, text=True, check=True, timeout=15)
    models = model_identity([anchor["PDK_PATH"]])
    initialization_files = [Path.home() / ".spiceinit", Path("/usr/share/ngspice/scripts/spinit"),
                            Path("/usr/local/share/ngspice/scripts/spinit")]
    if os.environ.get("SPICE_SCRIPTS"):
        initialization_files.append(Path(os.environ["SPICE_SCRIPTS"]) / "spinit")
    global_initialization = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in initialization_files if p.is_file()}
    primitives = resolve_mos_primitives(models)
    return {"schema_version": 1, "source": source_identity(source, name), "templates": templates,
            "initialization": (Path(source) / ".spiceinit").read_text() if (Path(source) / ".spiceinit").exists() else "",
            "global_initialization": global_initialization,
            "spice_scripts": os.environ.get("SPICE_SCRIPTS"),
            "op_implementation": hashlib.sha256(Path(__file__).with_name("operating_point.py").read_bytes()).hexdigest(),
            "op_schema_version": OP_SCHEMA_VERSION,
            "conditions": conditions, "models": models, "mos_primitives": primitives,
            "ngspice_version": version.stdout + version.stderr,
            "units": "W,L:um; Sky130 scale=1u; electrical:SI"}


def bind_context(database, context):
    fingerprint = digest(context)
    with closing(sqlite3.connect(database)) as con, con:
        con.execute("CREATE TABLE IF NOT EXISTS sampling_context (id INTEGER PRIMARY KEY CHECK(id=1), fingerprint TEXT NOT NULL, context_json TEXT NOT NULL)")
        old = con.execute("SELECT fingerprint FROM sampling_context WHERE id=1").fetchone()
        count = con.execute("SELECT COUNT(*) FROM samples").fetchone()[0]
        if old is None and count:
            raise ValueError("Existing history has no verified simulation context. Preserve it and choose a new target directory; legacy labels cannot warm-start this run.")
        if old is not None and old[0] != fingerprint:
            previous = json.loads(con.execute("SELECT context_json FROM sampling_context WHERE id=1").fetchone()[0])
            ignored = {"op_implementation", "op_schema_version"}
            compatible = (previous.get("op_implementation") == LEGACY_OP_IMPLEMENTATION
                          and previous.get("op_schema_version", 1) == 1
                          and context.get("op_schema_version") == 2
                          and {k: v for k, v in previous.items() if k not in ignored}
                          == {k: v for k, v in context.items() if k not in ignored})
            if not compatible:
                raise ValueError("Simulation context changed (netlist/testbench/PDK/conditions/ngspice). Preserve the history and choose a new target directory.")
            con.execute("UPDATE sampling_context SET fingerprint=?,context_json=? WHERE id=1",
                        (fingerprint, json.dumps(context, sort_keys=True)))
        con.execute("INSERT OR IGNORE INTO sampling_context VALUES (1,?,?)", (fingerprint, json.dumps(context, sort_keys=True)))
    return fingerprint


def record_invocation(database, run_id, design_key, category, bench, operation):
    """A durable launch reservation is kept even if a worker dies mid-command."""
    with closing(sqlite3.connect(database, timeout=60)) as con, con:
        cursor = con.execute("INSERT INTO spice_invocations(run_id,design_key,category,bench,status) VALUES (?,?,?,?, 'reserved')",
                             (run_id, design_key, category, bench))
        event = cursor.lastrowid
    try:
        value = operation()
    except BaseException:
        with closing(sqlite3.connect(database, timeout=60)) as con, con:
            con.execute("UPDATE spice_invocations SET status='failed' WHERE invocation_id=?", (event,))
        raise
    with closing(sqlite3.connect(database, timeout=60)) as con, con:
        con.execute("UPDATE spice_invocations SET status='finished' WHERE invocation_id=?", (event,))
    return value
