import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage

from chatbot import compare_runs, run_agent


def call(query, call_id):
    return AIMessage(content="", tool_calls=[{
        "name": "search_kakao_places", "args": {"query": query, "region": "경주", "place_type": "실내 장소"}, "id": call_id,
    }])


class AgentRunTests(unittest.TestCase):
    @patch("chatbot.load_kakao_rest_api_key", return_value="kakao-secret")
    @patch("chatbot.load_settings", return_value=("openai-secret", "test-model"))
    @patch("chatbot.ChatOpenAI")
    @patch("chatbot.search_places")
    def test_comparison_keeps_sequence_limits_and_last_evidence(self, search, client, settings, key):
        empty = {"status": "no_results", "message": "검색 결과가 없습니다.", "places": []}
        found = {"status": "ok", "message": "조회 성공", "places": [{
            "name": "조회된 미술관", "address": "경북 경주시", "category": "미술관", "map_url": "https://place.map.kakao.com/123",
        }]}
        search.side_effect = [empty.copy(), empty.copy(), found]
        client.return_value.bind_tools.return_value.invoke.side_effect = [call("경주 실내 전시관", "first"), call("경주 미술관", "second")]
        client.return_value.invoke.return_value = AIMessage(content="조회되지 않은 장소를 넣은 모델 답변")
        history = [{"role": "user", "content": "부모님과 경주에 갈 거야"}]
        single, retry = compare_runs("실내 장소를 찾아줘. 없으면 종류를 바꿔줘.", history)
        self.assertEqual((single["call_count"], single["limit"]), (1, 1))
        self.assertEqual((retry["call_count"], retry["limit"]), (2, 3))
        self.assertEqual(single["execution_log"][0]["arguments"], retry["execution_log"][0]["arguments"])
        self.assertEqual([e["event"] for e in single["events"]], ["tool_call", "tool_return", "answer"])
        self.assertEqual([e["event"] for e in retry["events"]], ["tool_call", "tool_return", "next_call", "tool_call", "tool_return", "answer"])
        self.assertEqual(retry["events"][2]["reason"], "no_results_retry")
        self.assertEqual(retry["events"][-1]["reason"], "search_succeeded")
        self.assertEqual(retry["events"][-1]["evidence_call"], 2)
        self.assertIn("조회된 미술관", retry["answer"])
        self.assertNotIn("조회되지 않은", retry["answer"])
        self.assertNotIn("검색 결과가 없습니다", retry["answer"])
        self.assertEqual(retry["execution_log"][-1]["result"]["places"], found["places"])
        self.assertEqual(len(history), 1)
        self.assertNotIn("kakao-secret", str(retry))
        self.assertNotIn("openai-secret", str(retry))
        self.assertTrue(all(c.kwargs == {"allow_fallback": False} for c in search.call_args_list))

    @patch("chatbot.load_kakao_rest_api_key", return_value="kakao-secret")
    @patch("chatbot.load_settings", return_value=("openai-secret", "test-model"))
    @patch("chatbot.ChatOpenAI")
    @patch("chatbot.search_places")
    def test_retry_stops_at_limit(self, search, client, settings, key):
        search.return_value = {"status": "no_results", "message": "검색 결과가 없습니다.", "places": []}
        client.return_value.bind_tools.return_value.invoke.side_effect = [call(f"검색어{i}", f"id{i}") for i in range(3)]
        client.return_value.invoke.return_value = AIMessage(content="조회 결과 없음")
        run = run_agent("경주 장소 찾아줘", mode="retry")
        self.assertEqual(search.call_count, 3)
        self.assertEqual(run["events"][-1]["reason"], "call_limit")
        self.assertEqual(run["events"][-1]["evidence_call"], 3)

    def test_greeting_has_answer_event_and_no_calls_in_both_modes(self):
        for run in compare_runs("안녕하세요"):
            self.assertEqual(run["call_count"], 0)
            self.assertEqual(run["events"][0]["reason"], "greeting_no_tool")

    def test_ui_automatically_runs_and_shows_execution_result(self):
        from pathlib import Path
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=20)
        with patch("chatbot.summarize_conversation", return_value="경주 장소 비교"):
            app.run()
            self.assertEqual(len(app.radio), 0)
            app.text_area[0].set_value("안녕하세요")
            next(button for button in app.button if button.label == "답변 받기").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.expander), 1)
        self.assertIn("실행 결과 (IPO)", app.expander[0].label)
        self.assertIn("0/3회", app.expander[0].label)
        active = app.session_state.conversations[app.session_state.active_conversation]
        self.assertEqual(len(active["messages"]), 2)
        self.assertEqual(len(active["messages"][-1]["runs"]), 1)
        self.assertEqual(active["messages"][-1]["runs"][0]["mode"], "retry")
