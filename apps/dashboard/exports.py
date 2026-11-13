from collections.abc import Callable, Iterable
from datetime import date, datetime
from io import BytesIO

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
RANKING_LEVEL = RANKING_HEADER.index("level")
RANKING_K = RANKING_HEADER.index("k")
HISTORY_HIGH_IMPACT = HISTORY_HEADER.index("is_high_impact")
INSUFFICIENT_HISTORY = "Insufficient history"
XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
DATE_TIME_FORMAT = "yyyy-mm-dd hh:mm"
DATE_FORMAT = "yyyy-mm-dd"
COLUMN_FORMATS = {"priority": "0.000"}
HEADER_COLOR = "1F4E78"
HIGHLIGHT_COLOR = "FCE4E4"
MIN_WIDTH = 8
MAX_WIDTH = 50


def _display_length(value) -> int:
    if isinstance(value, datetime):
        return len(DATE_TIME_FORMAT)
    if isinstance(value, date):
        return len(DATE_FORMAT)
    return len(str(value))


def xlsx_response(
    filename: str,
    sheet_title: str,
    header: list[str],
    rows: Iterable[list],
    highlight: Callable[[list], bool] | None = None,
) -> HttpResponse:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = sheet_title
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor=HEADER_COLOR)
    highlight_fill = PatternFill("solid", fgColor=HIGHLIGHT_COLOR)
    widths = [len(name) for name in header]
    worksheet.append(header)
    for cell in worksheet[1]:
        cell.data_type = "s"
        cell.font = header_font
        cell.fill = header_fill
    for row_number, row in enumerate(rows, start=2):
        worksheet.append(row)
        flagged = highlight is not None and highlight(row)
        for column, value in enumerate(row, start=1):
            cell = worksheet.cell(row=row_number, column=column)
            if isinstance(value, str):
                cell.data_type = "s"
            elif isinstance(value, datetime):
                cell.number_format = DATE_TIME_FORMAT
            elif isinstance(value, date):
                cell.number_format = DATE_FORMAT
            elif header[column - 1] in COLUMN_FORMATS:
                cell.number_format = COLUMN_FORMATS[header[column - 1]]
            if flagged:
                cell.fill = highlight_fill
            if value is not None:
                widths[column - 1] = max(widths[column - 1], _display_length(value))
    for column, width in enumerate(widths, start=1):
        worksheet.column_dimensions[get_column_letter(column)].width = min(
            max(width + 2, MIN_WIDTH), MAX_WIDTH
        )
    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = worksheet.dimensions
    buffer = BytesIO()
    workbook.save(buffer)
    response = HttpResponse(buffer.getvalue(), content_type=XLSX_CONTENT_TYPE)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _local(moment) -> datetime | None:
    return timezone.localtime(moment).replace(tzinfo=None) if moment else None


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


def _risk_level(output: dict | None) -> str | None:
    if output is None:
        return None
    if output["level"] is None:
        return INSUFFICIENT_HISTORY
    return f"{output['level']} of {output['k']}"


def _priority(output: dict | None) -> float | None:
    if output is None or output["probability"] is None:
        return None
    return round(output["probability"], 3)


def _impact_values(impact) -> list:
    if impact is None:
        return [None] * len(IMPACT_FIELDS)
    return [getattr(impact, field) for field in IMPACT_FIELDS]


def emergency_rows(emergencies) -> tuple[list[list], Callable[[list], bool]]:
    """Return the rows and a predicate that flags those estimated as high impact."""
    emergencies = list(
        emergencies.select_related("emergency_type", "municipality__department", "impact").order_by(
            "-occurred_at", "pk"
        )
    )
    latest = _latest_outputs([emergency.pk for emergency in emergencies])
    rows = []
    high_impact_ids = set()
    for emergency in emergencies:
        impact = getattr(emergency, "impact", None)
        estimate = latest.get((emergency.pk, IMPACT))
        profile = latest.get((emergency.pk, PROFILES))
        if estimate and estimate.get("is_high_impact"):
            high_impact_ids.add(emergency.pk)
        rows.append(
            [
                emergency.pk,
                _local(emergency.occurred_at),
                emergency.emergency_type.name,
                emergency.municipality.name,
                emergency.municipality.department.name,
                emergency.get_status_display(),
                _priority(estimate),
                profile["profile"] if profile else None,
                _risk_level(latest.get((emergency.pk, MUNICIPAL_RISK))),
                *_impact_values(impact),
                _local(emergency.closed_at),
            ]
        )
    return rows, lambda row: row[0] in high_impact_ids


def ranking_rows(ranking) -> list[list]:
    rows = []
    for row in ranking.rows:
        municipality = row.municipality
        rows.append(
            [
                row.position,
                row.code,
                municipality.name if municipality else row.code,
                municipality.department.name if municipality else None,
                row.level,
                row.k,
            ]
        )
    return rows


def is_top_risk(row: list) -> bool:
    return row[RANKING_LEVEL] == row[RANKING_K]


def history_rows(records) -> list[list]:
    labels = dict(ACTION_CODE_CHOICES)
    return [
        [
            record.source_row,
            record.occurred_on,
            record.emergency_type.name,
            record.department.name,
            record.municipality.name if record.municipality else None,
            *[getattr(record, field) for field in IMPACT_FIELDS],
            "Yes" if record.is_high_impact else "No",
            "; ".join(labels.get(code, code) for code in record.action_codes),
        ]
        for record in records
    ]


def is_high_impact_record(row: list) -> bool:
    return row[HISTORY_HIGH_IMPACT] == "Yes"
