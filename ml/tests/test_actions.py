from pathlib import Path

from ml.actions import ACTION_VOCABULARY, extract_actions
from ml.data import clean_ungrd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"


def test_extracts_from_actions_section():
    comment = "ACCIONES: ATIENDE CMGRD Y MAQUINARIA AMARILLA, SE REALIZA EDAN ESTADO: CERRADO"
    assert extract_actions(comment) == [
        "activate_municipal_council",
        "deploy_heavy_machinery",
        "assess_damage",
    ]


def test_extracts_from_firefighter_report():
    comment = "ATENDIDO POR: 3 UNIDADES DE BOMBEROS CON 1 VEHICULOS. AFECTACION: 5 HECTAREAS"
    assert extract_actions(comment) == ["deploy_fire_brigade"]


def test_text_outside_sections_is_ignored():
    comment = "AFECTACION: 1 EVACUACION ACCIONES: ATIENDE CMGRD"
    assert "evacuate_population" not in extract_actions(comment)
    assert extract_actions(comment) == ["activate_municipal_council"]


def test_dotted_civil_defense():
    comment = "Acciones: APOYAN CMGRD, D.C.C."
    assert "deploy_civil_defense" in extract_actions(comment)


def test_accents_and_case_are_normalized():
    assert extract_actions("Acción: Evacuación preventiva") == ["evacuate_population"]


def test_no_section_returns_empty():
    assert extract_actions("No Registra") == []


def test_labels_are_unique_and_english():
    labels = [rule.label for rule in ACTION_VOCABULARY.values()]
    assert len(ACTION_VOCABULARY) == 16
    assert len(set(labels)) == 16
    assert all(label.isascii() for label in labels)


def test_real_dataset_coverage():
    records = clean_ungrd(DATA / "ungrd_emergencies_v2.csv").records
    assert (records["action_codes"].str.len() > 0).sum() == 6437
    assert sum("deploy_fire_brigade" in codes for codes in records["action_codes"]) == 4099
