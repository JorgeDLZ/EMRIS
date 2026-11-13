import datetime
from urllib.parse import urlencode

from apps.history.models import UngrdRecord
from ml.text import normalize_name

HISTORY_PAGE_SIZE = 50


def _iso_date(value):
    try:
        return datetime.date.fromisoformat(value).isoformat()
    except ValueError:
        return ""


def _param(params, key):
    return params.get(key, "").replace("\x00", "").strip()


def filter_records(params):
    cleaned = {
        "type": _param(params, "type"),
        "department": _param(params, "department"),
        "q": _param(params, "q"),
        "from": _iso_date(_param(params, "from")),
        "to": _iso_date(_param(params, "to")),
        "high": _param(params, "high"),
    }
    if not (cleaned["type"].isascii() and cleaned["type"].isdigit() and len(cleaned["type"]) <= 9):
        cleaned["type"] = ""
    if len(cleaned["department"]) != 2:
        cleaned["department"] = ""
    if cleaned["high"] != "1":
        cleaned["high"] = ""

    records = UngrdRecord.objects.select_related("emergency_type", "department", "municipality")
    if cleaned["type"]:
        records = records.filter(emergency_type_id=int(cleaned["type"]))
    if cleaned["department"]:
        records = records.filter(department__code=cleaned["department"])
    if cleaned["q"]:
        records = records.filter(municipality__name_key__icontains=normalize_name(cleaned["q"]))
    if cleaned["from"]:
        records = records.filter(occurred_on__gte=cleaned["from"])
    if cleaned["to"]:
        records = records.filter(occurred_on__lte=cleaned["to"])
    if cleaned["high"]:
        records = records.filter(is_high_impact=True)
    return records.order_by("-occurred_on", "-source_row"), cleaned


def querystring(cleaned):
    return urlencode({key: value for key, value in cleaned.items() if value})
