from __future__ import annotations

import json
from pathlib import Path

STORE_PATH = Path(__file__).resolve().parents[2] / "data" / "store.json"


def load() -> dict:
    if not STORE_PATH.exists():
        raise FileNotFoundError(
            "No satellite water store yet. Run: python -m processing.ingest"
        )
    return json.loads(STORE_PATH.read_text())


def save(data: dict) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STORE_PATH.write_text(json.dumps(data, indent=2))
