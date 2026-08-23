import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock

from app.api.folders import create_folder, get_folder, get_folder_tree, update_folder
from app.db.models import Folder, User, Workflow
from app.models.schemas import FolderCreate, FolderUpdate


def make_result(value: object) -> Mock:
    result = Mock()
    result.scalar_one_or_none.return_value = value
    return result


def make_rows_result(rows: list | None = None) -> Mock:
    """Result for the latest-trigger-source lookup every workflow list response makes."""
    result = Mock()
    result.all.return_value = rows or []
    return result


def make_user() -> User:
    return User(
        id=uuid.uuid4(),
        email="owner@example.com",
        hashed_password="hashed",
        name="Anna",
    )


def make_folder(**overrides: object) -> Folder:
    values: dict[str, object] = {
        "id": uuid.uuid4(),
        "name": "Folder",
        "description": None,
        "owner_id": uuid.uuid4(),
        "parent_id": None,
        "icon": None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    values.update(overrides)
    return Folder(**values)


class FolderDescriptionCreateTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_folder_persists_description(self) -> None:
        current_user = make_user()
        db = AsyncMock()
        db.add = Mock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        await create_folder(
            FolderCreate(name="DevOps", description="Monitoring and incident routing"),
            db,
            current_user,
        )

        added_folder = db.add.call_args.args[0]
        self.assertEqual(added_folder.description, "Monitoring and incident routing")

    async def test_create_folder_blank_description_becomes_none(self) -> None:
        current_user = make_user()
        db = AsyncMock()
        db.add = Mock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        await create_folder(FolderCreate(name="DevOps", description="   "), db, current_user)

        self.assertIsNone(db.add.call_args.args[0].description)

    async def test_create_folder_without_description_is_none(self) -> None:
        current_user = make_user()
        db = AsyncMock()
        db.add = Mock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        await create_folder(FolderCreate(name="DevOps"), db, current_user)

        self.assertIsNone(db.add.call_args.args[0].description)


class FolderDescriptionUpdateTests(unittest.IsolatedAsyncioTestCase):
    async def test_update_folder_sets_description(self) -> None:
        current_user = make_user()
        folder = make_folder(owner_id=current_user.id)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=make_result(folder))
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        await update_folder(
            folder.id, FolderUpdate(description="Scrapers and publishing"), db, current_user
        )

        self.assertEqual(folder.description, "Scrapers and publishing")

    async def test_update_folder_clears_description(self) -> None:
        current_user = make_user()
        folder = make_folder(owner_id=current_user.id, description="Old text")
        db = AsyncMock()
        db.execute = AsyncMock(return_value=make_result(folder))
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        await update_folder(folder.id, FolderUpdate(description=None), db, current_user)

        self.assertIsNone(folder.description)

    async def test_rename_without_description_field_keeps_description(self) -> None:
        current_user = make_user()
        folder = make_folder(owner_id=current_user.id, description="Kept")
        db = AsyncMock()
        db.execute = AsyncMock(return_value=make_result(folder))
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        await update_folder(folder.id, FolderUpdate(name="Renamed"), db, current_user)

        self.assertEqual(folder.name, "Renamed")
        self.assertEqual(folder.description, "Kept")


class FolderDescriptionReadTests(unittest.IsolatedAsyncioTestCase):
    async def test_folder_tree_includes_description(self) -> None:
        current_user = make_user()
        folder = make_folder(owner_id=current_user.id, description="Monitoring")
        folder.workflows = []

        db = AsyncMock()
        folders_result = Mock()
        folders_result.scalars.return_value.unique.return_value.all.return_value = [folder]
        shares_result = Mock()
        shares_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(side_effect=[folders_result, shares_result, make_rows_result()])

        tree = await get_folder_tree(db, current_user)

        self.assertEqual(tree[0].description, "Monitoring")

    async def test_get_folder_includes_description_for_folder_and_children(self) -> None:
        current_user = make_user()
        child = make_folder(owner_id=current_user.id, description="Child text")
        folder = make_folder(owner_id=current_user.id, description="Parent text")
        folder.children = [child]
        folder.workflows = [
            Workflow(
                id=uuid.uuid4(),
                name="Workflow",
                owner_id=current_user.id,
                nodes=[],
                edges=[],
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        ]

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[make_result(folder), make_rows_result()])

        response = await get_folder(folder.id, db, current_user)

        self.assertEqual(response.description, "Parent text")
        self.assertEqual(response.children[0].description, "Child text")


if __name__ == "__main__":
    unittest.main()
