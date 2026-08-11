"""Tests for the shared workflow access clause."""

import unittest
import uuid

from sqlalchemy import select

from app.db.models import Workflow
from app.services.workflow_access import workflow_access_clause


class WorkflowAccessClauseTest(unittest.TestCase):
    def test_clause_covers_owner_user_share_and_team_share(self) -> None:
        user_id = uuid.uuid4()
        sql = str(select(Workflow.id).where(workflow_access_clause(user_id)))

        self.assertIn("workflows.owner_id", sql)
        self.assertIn("workflow_shares", sql)
        self.assertIn("workflow_team_shares", sql)
        self.assertIn("team_members", sql)

    def test_clause_is_an_or_of_three_branches(self) -> None:
        user_id = uuid.uuid4()
        clause = workflow_access_clause(user_id)

        self.assertEqual(len(clause.clauses), 3)
