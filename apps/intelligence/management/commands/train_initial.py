from django.core.management.base import BaseCommand, CommandError

from apps.intelligence import training


class Command(BaseCommand):
    help = "Train and activate the first version of every intelligence model."

    def handle(self, *args, **options):
        try:
            versions = training.train_initial()
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        for version in versions:
            self.stdout.write(f"{version}: {version.primary_metric} {version.score:.3f}")
