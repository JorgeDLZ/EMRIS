import csv
from collections.abc import Iterable

from django.http import HttpResponse
from django.utils import timezone

from apps.intelligence.models import IMPACT, MUNICIPAL_RISK, PROFILES, Prediction
from apps.plans.models import ACTION_CODE_CHOICES

IMPACT_FIELDS = [
    "deceased",
    "injured",
    "missing",
    "people_affected",
    "families_affected",
    "homes_destroyed",
    "homes_damaged",
    "roads_damaged",
    "bridges_damaged",
    "hectares",
]
EMERGENCY_HEADER = [
    "id", "occurred_at", "type", "municipality", "department", "status", "priority", "profile",
    "risk_level", *IMPACT_FIELDS, "closed_at",
]
RANKING_HEADER = ["position", "municipality_code", "municipality", "department", "level", "k"]
HISTORY_HEADER = [
    "source_row", "occurred_on", "type", "department", "municipality", *IMPACT_FIELDS,
    "is_high_impact", "actions",
]
INSUFFICIENT_HISTORY = "Insufficient history"
DATE_TIME_FORMAT = "%Y-%m-%d %H:%M"


def csv_response(filename: str, header: list[str], rows: Iterable[list]) -> HttpResponse:
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(header)
    writer.writerows(rows)
    return response


def _local(moment) -> str:
    return timezone.localtime(moment).strftime(DATE_TIME_FORMAT) if moment else ""


def _latest_outputs(emergency_ids: list[int]) -> dict[tuple[int, str], dict]:
    rows = (
        Prediction.objects.filter(
            emergency_id__in=emergency_ids, component__in=(IMPACT, PROFILES, MUNICIPAL_RISK)
        )
        .order_by("-created_at", "-pk")
        .values_list("emergency_id", "component", "output")
    )
    latest = {}
    for emergency_id, component, output in rows:
        latest.setdefault((emergency_id, component), output)
    return latest


def _risk_level(output: dict | None) -> str:
    if output is None:
        return ""
    if output["level"] is None:
        return INSUFFICIENT_HISTORY
    return f"{output['level']} of {output['k']}"


def _priority(output: dict | None) -> str:
    if output is None or output["probability"] is None:
        return ""
    return f"{output['probability']:.3f}"


def _impact_values(impact) -> list:
    if impact is None:
        return [""] * len(IMPACT_FIELDS)
    return [getattr(impact, field) for field in IMPACT_FIELDS]


def emergency_rows(emergencies) -> list[list]:
    emergencies = list(
        emergencies.select_related("emergency_type", "municipality__department", "impact").order_by(
            "-occurred_at", "pk"
        )
    )
    latest = _latest_outputs([emergency.pk for emergency in emergencies])
    rows = []
    for emergency in emergencies:
        impact = getattr(emergency, "impact", None)
        profile = latest.get((emergency.pk, PROFILES))
        rows.append(
            [
                emergency.pk,
                _local(emergency.occurred_at),
                emergency.emergency_type.name,
                emergency.municipality.name,
                emergency.municipality.department.name,
                emergency.get_status_display(),
                _priority(latest.get((emergency.pk, IMPACT))),
                profile["profile"] if profile else "",
                _risk_level(latest.get((emergency.pk, MUNICIPAL_RISK))),
                *_impact_values(impact),
                _local(emergency.closed_at),
            ]
        )
    return rows


def ranking_rows(ranking) -> list[list]:
    rows = []
    for row in ranking.rows:
        municipality = row.municipality
        rows.append(
            [
                row.position,
                row.code,
                municipality.name if municipality else row.code,
                municipality.department.name if municipality else "",
                row.level,
                row.k,
            ]
        )
    return rows


def history_rows(records) -> list[list]:
    labels = dict(ACTION_CODE_CHOICES)
    return [
        [
            record.source_row,
            record.occurred_on.isoformat(),
            record.emergency_type.name,
            record.department.name,
            record.municipality.name if record.municipality else "",
            *[getattr(record, field) for field in IMPACT_FIELDS],
            "true" if record.is_high_impact else "false",
            "; ".join(labels.get(code, code) for code in record.action_codes),
        ]
        for record in records
    ]
