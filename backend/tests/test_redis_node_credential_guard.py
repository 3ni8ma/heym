"""The Redis node must fail closed when a credential does not resolve to a destination.

`_get_accessible_credential` returns ``None`` both for a credential that does not exist
and for one the caller has no access to. Letting that become an empty configuration used
to fall through to the ``localhost:6379`` defaults, so an authorization result turned into
a connection. These tests pin the two halves of the fix: the access check raises, and the
host is required rather than defaulted.
"""

import unittest
from unittest.mock import MagicMock, patch

from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes import redis_node

OPERATIONS = ["get", "set", "hasKey", "deleteKey"]

COMPLETE_CONFIG = {
    "redis_host": "redis.internal.example.com",
    "redis_port": 6380,
    "redis_password": "secret",
    "redis_db": 2,
}


def _context(operation: str) -> NodeExecutionContext:
    executor = MagicMock()
    executor.evaluate_message_template.side_effect = lambda tpl, inputs, node_id: str(tpl)

    data = {
        "credentialId": "credential-under-test",
        "redisOperation": operation,
        "redisKey": "some-key",
        "redisValue": "some-value",
    }
    return NodeExecutionContext(
        executor=executor,
        node_id="redis-1",
        inputs={},
        allow_branch_skip=False,
        start_time=0,
        node={"id": "redis-1", "type": "redis", "data": data},
        node_type="redis",
        node_data=data,
        node_label="redisNode",
    )


def _run(operation: str, credential: object, config: dict):
    """Execute the node and report what it raised and whether it dialled."""
    ctx = _context(operation)
    ctx.executor._get_accessible_credential.return_value = credential

    with (
        patch("app.services.encryption.decrypt_config", return_value=config),
        patch("app.services.redis_pool.get_redis_connection") as connect,
    ):
        try:
            redis_node.execute(ctx)
        except Exception as exc:  # noqa: BLE001 - the test asserts on the raised value
            return exc, connect
        return None, connect


def _accessible_credential() -> MagicMock:
    credential = MagicMock()
    credential.encrypted_config = "encrypted"
    return credential


class RedisCredentialAccessTests(unittest.TestCase):
    def test_unresolvable_credential_raises_without_connecting(self) -> None:
        """Covers both a credential ID that does not exist and one the caller cannot reach.

        `_get_accessible_credential` collapses those two database states into ``None``,
        and the node sees only that. One message for both also keeps the response from
        disclosing whether a credential ID exists.
        """
        for operation in OPERATIONS:
            with self.subTest(operation=operation):
                error, connect = _run(operation, None, {})
                self.assertIsInstance(error, ValueError)
                self.assertIn("not found or invalid", str(error))
                connect.assert_not_called()

    def test_accessible_credential_with_empty_config_raises_without_connecting(self) -> None:
        for operation in OPERATIONS:
            with self.subTest(operation=operation):
                error, connect = _run(operation, _accessible_credential(), {})
                self.assertIsInstance(error, ValueError)
                self.assertIn("redis_host", str(error))
                connect.assert_not_called()

    def test_accessible_credential_without_host_raises_without_connecting(self) -> None:
        """A credential may legitimately lack `redis_host`; it must not resolve to loopback."""
        for config in ({"redis_password": "secret"}, {"redis_host": "   "}):
            with self.subTest(config=config):
                error, connect = _run("get", _accessible_credential(), config)
                self.assertIsInstance(error, ValueError)
                self.assertIn("redis_host", str(error))
                connect.assert_not_called()

    def test_no_failure_path_falls_back_to_localhost(self) -> None:
        """Whatever the failure, the node must never dial the default destination."""
        for credential, config in (
            (None, {}),
            (_accessible_credential(), {}),
            (_accessible_credential(), {"redis_password": "secret"}),
        ):
            with self.subTest(config=config, credential=credential is not None):
                _, connect = _run("get", credential, config)
                connect.assert_not_called()


class RedisCredentialControlTests(unittest.TestCase):
    def test_complete_credential_connects_to_its_own_destination(self) -> None:
        """Control: the normal path is unchanged and uses the credential, not the defaults."""
        ctx = _context("get")
        ctx.executor._get_accessible_credential.return_value = _accessible_credential()

        with (
            patch("app.services.encryption.decrypt_config", return_value=COMPLETE_CONFIG),
            patch("app.services.redis_pool.get_redis_connection") as connect,
        ):
            connect.return_value.get.return_value = "stored-value"
            output = redis_node.execute(ctx)

        connect.assert_called_once_with(
            host="redis.internal.example.com",
            port=6380,
            db=2,
            password="secret",
        )
        self.assertEqual(output["value"], "stored-value")


if __name__ == "__main__":
    unittest.main()
