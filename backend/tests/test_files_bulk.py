"""Tests for Drive bulk file team-sharing and share-link API behavior."""

from __future__ import annotations

import io
import tempfile
import unittest
import uuid
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api.files import (
    bulk_create_share,
    bulk_download_files,
    bulk_update_file_team_sharing,
)
from app.models.schemas import (
    BulkCreateFileShareRequest,
    BulkFileDownloadRequest,
    BulkFileTeamSharingRequest,
)


def _db() -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    return db


def _user(user_id: uuid.UUID | None = None) -> SimpleNamespace:
    return SimpleNamespace(id=user_id or uuid.uuid4(), email="user@example.com", name="User")


def _owned_lookup(owner: SimpleNamespace, owned_ids: set[uuid.UUID]) -> AsyncMock:
    """Fake _get_owned_file that returns a truthy row only for owned ids."""

    async def _lookup(_db: object, file_id: uuid.UUID, _user_id: uuid.UUID) -> object | None:
        return SimpleNamespace(id=file_id, owner_id=owner.id) if file_id in owned_ids else None

    return AsyncMock(side_effect=_lookup)


class BulkTeamSharingApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_enable_team_sharing_for_all_owned_files(self) -> None:
        owner = _user()
        ids = [uuid.uuid4() for _ in range(3)]
        db = _db()

        with (
            patch("app.api.files._get_owned_file", new=_owned_lookup(owner, set(ids))),
            patch("app.api.files._set_file_team_sharing", new=AsyncMock(return_value=1)) as share,
        ):
            response = await bulk_update_file_team_sharing(
                BulkFileTeamSharingRequest(file_ids=ids, enabled=True),
                user=owner,
                db=db,
            )

        self.assertEqual(set(response.succeeded), set(ids))
        self.assertEqual(response.failed, [])
        self.assertEqual(share.await_count, 3)
        for call in share.await_args_list:
            self.assertTrue(call.kwargs["enabled"])
            self.assertEqual(call.kwargs["owner_id"], owner.id)
        db.commit.assert_awaited_once()

    async def test_disable_team_sharing_passes_enabled_false(self) -> None:
        owner = _user()
        ids = [uuid.uuid4(), uuid.uuid4()]
        db = _db()

        with (
            patch("app.api.files._get_owned_file", new=_owned_lookup(owner, set(ids))),
            patch("app.api.files._set_file_team_sharing", new=AsyncMock(return_value=0)) as share,
        ):
            response = await bulk_update_file_team_sharing(
                BulkFileTeamSharingRequest(file_ids=ids, enabled=False),
                user=owner,
                db=db,
            )

        self.assertEqual(set(response.succeeded), set(ids))
        for call in share.await_args_list:
            self.assertFalse(call.kwargs["enabled"])
        db.commit.assert_awaited_once()

    async def test_non_owned_ids_land_in_failed(self) -> None:
        owner = _user()
        owned = uuid.uuid4()
        not_owned = uuid.uuid4()
        db = _db()

        with (
            patch("app.api.files._get_owned_file", new=_owned_lookup(owner, {owned})),
            patch("app.api.files._set_file_team_sharing", new=AsyncMock(return_value=1)) as share,
        ):
            response = await bulk_update_file_team_sharing(
                BulkFileTeamSharingRequest(file_ids=[owned, not_owned], enabled=True),
                user=owner,
                db=db,
            )

        self.assertEqual(response.succeeded, [owned])
        self.assertEqual(response.failed, [not_owned])
        share.assert_awaited_once()
        self.assertEqual(share.await_args.kwargs["file_id"], owned)
        db.commit.assert_awaited_once()


class BulkCreateShareApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_creates_share_with_same_settings_for_every_owned_file(self) -> None:
        owner = _user()
        ids = [uuid.uuid4() for _ in range(3)]
        db = _db()

        with (
            patch("app.api.files._get_owned_file", new=_owned_lookup(owner, set(ids))),
            patch("app.api.files.create_access_token", new=AsyncMock()) as create_token,
        ):
            response = await bulk_create_share(
                BulkCreateFileShareRequest(
                    file_ids=ids,
                    expires_hours=24,
                    basic_auth_password="secret",
                    max_downloads=5,
                ),
                user=owner,
                db=db,
            )

        self.assertEqual(set(response.succeeded), set(ids))
        self.assertEqual(response.failed, [])
        self.assertEqual(create_token.await_count, 3)
        for call in create_token.await_args_list:
            self.assertEqual(call.kwargs["expires_hours"], 24)
            self.assertEqual(call.kwargs["basic_auth_password"], "secret")
            self.assertEqual(call.kwargs["max_downloads"], 5)
            self.assertEqual(call.kwargs["created_by_id"], owner.id)
        db.commit.assert_awaited_once()

    async def test_skips_non_owned_files(self) -> None:
        owner = _user()
        owned = uuid.uuid4()
        not_owned = uuid.uuid4()
        db = _db()

        with (
            patch("app.api.files._get_owned_file", new=_owned_lookup(owner, {owned})),
            patch("app.api.files.create_access_token", new=AsyncMock()) as create_token,
        ):
            response = await bulk_create_share(
                BulkCreateFileShareRequest(file_ids=[not_owned, owned]),
                user=owner,
                db=db,
            )

        self.assertEqual(response.succeeded, [owned])
        self.assertEqual(response.failed, [not_owned])
        create_token.assert_awaited_once()
        self.assertEqual(create_token.await_args.kwargs["file_id"], owned)
        db.commit.assert_awaited_once()


async def _collect_stream(response: object) -> bytes:
    chunks: list[bytes] = []
    async for chunk in response.body_iterator:
        chunks.append(chunk if isinstance(chunk, bytes) else chunk.encode())
    return b"".join(chunks)


class BulkDownloadApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_zips_accessible_files_and_dedupes_names(self) -> None:
        owner = _user()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            paths: dict[uuid.UUID, Path] = {}
            rows: dict[uuid.UUID, SimpleNamespace] = {}
            # Two files share the same filename to exercise collision handling.
            specs = [("report.csv", b"a,b\n1,2\n"), ("report.csv", b"x,y\n3,4\n")]
            for i, (name, data) in enumerate(specs):
                fid = uuid.uuid4()
                disk = tmp_path / f"{i}.bin"
                disk.write_bytes(data)
                paths[fid] = disk
                rows[fid] = SimpleNamespace(id=fid, filename=name)

            async def _access(_db: object, file_id: uuid.UUID, _user: object) -> object:
                row = rows.get(file_id)
                return (row, False, None, None) if row else None

            with (
                patch("app.api.files._get_accessible_file", new=AsyncMock(side_effect=_access)),
                patch("app.api.files.get_file_path", new=lambda row: paths[row.id]),
            ):
                response = await bulk_download_files(
                    BulkFileDownloadRequest(file_ids=list(rows.keys())),
                    user=owner,
                    db=_db(),
                )

            self.assertEqual(response.media_type, "application/zip")
            body = await _collect_stream(response)
            with zipfile.ZipFile(io.BytesIO(body)) as archive:
                names = archive.namelist()
                self.assertEqual(len(names), 2)
                self.assertIn("report.csv", names)
                self.assertIn("report (1).csv", names)

    async def test_raises_404_when_no_files_accessible(self) -> None:
        owner = _user()
        with patch("app.api.files._get_accessible_file", new=AsyncMock(return_value=None)):
            with self.assertRaises(HTTPException) as ctx:
                await bulk_download_files(
                    BulkFileDownloadRequest(file_ids=[uuid.uuid4()]),
                    user=owner,
                    db=_db(),
                )
        self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
