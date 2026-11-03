"""Search-path only. Never displayed as the river. Clipped Natural Earth Brahmaputra."""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from shapely.geometry import LineString, Point, box, shape
from shapely.ops import nearest_points, substring

from .aoi import MAIN_STEM_LONLAT

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "guide_brahmaputra.geojson"
NE_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    "master/geojson/ne_10m_rivers_lake_centerlines.geojson"
)
# Official study endpoints (Sadiya → Dhubri).
UP = Point(MAIN_STEM_LONLAT[0])
DOWN = Point(MAIN_STEM_LONLAT[-1])


def _download_ne() -> dict:
    req = urllib.request.Request(NE_URL, headers={"User-Agent": "BrahmaputraBankChangePortal/1.0"})
    with urllib.request.urlopen(req, timeout=90) as response:
        return json.loads(response.read().decode())


def load_guide_lonlat() -> LineString:
    """East-to-west Brahmaputra guide clipped to Sadiya–Dhubri."""
    if CACHE.exists():
        feat = json.loads(CACHE.read_text())
        line = shape(feat["geometry"])
        if isinstance(line, LineString) and line.length > 0:
            return line

    data = _download_ne()
    feat = next(
        f
        for f in data["features"]
        if str((f.get("properties") or {}).get("name") or "").lower() == "brahmaputra"
    )
    geom = shape(feat["geometry"])
    pad = 0.15
    clipped = geom.intersection(box(DOWN.x - pad, 25.95, UP.x + pad, 27.95))
    if clipped.geom_type == "MultiLineString":
        clipped = max(clipped.geoms, key=lambda g: g.length)
    if not isinstance(clipped, LineString):
        return LineString(MAIN_STEM_LONLAT)

    # Orient upstream (Sadiya / east) → downstream (Dhubri / west).
    if Point(clipped.coords[0]).distance(UP) > Point(clipped.coords[-1]).distance(UP):
        clipped = LineString(list(clipped.coords)[::-1])

    start_d = clipped.project(nearest_points(clipped, UP)[0])
    end_d = clipped.project(nearest_points(clipped, DOWN)[0])
    if end_d <= start_d:
        line = LineString(MAIN_STEM_LONLAT)
    else:
        line = substring(clipped, start_d, end_d, normalized=False)
        if not isinstance(line, LineString) or line.length == 0:
            line = LineString(MAIN_STEM_LONLAT)
        else:
            coords = [MAIN_STEM_LONLAT[0], *list(line.coords), MAIN_STEM_LONLAT[-1]]
            line = LineString(coords)

    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(
        json.dumps(
            {
                "type": "Feature",
                "properties": {"role": "search_guide_only", "source": "Natural Earth 10m Brahmaputra"},
                "geometry": {"type": "LineString", "coordinates": [list(c) for c in line.coords]},
            }
        )
    )
    return line
