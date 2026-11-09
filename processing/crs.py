"""Regional metre CRS for Sadiya–Dhubri. Not UTM 46N (the reach crosses 90E and 93E)."""

from __future__ import annotations

from dataclasses import dataclass

from pyproj import CRS, Geod, Transformer
from shapely.ops import transform as shapely_transform

# Albers Equal Area centred on the Assam corridor.
# EPSG:7755 remains a candidate after a documented geodesic check.
OPERATIONAL_CRS_WKT = (
    'PROJCS["Assam_Brahmaputra_Albers",'
    'GEOGCS["WGS 84",DATUM["WGS_1984",'
    'SPHEROID["WGS 84",6378137,298.257223563]],'
    'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]],'
    'PROJECTION["Albers_Conic_Equal_Area"],'
    'PARAMETER["latitude_of_center",27],'
    'PARAMETER["longitude_of_center",93],'
    'PARAMETER["standard_parallel_1",26],'
    'PARAMETER["standard_parallel_2",28],'
    'PARAMETER["false_easting",0],'
    'PARAMETER["false_northing",0],'
    'UNIT["metre",1]]'
)

GEOGRAPHIC_CRS = "EPSG:4326"
OPERATIONAL_PIXEL_M = 20.0
LANDSAT_PIXEL_M = 30.0

CHECK_POINTS = {
    "sadiya": (95.67, 27.85),
    "guwahati": (91.7362, 26.1445),
    "dhubri": (89.985, 26.02),
}


@dataclass(frozen=True)
class CrsBundle:
    geographic: CRS
    projected: CRS
    to_metre: Transformer
    to_lonlat: Transformer


def load_crs() -> CrsBundle:
    geographic = CRS.from_user_input(GEOGRAPHIC_CRS)
    projected = CRS.from_wkt(OPERATIONAL_CRS_WKT)
    return CrsBundle(
        geographic=geographic,
        projected=projected,
        to_metre=Transformer.from_crs(geographic, projected, always_xy=True),
        to_lonlat=Transformer.from_crs(projected, geographic, always_xy=True),
    )


def to_metres(geometry, bundle: CrsBundle):
    return shapely_transform(bundle.to_metre.transform, geometry)


def to_lonlat(geometry, bundle: CrsBundle):
    return shapely_transform(bundle.to_lonlat.transform, geometry)


def distortion_report(bundle: CrsBundle) -> dict[str, float]:
    geod = Geod(ellps="WGS84")
    report: dict[str, float] = {}
    for name, (lon, lat) in CHECK_POINTS.items():
        x, y = bundle.to_metre.transform(lon, lat)
        lon2, lat2 = bundle.to_lonlat.transform(x + 1000.0, y)
        _, _, geodesic_m = geod.inv(lon, lat, lon2, lat2)
        report[name] = abs(geodesic_m - 1000.0)
    return report
