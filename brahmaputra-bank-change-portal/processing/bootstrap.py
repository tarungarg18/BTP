"""Deprecated. The portal is seeded from real satellite water via ingest."""

from __future__ import annotations

from pathlib import Path


def run() -> Path:
    from .ingest import run as ingest

    return ingest()


if __name__ == "__main__":
    path = run()
    print(f"Wrote {path}")
