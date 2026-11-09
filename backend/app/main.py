from __future__ import annotations

import re
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import store

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"

app = FastAPI(
    title="Brahmaputra Bank Change Portal API",
    description="Assam main-stem corridor monitoring. Candidate change only.",
    version="0.1.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    from processing.gee_init import gee_status

    return {"ok": True, "gee": gee_status(), "store": store.STORE_PATH.exists()}


@app.get("/api/method")
def method() -> dict:
    data = store.load()
    area = data["study_area"]
    return {
        "how_calculated": area.get("how_calculated", []),
        "source": area.get("source"),
        "gee": area.get("gee"),
        "disclaimer": area.get("disclaimer"),
    }


@app.get("/api/study-area")
def study_area() -> dict:
    return store.load()["study_area"]


@app.get("/api/acquisitions")
def acquisitions() -> list:
    return store.load()["acquisitions"]


@app.get("/api/jobs")
def jobs() -> list:
    return store.load()["jobs"]


@app.get("/api/jobs/{job_id}")
def job(job_id: str) -> dict:
    for item in store.load()["jobs"]:
        if item["id"] == job_id:
            return item
    raise HTTPException(404, "job not found")


@app.get("/api/epochs")
def epochs() -> list:
    data = store.load()
    return [
        {
            "id": e["id"],
            "date": e["date"],
            "sensors": e["sensors"],
            "status": e["status"],
            "validation_status": e["validation_status"],
            "source": e["source"],
            "method": e.get("method"),
            "scene_count": e.get("scene_count"),
        }
        for e in data["epochs"]
    ]


@app.get("/api/epochs/{epoch_id}")
def epoch(epoch_id: str) -> dict:
    for item in store.load()["epochs"]:
        if item["id"] == epoch_id:
            return item
    raise HTTPException(404, "epoch not found")


@app.get("/api/epochs/{epoch_id}/layers")
def epoch_layers(epoch_id: str) -> dict:
    return epoch(epoch_id)["layers"]


@app.get("/api/reference")
def reference() -> dict:
    return store.load()["reference"]


@app.get("/api/reaches")
def reaches() -> list:
    return store.load()["reference"]["reaches"]


@app.get("/api/comparisons")
def comparisons() -> list:
    data = store.load()
    return [
        {
            "id": c["id"],
            "epoch_a": c["epoch_a"],
            "epoch_b": c["epoch_b"],
            "epoch_a_id": c["epoch_a_id"],
            "epoch_b_id": c["epoch_b_id"],
            "tolerance_m": c["tolerance_m"],
            "disclaimer": c["disclaimer"],
        }
        for c in data["comparisons"]
    ]


@app.get("/api/comparisons/{cmp_id}")
def comparison(cmp_id: str) -> dict:
    for item in store.load()["comparisons"]:
        if item["id"] == cmp_id:
            return item
    raise HTTPException(404, "comparison not found")


@app.get("/api/summary")
def summary() -> dict:
    from processing.catalog import portal_summary

    return portal_summary()


@app.get("/api/masks")
def masks() -> list:
    from processing.catalog import list_masks

    return list_masks()


@app.get("/api/changes")
def mask_changes() -> list:
    from processing.catalog import list_step_changes

    return list_step_changes()


def _is_day(value: str | None) -> bool:
    return bool(value and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value))


@app.post("/api/compute")
def start_compute(later: str, earlier: str = "") -> dict:
    if not _is_day(later):
        raise HTTPException(400, "Use an end date as YYYY-MM-DD")
    if earlier and not _is_day(earlier):
        raise HTTPException(400, "Use a start date as YYYY-MM-DD")
    from processing.live_extract import begin_compute

    started = begin_compute(later, earlier or None)
    if not started:
        raise HTTPException(409, "A comparison is already running")
    return {"started": True}


@app.get("/api/compute")
def compute_status() -> dict:
    from processing.live_extract import progress_snapshot

    return progress_snapshot()


