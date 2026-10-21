import json
import runpy
import shutil
from pathlib import Path

import pytest

from src.sample_optimize.advanced.context import digest


PROJECT = Path(__file__).resolve().parents[1]


def local_sources(tmp_path):
    source = PROJECT / "src/sample_optimize"
    destination = tmp_path / "sample_optimize"
    shutil.copytree(source / "advanced", destination / "advanced")
    for name in ("resume_compat.py", "storage_resume_compat.json"):
        shutil.copy2(source / name, destination / name)
    manifest = json.loads((destination / "storage_resume_compat.json").read_text())
    old_implementation, current_implementation = {}, {}
    for path in (destination / "advanced").glob("*.py"):
        current = path.read_text()
        previous = current
        for edit in manifest["reverse_edits"].get(path.name, []):
            assert previous.count(edit["after"]) == 1
            previous = previous.replace(edit["after"], edit["before"], 1)
        if path.name in manifest["reverse_edits"]:
            assert digest(previous) == manifest["upgrades"][0]["before"][path.name]
            # Simulate a model-related local change already present at run start.
            previous += "\n# server-local model adaptation\n"
            current += "\n# server-local model adaptation\n"
            path.write_text(current)
        old_implementation[path.name] = digest(previous)
        current_implementation[path.name] = digest(current)
    previous = {"seed": 42, "sampling": {"batch_size": 32}, "context_fingerprint": "verified",
                "implementation": old_implementation}
    current = {**previous, "implementation": current_implementation}
    validate = runpy.run_path(str(destination / "resume_compat.py"))["validate_resume_configuration"]
    return destination, previous, current, validate


def test_exact_storage_patch_accepts_existing_local_code_without_changing_files(tmp_path):
    directory, previous, current, validate = local_sources(tmp_path)
    snapshots = {p: p.read_bytes() for p in directory.rglob("*.py")}
    assert validate(previous, digest(previous), current)
    assert all(p.read_bytes() == value for p, value in snapshots.items())


@pytest.mark.parametrize("change", ["outside_repair", "inside_repair", "algorithm", "lut", "bounds", "context", "seed", "saved_fingerprint"])
def test_local_compatibility_still_rejects_unrelated_changes(tmp_path, change):
    directory, previous, current, validate = local_sources(tmp_path)
    fingerprint = digest(previous)
    if change in {"outside_repair", "inside_repair"}:
        path = directory / "advanced/context.py"
        content = path.read_text()
        if change == "outside_repair":
            content += "\n# edit made after the original run started\n"
        else:
            content = content.replace("A durable launch reservation", "An altered launch reservation")
        path.write_text(content)
        current["implementation"]["context.py"] = digest(content)
    elif change == "algorithm":
        current["implementation"]["gmid.py"] = "different"
    elif change == "lut":
        current["implementation"]["lut.py"] = "different"
    elif change == "bounds":
        current["bounds"] = [[.35, 1., .01]]
    elif change == "context":
        current["context_fingerprint"] = "different-LVT-model-or-VCM"
    elif change == "seed":
        current["seed"] = 43
    else:
        fingerprint = "invalid"
    with pytest.raises(ValueError):
        validate(previous, fingerprint, current)
