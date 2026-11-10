from collections.abc import Iterable

from django.db import transaction

from .models import EmergencyType


@transaction.atomic
def seed_emergency_types(names: Iterable[str]) -> int:
    created_count = 0
    for name in names:
        _, created = EmergencyType.objects.get_or_create(name=name)
        created_count += created
    return created_count
