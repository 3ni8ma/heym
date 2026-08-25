"""Tests for global_variables_service, focusing on team-share support."""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.services.global_variables_service import get_global_variables_context


def _make_variable(name: str, value: object, owner_id: uuid.UUID | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        name=name,
        value={"v": value},
        owner_id=owner_id or uuid.uuid4(),
    )


class _AllResult:
    """Mock for Result.scalars().all() returning a preset list."""

    def __init__(self, items: list[SimpleNamespace]) -> None:
        self._items = items

    def scalars(self) -> MagicMock:
        result = MagicMock()
        result.all.return_value = self._items
        return result


class _EmptyResult:
    def scalars(self) -> MagicMock:
        result = MagicMock()
        result.all.return_value = []
        return result


class GetGlobalVariablesContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_team_shared_variables_are_loaded(self) -> None:
        owner_id = uuid.uuid4()
        team_var = _make_variable("team_secret", "from_team")

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _AllResult([team_var]),  # team-shared query
                _EmptyResult(),  # user-shared query
                _EmptyResult(),  # owned query
            ]
        )

        result = await get_global_variables_context(db, owner_id)

        self.assertEqual(result, {"team_secret": "from_team"})

    async def test_owned_variable_takes_precedence_over_team_shared(self) -> None:
        owner_id = uuid.uuid4()
        team_var = _make_variable("shared_name", "from_team")
        owned_var = _make_variable("shared_name", "from_owner", owner_id=owner_id)

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _AllResult([team_var]),
                _EmptyResult(),
                _AllResult([owned_var]),
            ]
        )

        result = await get_global_variables_context(db, owner_id)

        self.assertEqual(result, {"shared_name": "from_owner"})

    async def test_user_shared_variable_takes_precedence_over_team_shared(self) -> None:
        owner_id = uuid.uuid4()
        team_var = _make_variable("contested", "from_team")
        user_shared_var = _make_variable("contested", "from_user_share")

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _AllResult([team_var]),
                _AllResult([user_shared_var]),
                _EmptyResult(),
            ]
        )

        result = await get_global_variables_context(db, owner_id)

        self.assertEqual(result, {"contested": "from_user_share"})

    async def test_owned_beats_user_shared_which_beats_team_shared(self) -> None:
        owner_id = uuid.uuid4()
        team_var = _make_variable("x", "team")
        user_var = _make_variable("x", "user")
        owned_var = _make_variable("x", "owner", owner_id=owner_id)

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _AllResult([team_var]),
                _AllResult([user_var]),
                _AllResult([owned_var]),
            ]
        )

        result = await get_global_variables_context(db, owner_id)

        self.assertEqual(result["x"], "owner")

    async def test_different_names_merge_across_sources(self) -> None:
        owner_id = uuid.uuid4()
        team_var = _make_variable("a", 1)
        user_var = _make_variable("b", 2)
        owned_var = _make_variable("c", 3, owner_id=owner_id)

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _AllResult([team_var]),
                _AllResult([user_var]),
                _AllResult([owned_var]),
            ]
        )

        result = await get_global_variables_context(db, owner_id)

        self.assertEqual(result, {"a": 1, "b": 2, "c": 3})

    async def test_empty_when_no_variables_exist(self) -> None:
        owner_id = uuid.uuid4()

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _EmptyResult(),
                _EmptyResult(),
                _EmptyResult(),
            ]
        )

        result = await get_global_variables_context(db, owner_id)

        self.assertEqual(result, {})

    async def test_nested_dict_values_are_unwrapped(self) -> None:
        owner_id = uuid.uuid4()
        team_var = _make_variable("config", {"key": "value"})

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _AllResult([team_var]),
                _EmptyResult(),
                _EmptyResult(),
            ]
        )

        result = await get_global_variables_context(db, owner_id)

        self.assertEqual(result["config"], {"key": "value"})

    async def test_team_share_query_uses_correct_joins_and_user_filter(self) -> None:
        """Verify the team-share query joins GlobalVariableTeamShare and TeamMember
        and filters by TeamMember.user_id."""

        owner_id = uuid.uuid4()
        team_var = _make_variable("team_only", "secret")

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _AllResult([team_var]),
                _EmptyResult(),
                _EmptyResult(),
            ]
        )

        await get_global_variables_context(db, owner_id)

        first_call_args = db.execute.call_args_list[0]
        query = first_call_args[0][0]

        # Verify the query has the expected structure: SELECT ... JOIN TeamMember WHERE TeamMember.user_id = ?
        compiled = query.compile(compile_kwargs={"literal_binds": True})
        sql_str = str(compiled)

        self.assertIn("team_member", sql_str.lower())
        self.assertIn("global_variable_team_share", sql_str.lower())
        self.assertIn("user_id", sql_str.lower())

    async def test_id_tiebreaker_for_same_level_collisions(self) -> None:
        """When two variables have the same name at the same priority level,
        the one with the lower id wins (deterministic tiebreaker)."""
        owner_id = uuid.uuid4()

        var_early = SimpleNamespace(
            id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            name="dup",
            value={"v": "first"},
            owner_id=uuid.uuid4(),
        )
        var_late = SimpleNamespace(
            id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
            name="dup",
            value={"v": "second"},
            owner_id=uuid.uuid4(),
        )

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _AllResult([var_late, var_early]),  # team-shared: same name, two vars
                _EmptyResult(),
                _EmptyResult(),
            ]
        )

        result = await get_global_variables_context(db, owner_id)

        # The query orders by (name, id), so the first row wins via dict assignment
        self.assertEqual(result["dup"], "first")
