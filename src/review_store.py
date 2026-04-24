"""
review_store.py - Persist missed quiz questions per current study material.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


class ReviewStore:
    def __init__(self, study_material: str):
        material_path = Path(study_material).resolve()
        namespace = hashlib.md5(str(material_path).encode("utf-8")).hexdigest()[:12]
        store_dir = material_path.parent / ".study_agent_review"
        store_dir.mkdir(parents=True, exist_ok=True)
        self.path = store_dir / f"{material_path.stem}_{namespace}.json"

    def _load(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []

    def _save(self, items: list[dict]):
        self.path.write_text(
            json.dumps(items, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )

    def add(self, question_data: dict, label: str):
        if label not in {"errato", "parzialmente corretto"}:
            return

        items = self._load()
        question_text = question_data["text"]
        items = [item for item in items if item.get("text") != question_text]
        items.append(
            {
                "text": question_text,
                "label": label,
                "source_chunks": question_data.get("source_chunks", []),
            }
        )
        self._save(items)

    def list_all(self) -> list[dict]:
        return self._load()

    def pop_many(self, n: int) -> list[dict]:
        items = self._load()
        if not items:
            return []
        selected = items[:n]
        remaining = items[n:]
        self._save(remaining)
        return selected
