"""The single definition of which workflows a user can reach.

Both the async API layer and the synchronous node handlers need this answer, so
it is expressed as a SQLAlchemy clause rather than an executed query - the caller
supplies the session and the engine.
"""

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.db.models import TeamMember, Workflow, WorkflowShare, WorkflowTeamShare


def workflow_access_clause(user_id: UUID) -> ColumnElement[bool]:
    """Return the WHERE clause matching every workflow ``user_id`` can reach.

    A user reaches a workflow by owning it, by holding a direct share, or by
    belonging to a team the workflow is shared with.
    """
    return or_(
        Workflow.owner_id == user_id,
        Workflow.id.in_(select(WorkflowShare.workflow_id).where(WorkflowShare.user_id == user_id)),
        Workflow.id.in_(
            select(WorkflowTeamShare.workflow_id).where(
                WorkflowTeamShare.team_id.in_(
                    select(TeamMember.team_id).where(TeamMember.user_id == user_id)
                )
            )
        ),
    )


async def get_accessible_workflow(
    db: AsyncSession,
    workflow_id: UUID,
    user_id: UUID,
) -> Workflow | None:
    """Return a workflow the user owns or that has been shared with them."""
    result = await db.execute(
        select(Workflow).where(
            Workflow.id == workflow_id,
            workflow_access_clause(user_id),
        )
    )
    return result.scalar_one_or_none()
