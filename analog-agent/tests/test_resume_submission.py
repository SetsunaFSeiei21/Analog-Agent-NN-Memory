import os
import json
import shlex
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

from src.sample_optimize.advanced.context import digest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/run/submit_resume_sampling.sh"


def run(*args, **env):
    return subprocess.run(["bash", str(SCRIPT), *args], text=True, capture_output=True,
                          env={**os.environ, "DRY_RUN": "1", **env})


def test_default_submission_requests_32_cpus_and_resumes_exact_runs():
    result = run()
    assert result.returncode == 0, result.stderr
    commands = [shlex.split(line) for line in result.stdout.splitlines()]
    assert len(commands) == 2
    for command, circuit, run_id in zip(commands, ["5t_ota", "two_stage_opamp_otaf"],
                                       ["1e9b2d5c2b0a4558824b7437f30305d8", "8459175daab247d5aac6243418564861"]):
        assert command[:3] == ["env", f"ANALOG_RESUME_RUN_ID={run_id}", "sbatch"]
        assert "--cpus-per-task=32" in command
        runner = command.index("scripts/run/run_sampling.sh")
        assert command[runner + 1].endswith("sampling_database/" + circuit)
        assert command[runner + 2] == circuit
        assert command[runner + 5:runner + 7] == ["60000", "32"]
        assert command[runner + 7:] == ["DC_GAIN", "UGF", "PM", "CMRR", "P_PSRR", "N_PSRR", "P_SR", "N_SR", "POWER"]


def test_select_one_circuit_and_override_resources():
    result = run("5t_ota", ANALOG_RESUME_WORKERS="16", ANALOG_SLURM_GPUS="0")
    assert result.returncode == 0, result.stderr
    assert len(result.stdout.splitlines()) == 1
    assert "--cpus-per-task=16" in result.stdout
    assert "--gres=gpu:0" in result.stdout


@pytest.mark.parametrize("args,workers", [(["unknown"], "32"), (["5t_ota", "5t_ota"], "32"), ([], "64"), ([], "0")])
def test_invalid_submission_fails_before_sbatch(args, workers):
    result = run(*args, ANALOG_RESUME_WORKERS=workers)
    assert result.returncode == 2
    assert not result.stdout


@pytest.mark.parametrize("circuit,run_id", [
    ("5t_ota", "1e9b2d5c2b0a4558824b7437f30305d8"),
    ("two_stage_opamp_otaf", "8459175daab247d5aac6243418564861"),
])
def test_per_circuit_entrypoints(circuit, run_id):
    script = SCRIPT.with_name(f"submit_resume_{circuit}.sh")
    result = subprocess.run(["bash", str(script)], text=True, capture_output=True,
                            env={**os.environ, "DRY_RUN": "1", "ANALOG_RESUME_WORKERS": "32"})
    assert result.returncode == 0, result.stderr
    assert len(result.stdout.splitlines()) == 1
    command = shlex.split(result.stdout)
    assert command[:3] == ["env", f"ANALOG_RESUME_RUN_ID={run_id}", "sbatch"]
    assert "--cpus-per-task=32" in command
    assert circuit in command


@pytest.mark.parametrize("failure", ["completed", "algorithm", "fingerprint"])
def test_submission_preflight_and_sbatch_environment(tmp_path, failure):
    target = tmp_path / "existing history"
    source = SCRIPT.parents[2] / "src/sample_optimize"
    manifest = json.loads((source / "storage_resume_compat.json").read_text())
    implementation = {path.name: digest(path.read_text()) for path in (source / "advanced").glob("*.py")}
    # A run started on the latest repository before applying the storage patch.
    implementation.update(manifest["upgrades"][0]["before"])
    config = {"sampling": {"batch_size": 32}, "implementation": implementation}
    runs = {"5t_ota": "1e9b2d5c2b0a4558824b7437f30305d8",
            "two_stage_opamp_otaf": "8459175daab247d5aac6243418564861"}
    for circuit, run_id in runs.items():
        directory = target / circuit
        directory.mkdir(parents=True)
        with closing(sqlite3.connect(directory / "sampling_history.sqlite3")) as con, con:
            con.executescript("CREATE TABLE sampling_runs(run_id,status,requested_points,config_json); "
                              "CREATE TABLE sampling_state(run_id,state_json);")
            con.execute("INSERT INTO sampling_runs VALUES (?,?,?,?)",
                        (run_id, "FAILED", 60000, json.dumps(config)))
            con.execute("INSERT INTO sampling_state VALUES (?,?)",
                        (run_id, json.dumps({"completed": {"random": 100}, "config_fingerprint": digest(config)})))
    # No real scheduler is called: capture arguments/environment at the boundary.
    executable = tmp_path / "sbatch"
    executable.write_text(f"#!{sys.executable}\n" + '''import json, os, sys
with open(os.environ["CAPTURE"], "a") as output:
    output.write(json.dumps({"args": sys.argv[1:], "run": os.environ["ANALOG_RESUME_RUN_ID"],
                             "threads": os.environ["OPENBLAS_NUM_THREADS"]}) + "\\n")
print("12345")
''')
    executable.chmod(0o755)
    capture = tmp_path / "submitted.jsonl"
    result = run(DRY_RUN="0", ANALOG_RESUME_TARGET_ROOT=str(target), ANALOG_PYTHON=sys.executable,
                 PATH=str(tmp_path) + os.pathsep + os.environ["PATH"], CAPTURE=str(capture))
    assert result.returncode == 0, result.stderr
    submissions = [json.loads(line) for line in capture.read_text().splitlines()]
    assert [item["run"] for item in submissions] == list(runs.values())
    assert all(item["threads"] == "1" for item in submissions)
    assert all("--cpus-per-task=32" in item["args"] for item in submissions)
    # An incompatible second run must prevent submitting the first one, too.
    with closing(sqlite3.connect(target / "two_stage_opamp_otaf/sampling_history.sqlite3")) as con, con:
        if failure == "completed":
            con.execute("UPDATE sampling_runs SET status='COMPLETED'")
        else:
            if failure == "algorithm":
                config["implementation"]["gmid.py"] = "pre-LVT-algorithm"
            con.execute("UPDATE sampling_runs SET config_json=?", (json.dumps(config),))
            con.execute("UPDATE sampling_state SET state_json=?", (json.dumps({
                "completed": {"random": 100},
                "config_fingerprint": digest(config) if failure == "algorithm" else "invalid"}),))
    result = run(DRY_RUN="0", ANALOG_RESUME_TARGET_ROOT=str(target), ANALOG_PYTHON=sys.executable,
                 PATH=str(tmp_path) + os.pathsep + os.environ["PATH"], CAPTURE=str(capture))
    assert result.returncode != 0
    assert len(capture.read_text().splitlines()) == 2
    if failure != "completed":
        assert "原任务与当前采样实现不兼容" in result.stderr
