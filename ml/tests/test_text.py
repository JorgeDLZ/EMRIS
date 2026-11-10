from ml.text import normalize_name, repair_mojibake


def test_normalize_name():
    assert normalize_name(" Bogotá,  d.c. ") == "BOGOTA, D.C."
    assert normalize_name("NARIÑO") == "NARINO"


def test_repair_mojibake():
    assert repair_mojibake("BolÃ­var") == "Bolívar"
    assert repair_mojibake("Bolívar") == "Bolívar"
    assert repair_mojibake("Ã") == "Ã"
