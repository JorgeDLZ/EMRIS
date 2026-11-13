from django.utils import timezone

from apps.emergencies.models import CLOSED, Emergency, Impact
from apps.history.models import UngrdRecord
from apps.places.models import Municipality
from apps.plans.models import Action
from apps.seismic.models import SeismicEvent


def _municipality_key(pk, code) -> str:
    if pk is None:
        return ""
    return code or f"user-{pk}"


def municipality_id(municipality) -> str:
    if municipality is None:
        return ""
    return _municipality_key(municipality.pk, municipality.code)


def _impact_values(impact) -> dict:
    from ml.features import IMPACT_VARIABLES

    return {name: getattr(impact, name, 0) for name in IMPACT_VARIABLES}


def _ordered_codes(codes) -> list[str]:
    from ml.actions import ACTION_VOCABULARY

    present = set(codes)
    return [code for code in ACTION_VOCABULARY if code in present]


def _row(reference, occurred_on, event_type, department, municipality, impact, has_impact, codes):
    from ml.features import IMPACT_VARIABLES

    return {
        "reference": reference,
        "occurred_on": occurred_on,
        "event_type": event_type,
        "department": department,
        "municipality": municipality,
        **{name: float(impact[name]) for name in IMPACT_VARIABLES},
        "has_impact": has_impact,
        "action_codes": _ordered_codes(codes),
        "is_high_impact": False,
    }


def _frame(rows):
    import pandas as pd

    from ml.features import FRAME_COLUMNS

    return pd.DataFrame(rows, columns=list(FRAME_COLUMNS))


def build_training_frame():
    from ml.data import high_impact_mask
    from ml.features import IMPACT_VARIABLES

    rows = []
    history = UngrdRecord.objects.values(
        "source_row", "occurred_on", "emergency_type__name", "department__code",
        "municipality_id", "municipality__code", "action_codes", *IMPACT_VARIABLES,
    )
    for record in history.iterator():
        rows.append(
            _row(
                f"ungrd:{record['source_row']}",
                record["occurred_on"],
                record["emergency_type__name"],
                record["department__code"],
                _municipality_key(record["municipality_id"], record["municipality__code"]),
                record,
                True,
                record["action_codes"],
            )
        )

    plan_codes: dict[int, set[str]] = {}
    for emergency_id, code in Action.objects.filter(
        plan__emergency__status=CLOSED, plan__emergency__impact__isnull=False
    ).exclude(code="").values_list("plan__emergency_id", "code"):
        plan_codes.setdefault(emergency_id, set()).add(code)
    closed = Emergency.objects.filter(status=CLOSED, impact__isnull=False).select_related(
        "emergency_type", "municipality__department", "impact"
    )
    for emergency in closed:
        rows.append(
            _row(
                f"emergency:{emergency.pk}",
                timezone.localtime(emergency.occurred_at).date(),
                emergency.emergency_type.name,
                emergency.municipality.department.code,
                municipality_id(emergency.municipality),
                _impact_values(emergency.impact),
                True,
                plan_codes.get(emergency.pk, ()),
            )
        )

    frame = _frame(rows)
    if frame.empty:
        return frame
    frame["is_high_impact"] = high_impact_mask(frame)
    return frame.sort_values(["occurred_on", "reference"]).reset_index(drop=True)


def emergency_frame(emergency):
    impact = Impact.objects.filter(emergency=emergency).first()
    values = _impact_values(impact)
    codes = Action.objects.filter(plan__emergency=emergency).exclude(code="").values_list(
        "code", flat=True
    )
    municipality = emergency.municipality
    return _frame(
        [
            _row(
                f"emergency:{emergency.pk}",
                timezone.localtime(emergency.occurred_at).date(),
                emergency.emergency_type.name,
                municipality.department.code,
                municipality_id(municipality),
                values,
                impact is not None,
                codes,
            )
        ]
    )


def seismic_inputs():
    from ml.seismic import seismic_features

    centroids = {
        municipality_id(municipality): (
            (municipality.latitude, municipality.longitude)
            if municipality.latitude is not None and municipality.longitude is not None
            else None
        )
        for municipality in Municipality.objects.all()
    }
    return seismic_features(centroids, SeismicEvent.objects.iterator())
