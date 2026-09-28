from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping

import torch


@dataclass(frozen=True)
class MemoryEntry:
    memory_id: str
    topology_id: str
    stable_index: int
    created_step: int
    backbone_version: str
    adapter_file: str
    embedding_centroid: tuple[float, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


class MemoryRegistry:
    SCHEMA_VERSION = 1

    def __init__(self, root: Path | str, *, backbone_version: str = "backbone-v0") -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.adapter_root = self.root / "adapters"
        self.adapter_root.mkdir(exist_ok=True)
        self.index_path = self.root / "registry.json"
        self.backbone_version = backbone_version
        self._entries: dict[str, MemoryEntry] = {}
        if self.index_path.exists():
            self._load()
        else:
            self._save()

    def _load(self) -> None:
        payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != self.SCHEMA_VERSION:
            raise ValueError("memory registry schema 版本不兼容")
        self.backbone_version = str(payload["backbone_version"])
        entries = {}
        for raw in payload.get("entries", []):
            raw["embedding_centroid"] = tuple(raw.get("embedding_centroid", ()))
            entries[raw["memory_id"]] = MemoryEntry(**raw)
        self._entries = entries

    def _save(self) -> None:
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "backbone_version": self.backbone_version,
            "entries": [asdict(entry) for entry in self.entries()],
        }
        descriptor, temporary = tempfile.mkstemp(prefix=".registry.", suffix=".json", dir=self.root)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                json.dump(payload, file, indent=2)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.index_path)
        except Exception:
            Path(temporary).unlink(missing_ok=True)
            raise

    def entries(self, *, compatible_only: bool = True) -> tuple[MemoryEntry, ...]:
        result = tuple(sorted(self._entries.values(), key=lambda entry: entry.stable_index))
        if compatible_only:
            result = tuple(entry for entry in result if entry.backbone_version == self.backbone_version)
        return result

    def register(
        self,
        *,
        topology_id: str,
        adapter_state: Mapping[str, torch.Tensor],
        created_step: int,
        embedding_centroid: tuple[float, ...] = (),
        metadata: Mapping[str, Any] | None = None,
        memory_id: str | None = None,
    ) -> MemoryEntry:
        memory_id = memory_id or f"memory-{len(self._entries):04d}-{topology_id}"
        existing = self._entries.get(memory_id)
        stable_index = existing.stable_index if existing else len(self._entries) + 1
        adapter_file = f"adapters/{memory_id}.pt"
        torch.save({name: tensor.detach().cpu() for name, tensor in adapter_state.items()}, self.root / adapter_file)
        entry = MemoryEntry(
            memory_id=memory_id, topology_id=topology_id, stable_index=stable_index,
            created_step=created_step, backbone_version=self.backbone_version,
            adapter_file=adapter_file, embedding_centroid=embedding_centroid,
            metadata=dict(metadata or {}),
        )
        self._entries[memory_id] = entry
        self._save()
        return entry

    def load_state(self, memory_id: str) -> dict[str, torch.Tensor]:
        entry = self._entries[memory_id]
        if entry.backbone_version != self.backbone_version:
            raise ValueError(f"memory {memory_id} 属于 {entry.backbone_version}，当前为 {self.backbone_version}")
        return torch.load(self.root / entry.adapter_file, map_location="cpu", weights_only=True)

    def bump_backbone_version(self, version: str) -> None:
        if version == self.backbone_version:
            raise ValueError("新 backbone_version 必须不同")
        self.backbone_version = version
        self._save()
