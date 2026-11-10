import csv
import math
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable, Iterator, Mapping

from ml.text import normalize_name, repair_mojibake

MIN_MAGNITUDE = 2.5
LINK_WINDOW_DAYS = 2
MIN_LINK_RADIUS_KM = 30.0
EARTH_RADIUS_KM = 6371.0088
SHALLOW_DEPTH_KM = 70.0
RISK_MIN_MAGNITUDE = 4.0
RISK_RADIUS_KM = 50.0
COLOMBIA_TZ = timezone(timedelta(hours=-5))
COUNTRY_SUFFIX = ", Colombia"
UTC_FORMAT = "%Y-%m-%d %H:%M:%S"

SGC_MUNICIPALITY_ALIASES: dict[tuple[str, str], str] = {
    ("SANTANDER", "EL CARMEN"): "68235",
    ("CHOCO", "EL CARMEN"): "27245",
    ("VALLE DEL CAUCA", "BUGA"): "76111",
    ("CUNDINAMARCA", "UBATE"): "25843",
    ("BOYACA", "GUICAN"): "15332",
    ("NARINO", "TUMACO"): "52835",
    ("CESAR", "BECERRILL"): "20045",
    ("BOLIVAR", "RIOVIEJO"): "13600",
    ("CAUCA", "LOPEZ"): "19418",
    ("CAUCA", "SOTARA"): "19760",
    ("BOYACA", "PISVA"): "15550",
    ("LA GUAJIRA", "HATO NUEVO"): "44378",
    ("NORTE DE SANTANDER", "CUCUTA"): "54001",
    ("VALLE DEL CAUCA", "CALI"): "76001",
    ("CUNDINAMARCA", "BOGOTA"): "11001",
    ("ANTIOQUIA", "SAN PEDRO"): "05664",
    ("SUCRE", "SINCE"): "70742",
    ("BOYACA", "VILLA DE LEIVA"): "15407",
}


@dataclass(frozen=True)
class CatalogEvent:
    sgc_id: str
    event_time: datetime
    magnitude: float
    depth_km: float
    latitude: float
    longitude: float
    place: str
    department_key: str | None
    municipality_key: str | None


@dataclass(frozen=True)
class LinkCandidate:
    key: str
    event_time: datetime
    magnitude: float
    latitude: float
    longitude: float


@dataclass(frozen=True)
class SeismicLink:
    key: str
    distance_km: float


@dataclass(frozen=True)
class SeismicFeatures:
    shallow_event_count: int = 0
    max_shallow_magnitude: float = 0.0


def parse_place(place: str) -> tuple[str, str] | None:
    if not place.endswith(COUNTRY_SUFFIX):
        return None
    body = place[: -len(COUNTRY_SUFFIX)]
    if " - " not in body:
        return None
    municipality, department = body.rsplit(" - ", 1)
    municipality = re.sub(r"\([^)]*\)", "", municipality)
    return normalize_name(department), normalize_name(municipality)


def read_catalog(path) -> Iterator[CatalogEvent]:
    with open(path, encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            magnitude = float(row["magnitude"])
            if magnitude < MIN_MAGNITUDE:
                continue
            place = repair_mojibake(row["place"])
            keys = parse_place(place)
            yield CatalogEvent(
                sgc_id=row["id"],
                event_time=datetime.strptime(row["utc_time"], UTC_FORMAT).replace(
                    tzinfo=timezone.utc
                ),
                magnitude=magnitude,
                depth_km=float(row["depth"]),
                latitude=float(row["latitude"]),
                longitude=float(row["longitude"]),
                place=place,
                department_key=keys[0] if keys else None,
                municipality_key=keys[1] if keys else None,
            )


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = phi2 - phi1
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def link_radius_km(magnitude: float) -> float:
    return max(MIN_LINK_RADIUS_KM, 10 ** (0.5 * magnitude - 0.55))


def suggest_event(
    reported_on: date,
    latitude: float | None,
    longitude: float | None,
    candidates: Iterable[LinkCandidate],
) -> SeismicLink | None:
    if latitude is None or longitude is None:
        return None
    start = datetime.combine(reported_on - timedelta(days=LINK_WINDOW_DAYS), time.min, COLOMBIA_TZ)
    end = datetime.combine(reported_on + timedelta(days=1), time.min, COLOMBIA_TZ)
    best: tuple[float, float, str] | None = None
    for event in candidates:
        if not start <= event.event_time.astimezone(COLOMBIA_TZ) < end:
            continue
        distance = haversine_km(latitude, longitude, event.latitude, event.longitude)
        if distance > link_radius_km(event.magnitude):
            continue
        rank = (-event.magnitude, distance, event.key)
        if best is None or rank < best:
            best = rank
    if best is None:
        return None
    return SeismicLink(key=best[2], distance_km=best[1])


def seismic_features(
    centroids: Mapping[str, tuple[float, float] | None], events: Iterable
) -> dict[str, SeismicFeatures]:
    qualifying = [
        event
        for event in events
        if event.depth_km < SHALLOW_DEPTH_KM and event.magnitude >= RISK_MIN_MAGNITUDE
    ]
    features = {}
    for code, centroid in centroids.items():
        if centroid is None:
            features[code] = SeismicFeatures()
            continue
        magnitudes = [
            event.magnitude
            for event in qualifying
            if haversine_km(*centroid, event.latitude, event.longitude) <= RISK_RADIUS_KM
        ]
        features[code] = SeismicFeatures(
            shallow_event_count=len(magnitudes),
            max_shallow_magnitude=max(magnitudes, default=0.0),
        )
    return features
