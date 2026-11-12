from collections.abc import Iterable

from django.db import transaction

from .models import EmergencyType


@transaction.atomic
def seed_emergency_types(names: Iterable[str]) -> int:
    created_count = 0
    for name in names:
        if EmergencyType.objects.filter(seed_key=name).exists():
            continue
        existing = EmergencyType.objects.filter(name__iexact=name, seed_key__isnull=True).first()
        if existing is None:
            EmergencyType.objects.create(name=name, seed_key=name)
            created_count += 1
        else:
            existing.seed_key = name
            existing.save(update_fields=["seed_key"])
    return created_count
