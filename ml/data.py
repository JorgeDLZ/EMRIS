import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from ml.actions import extract_actions
from ml.features import FRAME_COLUMNS
from ml.text import normalize_name, repair_mojibake

DEPARTMENT_LEVEL = "DEPARTAMENTO"
REFERENCE_PREFIX = "ungrd:"

EVENT_TYPE_LABELS: dict[str, str] = {
    "INCENDIO FORESTAL": "Wildfire",
    "MOVIMIENTO EN MASA": "Landslide",
    "INUNDACION": "Flood",
    "VENDAVAL": "Windstorm",
    "INCENDIO ESTRUCTURAL": "Structural fire",
    "CRECIENTE SUBITA": "Flash flood",
    "ACCIDENTE TRANSPORTE TERRESTRE": "Road transport accident",
    "ACCIDENTE DE TRANSPORTE TERRESTRE": "Road transport accident",
    "AVENIDA TORRENCIAL": "Debris flow",
    "CASO FORTUITO": "Fortuitous event",
    "COLAPSO ESTRUCTURAL": "Structural collapse",
    "SISMO": "Earthquake",
    "INCENDIO": "Other fire",
    "ACTIVIDAD VOLCANICA": "Volcanic activity",
    "ACCIDENTE TECNOLOGICO": "Technological accident",
    "ACCIDENTE MINERO": "Mining accident",
    "TORMENTA ELECTRICA": "Electrical storm",
    "SEQUIA": "Drought",
    "INMERSION": "Drowning",
    "ACCIDENTE TRANSPORTE AEREO": "Air transport accident",
    "EROSION": "Erosion",
    "ACCIDENTE FLUVIAL": "River accident",
    "DESABASTECIMIENTO DE AGUA": "Water shortage",
    "GRANIZADA": "Hailstorm",
    "EROSION COSTERA": "Coastal erosion",
    "ACCIDENTE MARITIMO": "Maritime accident",
    "HELADA": "Frost",
    "EXPLOSION": "Explosion",
    "FUGA": "Hazardous leak",
}

MUNICIPALITY_ALIASES: dict[tuple[str, str], str] = {
    ("VALLE DEL CAUCA", "CALI"): "76001",
    ("CUNDINAMARCA", "BOGOTA, D.C."): "11001",
    ("CUNDINAMARCA", "SAN JUAN DE RIO SECO"): "25662",
    ("ANTIOQUIA", "SAN VICENTE"): "05674",
    ("CAUCA", "SOTARA"): "19760",
    ("NORTE DE SANTANDER", "CUCUTA"): "54001",
    ("BOLIVAR", "CARTAGENA"): "13001",
    ("TOLIMA", "MARIQUITA"): "73443",
    ("CESAR", "MANAURE"): "20443",
    ("BOLIVAR", "MOMPOS"): "13468",
    ("CAUCA", "PIENDAMO"): "19548",
    ("ANTIOQUIA", "SANTAFE DE ANTIOQUIA"): "05042",
    ("META", "LA URIBE"): "50370",
    ("CHOCO", "BELEN DE BAJIRA"): "27493",
    ("MAGDALENA", "CHIBOLO"): "47170",
    ("CHOCO", "CANTON DE SAN PABLO"): "27135",
    ("BOYACA", "GUICAN"): "15332",
    ("CUNDINAMARCA", "UBATE"): "25843",
    ("ANTIOQUIA", "DON MATIAS"): "05237",
    ("CORDOBA", "PURISIMA"): "23586",
    ("NARINO", "CUASPUD"): "52224",
    ("SUCRE", "TOLU VIEJO"): "70823",
    ("NARINO", "MAGUI PAYAN"): "52427",
    ("SAN ANDRES", "SAN ANDRES"): "88001",
    ("SAN ANDRES", "PROVIDENCIA"): "88564",
}

DATE_FORMAT = "%Y %b %d %I:%M:%S %p"

NUMERIC_COLUMNS = {
    "deceased": "FALLECIDOS",
    "injured": "HERIDOS",
    "missing": "DESAPARECIDOS",
    "people_affected": "PERSONAS",
    "families_affected": "FAMILIAS",
    "homes_destroyed": "VIVIENDAS DESTRUIDAS",
    "homes_damaged": "VIVIVIENDAS AVERIADAS",
    "roads_damaged": "VIAS",
    "hectares": "HECTAREAS",
}

REQUIRED_COLUMNS = {
    "FECHA",
    "DEPARTAMENTO",
    "MUNICIPIO",
    "EVENTO",
    "CODIGO EMERGENCIA",
    "COMENTARIOS",
    "PPUENTES VEHICULARES",
    "PPUENTES PEATONALES",
    *NUMERIC_COLUMNS.values(),
}

RECORD_COLUMNS = [
    "source_row", "source_code", "occurred_on", "department_key", "municipality_key",
    "event_type", "deceased", "injured", "missing", "people_affected",
    "families_affected", "homes_destroyed", "homes_damaged", "roads_damaged",
    "bridges_damaged", "hectares", "comments", "action_codes", "is_high_impact",
]


@dataclass
class CleanResult:
    records: pd.DataFrame
    discarded: Counter


