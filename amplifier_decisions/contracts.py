"""v1 portable contract. No Amplifier, GUI, provider SDK, or host imports."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

QuestionKind = Literal["predicate", "choice", "score", "box"]
AnswerStatus = Literal["answered", "refused", "unavailable", "invalid", "abstained"]


@dataclass(frozen=True)
class Question:
    name: str
    kind: QuestionKind
    instructions: str
    # Choice keys remain opaque identities; score level positions are ordinal indices.
    choices: dict[str, str] = field(default_factory=dict)
    levels: tuple[str, ...] = ()


@dataclass(frozen=True)
class Image:
    data: bytes = field(repr=False)
    media_type: str = "image/png"


@dataclass(frozen=True)
class DecisionRequest:
    state: str | dict | list
    questions: tuple[Question, ...]
    timeout_seconds: float = 10.0
    images: tuple[Image, ...] = ()
    # Each caller must deliberately authorize transferring its observation.
    allow_external_state: bool = False


@dataclass(frozen=True)
class Capabilities:
    kinds: frozenset[str] = frozenset({"predicate", "choice", "score"})
    images: bool = False
    max_questions: int = 200  # Conservative common subset, not a provider maximum.
    max_choices: int = 255
    max_levels: int = 10
    max_text_bytes: int = 65_536  # Conservative local bound; not a tokenizer claim.
    max_images: int = 8
    confidence_semantics: str = "provider-specific; not calibrated across backends"


@dataclass(frozen=True)
class Answer:
    name: str
    kind: str
    status: AnswerStatus
    value: Any = None
    probabilities: dict[str, float] = field(default_factory=dict)
    confidence: float | None = None
    reason: str | None = None  # Local code, never provider text or input contents.


@dataclass(frozen=True)
class DecisionResult:
    backend: str
    requested_model: str
    reported_model: str | None
    answers: dict[str, Answer]
    elapsed_ms: float
    usage: dict[str, int] = field(default_factory=dict)
    request_id: str | None = None
    # A returned alias is not evidence of an immutable model checkpoint.
    checkpoint: str | None = None
    # Provider-owned API accounting, separate from usage and infrastructure cost.
    cost: dict[str, Any] = field(default_factory=dict)


class Backend(Protocol):
    capabilities: Capabilities

    async def decide(self, request: DecisionRequest) -> DecisionResult: ...
    async def close(self) -> None: ...
