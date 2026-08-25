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

    async def test_three_queries_are_executed(self) -> None:
        owner_id = uuid.uuid4()

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _EmptyResult(),
                _EmptyResult(),
                _EmptyResult(),
            ]
        )

        await get_global_variables_context(db, owner_id)

        self.assertEqual(db.execute.call_count, 3)