@app.get("/api/change")
def mask_change(later: str, earlier: str | None = None) -> dict:
    if _is_day(later):
        from processing.gee_init import GeeUnavailable
        from processing.live_extract import compare_dates

        try:
            return compare_dates(later, earlier if _is_day(earlier) else None)
        except GeeUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(404, str(exc)) from exc
    from processing.catalog import get_change

    try:
        record = get_change(later, earlier)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    from processing.inspect import mask_centerline

    record["centerline"] = mask_centerline(record["later_id"]) if record.get("later_id") else None
    return record


@app.get("/api/points")
def points(later: str, earlier: str = "") -> dict:
    if _is_day(later):
        from processing.gee_init import GeeUnavailable
        from processing.live_extract import period_points

        try:
            return period_points(later, earlier if _is_day(earlier) else None)
        except GeeUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(404, str(exc)) from exc
    from processing.inspect import change_points

    try:
        return change_points(later, earlier)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, "Unknown observation") from exc


@app.get("/api/identify")
def identify(lon: float, lat: float, later: str, earlier: str | None = None) -> dict:
    if _is_day(later):
        from processing.gee_init import GeeUnavailable
        from processing.live_extract import period_identify

        try:
            return period_identify(lon, lat, later, earlier if _is_day(earlier) else None)
        except GeeUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(404, str(exc)) from exc
    from processing.inspect import identify as locate

    try:
        return locate(lon, lat, later, earlier)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, "Unknown observation") from exc


@app.get("/api/profile")
def profile(later: str, earlier: str) -> dict:
    from processing.inspect import build_profile

    try:
        return build_profile(later, earlier)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, "Unknown observation") from exc


@app.get("/api/profile.csv")
def profile_csv(later: str, earlier: str):
    from fastapi.responses import Response
    from processing.inspect import profile_csv as csv_text

    try:
        body = csv_text(later, earlier)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, "Unknown observation") from exc
    filename = f"{later}__{earlier}-sections.csv"
    return Response(
        content=body,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/masks/{mask_id}/file")
def mask_file(mask_id: str) -> FileResponse:
    from processing.inspect import mask_path

    if not re.fullmatch(r"[a-z0-9-]+", mask_id):
        raise HTTPException(404, "Unknown observation")
    try:
        path = mask_path(mask_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, "File is not available") from exc
    except KeyError as exc:
        raise HTTPException(404, "Unknown observation") from exc
    return FileResponse(path, media_type="image/tiff", filename=path.name)


@app.get("/api/latest")
def latest() -> dict:
    from processing.live_extract import latest_report

    try:
        return latest_report()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, "Earth Engine did not respond") from exc


@app.get("/api/periods")
def periods() -> list:
    from processing.live_extract import list_periods

    return list_periods()


@app.get("/api/periods/{key}/file")
def period_file(key: str) -> FileResponse:
    from processing.live_extract import period_tif

    try:
        path = period_tif(key)
    except (FileNotFoundError, KeyError) as exc:
        raise HTTPException(404, "That extract is not on disk") from exc
    return FileResponse(path, media_type="image/tiff", filename=path.name)


@app.get("/api/overlays/{name}")
def overlay(name: str) -> FileResponse:
    from processing.catalog import OVERLAY_DIR

    if not re.fullmatch(r"[a-z0-9_-]+\.png", name):
        raise HTTPException(404, "overlay not found")
    path = OVERLAY_DIR / name
    if not path.is_file():
        raise HTTPException(404, "overlay not found")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-cache"})


if FRONTEND_DIST.exists():
    assets = FRONTEND_DIST / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/")
    def spa_index() -> FileResponse:
        return FileResponse(FRONTEND_DIST / "index.html")

    @app.get("/{path:path}")
    def spa_fallback(path: str) -> FileResponse:
        if path.startswith("api/") or path == "api":
            raise HTTPException(404, "not found")
        candidate = FRONTEND_DIST / path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")
