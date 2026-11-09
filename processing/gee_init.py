"""Google Earth Engine login. Optional: set GEE_PROJECT after earthengine authenticate."""

from __future__ import annotations

import os


class GeeUnavailable(RuntimeError):
    pass


def gee_status() -> dict:
    project = os.environ.get("GEE_PROJECT", "community-hero-5c501").strip()
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
        text = str(exc)
        if "authorize" in text.lower() or "authenticate" in text.lower():
            reason = "Earth Engine is not signed in on this computer."
        elif "permission" in text.lower() or "not registered" in text.lower() or "not signed up" in text.lower():
            reason = f"This Google login cannot use the Earth Engine project {project}."
        else:
            reason = "Earth Engine did not accept this request."
        return {"available": False, "reason": reason, "project": project}


def gee_available() -> bool:
    return bool(gee_status().get("available"))


def require_ee():
    status = gee_status()
    if not status["available"]:
        raise GeeUnavailable(status["reason"])
    import ee

    return ee
