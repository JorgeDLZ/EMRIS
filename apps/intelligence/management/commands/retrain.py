from django.core.management.base import BaseCommand, CommandError

from apps.intelligence import training
from apps.intelligence.models import TrainingRun


class Command(BaseCommand):
    help = "Retrain every intelligence model and activate the candidates that qualify."

    def handle(self, *args, **options):
        try:
            runs = training.start_runs(None)
        except training.RetrainInProgress as exc:
            raise CommandError(str(exc)) from exc
        training.execute_runs(runs)
        finished = TrainingRun.objects.filter(pk__in=[run.pk for run in runs]).order_by("pk")
        for run in finished:
            self.stdout.write(
                f"{run.get_component_display()}: {run.get_status_display()} — {run.message}"
            )
        failed = [run.get_component_display() for run in finished if run.status == TrainingRun.FAILED]
        if failed:
            raise CommandError(f"Training failed for: {', '.join(failed)}")
