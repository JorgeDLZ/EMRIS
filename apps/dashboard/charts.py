from collections.abc import Iterable
from dataclasses import dataclass

STEP = 5


@dataclass(frozen=True)
class Bar:
    label: str
    value: int | float
    percent: int

    @property
    def step(self) -> int:
        if self.value > 0:
            return max(STEP, STEP * round(self.percent / STEP))
        return STEP * round(self.percent / STEP)


def bars(pairs: Iterable[tuple[str, int | float]]) -> list[Bar]:
    items = list(pairs)
    peak = max((value for _, value in items), default=0)
    return [Bar(label, value, round(value / peak * 100) if peak else 0) for label, value in items]
