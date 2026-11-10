import csv
from difflib import SequenceMatcher
from pathlib import Path

from django.db import transaction

from apps.accounts.roles import OPERATOR, get_role
from ml.text import normalize_name

from .models import Department, Municipality


class DuplicateMunicipality(Exception):
    pass


@transaction.atomic
def load_divipola(path: str | Path) -> int:
    with open(path, encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))

    departments = {
        row["department_code"]: Department(
            code=row["department_code"],
            name=row["department_name"],
            name_key=normalize_name(row["department_name"]),
        )
        for row in rows
    }
    Department.objects.bulk_create(
        departments.values(),
        update_conflicts=True,
        unique_fields=["code"],
        update_fields=["name", "name_key"],
    )
    department_ids = dict(Department.objects.values_list("code", "id"))

    municipalities = [
        Municipality(
            department_id=department_ids[row["department_code"]],
            code=row["municipality_code"],
            name=row["municipality_name"],
            name_key=normalize_name(row["municipality_name"]),
            latitude=float(row["latitude"]) if row["latitude"] else None,
            longitude=float(row["longitude"]) if row["longitude"] else None,
            source=Municipality.OFFICIAL,
            validation=Municipality.APPROVED,
        )
        for row in rows
    ]
    Municipality.objects.bulk_create(
        municipalities,
        update_conflicts=True,
        unique_fields=["code"],
        update_fields=["department", "name", "name_key", "latitude", "longitude", "source", "validation"],
    )
    return len(municipalities)


def find_similar(department: Department, name: str, cutoff: float = 0.75) -> list[Municipality]:
    key = normalize_name(name)
    return [
        municipality
        for municipality in Municipality.objects.filter(department=department)
        if SequenceMatcher(None, key, municipality.name_key).ratio() >= cutoff
    ]


def register_municipality(department: Department, name: str, actor) -> Municipality:
    key = normalize_name(name)
    if Municipality.objects.filter(department=department, name_key=key).exists():
        raise DuplicateMunicipality(f"{name} already exists in {department.name}")
    validation = Municipality.PENDING if get_role(actor) == OPERATOR else Municipality.APPROVED
    return Municipality.objects.create(
        department=department,
        name=name.strip(),
        source=Municipality.USER,
        validation=validation,
        created_by=actor,
    )


def approve_municipality(municipality: Municipality) -> None:
    municipality.validation = Municipality.APPROVED
    municipality.save(update_fields=["validation"])


def reject_municipality(municipality: Municipality) -> None:
    if municipality.validation != Municipality.PENDING:
        raise ValueError("Only pending municipalities can be rejected")
    municipality.delete()
