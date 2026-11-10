from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from django.db import transaction

from apps.emergencies.models import EmergencyType
from apps.emergencies.services import seed_emergency_types
from apps.places.models import Department, Municipality
from apps.places.services import load_divipola
from ml.data import EVENT_TYPE_LABELS, MUNICIPALITY_ALIASES, clean_ungrd

from .models import UngrdRecord

BATCH_SIZE = 500
COUNT_FIELDS = [
    "deceased", "injured", "missing", "people_affected", "families_affected",
    "homes_destroyed", "homes_damaged", "roads_damaged", "bridges_damaged",
]
UPDATE_FIELDS = [
    "source_code", "occurred_on", "department", "municipality", "emergency_type",
    *COUNT_FIELDS, "hectares", "comments", "action_codes", "is_high_impact",
]


@dataclass
class BaselineReport:
    records: int
    discarded: Counter
    types_created: int
    municipalities: int


def _municipality_lookups():
    official = Municipality.objects.filter(source=Municipality.OFFICIAL).select_related("department")
    by_code = {municipality.code: municipality for municipality in official}
    by_name = {(m.department.name_key, m.name_key): m for m in official}
    return by_code, by_name


def _resolve(department_key, municipality_key, by_code, by_name, departments):
    if municipality_key is None:
        return departments.get(department_key), None
    code = MUNICIPALITY_ALIASES.get((department_key, municipality_key))
    municipality = by_code.get(code) if code else by_name.get((department_key, municipality_key))
    if municipality is None:
        return None, None
    return municipality.department, municipality


@transaction.atomic
def load_baseline(ungrd_path: str | Path, divipola_path: str | Path) -> BaselineReport:
    municipalities = load_divipola(divipola_path)
    types_created = seed_emergency_types(sorted(set(EVENT_TYPE_LABELS.values())))
    cleaned = clean_ungrd(ungrd_path)
    discarded = Counter(cleaned.discarded)

    by_code, by_name = _municipality_lookups()
    departments = {department.name_key: department for department in Department.objects.all()}
    type_ids = dict(EmergencyType.objects.values_list("name", "id"))

    instances = []
    for row in cleaned.records.to_dict("records"):
        municipality_key = row["municipality_key"]
        if not isinstance(municipality_key, str):
            municipality_key = None
        department, municipality = _resolve(
            row["department_key"], municipality_key, by_code, by_name, departments
        )
        if department is None:
            reason = f"unknown municipality: {row['department_key']}/{municipality_key or 'DEPARTAMENTO'}"
            discarded[reason] += 1
            continue
        instances.append(
            UngrdRecord(
                source_row=int(row["source_row"]),
                source_code=row["source_code"],
                occurred_on=row["occurred_on"],
                department=department,
                municipality=municipality,
                emergency_type_id=type_ids[row["event_type"]],
                **{field: int(row[field]) for field in COUNT_FIELDS},
                hectares=float(row["hectares"]),
                comments=row["comments"],
                action_codes=list(row["action_codes"]),
                is_high_impact=bool(row["is_high_impact"]),
            )
        )

    UngrdRecord.objects.bulk_create(
        instances,
        batch_size=BATCH_SIZE,
        update_conflicts=True,
        unique_fields=["source_row"],
        update_fields=UPDATE_FIELDS,
    )
    return BaselineReport(
        records=len(instances),
        discarded=+discarded,
        types_created=types_created,
        municipalities=municipalities,
    )
