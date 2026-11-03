"""Google Earth Engine login. Optional: set GEE_PROJECT after earthengine authenticate."""

from __future__ import annotations

import os
from functools import lru_cache


class GeeUnavailable(RuntimeError):
    pass


@lru_cache(maxsize=1)
def gee_status() -> dict:
    project = os.environ.get("GEE_PROJECT", "").strip()
    try:
        import ee  # noqa: F401
    except ImportError:
        return {"available": False, "reason": "earthengine-api is not installed", "project": project}
    if not project:
        return {
            "available": False,
            "reason": "GEE_PROJECT is not set",
            "project": "",
        }
    try:
        import ee

        ee.Initialize(project=project)
        ee.Number(1).getInfo()
        return {"available": True, "reason": "ok", "project": project}
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": str(exc), "project": project}


def gee_available() -> bool:
    return bool(gee_status().get("available"))


def require_ee():
    status = gee_status()
    if not status["available"]:
        raise GeeUnavailable(status["reason"])
    import ee

    return ee
