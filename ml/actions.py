import re
from dataclasses import dataclass

from ml.text import normalize_name

SECTION_PATTERNS = [
    re.compile(r"\bACCION(?:ES)?\s*:?\s*(.*?)(?=ESTADO\s*:|ACTUALIZACION|$)"),
    re.compile(r"ATENDIDO POR\s*:?\s*(.*?)(?=AFECTACION|ESTADO\s*:|\.|$)"),
]


@dataclass(frozen=True)
class ActionRule:
    label: str
    pattern: re.Pattern


def _rule(label: str, pattern: str) -> ActionRule:
    return ActionRule(label=label, pattern=re.compile(pattern))


ACTION_VOCABULARY: dict[str, ActionRule] = {
    "activate_municipal_council": _rule(
        "Activate the municipal risk council",
        r"\bCMGRD?\b|CONSEJO MUNICIPAL|ALCALDIA|GESTION DEL? RIESGOS? MUNICIPAL"
        r"|SECRETARIA DE GOBIERNO|ORGANISMOS DE SOCORRO",
    ),
    "request_departmental_support": _rule(
        "Request departmental support",
        r"\bCDGRD\b|\bDAGRAN\b|\bDAGRD\b|\bDIGER\b|CONSEJO DEPARTAMENTAL|GOBERNACION",
    ),
    "deploy_fire_brigade": _rule(
        "Deploy the fire brigade",
        r"BOMBER|\bCBV\b|\bCBO\b|\bCOB\b|\bBCV\b|\bBCBV\b|\bDNBC\b|EXTINTOR|BOMBAS? DE ESPALDA",
    ),
    "deploy_heavy_machinery": _rule(
        "Deploy heavy machinery",
        r"MAQUINARIA|RETROEXCAVADORA|VOLQUETA|BULLDOZER|MOTONIVELADORA",
    ),
    "deploy_civil_defense": _rule("Deploy Civil Defense", r"\bD\.?C\.?C\b|DEFENSA CIVIL"),
    "deploy_red_cross": _rule("Deploy the Red Cross", r"CRUZ ROJA"),
    "deploy_security_forces": _rule(
        "Coordinate with police and army",
        r"POLICIA|EJERCITO|ARMADA|FUERZA AEREA|BATALLON",
    ),
    "provide_medical_care": _rule(
        "Provide medical care",
        r"AMBULANCIA|\bCRUE\b|HOSPITAL|SECRETARIA DE SALUD|PARAMEDICO|\bAPH\b",
    ),
    "assess_damage": _rule(
        "Assess damage and needs",
        r"\bEDAN\b|CENSO|EVALUACION DE DANOS|\bRUD\b|INSPECCION|VISITA TECNICA",
    ),
    "deliver_humanitarian_aid": _rule(
        "Deliver humanitarian aid",
        r"\bAHE\b|\bKITS?\b|AYUDA HUMANITARIA|ASISTENCIA HUMANITARIA|ALBERGUE|MERCADOS",
    ),
    "search_and_rescue": _rule("Run search and rescue", r"RESCATE|BUSQUEDA"),
    "supply_water": _rule(
        "Supply drinking water", r"CARROTANQUE|AGUA POTABLE|SUMINISTRO DE AGUA"
    ),
    "evacuate_population": _rule("Evacuate the population", r"EVACU"),
    "declare_public_calamity": _rule("Declare public calamity", r"CALAMIDAD"),
    "engage_community": _rule("Engage the community", r"COMUNIDAD"),
    "clear_roads": _rule("Clear and reopen roads", r"REMOCION|DESPEJE|HABILITA|LIMPIEZA"),
}


def action_section(normalized_comment: str) -> str:
    matches = (
        match.group(1)
        for pattern in SECTION_PATTERNS
        for match in pattern.finditer(normalized_comment)
    )
    return " ".join(matches)


def extract_actions(comment: str) -> list[str]:
    section = action_section(normalize_name(comment))
    return [code for code, rule in ACTION_VOCABULARY.items() if rule.pattern.search(section)]
