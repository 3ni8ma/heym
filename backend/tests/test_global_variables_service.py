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

    async def test_team_share_query_uses_correct_joins_and_filter(self) -> None:
        """Assert exact join conditions and WHERE clause for team-share query."""
        owner_id = uuid.uuid4()

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[_EmptyResult(), _EmptyResult(), _EmptyResult()]
        )

        await get_global_variables_context(db, owner_id)

        query = db.execute.call_args_list[0][0][0]
        compiled = query.compile(compile_kwargs={"literal_binds": True})
        sql = str(compiled).lower()

        # Verify join: global_variable_team_shares
        self.assertIn("global_variable_team_shares", sql)
        # Verify join: team_members
        self.assertIn("team_members", sql)
        # Verify filter column: user_id
        self.assertIn("team_members.user_id =", sql)
        # UUID bind params strip hyphens in compiled SQL
        self.assertIn(str(owner_id).replace("-", ""), sql)

    async def test_team_share_query_orders_by_name_created_at_id(self) -> None:
        """Verify ORDER BY uses name, team share created_at, then variable id."""
        owner_id = uuid.uuid4()

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[_EmptyResult(), _EmptyResult(), _EmptyResult()]
        )

        await get_global_variables_context(db, owner_id)

        query = db.execute.call_args_list[0][0][0]
        compiled = query.compile(compile_kwargs={"literal_binds": True})
        sql = str(compiled).lower()

        # Extract the ORDER BY clause
        order_pos = sql.rindex("order by")
        order_clause = sql[order_pos:]
        self.assertIn("name", order_clause)
        self.assertIn("created_at", order_clause)

    async def test_direct_share_query_orders_by_name_created_at_id(self) -> None:
        """Verify direct-share ORDER BY uses name, share created_at, then variable id."""
        owner_id = uuid.uuid4()

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[_EmptyResult(), _EmptyResult(), _EmptyResult()]
        )

        await get_global_variables_context(db, owner_id)

        query = db.execute.call_args_list[1][0][0]
        compiled = query.compile(compile_kwargs={"literal_binds": True})
        sql = str(compiled).lower()

        self.assertIn("order by", sql)
        self.assertIn("name", sql)

    async def test_owned_query_orders_by_name_only(self) -> None:
        """Verify owned query only orders by name (unique constraint on owner_id+name)."""
        owner_id = uuid.uuid4()

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[_EmptyResult(), _EmptyResult(), _EmptyResult()]
        )

        await get_global_variables_context(db, owner_id)

        query = db.execute.call_args_list[2][0][0]
        compiled = query.compile(compile_kwargs={"literal_binds": True})
        sql = str(compiled).lower()

        self.assertIn("order by", sql)
        # Should only have name in the order by
        order_clause = sql[sql.index("order by"):]
        self.assertNotIn("created_at", order_clause)
        self.assertNotIn("global_variable_team_share", order_clause)

    async def test_team_share_last_write_wins_among_same_level_collisions(self) -> None:
        """With ascending created_at, last-write-wins means the row that appears
        last in the DB result overwrites earlier ones. The most recently shared
        variable wins."""
        owner_id = uuid.uuid4()

        early_share = SimpleNamespace(
            id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            name="dup",
            value={"v": "shared_early"},
            owner_id=uuid.uuid4(),
        )
        late_share = SimpleNamespace(
            id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
            name="dup",
            value={"v": "shared_late"},
            owner_id=uuid.uuid4(),
        )

        # DB returns in ascending (created_at, id) order: early first, late second.
        # Dict assignment: late overwrites early → "shared_late" wins.
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _AllResult([early_share, late_share]),
                _EmptyResult(),
                _EmptyResult(),
            ]
        )

        result = await get_global_variables_context(db, owner_id)

        self.assertEqual(result["dup"], "shared_late")

    async def test_team_share_timestamp_overrides_id_order(self) -> None:
        """When timestamps conflict with ID order, the most recently shared
        variable wins (not the one with the higher ID)."""
        owner_id = uuid.uuid4()

        # Lower ID but shared later
        lower_id_later = SimpleNamespace(
            id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            name="conflict",
            value={"v": "lower_id_later"},
            owner_id=uuid.uuid4(),
        )
        # Higher ID but shared earlier
        higher_id_earlier = SimpleNamespace(
            id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
            name="conflict",
            value={"v": "higher_id_earlier"},
            owner_id=uuid.uuid4(),
        )

        # DB returns in ascending (created_at, id) order:
        # earlier share first (higher_id), later share second (lower_id)
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _AllResult([higher_id_earlier, lower_id_later]),
                _EmptyResult(),
                _EmptyResult(),
            ]
        )

        result = await get_global_variables_context(db, owner_id)

        # The one shared later wins regardless of ID order
        self.assertEqual(result["conflict"], "lower_id_later")
