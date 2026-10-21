import unittest
from types import SimpleNamespace
from unittest.mock import patch
from chatbot import ChatbotError, answer_question, summarize_conversation


class ChatbotTests(unittest.TestCase):
    def setUp(self):
        key_patch = patch("chatbot.load_kakao_rest_api_key", return_value="")
        key_patch.start()
        self.addCleanup(key_patch.stop)

    @patch("chatbot.ChatOpenAI")
    @patch("chatbot.load_settings")
    def test_blank(self, settings, client):
        with self.assertRaises(ChatbotError):
            answer_question("  \n")
        settings.assert_not_called()
        client.assert_not_called()

    @patch("chatbot.ChatOpenAI")
    @patch("chatbot.load_settings", return_value=("", "test-model"))
    def test_missing_key(self, settings, client):
        with self.assertRaises(ChatbotError):
            answer_question("여행")
        client.assert_not_called()

    @patch("chatbot.ChatOpenAI")
    @patch("chatbot.load_settings", return_value=("secret-test-key", "test-model"))
    def test_safe_error(self, settings, client):
        client.return_value.invoke.side_effect = RuntimeError("secret-test-key")
        with self.assertRaises(ChatbotError) as caught:
            answer_question("여행")
        self.assertNotIn("secret-test-key", str(caught.exception))

    @patch("chatbot.ChatOpenAI")
    @patch("chatbot.load_settings", return_value=("secret-test-key", "test-model"))
    def test_no_history(self, settings, client):
        client.return_value.invoke.return_value = SimpleNamespace(content="여행 안내")
        answer_question("부산")
        answer_question("제주")
        messages = client.return_value.invoke.call_args.args[0]
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[1].content, "제주")
        self.assertNotIn("부산", str(messages))

    @patch("chatbot.ChatOpenAI")
    @patch("chatbot.load_settings", return_value=("secret-test-key", "test-model"))
    def test_text_blocks_are_supported(self, settings, client):
        client.return_value.invoke.return_value = SimpleNamespace(content=[
            {"type": "reasoning", "summary": []},
            {"type": "text", "text": "제주 여행 안내"},
        ])
        self.assertEqual(answer_question("제주 여행"), "제주 여행 안내")

    @patch("chatbot.ChatOpenAI")
    @patch("chatbot.load_settings", return_value=("secret-test-key", "test-model"))
    def test_selected_history_is_sent_in_order(self, settings, client):
        client.return_value.invoke.return_value = SimpleNamespace(content="네, 추천합니다.")
        history = [
            {"role": "user", "content": "제주도로 갈게"},
            {"role": "assistant", "content": "며칠 여행하시나요?"},
        ]
        original = [message.copy() for message in history]
        answer_question("3일이야", history)
        messages = client.return_value.invoke.call_args.args[0]
        self.assertEqual([message.type for message in messages], ["system", "human", "ai", "human"])
        self.assertEqual([message.content for message in messages[1:]], ["제주도로 갈게", "며칠 여행하시나요?", "3일이야"])
        self.assertEqual(history, original)
        from chatbot import SYSTEM_PROMPT_PATH
        self.assertEqual(messages[0].content, SYSTEM_PROMPT_PATH.read_text(encoding="utf-8"))

    def test_conversation_switch_and_memory(self):
        from pathlib import Path
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=20)
        received_histories = []

        def reply(question, history, *, execution_log=None, **kwargs):
            received_histories.append([message.copy() for message in history])
            return "여행 일정입니다."

        with patch("chatbot.answer_question", side_effect=reply), patch(
            "chatbot.summarize_conversation", side_effect=lambda history, fallback: "제주 여행" if "제주" in history[0]["content"] else "부산 여행"
        ):
            app.run()
            app.text_area[0].set_value("제주 여행")
            next(button for button in app.button if button.label == "답변 받기").click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(any(item.label.startswith("실행 결과 (IPO)") for item in app.expander))
            first_id = app.session_state.active_conversation
            first_time = app.session_state.conversations[first_id]["last_question_at"]
            self.assertEqual(first_time.utcoffset().total_seconds(), 9 * 3600)
            self.assertEqual(app.session_state.conversations[first_id]["messages"][0]["sent_at"], first_time.strftime("%Y.%m.%d %H:%M"))
            question_rows = [item.value for item in app.markdown if 'class="question-row"' in item.value]
            self.assertTrue(any(first_time.strftime("%Y.%m.%d %H:%M") in row for row in question_rows))
            self.assertTrue(any(first_time.strftime("%Y.%m.%d %H:%M") in button.label for button in app.sidebar.button))
            app.text_area[0].set_value("3일로 해줘")
            next(button for button in app.button if button.label == "답변 받기").click().run()
            self.assertEqual(len(received_histories[0]), 0)
            self.assertEqual(len(received_histories[1]), 2)
            next(button for button in app.sidebar.button if button.key == "sidebar_new_conversation").click().run()
            self.assertNotEqual(app.session_state.active_conversation, first_id)
            self.assertEqual(len(app.chat_message), 0)
            self.assertIsNone(app.session_state.conversations[app.session_state.active_conversation]["last_question_at"])
            app.text_area[0].set_value("부산 여행")
            next(button for button in app.button if button.label == "답변 받기").click().run()
            self.assertEqual(received_histories[2], [])
            self.assertEqual(len(app.session_state.conversations[first_id]["messages"]), 4)
            old_chat_button = next(button for button in app.sidebar.button if button.label.startswith("제주 여행\n"))
            old_chat_button.click().run()
            self.assertEqual(app.session_state.active_conversation, first_id)
            self.assertEqual(len(app.chat_message), 4)
            self.assertEqual(len(app.exception), 0)
            # 오래된 대화에 새 질문을 보내면 새로 만든 대화보다 위로 이동합니다.
            app.text_area[0].set_value("제주 마지막 날도 추천해줘")
            next(button for button in app.button if button.label == "답변 받기").click().run()
            self.assertTrue(next(button for button in app.sidebar.button if button.key in app.session_state.conversations).label.startswith("제주 여행\n"))


    @patch("chatbot.ChatOpenAI")
    @patch("chatbot.load_settings", return_value=("secret-test-key", "test-model"))
    def test_summary_uses_whole_conversation(self, settings, client):
        client.return_value.invoke.return_value = SimpleNamespace(content="제주 3일 버스 여행")
        history = [
            {"role": "user", "content": "제주 3일 여행"},
            {"role": "assistant", "content": "렌터카를 쓰시나요?"},
            {"role": "user", "content": "버스만 탈게"},
        ]
        self.assertEqual(summarize_conversation(history), "제주 3일 버스 여행")
        data = client.return_value.invoke.call_args.args[0][1].content
        self.assertIn("제주 3일 여행", data)
        self.assertIn("버스만 탈게", data)

    @patch("chatbot.ChatOpenAI")
    @patch("chatbot.load_settings", return_value=("secret-test-key", "test-model"))
    def test_summary_failure_keeps_title(self, settings, client):
        client.return_value.invoke.side_effect = RuntimeError("secret-test-key")
        self.assertEqual(summarize_conversation([{"role": "user", "content": "여행"}], "기존 제목"), "기존 제목")

    @patch("chatbot.search_places")
    @patch("chatbot.ChatOpenAI")
    @patch("chatbot.load_settings", return_value=("secret-test-key", "test-model"))
    def test_kakao_tool_results_reach_answer(self, settings, client, search):
        from langchain_core.messages import AIMessage
        search.return_value = {"status": "ok", "message": "검색 결과", "places": [{
            "name": "테스트 관광지", "address": "제주시", "map_url": "https://place.map.kakao.com/123",
        }]}
        client.return_value.bind_tools.return_value.invoke.side_effect = [
            AIMessage(content="", tool_calls=[{"name": "search_kakao_places", "args": {"query": "제주 관광지"}, "id": "lookup1"}]),
            AIMessage(content="제주 관광지를 추천합니다."),
        ]
        client.return_value.invoke.return_value = AIMessage(content="조회한 관광지입니다.")
        with patch("chatbot.load_kakao_rest_api_key", return_value="kakao-secret"):
            answer = answer_question("제주 관광지 찾아줘")
        search.assert_called_once_with("제주 관광지", "kakao-secret", allow_fallback=False)
        self.assertIn("https://place.map.kakao.com/123", answer)
        self.assertIn("제주시", answer)
        self.assertNotIn("kakao-secret", answer)
        messages = client.return_value.invoke.call_args.args[0]
        self.assertEqual(messages[-1].type, "tool")
        self.assertEqual(messages[-1].tool_call_id, "lookup1")

    @patch("chatbot.search_places")
    @patch("chatbot.ChatOpenAI")
    @patch("chatbot.load_settings", return_value=("secret-test-key", "test-model"))
    def test_kakao_is_not_called_without_tool_request(self, settings, client, search):
        from langchain_core.messages import AIMessage
        client.return_value.bind_tools.return_value.invoke.return_value = AIMessage(content="여행 관련 질문을 해 주세요.")
        with patch("chatbot.load_kakao_rest_api_key", return_value="kakao-secret"):
            answer_question("수학 숙제를 풀어줘")
        search.assert_not_called()

    @patch("chatbot.search_places")
    @patch("chatbot.ChatOpenAI")
    @patch("chatbot.load_settings", return_value=("secret-test-key", "test-model"))
    def test_tool_calls_are_bounded(self, settings, client, search):
        from langchain_core.messages import AIMessage
        search.return_value = {"status": "no_results", "message": "검색 결과가 없습니다.", "places": []}
        client.return_value.bind_tools.return_value.invoke.return_value = AIMessage(content="", tool_calls=[
            {"name": "search_kakao_places", "args": {"query": "제주 관광지"}, "id": f"lookup{i}"} for i in range(5)
        ])
        client.return_value.invoke.return_value = AIMessage(content="지역을 구체적으로 알려 주세요.")
        with patch("chatbot.load_kakao_rest_api_key", return_value="kakao-secret"):
            answer = answer_question("제주 여행")
        self.assertEqual(search.call_count, 3)
        self.assertIn("검색 결과가 없습니다", answer)

    @patch("chatbot.ChatOpenAI")
    @patch("chatbot.search_places")
    def test_greeting_never_calls_model_or_place_tool(self, search, client):
        log = []
        self.assertIn("안녕하세요", answer_question("안녕하세요!", execution_log=log))
        self.assertEqual(log, [])
        search.assert_not_called()
        client.assert_not_called()

    @patch("chatbot.search_places")
    @patch("chatbot.ChatOpenAI")
    @patch("chatbot.load_settings", return_value=("secret-test-key", "test-model"))
    def test_ipo_records_structured_arguments_and_only_returns_places(self, settings, client, search):
        from langchain_core.messages import AIMessage
        search.return_value = {"status": "ok", "message": "검색 결과", "places": [{
            "name": "조회된 식당", "address": "부산 해운대구", "map_url": "https://place.map.kakao.com/123",
        }]}
        client.return_value.bind_tools.return_value.invoke.side_effect = [
            AIMessage(content="", tool_calls=[{"name": "search_kakao_places", "args": {
                "region": "해운대", "place_type": "식당", "visit_conditions": "주차 가능",
            }, "id": "lookup1"}]),
            AIMessage(content="조회하지 않은 식당과 주차 가능을 확정하는 잘못된 설명"),
        ]
        log = []
        client.return_value.invoke.return_value = AIMessage(content="조회한 식당입니다.")
        with patch("chatbot.load_kakao_rest_api_key", return_value="kakao-secret"):
            answer = answer_question("주차 가능한 해운대 식당 찾아줘", execution_log=log)
        search.assert_called_once_with("해운대 식당", "kakao-secret", allow_fallback=False)
        self.assertEqual(log[0]["arguments"], {"region": "해운대", "place_type": "식당", "visit_conditions": "주차 가능", "query": "해운대 식당"})
        self.assertEqual(log[0]["status"], "ok")
        self.assertEqual(log[0]["result_count"], 1)
        self.assertIn("조회된 식당", answer)
        self.assertNotIn("조회하지 않은", answer)
        self.assertNotIn("날짜", answer)
        self.assertNotIn("kakao-secret", str(log))

    @patch("chatbot.search_places")
    @patch("chatbot.ChatOpenAI")
    @patch("chatbot.load_settings", return_value=("secret-test-key", "test-model"))
    def test_ipo_logs_search_failure_without_key(self, settings, client, search):
        from langchain_core.messages import AIMessage
        search.return_value = {"status": "auth_error", "message": "인증 또는 권한을 확인해 주세요.", "places": []}
        client.return_value.bind_tools.return_value.invoke.side_effect = [
            AIMessage(content="", tool_calls=[{"name": "search_kakao_places", "args": {"query": "해운대 식당"}, "id": "lookup1"}]),
            AIMessage(content="인증 실패"),
        ]
        log = []
        client.return_value.invoke.return_value = AIMessage(content="인증 실패")
        with patch("chatbot.load_kakao_rest_api_key", return_value="kakao-secret"):
            answer_question("해운대 식당 찾아줘", execution_log=log)
        self.assertEqual(log[0]["status"], "auth_error")
        self.assertNotIn("kakao-secret", str(log))
