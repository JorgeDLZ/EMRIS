from collections import Counter
from datetime import timedelta

from django.db.models import Max, QuerySet

from apps.emergencies.models import CLOSED, CONTROLLED, IN_RESPONSE, REPORTED, Emergency
from apps.emergencies.workflow import LABELS
from apps.intelligence.models import PROFILES, Prediction
from apps.seismic.models import SeismicEvent

TOP_MUNICIPALITIES = 10
PROFILE_PENDING = "Profile pending"
ACTIVE_STATUSES = (REPORTED, IN_RESPONSE, CONTROLLED)
SEISMIC_WINDOW = timedelta(days=30)
SEISMIC_MIN_MAGNITUDE = 4.0
SEISMIC_MAX_ROWS = 20


def _ranked(counter: Counter) -> list[tuple]:
    return sorted(counter.items(), key=lambda item: (-item[1], item[0]))


def _latest_profiles(emergency_ids: list[int]) -> dict[int, str]:
    rows = (
        Prediction.objects.filter(emergency_id__in=emergency_ids, component=PROFILES)
        .order_by("emergency_id", "-created_at", "-pk")
        .values_list("emergency_id", "output")
    )
    latest = {}
    for emergency_id, output in rows:
        latest.setdefault(emergency_id, output["profile"])
    return latest


def emergency_summary(emergencies: QuerySet[Emergency]) -> dict:
    active = list(
        emergencies.filter(status__in=ACTIVE_STATUSES)
        .order_by()
        .values_list(
            "pk", "status", "emergency_type__name", "municipality__name", "municipality__department__name"
        )
    )
    profiles = _latest_profiles([row[0] for row in active])
    by_status = Counter(row[1] for row in active)
    by_municipality = Counter((row[3], row[4]) for row in active)
    top_municipalities = sorted(by_municipality.items(), key=lambda item: (-item[1], item[0]))
    return {
        "active": len(active),
        "closed": emergencies.filter(status=CLOSED).count(),
        "by_status": [(LABELS[status], by_status[status]) for status in ACTIVE_STATUSES],
        "by_type": _ranked(Counter(row[2] for row in active)),
        "by_municipality": [
            (municipality, department, count)
            for (municipality, department), count in top_municipalities[:TOP_MUNICIPALITIES]
        ],
        "by_profile": _ranked(Counter(profiles.get(row[0], PROFILE_PENDING) for row in active)),
    }


def seismic_activity() -> dict:
    catalog_end = SeismicEvent.objects.aggregate(latest=Max("event_time"))["latest"]
    if catalog_end is None:
        return {"catalog_end": None, "window_start": None, "event_count": 0, "events": []}
    window_start = catalog_end - SEISMIC_WINDOW
    window = SeismicEvent.objects.filter(event_time__gte=window_start, event_time__lte=catalog_end)
    events = (
        window.filter(magnitude__gte=SEISMIC_MIN_MAGNITUDE)
        .select_related("municipality__department")
        .order_by("-magnitude", "-event_time")[:SEISMIC_MAX_ROWS]
    )
    return {
        "catalog_end": catalog_end,
        "window_start": window_start,
        "event_count": window.count(),
        "events": list(events),
    }
