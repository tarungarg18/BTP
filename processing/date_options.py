"""Date / period selection for two-envelope bankline comparison.

Mode A — two dates, each ending a composite window of 1 / 15 / 30 / 60 days.
Mode B — two explicit periods (start–end inclusive), each composited independently.

Archive floors (GEE catalogue):
  Sentinel-1 GRD: 2014-10-03
  Sentinel-2 SR Harmonized: 2017-03-28
Scene existence over the Assam AOI is still checked per request.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta

OPTICAL_ARCHIVE_START = date(2017, 3, 28)
MICROWAVE_ARCHIVE_START = date(2014, 10, 3)
ALLOWED_WINDOW_DAYS = (1, 15, 30, 60)
DEFAULT_WINDOW_DAYS = 15
MIN_VALID_FRACTION = 0.70  # provisional warning / acceptance setting
ALGORITHM_VERSION = "envv4"
CLASSIFICATION = {
    "optical": "MNDWI_B3_B11_gt_0",
    "microwave": "VV_lt_-16dB",
}
# Fixed baselines for reproducibility — not claimed as universal science standards.
CLASSIFICATION_NOTE = (
    "Optical MNDWI>0 and SAR VV<-16 dB are Assam corridor baselines. "
    "Validate against representative samples before scientific claims; "
    "adaptive/Otsu thresholds are not used unless explicitly recorded."
)
MASKING = {
    "optical": "SCL_exclude_0_1_3_8_9_10_11",
    "microwave": "IW_VV_mixed_orbits_recorded",
}


@dataclass(frozen=True)
class ObservationWindow:
    start: date  # inclusive
    end_exclusive: date

    @property
    def end(self) -> date:
        return self.end_exclusive - timedelta(days=1)

    @property
    def label(self) -> str:
        if self.start == self.end:
            return self.start.isoformat()
        return f"{self.start.isoformat()} → {self.end.isoformat()}"

    @property
    def key(self) -> str:
        return f"{self.start.isoformat()}_{self.end.isoformat()}"

    @property
    def days(self) -> int:
        return (self.end_exclusive - self.start).days


@dataclass(frozen=True)
class CompareRequest:
    mode: str  # "dates" | "periods"
    sensor: str  # "optical" | "microwave"
    window_days: int
    earlier: ObservationWindow
    later: ObservationWindow
    acknowledge_partial: bool = False
    overlap_days: int = 0

    def cache_key(self, *, close_m: float, scale_m: float, crs: str) -> str:
        return (
            f"{ALGORITHM_VERSION}"
            f"|sensor={self.sensor}"
            f"|mode={self.mode}"
            f"|win={self.window_days}"
            f"|earlier={self.earlier.key}"
            f"|later={self.later.key}"
            f"|close_m={close_m:g}"
            f"|scale_m={scale_m:g}"
            f"|crs={crs}"
            f"|class={CLASSIFICATION[self.sensor]}"
            f"|mask={MASKING[self.sensor]}"
        )

    def as_dict(self) -> dict:
        return {
            "mode": self.mode,
            "sensor": self.sensor,
            "window_days": self.window_days,
            "acknowledge_partial": self.acknowledge_partial,
            "overlap_days": self.overlap_days,
            "overlap_note": (
                None
                if self.overlap_days <= 0
                else (
                    f"The two composites share {self.overlap_days} day(s). "
                    "They are not independent observations."
                )
            ),
            "earlier": {
                "start": self.earlier.start.isoformat(),
                "end": self.earlier.end.isoformat(),
                "label": self.earlier.label,
            },
            "later": {
                "start": self.later.start.isoformat(),
                "end": self.later.end.isoformat(),
                "label": self.later.label,
            },
        }


def parse_day(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("Use a date as YYYY-MM-DD") from exc


def _window_ending(day: date, window_days: int) -> ObservationWindow:
    if window_days not in ALLOWED_WINDOW_DAYS:
        raise ValueError(f"window_days must be one of {ALLOWED_WINDOW_DAYS}")
    start = day - timedelta(days=window_days - 1)
    return ObservationWindow(start=start, end_exclusive=day + timedelta(days=1))


def _period(start: date, end: date) -> ObservationWindow:
    if end < start:
        raise ValueError("Period end must be on or after period start")
    return ObservationWindow(start=start, end_exclusive=end + timedelta(days=1))


def archive_start(sensor: str) -> date:
    if sensor == "optical":
        return OPTICAL_ARCHIVE_START
    if sensor == "microwave":
        return MICROWAVE_ARCHIVE_START
    raise ValueError("sensor must be optical or microwave")


def validate_against_archive(window: ObservationWindow, sensor: str) -> None:
    floor = archive_start(sensor)
    if window.end < floor:
        raise ValueError(
            f"{sensor} archive starts {floor.isoformat()}; "
            f"requested window ends {window.end.isoformat()}."
        )
    if window.start < floor:
        raise ValueError(
            f"{sensor} archive starts {floor.isoformat()}; "
            f"requested window starts {window.start.isoformat()}."
        )


def build_compare_request(
    *,
    mode: str = "dates",
    sensor: str = "optical",
    window_days: int = DEFAULT_WINDOW_DAYS,
    later: str | None = None,
    earlier: str | None = None,
    earlier_start: str | None = None,
    earlier_end: str | None = None,
    later_start: str | None = None,
    later_end: str | None = None,
    acknowledge_partial: bool = False,
) -> CompareRequest:
    if sensor not in ("optical", "microwave"):
        raise ValueError("sensor must be optical or microwave")
    mode = (mode or "dates").lower()
    if mode not in ("dates", "periods"):
        raise ValueError("mode must be dates or periods")

    if mode == "dates":
        if not later:
            raise ValueError("Later date is required")
        later_day = parse_day(later)
        later_window = _window_ending(later_day, window_days)
        if earlier:
            earlier_day = parse_day(earlier)
            if earlier_day >= later_day:
                raise ValueError("Earlier date must be before the later date")
            earlier_window = _window_ending(earlier_day, window_days)
        else:
            earlier_window = _window_ending(later_day - timedelta(days=window_days), window_days)
    else:
        if not (earlier_start and earlier_end and later_start and later_end):
            raise ValueError("Period mode needs earlier_start, earlier_end, later_start, later_end")
        earlier_window = _period(parse_day(earlier_start), parse_day(earlier_end))
        later_window = _period(parse_day(later_start), parse_day(later_end))
        if later_window.start <= earlier_window.end:
            raise ValueError(
                "Mode B periods must not overlap: later period must start after "
                f"the earlier period ends ({earlier_window.end.isoformat()}). "
                f"Later period starts {later_window.start.isoformat()}."
            )
        window_days = max(earlier_window.days, later_window.days)

    validate_against_archive(earlier_window, sensor)
    validate_against_archive(later_window, sensor)
    shared_start = max(earlier_window.start, later_window.start)
    shared_end = min(earlier_window.end, later_window.end)
    shared = (shared_end - shared_start).days + 1 if shared_end >= shared_start else 0
    return CompareRequest(
        mode=mode,
        sensor=sensor,
        window_days=int(window_days),
        earlier=earlier_window,
        later=later_window,
        acknowledge_partial=bool(acknowledge_partial),
        overlap_days=int(shared),
    )


def probe_collection(ee, sensor: str, window: ObservationWindow, region) -> dict:
    """Query Earth Engine for scene availability inside the AOI / window."""
    if sensor == "microwave":
        collection = (
            ee.ImageCollection("COPERNICUS/S1_GRD")
            .filterBounds(region)
            .filterDate(window.start.isoformat(), window.end_exclusive.isoformat())
            .filter(ee.Filter.eq("instrumentMode", "IW"))
            .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
            .select(["VV"])
        )
        band = "VV"
    else:
        collection = (
            ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
            .filterBounds(region)
            .filterDate(window.start.isoformat(), window.end_exclusive.isoformat())
            .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 90))
            .select(["B3", "B8", "B11", "SCL"])
        )
        band = "B3"

    count = int(collection.size().getInfo())
    if count == 0:
        return {
            "sensor": sensor,
            "window": window.label,
            "scene_count": 0,
            "earliest_acquisition": None,
            "latest_acquisition": None,
            "band_or_polarization": band,
            "ok": False,
            "detail": f"No {sensor} scenes in {window.label} over the Assam AOI.",
        }
    earliest = str(ee.Date(collection.aggregate_min("system:time_start")).format("yyyy-MM-dd").getInfo())
    latest = str(ee.Date(collection.aggregate_max("system:time_start")).format("yyyy-MM-dd").getInfo())
    return {
        "sensor": sensor,
        "window": window.label,
        "scene_count": count,
        "earliest_acquisition": earliest,
        "latest_acquisition": latest,
        "band_or_polarization": band,
        "ok": True,
        "detail": f"{count} scene(s), {earliest} → {latest}",
    }
