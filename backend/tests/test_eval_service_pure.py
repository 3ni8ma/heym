"""Tests for eval_service — pure functions: retry logic, scoring, and judge response parsing."""

import unittest

from app.services.eval_service import (
    _is_retryable_error,
    _parse_combined_judge_response,
    _score_contains,
    _score_exact_match,
)


class IsRetryableErrorTests(unittest.TestCase):
    """Tests for _is_retryable_error exception classification."""

    def test_503_in_message(self) -> None:
        assert _is_retryable_error(Exception("Error 503")) is True

    def test_too_many_requests(self) -> None:
        assert _is_retryable_error(Exception("too_many_requests_error")) is True

    def test_queue_exceeded(self) -> None:
        assert _is_retryable_error(Exception("queue_exceeded")) is True

    def test_rate_limit(self) -> None:
        assert _is_retryable_error(Exception("rate_limit exceeded")) is True

    def test_non_retryable_error(self) -> None:
        assert _is_retryable_error(Exception("invalid api key")) is False

    def test_empty_message(self) -> None:
        assert _is_retryable_error(Exception("")) is False

    def test_case_insensitive(self) -> None:
        assert _is_retryable_error(Exception("TOO_MANY_REQUESTS_ERROR")) is True

    def test_mixed_content(self) -> None:
        assert _is_retryable_error(Exception("Server returned 503 temporarily")) is True


class ScoreExactMatchTests(unittest.TestCase):
    """Tests for _score_exact_match string comparison."""

    def test_exact_match(self) -> None:
        assert _score_exact_match("hello", "hello") == "100"

    def test_no_match(self) -> None:
        assert _score_exact_match("hello", "world") == "0"

    def test_whitespace_stripped(self) -> None:
        assert _score_exact_match("  hello  ", "hello") == "100"

    def test_case_sensitive(self) -> None:
        assert _score_exact_match("Hello", "hello") == "0"

    def test_empty_strings(self) -> None:
        assert _score_exact_match("", "") == "100"

    def test_none_actual(self) -> None:
        assert _score_exact_match(None, "hello") == "0"

    def test_none_expected(self) -> None:
        assert _score_exact_match("hello", None) == "0"

    def test_both_none(self) -> None:
        assert _score_exact_match(None, None) == "100"


class ScoreContainsTests(unittest.TestCase):
    """Tests for _score_contains substring matching."""

    def test_contains(self) -> None:
        assert _score_contains("hello world", "world") == "100"

    def test_not_contains(self) -> None:
        assert _score_contains("hello world", "xyz") == "0"

    def test_empty_expected_returns_100(self) -> None:
        assert _score_contains("hello", "") == "100"

    def test_whitespace_expected_returns_100(self) -> None:
        assert _score_contains("hello", "  ") == "100"

    def test_none_actual(self) -> None:
        assert _score_contains(None, "hello") == "0"

    def test_none_expected(self) -> None:
        assert _score_contains("hello", None) == "100"

    def test_empty_actual(self) -> None:
        assert _score_contains("", "hello") == "0"

    def test_case_sensitive(self) -> None:
        assert _score_contains("Hello World", "hello") == "0"


class ParseCombinedJudgeResponseTests(unittest.TestCase):
    """Tests for _parse_combined_judge_response JSON parsing with format handling."""

    def test_plain_json(self) -> None:
        text = '{"actual_answer": "Paris", "score": 95, "explanation": "Correct"}'
        actual, score, explanation = _parse_combined_judge_response(text)
        assert actual == "Paris"
        assert score == "95"
        assert explanation == "Correct"

    def test_markdown_fenced_json(self) -> None:
        text = '```json\n{"actual_answer": "Paris", "score": 85, "explanation": "Good"}\n```'
        actual, score, explanation = _parse_combined_judge_response(text)
        assert actual == "Paris"
        assert score == "85"

    def test_markdown_fenced_without_json_label(self) -> None:
        text = '```\n{"actual_answer": "Paris", "score": 90, "explanation": "OK"}\n```'
        actual, score, explanation = _parse_combined_judge_response(text)
        assert actual == "Paris"
        assert score == "90"

    def test_nested_response_wrapper(self) -> None:
        text = '{"response": {"actual_answer": "Paris", "score": 80, "explanation": "Fine"}}'
        actual, score, explanation = _parse_combined_judge_response(text)
        assert actual == "Paris"
        assert score == "80"

    def test_nested_output_wrapper(self) -> None:
        text = '{"output": {"actual_answer": "Paris", "score": 70, "explanation": "OK"}}'
        actual, score, explanation = _parse_combined_judge_response(text)
        assert actual == "Paris"
        assert score == "70"

    def test_alternative_answer_key(self) -> None:
        text = '{"answer": "Paris", "score": 90, "explanation": "Correct"}'
        actual, score, explanation = _parse_combined_judge_response(text)
        assert actual == "Paris"
        assert score == "90"

    def test_score_clamped_to_100(self) -> None:
        text = '{"actual_answer": "Paris", "score": 150, "explanation": "High"}'
        _, score, _ = _parse_combined_judge_response(text)
        assert score == "100"

    def test_score_clamped_to_0(self) -> None:
        text = '{"actual_answer": "Paris", "score": -10, "explanation": "Low"}'
        _, score, _ = _parse_combined_judge_response(text)
        assert score == "0"

    def test_invalid_score_falls_back_to_0(self) -> None:
        text = '{"actual_answer": "Paris", "score": "not_a_number", "explanation": "Bad"}'
        _, score, _ = _parse_combined_judge_response(text)
        assert score == "0"

    def test_none_score_falls_back_to_0(self) -> None:
        text = '{"actual_answer": "Paris", "score": null, "explanation": "Null"}'
        _, score, _ = _parse_combined_judge_response(text)
        assert score == "0"

    def test_empty_text(self) -> None:
        actual, score, explanation = _parse_combined_judge_response("")
        assert actual == ""
        assert score == "0"
        assert explanation is None

    def test_none_text(self) -> None:
        actual, score, explanation = _parse_combined_judge_response(None)
        assert actual == ""
        assert score == "0"
        assert explanation is None

    def test_no_json_found(self) -> None:
        actual, score, explanation = _parse_combined_judge_response("just plain text")
        assert actual == ""
        assert score == "0"
        assert explanation is None

    def test_malformed_json(self) -> None:
        actual, score, explanation = _parse_combined_judge_response("{invalid json}}")
        assert actual == ""
        assert score == "0"

    def test_extra_text_around_json(self) -> None:
        text = 'Here is my analysis:\n{"actual_answer": "Paris", "score": 90, "explanation": "Good"}\nDone.'
        actual, score, explanation = _parse_combined_judge_response(text)
        assert actual == "Paris"
        assert score == "90"

    def test_empty_actual_answer(self) -> None:
        text = '{"actual_answer": "", "score": 0, "explanation": "No answer"}'
        actual, score, explanation = _parse_combined_judge_response(text)
        assert actual == ""
        assert score == "0"

    def test_missing_explanation(self) -> None:
        text = '{"actual_answer": "Paris", "score": 90}'
        actual, score, explanation = _parse_combined_judge_response(text)
        assert actual == "Paris"
        assert score == "90"
        assert explanation is None

    def test_empty_explanation(self) -> None:
        text = '{"actual_answer": "Paris", "score": 90, "explanation": ""}'
        actual, score, explanation = _parse_combined_judge_response(text)
        assert explanation is None


if __name__ == "__main__":
    unittest.main()
