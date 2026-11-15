from pathlib import Path

from django.urls import reverse

from ml.data import clean_ungrd

DATA = Path(__file__).resolve().parents[2] / "data"


def test_data_figures_match_the_source_files(client, db):
    result = clean_ungrd(DATA / "ungrd_emergencies_v2.csv")
    html = client.get(reverse("home")).content.decode()
    section = html[html.index('id="data-engineering"') : html.index('id="model-engineering"')]
    assert f"{len(result.records):,}" in section
    for reason, count in result.discarded.items():
        assert f"{count:,}" in section and reason in section
