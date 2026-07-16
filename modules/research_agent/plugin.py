from __future__ import annotations

from app.agent.base import BaseAgent
from app.agent.models import AgentResult, TaskInput


class ResearchAgent(BaseAgent):
    name = "research"
    description = (
        "Explains technologies, compares options, generates learning "
        "materials, and builds knowledge graphs. "
        "Read-only: does not produce file changes."
    )
    capabilities = ["research", "explain", "compare", "teach"]
    requires_confirmation = False

    async def execute(self, task: TaskInput) -> AgentResult:
        return AgentResult(
            summary=(
                "Research Agent: use explanation or comparison data "
                "from task.context to produce knowledge output. "
                "This agent is a structural placeholder; actual knowledge "
                "processing occurs at the Cognitive + LLM layer."
            ),
            changes=[],
        )


agent = ResearchAgent()
