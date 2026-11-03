from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from . import store

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
    return {"ok": True}


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


@app.post("/api/comparisons")
def make_comparison(payload: dict) -> dict:
    data = store.load()
    a_id = payload.get("epoch_a_id")
    b_id = payload.get("epoch_b_id")
    epochs = {e["id"]: e for e in data["epochs"]}
    if a_id not in epochs or b_id not in epochs:
        raise HTTPException(400, "unknown epoch")
    from processing.change import compare_epochs

    cmp = compare_epochs(
        epochs[a_id]["layers"],
        epochs[b_id]["layers"],
        data["reference"]["reaches"],
    )
    record = {
        "id": f"cmp-{epochs[a_id]['date']}__{epochs[b_id]['date']}",
        "epoch_a_id": a_id,
        "epoch_b_id": b_id,
        **cmp,
    }
    data["comparisons"] = [c for c in data["comparisons"] if c["id"] != record["id"]] + [record]
    store.save(data)
    return record


@app.post("/api/processing/discover")
def discover() -> dict:
    return {
        "status": "queued",
        "message": "GEE discovery requires GEE_PROJECT and earthengine authenticate.",
        "next": "python -m processing.gee_discover",
    }
