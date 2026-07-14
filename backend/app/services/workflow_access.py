from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TeamMember, Workflow, WorkflowShare, WorkflowTeamShare


async def get_accessible_workflow(
    db: AsyncSession,
    workflow_id: UUID,
    user_id: UUID,
) -> Workflow | None:
    """Return a workflow the user owns or that has been shared with them."""
    result = await db.execute(
        select(Workflow).where(
            Workflow.id == workflow_id,
            Workflow.owner_id == user_id,
        )
    )
    workflow = result.scalar_one_or_none()
    if workflow is not None:
        return workflow

    shared_result = await db.execute(
        select(Workflow)
        .join(WorkflowShare, WorkflowShare.workflow_id == Workflow.id)
        .where(
            Workflow.id == workflow_id,
            WorkflowShare.user_id == user_id,
        )
    )
    workflow = shared_result.scalar_one_or_none()
    if workflow is not None:
        return workflow

    team_result = await db.execute(
        select(Workflow)
        .join(WorkflowTeamShare, WorkflowTeamShare.workflow_id == Workflow.id)
        .join(TeamMember, TeamMember.team_id == WorkflowTeamShare.team_id)
        .where(
            Workflow.id == workflow_id,
            TeamMember.user_id == user_id,
        )
    )
    return team_result.scalar_one_or_none()