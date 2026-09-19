from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class FactState(str, Enum):
    PRIVATE = "private"
    ANNOUNCED = "announced"
    CLEARED = "cleared"
    ABANDONED = "abandoned"


class MaterialityLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


class ResolutionMode(str, Enum):
    CONVEYS = "conveys"
    MENTIONS = "mentions"


_VERDICT_SEVERITY = {
    "clean": 0,
    "review": 1,
    "violation_disclosure": 2,
    "violation_upstream_leak": 3,
}


class Verdict(str, Enum):
    CLEAN = "clean"
    REVIEW = "review"
    VIOLATION_DISCLOSURE = "violation_disclosure"
    VIOLATION_UPSTREAM_LEAK = "violation_upstream_leak"

    def _severity(self) -> int:
        return _VERDICT_SEVERITY[self.value]

    def __lt__(self, other: "Verdict") -> bool:
        if self.__class__ is not other.__class__:
            return NotImplemented
        return self._severity() < other._severity()

    def __le__(self, other: "Verdict") -> bool:
        if self.__class__ is not other.__class__:
            return NotImplemented
        return self._severity() <= other._severity()

    def __gt__(self, other: "Verdict") -> bool:
        if self.__class__ is not other.__class__:
            return NotImplemented
        return self._severity() > other._severity()

    def __ge__(self, other: "Verdict") -> bool:
        if self.__class__ is not other.__class__:
            return NotImplemented
        return self._severity() >= other._severity()


@dataclass
class Fact:
    fact_id: str
    summary: str
    entities: list[str]
    aliases: list[str]
    state: FactState
    recorded_at: datetime
    materiality: list[tuple[datetime, MaterialityLevel]]
    announced_at: datetime | None = None
    cleared_at: datetime | None = None
    # When the fact became true in the world, distinct from recorded_at (when
    # the ledger learned it). Defaults to recorded_at when not given.
    valid_from: datetime | None = None

    def __post_init__(self) -> None:
        if self.valid_from is None:
            self.valid_from = self.recorded_at


@dataclass
class Crossing:
    party_id: str
    fact_id: str
    effective_from: datetime
    effective_until: datetime | None = None


@dataclass
class Message:
    message_id: str
    sender: str
    recipients: list[str]
    timestamp: datetime
    body: str


@dataclass
class Resolution:
    fact_id: str
    mode: ResolutionMode
    confidence: float
    span: str
