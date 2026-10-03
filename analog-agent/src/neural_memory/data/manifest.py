from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROLES = ("initial_train", "sequential", "final_blind")
EXPECTED_ROLE_COUNTS = {"initial_train": 8, "sequential": 10, "final_blind": 2}


@dataclass(frozen=True)
class TopologyEntry:
    topology_id: str
    role: str
    circuit_path: Path
    parameter_path: Path
    database_path: Path
    arrival_index: int | None = None
    expected_usable_points: int = 20_000


@dataclass(frozen=True)
class ExperimentManifest:
    entries: tuple[TopologyEntry, ...]
    root: Path
    schema_version: int = 1

    @classmethod
    def load(cls, path: Path | str, *, enforce_frozen_protocol: bool = True) -> "ExperimentManifest":
        path = Path(path).resolve()
        payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != 1:
            raise ValueError("manifest.schema_version 必须为 1")
        root = (path.parent / payload.get("root", ".")).resolve()
        entries: list[TopologyEntry] = []
        for raw in payload.get("topologies", []):
            role = raw["role"]
            if role not in ROLES:
                raise ValueError(f"未知 topology role：{role}")
            topology_id = str(raw["topology_id"])
            directory = (root / raw["directory"]).resolve()
            circuit_name = str(raw.get("circuit_name", topology_id))
            entries.append(TopologyEntry(
                topology_id=topology_id,
                role=role,
                circuit_path=directory / f"{circuit_name}.sp",
                parameter_path=directory / f"{circuit_name}_params.sp",
                database_path=directory / "sampling_history.sqlite3",
                arrival_index=raw.get("arrival_index"),
                expected_usable_points=int(raw.get("expected_usable_points", 20_000)),
            ))
        manifest = cls(tuple(entries), root)
        manifest.validate(enforce_frozen_protocol=enforce_frozen_protocol)
        return manifest

    def validate(self, *, enforce_frozen_protocol: bool = True, require_files: bool = True) -> None:
        ids = [entry.topology_id for entry in self.entries]
        if len(ids) != len(set(ids)):
            raise ValueError("manifest 中 topology_id 重复")
        if enforce_frozen_protocol:
            counts = {role: sum(entry.role == role for entry in self.entries) for role in ROLES}
            if counts != EXPECTED_ROLE_COUNTS:
                raise ValueError(f"冻结协议要求 8/10/2 个拓扑，实际为 {counts}")
            arrivals = sorted(
                entry.arrival_index for entry in self.entries if entry.role == "sequential"
            )
            if arrivals != list(range(10)):
                raise ValueError("sequential 拓扑 arrival_index 必须恰为 0..9")
        if require_files:
            missing = [
                str(path)
                for entry in self.entries
                for path in (entry.circuit_path, entry.parameter_path, entry.database_path)
                if not path.is_file()
            ]
            if missing:
                raise FileNotFoundError(f"manifest 引用的文件不存在：{missing}")

    def by_role(self, role: str) -> tuple[TopologyEntry, ...]:
        if role not in ROLES:
            raise ValueError(role)
        entries = tuple(entry for entry in self.entries if entry.role == role)
        if role == "sequential":
            entries = tuple(sorted(entries, key=lambda entry: int(entry.arrival_index or 0)))
        return entries
