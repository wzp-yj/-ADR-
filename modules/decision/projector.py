from __future__ import annotations

import json
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.decision.base import (
    DecisionCandidateProjection,
    DecisionProjector,
    DecisionStatus,
)

if TYPE_CHECKING:
    from app.models.cognitive import CognitiveAssessment
    from app.models.decision import DecisionCandidate


class AssessmentDecisionProjector:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def project(
        self, assessment: CognitiveAssessment,
    ) -> list[DecisionCandidate]:
        to_save: list[DecisionCandidateProjection] = []
        for i, artifact in enumerate(assessment.proposed_artifacts or []):
            if artifact.get("kind") != "decision":
                continue
            title = (artifact.get("title") or "").strip()
            content = (artifact.get("content") or "").strip()
            if not title or not content:
                continue
            proj = DecisionCandidateProjection(
                assessment_id=assessment.id,
                artifact_index=i,
                session_id=assessment.session_id,
                turn_id=assessment.turn_id,
                source_message_id=assessment.source_message_id,
                project_id=assessment.project_id,
                title=title,
                why=content,
                candidate_solutions=[],
                confidence=float(artifact.get("confidence", 0.7)),
            )
            to_save.append(proj)

        from app.models.decision import DecisionCandidate as DCModel

        for proj in to_save:
            stmt = (
                insert(DCModel)
                .values(
                    id=uuid.uuid4(),
                    session_id=proj.session_id,
                    turn_id=proj.turn_id,
                    source_message_id=proj.source_message_id,
                    assessment_id=proj.assessment_id,
                    artifact_index=proj.artifact_index,
                    project_id=proj.project_id,
                    title=proj.title,
                    why=proj.why,
                    candidate_solutions=json.dumps(
                        [s.model_dump(mode="json") for s in proj.candidate_solutions]
                    ) if proj.candidate_solutions else None,
                    final_choice=proj.final_choice,
                    decision_maker=proj.decision_maker.value,
                    future_review=json.dumps(proj.future_review.model_dump(mode="json"))
                    if proj.future_review else None,
                    confidence=Decimal(str(proj.confidence)),
                    status=DecisionStatus.PENDING.value,
                    version=1,
                )
                .on_conflict_do_nothing(
                    index_elements=["assessment_id", "artifact_index"],
                )
            )
            await self._db.execute(stmt)

        candidates: list[DCModel] = []
        if to_save:
            result = await self._db.execute(
                select(DCModel).where(
                    DCModel.assessment_id == assessment.id,
                ).order_by(DCModel.artifact_index.asc()),
            )
            candidates = list(result.scalars().all())
        return candidates
