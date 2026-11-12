from django.db import migrations

SEEDED_NAMES = (
    "Air transport accident",
    "Coastal erosion",
    "Debris flow",
    "Drought",
    "Drowning",
    "Earthquake",
    "Electrical storm",
    "Erosion",
    "Explosion",
    "Flash flood",
    "Flood",
    "Fortuitous event",
    "Frost",
    "Hailstorm",
    "Hazardous leak",
    "Landslide",
    "Maritime accident",
    "Mining accident",
    "Other fire",
    "River accident",
    "Road transport accident",
    "Structural collapse",
    "Structural fire",
    "Technological accident",
    "Volcanic activity",
    "Water shortage",
    "Wildfire",
    "Windstorm",
)


def set_seed_keys(apps, schema_editor):
    EmergencyType = apps.get_model("emergencies", "EmergencyType")
    for emergency_type in EmergencyType.objects.filter(name__in=SEEDED_NAMES):
        emergency_type.seed_key = emergency_type.name
        emergency_type.save(update_fields=["seed_key"])


def clear_seed_keys(apps, schema_editor):
    EmergencyType = apps.get_model("emergencies", "EmergencyType")
    EmergencyType.objects.update(seed_key=None)


class Migration(migrations.Migration):

    dependencies = [
        ("emergencies", "0002_emergencytype_seed_key"),
    ]

    operations = [
        migrations.RunPython(set_seed_keys, clear_seed_keys),
    ]
