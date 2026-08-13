from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.opencode_usage_service import (
    fetch_opencode_usage,
    parse_opencode_usage,
    usage_url,
)


def _payload(**overrides) -> dict:
    usage = {
        "rolling": {"percent": 12, "status": "ok", "resetsAt": "2099-01-01T00:00:00Z"},
        "weekly": {"percent": 40, "status": "ok", "resetsAt": "2099-01-02T00:00:00Z"},
        "monthly": {"percent": 100, "status": "rate-limited", "resetsAt": "2099-02-01T00:00:00Z"},
    }
    usage.update(overrides)
    return {"usage": usage}


class UsageUrlTest(TestCase):
    def test_strips_v1_and_trailing_slash(self) -> None:
        for base in (
            "https://opencode.ai/zen/go/v1",
            "https://opencode.ai/zen/go/v1/",
            "https://opencode.ai/zen/go",
            "",
        ):
            self.assertEqual(usage_url(base), "https://opencode.ai/zen/go/v1/usage")

    def test_preserves_a_custom_gateway_prefix(self) -> None:
        self.assertEqual(
            usage_url("https://gw.example.com/oc/v1"), "https://gw.example.com/oc/v1/usage"
        )


class ParseUsageTest(TestCase):
    def test_parses_all_three_windows_in_order(self) -> None:
        result = parse_opencode_usage(_payload())
        self.assertTrue(result.available)
        self.assertEqual([w.key for w in result.windows], ["rolling", "weekly", "monthly"])
        self.assertEqual([w.label for w in result.windows], ["5 hours", "Weekly", "Monthly"])
        self.assertEqual(result.windows[0].used_percent, 12.0)
        self.assertEqual(result.windows[2].status, "rate-limited")

    def test_reset_seconds_derived_from_iso_timestamp(self) -> None:
        window = parse_opencode_usage(_payload()).windows[0]
        self.assertEqual(window.resets_at, "2099-01-01T00:00:00Z")
        self.assertIsNotNone(window.reset_after_seconds)
        self.assertGreater(window.reset_after_seconds or 0, 0)

    def test_accepts_the_unwrapped_shape(self) -> None:
        # The route is undocumented and has already changed shape once.
        result = parse_opencode_usage(_payload()["usage"])
        self.assertTrue(result.available)
        self.assertEqual(len(result.windows), 3)

    def test_skips_malformed_windows_instead_of_failing(self) -> None:
        result = parse_opencode_usage(
            _payload(
                weekly={"percent": "40", "status": "ok"},
                monthly={"percent": 150, "status": "ok"},
            )
        )
        self.assertTrue(result.available)
        self.assertEqual([w.key for w in result.windows], ["rolling"])

    def test_missing_status_defaults_to_ok(self) -> None:
        result = parse_opencode_usage({"usage": {"rolling": {"percent": 5}}})
        self.assertEqual(result.windows[0].status, "ok")
        self.assertIsNone(result.windows[0].reset_after_seconds)

    def test_no_usable_windows_is_unavailable(self) -> None:
        for payload in ({"usage": {}}, {"usage": {"rolling": {}}}, [], None, "nope"):
            result = parse_opencode_usage(payload)
            self.assertFalse(result.available)
            self.assertTrue(result.error)


class FetchUsageTest(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        import app.services.opencode_usage_service as mod

        mod._cache.clear()

    async def _fetch_with_response(self, status_code: int, json_payload: object) -> object:
        response = MagicMock()
        response.status_code = status_code
        response.json.return_value = json_payload
        client = AsyncMock()
        client.get = AsyncMock(return_value=response)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        with patch("app.services.opencode_usage_service.httpx.AsyncClient", return_value=client):
            result = await fetch_opencode_usage(credential_id="c1", api_key="sk-test")
        return result, client

    async def test_success_sends_bearer_token_to_the_usage_url(self) -> None:
        result, client = await self._fetch_with_response(200, _payload())
        self.assertTrue(result.available)
        self.assertEqual(len(result.windows), 3)
        url = client.get.call_args[0][0]
        headers = client.get.call_args.kwargs["headers"]
        self.assertEqual(url, "https://opencode.ai/zen/go/v1/usage")
        self.assertEqual(headers["Authorization"], "Bearer sk-test")

    async def test_401_reports_an_invalid_key(self) -> None:
        result, _ = await self._fetch_with_response(401, {})
        self.assertFalse(result.available)
        self.assertIn("API key", result.error or "")

    async def test_403_reports_a_missing_subscription(self) -> None:
        result, _ = await self._fetch_with_response(403, {})
        self.assertFalse(result.available)
        self.assertIn("subscription", result.error or "")

    async def test_missing_api_key_never_calls_the_gateway(self) -> None:
        with patch("app.services.opencode_usage_service.httpx.AsyncClient") as client:
            result = await fetch_opencode_usage(credential_id="c2", api_key="")
        client.assert_not_called()
        self.assertFalse(result.available)

    async def test_result_is_cached_per_credential(self) -> None:
        _, client = await self._fetch_with_response(200, _payload())
        self.assertEqual(client.get.await_count, 1)
        with patch("app.services.opencode_usage_service.httpx.AsyncClient") as second:
            again = await fetch_opencode_usage(credential_id="c1", api_key="sk-test")
        second.assert_not_called()
        self.assertTrue(again.available)

    async def test_transport_error_is_swallowed(self) -> None:
        client = AsyncMock()
        client.get = AsyncMock(side_effect=OSError("boom"))
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        with patch("app.services.opencode_usage_service.httpx.AsyncClient", return_value=client):
            result = await fetch_opencode_usage(credential_id="c3", api_key="sk-test")
        self.assertFalse(result.available)
        self.assertIn("OSError", result.error or "")
