import csv
import subprocess
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from ml.data import MUNICIPALITY_ALIASES, clean_ungrd, municipality_centroids, read_divipola
from ml.seismic import (
    LinkCandidate,
    SGC_MUNICIPALITY_ALIASES,
    SeismicFeatures,
    link_radius_km,
    link_window,
    parse_place,
    read_catalog,
    seismic_features,
    suggest_event,
)
from ml.text import normalize_name

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"

BOGOTA = (4.6, -74.1)
NEARBY = (4.7, -74.1)


def candidate(key, local_time, magnitude=5.0, position=BOGOTA):
    utc_time = (local_time + timedelta(hours=5)).replace(tzinfo=timezone.utc)
    return LinkCandidate(key, utc_time, magnitude, *position)


def test_radius_grows_with_magnitude():
    assert link_radius_km(3.0) == 30.0
    assert link_radius_km(4.0) == 30.0
    radii = [link_radius_km(m / 10) for m in range(45, 71)]
    assert all(a < b for a, b in zip(radii, radii[1:]))


def test_radius_values():
    assert abs(link_radius_km(5.8) - 224) < 1
    assert abs(link_radius_km(6.3) - 398) < 1
    assert abs(link_radius_km(6.4) - 447) < 1


def test_event_after_report_date_is_ignored():
    after = candidate("late", datetime(2025, 6, 9, 0, 0))
    assert suggest_event(date(2025, 6, 8), *BOGOTA, [after]) is None
    last_minute = candidate("ok", datetime(2025, 6, 8, 23, 59))
    assert suggest_event(date(2025, 6, 8), *BOGOTA, [last_minute]).key == "ok"


def test_event_outside_window_is_ignored():
    three_days = candidate("old", datetime(2025, 6, 5, 23, 59))
    two_days = candidate("ok", datetime(2025, 6, 6, 0, 0))
    assert suggest_event(date(2025, 6, 8), *BOGOTA, [three_days]) is None
    assert suggest_event(date(2025, 6, 8), *BOGOTA, [two_days]).key == "ok"


def test_local_time_decides_the_window_not_utc():
    evening = candidate("evening", datetime(2025, 6, 8, 20, 0))
    assert evening.event_time.date() == date(2025, 6, 9)
    assert suggest_event(date(2025, 6, 8), *BOGOTA, [evening]).key == "evening"


def test_event_beyond_radius_is_ignored():
    far = candidate("far", datetime(2025, 6, 8, 10, 0), 4.0, (6.0, -74.1))
    assert suggest_event(date(2025, 6, 8), *BOGOTA, [far]) is None


def test_largest_magnitude_wins_then_nearest():
    when = datetime(2025, 6, 8, 10, 0)
    small_near = candidate("small", when, 4.0, BOGOTA)
    big_far = candidate("big_far", when, 5.0, (4.9, -74.1))
    big_near = candidate("big_near", when, 5.0, NEARBY)
    link = suggest_event(date(2025, 6, 8), *BOGOTA, [small_near, big_far, big_near])
    assert link.key == "big_near"
    assert 10 < link.distance_km < 12
    assert suggest_event(date(2025, 6, 8), *BOGOTA, [small_near, big_far]).key == "big_far"


def test_no_coordinates_or_no_candidates_returns_none():
    event = candidate("a", datetime(2025, 6, 8, 10, 0))
    assert suggest_event(date(2025, 6, 8), None, None, [event]) is None
    assert suggest_event(date(2025, 6, 8), 4.6, None, [event]) is None
    assert suggest_event(date(2025, 6, 8), *BOGOTA, []) is None


def test_parse_place():
    assert parse_place("Yondó (Casabe) - Antioquia, Colombia") == ("ANTIOQUIA", "YONDO")
    assert parse_place("Océano Pacífico") is None
    assert parse_place("Tufiño - Carchi, Ecuador, Colombia") == ("CARCHI, ECUADOR", "TUFINO")


def test_aliases_point_to_divipola_codes():
    with open(DATA / "divipola_dane.csv", newline="", encoding="utf-8") as handle:
        codes = {row["municipality_code"] for row in csv.DictReader(handle)}
    assert set(SGC_MUNICIPALITY_ALIASES.values()) <= codes


