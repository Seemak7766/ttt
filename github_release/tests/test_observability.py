import os
import unittest
from contextlib import nullcontext
from unittest.mock import Mock, patch

from observability import observed, redact


class ObservabilityTests(unittest.TestCase):
    def settings(self, enabled=False, key=""):
        return {"enabled": enabled, "api_key": key, "project": "test-project", "endpoint": "https://api.smith.langchain.com", "workspace_id": None}

    def test_secrets_are_redacted_in_fields_and_nested_strings(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "private-openai", "KAKAO_REST_API_KEY": "private-kakao", "LANGSMITH_API_KEY": "private-langsmith"}):
            data = redact({"api_key": "do-not-log", "items": [{"query": "private-openai private-kakao private-langsmith"}], "Authorization": "KakaoAK key"})
        self.assertNotIn("private-", str(data))
        self.assertNotIn("do-not-log", str(data))
        self.assertEqual(data["Authorization"], "[비공개]")

    def test_disabled_or_missing_key_never_creates_client(self):
        for settings in (self.settings(), self.settings(True)):
            with patch("observability.load_langsmith_settings", return_value=settings), patch("observability.configured_client") as client, patch("observability.tracing_context", return_value=nullcontext()) as context:
                @observed("test")
                def operation():
                    return "ok"
                self.assertEqual(operation(), "ok")
                client.assert_not_called()
                self.assertFalse(context.call_args.kwargs["enabled"])

    def test_client_configuration_failure_does_not_repeat_operation(self):
        calls = Mock(return_value="answer")
        with patch("observability.load_langsmith_settings", return_value=self.settings(True, "secret")), patch("observability.configured_client", side_effect=ValueError("secret")), patch("observability.tracing_context", return_value=nullcontext()):
            wrapped = observed("test")(calls)
            self.assertEqual(wrapped(), "answer")
            calls.assert_called_once()
