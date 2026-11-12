from django.db import transaction
from django.utils import timezone

from .models import (
    CLOSED,
    CONTROLLED,
    IN_RESPONSE,
    REPORTED,
    STATUS_CHOICES,
    Emergency,
    Impact,
    StatusLog,
)

TRANSITIONS = {
    REPORTED: (IN_RESPONSE,),
    IN_RESPONSE: (CONTROLLED,),
    CONTROLLED: (CLOSED, IN_RESPONSE),
    CLOSED: (),
}

LABELS = dict(STATUS_CHOICES)


class WorkflowError(Exception):
    pass


def ensure_open(emergency: Emergency) -> None:
    if emergency.is_closed:
        raise WorkflowError("This emergency is closed.")


def lock_open(emergency: Emergency) -> Emergency:
    locked = Emergency.objects.select_for_update().get(pk=emergency.pk)
    ensure_open(locked)
    return locked


def _sync(emergency: Emergency, locked: Emergency) -> None:
    emergency.status = locked.status
    emergency.closed_at = locked.closed_at
    emergency.updated_at = locked.updated_at


@transaction.atomic
def create_emergency(actor, **fields) -> Emergency:
    emergency = Emergency.objects.create(status=REPORTED, reported_by=actor, **fields)
    StatusLog.objects.create(
        emergency=emergency, status=REPORTED, note="Emergency reported", author=actor
    )
    return emergency


@transaction.atomic
def change_status(emergency: Emergency, new_status: str, actor, note: str = "") -> None:
    locked = lock_open(emergency)
    current = locked.status
    if new_status not in TRANSITIONS[current]:
        raise WorkflowError(
            f"Cannot move from {LABELS[current]} to {LABELS.get(new_status, new_status)}."
        )
    if new_status == CLOSED and not Impact.objects.filter(emergency=locked).exists():
        raise WorkflowError("Record the impact before closing.")
    locked.status = new_status
    locked.closed_at = timezone.now() if new_status == CLOSED else None
    locked.save(update_fields=["status", "closed_at", "updated_at"])
    StatusLog.objects.create(
        emergency=locked,
        status=new_status,
        previous_status=current,
        note=note,
        author=actor,
    )
    _sync(emergency, locked)


@transaction.atomic
def add_note(emergency: Emergency, actor, note: str) -> StatusLog:
    locked = lock_open(emergency)
    note = note.strip()
    if not note:
        raise WorkflowError("Write a note.")
    entry = StatusLog.objects.create(
        emergency=locked, status=locked.status, note=note, author=actor
    )
    _sync(emergency, locked)
    return entry


@transaction.atomic
def save_impact(emergency: Emergency, actor, values: dict) -> Impact:
    locked = lock_open(emergency)
    impact, _ = Impact.objects.update_or_create(
        emergency=locked, defaults={**values, "recorded_by": actor}
    )
    _sync(emergency, locked)
    return impact
