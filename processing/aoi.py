"""Assam main-stem AOI: Sadiya to Dhubri. Replaces the old 90–92.5E / 26–27.2N box."""

from __future__ import annotations

from shapely.geometry import LineString

# Downstream-ordered vertices (east/upstream → west/downstream), WGS84 lon/lat.
MAIN_STEM_LONLAT: list[tuple[float, float]] = [
    (95.670, 27.848),  # Sadiya
    (95.380, 27.790),
    (95.150, 27.720),
    (94.910, 27.480),  # Dibrugarh
    (94.580, 27.290),
    (94.250, 27.180),
    (93.850, 26.980),
    (93.500, 26.800),
    (92.800, 26.633),  # Tezpur
    (92.400, 26.400),
    (92.050, 26.280),
    (91.736, 26.180),  # Guwahati
    (91.400, 26.160),
    (91.050, 26.150),
    (90.620, 26.100),  # Goalpara
    (90.280, 26.060),
    (89.985, 26.020),  # Dhubri
]

UPSTREAM_NAME = "Sadiya"
DOWNSTREAM_NAME = "Dhubri / Bangladesh border"
CORRIDOR_BUFFER_M = 12_000.0
TILE_SIZE_M = 40_000.0
TILE_OVERLAP_M = 4_000.0


def mainstem_line() -> LineString:
    return LineString(MAIN_STEM_LONLAT)


def endpoints_lonlat() -> dict[str, dict[str, float | str]]:
    up = MAIN_STEM_LONLAT[0]
    down = MAIN_STEM_LONLAT[-1]
    return {
        "upstream": {"name": UPSTREAM_NAME, "lon": up[0], "lat": up[1]},
        "downstream": {"name": DOWNSTREAM_NAME, "lon": down[0], "lat": down[1]},
    }
