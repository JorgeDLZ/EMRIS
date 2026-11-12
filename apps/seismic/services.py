from dataclasses import dataclass
from pathlib import Path

from django.db import transaction
from django.utils import timezone

from apps.emergencies.models import Emergency
from apps.emergencies.workflow import _lock_open
from apps.places.models import Municipality
from ml.seismic import (
    SGC_MUNICIPALITY_ALIASES,
    LinkCandidate,
    link_window,
    read_catalog,
    suggest_event,
)

from .models import SeismicEvent

BATCH_SIZE = 500
UPDATE_FIELDS = [
    "event_time", "magnitude", "depth_km", "latitude", "longitude", "place",
    "department", "municipality",
]


@dataclass
class SeismicReport:
    loaded: int
    matched: int
    unmatched: int


def _municipality_lookups():
    official = Municipality.objects.filter(source=Municipality.OFFICIAL).select_related("department")
    by_code = {municipality.code: municipality for municipality in official}
    by_name = {(m.department.name_key, m.name_key): m for m in official}
    return by_code, by_name


def _resolve(event, by_code, by_name):
    key = (event.department_key, event.municipality_key)
    code = SGC_MUNICIPALITY_ALIASES.get(key)
    return by_code.get(code) if code else by_name.get(key)


@transaction.atomic
def load_seismic(path: str | Path) -> SeismicReport:
    by_code, by_name = _municipality_lookups()
    instances = []
    matched = 0
    for event in read_catalog(path):
        municipality = _resolve(event, by_code, by_name)
        if municipality is not None:
            matched += 1
        instances.append(
            SeismicEvent(
                sgc_id=event.sgc_id,
                event_time=event.event_time,
                magnitude=event.magnitude,
                depth_km=event.depth_km,
                latitude=event.latitude,
                longitude=event.longitude,
                place=event.place,
                department=municipality.department if municipality else None,
                municipality=municipality,
            )
        )
    SeismicEvent.objects.bulk_create(
        instances,
        batch_size=BATCH_SIZE,
        update_conflicts=True,
        unique_fields=["sgc_id"],
        update_fields=UPDATE_FIELDS,
    )
    return SeismicReport(loaded=len(instances), matched=matched, unmatched=len(instances) - matched)


@dataclass(frozen=True)
class SeismicSuggestion:
    event: SeismicEvent
    distance_km: float


def suggest_link(emergency: Emergency) -> SeismicSuggestion | None:
    if not emergency.is_earthquake:
        return None
    municipality = emergency.municipality
    if municipality.latitude is None or municipality.longitude is None:
        return None
    reported_on = timezone.localdate(emergency.occurred_at)
    start, end = link_window(reported_on)
    events = {
        event.sgc_id: event
        for event in SeismicEvent.objects.filter(event_time__gte=start, event_time__lt=end)
    }
    candidates = [
        LinkCandidate(
            key=event.sgc_id,
            event_time=event.event_time,
            magnitude=event.magnitude,
            latitude=event.latitude,
            longitude=event.longitude,
        )
        for event in events.values()
    ]
    link = suggest_event(reported_on, municipality.latitude, municipality.longitude, candidates)
    if link is None:
        return None
    return SeismicSuggestion(event=events[link.key], distance_km=link.distance_km)


def _store_link(
    emergency: Emergency, locked: Emergency, event: SeismicEvent | None, distance_km: float | None
) -> None:
    locked.seismic_event = event
    locked.seismic_link_distance_km = distance_km
    locked.save(update_fields=["seismic_event", "seismic_link_distance_km", "updated_at"])
    emergency.seismic_event = locked.seismic_event
    emergency.seismic_link_distance_km = locked.seismic_link_distance_km
    emergency.updated_at = locked.updated_at


@transaction.atomic
def confirm_link(emergency: Emergency) -> SeismicSuggestion | None:
    locked = _lock_open(emergency)
    suggestion = suggest_link(locked)
    if suggestion is not None:
        _store_link(emergency, locked, suggestion.event, suggestion.distance_km)
    return suggestion


@transaction.atomic
def clear_link(emergency: Emergency) -> None:
    _store_link(emergency, _lock_open(emergency), None, None)
