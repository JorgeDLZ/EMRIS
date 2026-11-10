from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.places.services import load_divipola
from apps.seismic.models import SeismicEvent
from apps.seismic.services import load_seismic

DATA = Path(__file__).resolve().parents[3] / "data"
EXTRACT = DATA / "sgc_seismicity_m25.csv"
DIVIPOLA = DATA / "divipola_dane.csv"

HEADER = (
    "id,status,rms,agency,gap,place,local_time,utc_time,magnitude,magnitude_error,"
    "nst,mag_type,latitude,latitude_error,longitude,longitude_error,depth,depth_error\n"
)


def test_real_extract_loads_and_reloads(db):
    load_divipola(DIVIPOLA)
    report = load_seismic(EXTRACT)
    assert (report.loaded, report.matched, report.unmatched) == (14332, 12266, 2066)
    load_seismic(EXTRACT)
    assert SeismicEvent.objects.count() == 14332
    assert SeismicEvent.objects.filter(place__contains="Ã").count() == 0


def test_command_requires_places(db):
    with pytest.raises(CommandError, match="Run load_baseline first: no municipalities are loaded."):
        call_command("load_seismic", path=str(EXTRACT))
    assert SeismicEvent.objects.count() == 0


def test_foreign_event_has_no_place_link(db, tmp_path):
    load_divipola(DIVIPOLA)
    path = tmp_path / "foreign.csv"
    path.write_text(
        HEADER
        + 'SGC1,manual,1.0,SGC,75,"Venezuela - Colombia, Región Fronteriza",'
        "2026-11-02 23:57:06,2026-11-03 04:57:06,2.6,0.3,25,MLr,7.05,1.1,-71.92,1.1,1,2\n",
        encoding="utf-8",
    )
    report = load_seismic(path)
    assert (report.loaded, report.matched, report.unmatched) == (1, 0, 1)
    event = SeismicEvent.objects.get()
    assert event.department is None and event.municipality is None
