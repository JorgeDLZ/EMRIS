from django.conf import settings
from django.core.management.base import BaseCommand

from apps.history.services import load_baseline


class Command(BaseCommand):
    help = "Load places, emergency types and the cleaned UNGRD records."

    def add_arguments(self, parser):
        data_dir = settings.BASE_DIR / "data"
        parser.add_argument("--ungrd", default=str(data_dir / "ungrd_emergencies_v2.csv"))
        parser.add_argument("--divipola", default=str(data_dir / "divipola_dane.csv"))

    def handle(self, *args, **options):
        report = load_baseline(options["ungrd"], options["divipola"])
        self.stdout.write(f"Municipalities loaded: {report.municipalities}")
        self.stdout.write(f"Emergency types created: {report.types_created}")
        self.stdout.write(f"Records loaded: {report.records}")
        for reason, count in sorted(report.discarded.items()):
            self.stdout.write(f"Discarded - {reason}: {count}")
