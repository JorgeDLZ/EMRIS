from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.places.models import Municipality
from apps.seismic.services import load_seismic


class Command(BaseCommand):
    help = "Load the SGC seismic catalog and link events to municipalities."

    def add_arguments(self, parser):
        parser.add_argument("--path", default=str(settings.BASE_DIR / "data" / "sgc_seismicity_m25.csv"))

    def handle(self, *args, **options):
        if not Municipality.objects.exists():
            raise CommandError("Run load_baseline first: no municipalities are loaded.")
        report = load_seismic(options["path"])
        self.stdout.write(f"Events loaded: {report.loaded}")
        self.stdout.write(f"Linked to a municipality: {report.matched}")
        self.stdout.write(f"Without a municipality: {report.unmatched}")
