from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Annotated, Protocol, TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

if TYPE_CHECKING:
    from app.models.decision import DecisionCandidate


NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
TitleStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]


class DecisionContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DecisionStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class DecisionMaker(str, Enum):
    USER = "user"
    AI = "ai"
    BOTH = "both"


class CandidateSolution(DecisionContract):
    name: NonEmptyStr
    pros: list[NonEmptyStr] = Field(default_factory=list)
    cons: list[NonEmptyStr] = Field(default_factory=list)


class FutureReviewCondition(DecisionContract):
    trigger: NonEmptyStr
    description: NonEmptyStr = ""


class DecisionCandidateProjection(DecisionContract):
    assessment_id: uuid.UUID
    artifact_index: int = Field(ge=0)
    session_id: uuid.UUID
    turn_id: uuid.UUID
    source_message_id: uuid.UUID
    project_id: uuid.UUID | None
    title: TitleStr
    why: NonEmptyStr
    candidate_solutions: list[CandidateSolution] = Field(default_factory=list)
    final_choice: NonEmptyStr | None = None
    decision_maker: DecisionMaker = DecisionMaker.USER
    future_review: FutureReviewCondition | None = None
    confidence: float = Field(ge=0, le=1)


class DecisionProjector(Protocol):
    """Projects CognitiveAssessment artifacts (kind=DECISION) into DecisionCandidate rows."""

    async def project(self, assessment: "CognitiveAssessment") -> list["DecisionCandidate"]:
        raise NotImplementedError