def parse_number(raw: str) -> float:
    try:
        value = float(raw.replace(",", ""))
    except ValueError:
        return 0.0
    return value if math.isfinite(value) and value >= 0 else 0.0


def _percentile_90_by_type(df: pd.DataFrame, column: str) -> pd.Series:
    positive = df[df[column] > 0]
    thresholds = positive.groupby("event_type")[column].quantile(0.9)
    return df["event_type"].map(thresholds)


def high_impact_mask(df: pd.DataFrame) -> pd.Series:
    victims = df["deceased"] + df["injured"] + df["missing"] > 0
    people = (df["people_affected"] > 0) & (
        df["people_affected"] >= _percentile_90_by_type(df, "people_affected")
    )
    hectares = (df["hectares"] > 0) & (
        df["hectares"] >= _percentile_90_by_type(df, "hectares")
    )
    return victims | (df["homes_destroyed"] > 0) | people | hectares


def clean_ungrd(path) -> CleanResult:
    raw = pd.read_csv(Path(path), dtype=str, keep_default_na=False)
    missing = REQUIRED_COLUMNS - set(raw.columns)
    if missing:
        raise ValueError(f"UNGRD file is missing columns: {', '.join(sorted(missing))}")
    event_type = raw["EVENTO"].map(lambda value: EVENT_TYPE_LABELS.get(normalize_name(value)))
    occurred_on = pd.to_datetime(raw["FECHA"], format=DATE_FORMAT, errors="coerce")
    unknown_event = event_type.isna()
    bad_date = occurred_on.isna()
    counts = {
        "unknown event type": int(unknown_event.sum()),
        "invalid date": int((bad_date & ~unknown_event).sum()),
    }
    discarded = Counter({reason: count for reason, count in counts.items() if count > 0})
    keep = ~(unknown_event | bad_date)

    records = pd.DataFrame(
        {
            "source_row": raw.index + 1,
            "source_code": raw["CODIGO EMERGENCIA"],
            "occurred_on": occurred_on.dt.date,
            "department_key": raw["DEPARTAMENTO"].map(normalize_name),
            "event_type": event_type,
        }
    )
    municipality_key = raw["MUNICIPIO"].map(normalize_name)
    records["municipality_key"] = municipality_key.where(municipality_key != DEPARTMENT_LEVEL, None)
    for column, source in NUMERIC_COLUMNS.items():
        records[column] = raw[source].map(parse_number)
    records["bridges_damaged"] = raw["PPUENTES VEHICULARES"].map(parse_number) + raw[
        "PPUENTES PEATONALES"
    ].map(parse_number)
    records["comments"] = raw["COMENTARIOS"].map(repair_mojibake)
    records["action_codes"] = records["comments"].map(extract_actions)

    records = records[keep].reset_index(drop=True)
    records["is_high_impact"] = high_impact_mask(records)
    return CleanResult(records=records[RECORD_COLUMNS], discarded=discarded)


def read_divipola(path) -> pd.DataFrame:
    raw = pd.read_csv(Path(path), dtype=str, keep_default_na=False)
    return pd.DataFrame(
        {
            "department_code": raw["department_code"],
            "department_key": raw["department_name"].map(normalize_name),
            "municipality_code": raw["municipality_code"],
            "municipality_key": raw["municipality_name"].map(normalize_name),
            "latitude": raw["latitude"].astype(float),
            "longitude": raw["longitude"].astype(float),
        }
    )


def municipality_centroids(divipola: pd.DataFrame) -> dict[str, tuple[float, float]]:
    return {
        code: (latitude, longitude)
        for code, latitude, longitude in zip(
            divipola["municipality_code"], divipola["latitude"], divipola["longitude"]
        )
    }


def load_frame(ungrd_path, divipola_path) -> pd.DataFrame:
    divipola = read_divipola(divipola_path)
    department_codes = dict(zip(divipola["department_key"], divipola["department_code"]))
    municipality_codes = {
        (department, municipality): code
        for department, municipality, code in zip(
            divipola["department_key"], divipola["municipality_key"], divipola["municipality_code"]
        )
    }
    known_codes = set(divipola["municipality_code"])

    rows = []
    for record in clean_ungrd(ungrd_path).records.to_dict("records"):
        department_key = record["department_key"]
        municipality_key = record["municipality_key"]
        if not isinstance(municipality_key, str):
            department = department_codes.get(department_key)
            municipality = ""
        else:
            municipality = MUNICIPALITY_ALIASES.get((department_key, municipality_key))
            if municipality not in known_codes:
                municipality = municipality_codes.get((department_key, municipality_key))
            department = municipality[:2] if municipality else None
        if department is None:
            continue
        rows.append(
            {
                "reference": f"{REFERENCE_PREFIX}{record['source_row']}",
                "occurred_on": record["occurred_on"],
                "event_type": record["event_type"],
                "department": department,
                "municipality": municipality,
                **{column: record[column] for column in NUMERIC_COLUMNS},
                "has_impact": True,
                "action_codes": list(record["action_codes"]),
                "is_high_impact": bool(record["is_high_impact"]),
            }
        )
    return pd.DataFrame(rows, columns=list(FRAME_COLUMNS))
