from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.decision.base import DecisionStatus
from app.errors import NotFoundError
from app.models.decision import DecisionCandidate


class DecisionService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def list_candidates(
        self,
        *,
        session_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
        status: DecisionStatus | None = None,
    ) -> list[DecisionCandidate]:
        stmt = select(DecisionCandidate).order_by(DecisionCandidate.created_at.desc())
        if session_id is not None:
            stmt = stmt.where(DecisionCandidate.session_id == session_id)
        if project_id is not None:
            stmt = stmt.where(DecisionCandidate.project_id == project_id)
        if status is not None:
            stmt = stmt.where(DecisionCandidate.status == status.value)
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    async def get_candidate(self, candidate_id: uuid.UUID) -> DecisionCandidate:
        result = await self._db.execute(
            select(DecisionCandidate).where(DecisionCandidate.id == candidate_id),
        )
        candidate = result.scalar_one_or_none()
        if candidate is None:
            raise NotFoundError("decision_candidate", str(candidate_id))
        return candidate

    async def decide(
        self,
        *,
        candidate_id: uuid.UUID,
        status: DecisionStatus,
        decision_reason: str | None = None,
    ) -> DecisionCandidate:
        candidate = await self.get_candidate(candidate_id)
        if candidate.status != DecisionStatus.PENDING.value:
            raise ValueError(
                f"Cannot decide on candidate with status '{candidate.status}'"
            )
        candidate.status = status.value
        candidate.decided_at = datetime.now(timezone.utc)
        candidate.decision_reason = decision_reason
        await self._db.flush()
        return candidate

    async def supersede(
        self,
        *,
        candidate_id: uuid.UUID,
        by_candidate_id: uuid.UUID,
    ) -> DecisionCandidate:
        candidate = await self.get_candidate(candidate_id)
        if candidate.status != DecisionStatus.ACCEPTED.value:
            raise ValueError("Only accepted decisions can be superseded")
        candidate.status = DecisionStatus.SUPERSEDED.value
        candidate.decided_at = datetime.now(timezone.utc)
        candidate.supersedes_id = by_candidate_id
        candidate.version = (candidate.version or 1) + 1
        await self._db.flush()
        return candidate
