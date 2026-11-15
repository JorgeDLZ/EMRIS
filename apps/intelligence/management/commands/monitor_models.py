from django.core.management.base import BaseCommand, CommandError

from apps.intelligence.monitoring import MonitoringUnavailable, run_check


class Command(BaseCommand):
    help = "Run a monitoring check of the active impact estimator and save it."

    def add_arguments(self, parser):
        parser.add_argument(
            "--simulate",
            action="store_true",
            help="Use simulated emergencies instead of the registered ones.",
        )

    def handle(self, *args, simulate=False, **options):
        try:
            check = run_check(simulate=simulate)
        except MonitoringUnavailable as error:
            raise CommandError(str(error)) from error
        if simulate:
            self.stdout.write("Simulated data")
        self.stdout.write(f"Status: {check.get_status_display()}")
        self.stdout.write(f"Window: {check.window_start} to {check.window_end}")
        for name, value in check.indicators.items():
            if name != "alerts":
                self.stdout.write(f"{name}: {value}")
        for alert in check.indicators["alerts"]:
            self.stdout.write(f"Alert: {alert}")
