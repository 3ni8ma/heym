"""GHSA-6x65-w7q7-wg93 finding 5: Discord interaction token in persisted run data."""

import unittest

from app.api.discord import _redact_interaction_token

_TOKEN = "discord-interaction-token"


class DiscordTokenRedactionTests(unittest.TestCase):
    def test_token_is_dropped_from_run_inputs(self) -> None:
        inputs = {
            "triggered_by": "Discord",
            "interaction": {"token": _TOKEN, "application_id": "123", "id": "456"},
        }

        redacted = _redact_interaction_token(inputs, _TOKEN)

        self.assertEqual(redacted["interaction"]["token"], "[redacted]")

    def test_application_id_is_kept(self) -> None:
        """It identifies the app but is not the capability secret."""
        inputs = {"interaction": {"token": _TOKEN, "application_id": "123"}}

        redacted = _redact_interaction_token(inputs, _TOKEN)

        self.assertEqual(redacted["interaction"]["application_id"], "123")

    def test_node_output_copy_is_redacted_too(self) -> None:
        """The discordTrigger node copies the interaction into its own output."""
        node_results = [
            {
                "node_type": "discordTrigger",
                "output": {"interaction": {"token": _TOKEN, "id": "456"}},
            }
        ]

        redacted = _redact_interaction_token(node_results, _TOKEN)

        self.assertEqual(redacted[0]["output"]["interaction"]["token"], "[redacted]")
        self.assertEqual(redacted[0]["output"]["interaction"]["id"], "456")

    def test_token_embedded_in_a_string_is_scrubbed(self) -> None:
        outputs = {"url": f"https://discord.com/api/v10/webhooks/123/{_TOKEN}"}

        redacted = _redact_interaction_token(outputs, _TOKEN)

        self.assertNotIn(_TOKEN, redacted["url"])

    def test_nested_sub_workflow_structures_are_reached(self) -> None:
        payload = {"runs": [{"nodes": [{"out": {"interaction": {"token": _TOKEN}}}]}]}

        redacted = _redact_interaction_token(payload, _TOKEN)

        self.assertEqual(
            redacted["runs"][0]["nodes"][0]["out"]["interaction"]["token"], "[redacted]"
        )

    def test_original_structure_is_left_intact_for_the_followup_sender(self) -> None:
        interaction = {"token": _TOKEN, "application_id": "123"}
        inputs = {"interaction": interaction}

        _redact_interaction_token(inputs, _TOKEN)

        # The follow-up request reads this same object after the run finishes.
        self.assertEqual(interaction["token"], _TOKEN)
        self.assertEqual(inputs["interaction"]["token"], _TOKEN)

    def test_unrelated_values_are_untouched(self) -> None:
        payload = {"token": "some-other-value", "count": 3, "flag": None}

        self.assertEqual(_redact_interaction_token(payload, _TOKEN), payload)


if __name__ == "__main__":
    unittest.main()
