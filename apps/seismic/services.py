from dataclasses import dataclass
from pathlib import Path

from django.db import transaction

from apps.places.models import Municipality
from ml.seismic import SGC_MUNICIPALITY_ALIASES, read_catalog

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