def test_mojibake_is_repaired_in_real_extract():
    events = list(read_catalog(DATA / "sgc_seismicity_m25.csv"))
    assert all("Ã" not in event.place for event in events)


def test_seismic_module_does_not_load_pandas():
    code = "import sys, ml.seismic; assert 'pandas' not in sys.modules"
    subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=True)


def test_real_catalog_figures():
    events = list(read_catalog(DATA / "sgc_seismicity_m25.csv"))
    assert len(events) == 14332
    assert sum(e.department_key is not None for e in events) == 12270


def test_links_reproduce_known_ungrd_earthquakes():
    centroids = {}
    by_name = {}
    with open(DATA / "divipola_dane.csv", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            point = (float(row["latitude"]), float(row["longitude"]))
            centroids[row["municipality_code"]] = point
            key = (normalize_name(row["department_name"]), normalize_name(row["municipality_name"]))
            by_name[key] = point
    candidates = [
        LinkCandidate(e.sgc_id, e.event_time, e.magnitude, e.latitude, e.longitude)
        for e in read_catalog(DATA / "sgc_seismicity_m25.csv")
    ]
    records = clean_ungrd(DATA / "ungrd_emergencies_v2.csv").records
    quakes = records[records.event_type == "Earthquake"]
    assert len(quakes) == 41

    links = []
    for record in quakes.itertuples():
        key = (record.department_key, record.municipality_key)
        code = MUNICIPALITY_ALIASES.get(key)
        point = centroids[code] if code else by_name.get(key)
        link = suggest_event(record.occurred_on, *(point or (None, None)), candidates)
        if link:
            links.append(link.key)
    assert Counter(links) == {
        "SGC2025lfawhz": 32,
        "SGC2025scmftx": 3,
        "SGC2025swkoot": 3,
        "SGC2025kbayra": 1,
        "SGC2025qvpuao": 1,
        "SGC2025yggwzi": 1,
    }


def quake(magnitude, depth_km, latitude, longitude):
    return SimpleNamespace(
        magnitude=magnitude, depth_km=depth_km, latitude=latitude, longitude=longitude
    )


def test_seismic_features_rules():
    events = [
        quake(4.0, 69.0, 4.69, -74.1),
        quake(4.5, 70.0, 4.6, -74.1),
        quake(3.9, 10.0, 4.6, -74.1),
        quake(5.0, 10.0, 5.14, -74.1),
    ]
    assert seismic_features({"x": BOGOTA}, events) == {"x": SeismicFeatures(1, 4.0)}


def test_deep_strong_events_do_not_count():
    events = [quake(6.0, 140.0, *BOGOTA) for _ in range(50)]
    assert seismic_features({"x": BOGOTA}, events) == {"x": SeismicFeatures(0, 0.0)}


def test_missing_centroid_gets_zeros():
    assert seismic_features({"x": None}, [quake(5.0, 5.0, *BOGOTA)]) == {
        "x": SeismicFeatures(0, 0.0)
    }


def test_real_seismic_features():
    centroids = municipality_centroids(read_divipola(DATA / "divipola_dane.csv"))
    features = seismic_features(centroids, read_catalog(DATA / "sgc_seismicity_m25.csv"))
    assert len(features) == 1122
    assert sum(f.shallow_event_count > 0 for f in features.values()) == 525
    assert features["25438"] == SeismicFeatures(19, 6.4)
    assert features["68418"] == SeismicFeatures(0, 0.0)


def test_naive_event_time_is_rejected():
    naive = LinkCandidate("naive", datetime(2025, 6, 8, 12, 0), 5.0, *BOGOTA)
    with pytest.raises(ValueError, match="timezone-aware"):
        suggest_event(date(2025, 6, 8), *BOGOTA, [naive])


def test_link_window_bounds():
    start, end = link_window(date(2025, 6, 8))
    assert start == datetime(2025, 6, 6, 5, 0, tzinfo=timezone.utc)
    assert end == datetime(2025, 6, 9, 5, 0, tzinfo=timezone.utc)
    assert start.utcoffset() == timedelta(hours=-5)
