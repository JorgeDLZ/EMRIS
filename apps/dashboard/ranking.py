from dataclasses import dataclass

from apps.intelligence.models import MUNICIPAL_RISK, ModelVersion
from apps.places.models import Municipality

USER_PREFIX = "user-"


@dataclass(frozen=True)
class RankedMunicipality:
    position: int
    municipality: Municipality | None
    code: str
    level: int
    k: int


@dataclass(frozen=True)
class RiskRanking:
    version: ModelVersion | None
    available: bool
    rows: list[RankedMunicipality]
    insufficient_history: int


def _resolve(codes: list[str]) -> dict[str, Municipality]:
    user_pks = []
    official = []
    for code in codes:
        suffix = code[len(USER_PREFIX) :]
        if code.startswith(USER_PREFIX) and suffix.isdigit():
            user_pks.append(int(suffix))
        else:
            official.append(code)
    found = {
        municipality.code: municipality
        for municipality in Municipality.objects.select_related("department").filter(code__in=official)
    }
    if user_pks:
        for municipality in Municipality.objects.select_related("department").filter(
            pk__in=user_pks
        ):
            found[f"{USER_PREFIX}{municipality.pk}"] = municipality
    return found


def in_department(row: RankedMunicipality, department_code: str | None) -> bool:
    if not department_code:
        return True
    return row.municipality is not None and row.municipality.department.code == department_code


def departments(rows: list[RankedMunicipality]) -> list:
    found = {row.municipality.department for row in rows if row.municipality is not None}
    return sorted(found, key=lambda department: department.name)


def risk_ranking(department_code: str | None = None) -> RiskRanking:
    version = ModelVersion.objects.defer("artifact").filter(component=MUNICIPAL_RISK, is_active=True).first()
    ranking = version.metadata.get("ranking") if version else None
    if not ranking:
        return RiskRanking(version=version, available=False, rows=[], insufficient_history=0)
    k = version.metrics["k"]
    ranking = sorted(ranking, key=lambda entry: (-entry["level"], -entry["score"], entry["code"]))
    municipalities = _resolve([entry["code"] for entry in ranking])
    rows = []
    for position, entry in enumerate(ranking, start=1):
        municipality = municipalities.get(entry["code"])
        row = RankedMunicipality(
            position=position,
            municipality=municipality,
            code=entry["code"],
            level=entry["level"],
            k=k,
        )
        if in_department(row, department_code):
            rows.append(row)
    return RiskRanking(
        version=version,
        available=True,
        rows=rows,
        insufficient_history=version.metrics.get("insufficient_history", 0),
    )
