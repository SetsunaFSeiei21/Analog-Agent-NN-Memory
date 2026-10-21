"""Narrow, audited compatibility for a storage-only sampling repair."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _matches_storage_preimage(before, after, edits):
    """Reconstruct the exact pre-patch sources in memory, without changing files.

    This allows unrelated server-local code only when it was already present
    in the saved run. Every byte outside the reviewed storage edits still
    participates in the old fingerprint. Unknown edits inside the repair fail.
    """
    directory = Path(__file__).with_name("advanced")
    for name, replacements in edits.items():
        if name not in {"context.py", "controller.py"}:
            return False
        source = (directory / name).read_text()
        if _digest(source) != after.get(name):
            return False
        for replacement in replacements:
            old, new = replacement["before"], replacement["after"]
            if not new or source.count(new) != 1:
                return False
            source = source.replace(new, old, 1)
        if _digest(source) != before.get(name):
            return False
    return bool(edits)


def validate_resume_configuration(previous, saved_fingerprint, current):
    """Return True only for a verified storage upgrade; reject all other drift.

    Both sides of the changed files are pinned. Sampling, RNG, circuit/PDK,
    bounds, labels and every other implementation hash must match exactly.
    """
    if _digest(previous) != saved_fingerprint:
        raise ValueError("Saved resume configuration fingerprint is inconsistent")
    if _digest(current) == saved_fingerprint:
        return False
    manifest = json.loads(Path(__file__).with_name("storage_resume_compat.json").read_text())
    before = previous.get("implementation", {})
    after = current.get("implementation", {})
    if set(before) == set(after):
        changed = {name for name in before if before[name] != after[name]}
        for upgrade in manifest["upgrades"]:
            if (changed == set(upgrade["before"]) == set(upgrade["after"])
                    and all(before[name] == upgrade["before"][name]
                            and after[name] == upgrade["after"][name] for name in changed)):
                expected = {**previous, "implementation": after}
                if _digest(expected) == _digest(current):
                    return True
        edits = manifest.get("reverse_edits", {})
        if (changed == set(edits)
                and _digest({**previous, "implementation": after}) == _digest(current)
                and _matches_storage_preimage(before, after, edits)):
            return True
    raise ValueError("Resume configuration/seed/context/implementation differs from original run; "
                     "only the verified SQLite storage repair is compatible")


def validate_current_implementation(previous, saved_fingerprint):
    """Read-only submission preflight; the controller also checks runtime inputs.

    Do not submit a known incompatible algorithm upgrade to the scheduler.
    Bounds, simulation conditions and PDK identity are checked again by the
    controller when the job starts in its actual runtime environment.
    """
    directory = Path(__file__).with_name("advanced")
    implementation = {path.name: _digest(path.read_text()) for path in directory.glob("*.py")}
    return validate_resume_configuration(
        previous, saved_fingerprint, {**previous, "implementation": implementation})
