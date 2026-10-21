from datetime import date, datetime, timedelta
import unittest
from threading import Barrier
from unittest.mock import patch

import httpx

from chatbot import answer_question, run_agent
from weather_forecast import KST, ENDPOINT, resolve_relative_dates, fetch_forecast, render_forecast

NOW = datetime(2026, 10, 20, 23, 30, tzinfo=KST)
PLACE = {"name": "경주시청", "address": "경북 경주시", "x": "129.224", "y": "35.856", "map_url": "https://place.map.kakao.com/123"}


class WeatherTests(unittest.TestCase):
    @patch("weather_forecast.now_kst", return_value=NOW + timedelta(days=1))
    @patch("chatbot.infer_region_change", return_value="부산")
    @patch("chatbot.load_settings", return_value=("openai-secret", "test-model"))
    @patch("chatbot.load_kakao_rest_api_key", return_value="kakao-secret")
    @patch("chatbot.ChatOpenAI")
    @patch("weather_agent.search_places")
    @patch("weather_agent.fetch_forecast")
    def test_region_only_followup_refreshes_both_and_keeps_resolved_date(self, forecast, search, client, key, settings, infer, now):
        busan = {**PLACE, "name": "부산시청", "address": "부산", "x": "129.075", "y": "35.180"}
        search.return_value = {"status": "ok", "message": "검색 결과", "places": [busan]}
        forecast.return_value = {"status": "ok", "source": "Open-Meteo", "retrieved_at": NOW.isoformat(), "place": busan,
                                 "days": [{"date": "2026-10-23", "max_c": 24, "min_c": 14, "precipitation_probability": 10}]}
        history = [{"role": "user", "content": "3일 뒤 경주 날씨랑 장소 추천해줘"}, {
            "role": "assistant", "content": "경주 결과", "runs": [{"request_context": {
                "region": "경주", "dates": ["2026-10-23"], "combined": True,
            }}],
        }]
        run = run_agent("그럼 부산은?", history)
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["request_context"], {"region": "부산", "dates": ["2026-10-23"], "combined": True})
        self.assertEqual(run["call_count"], 3)
        self.assertEqual(set(run["sections"]), {"weather", "places"})
        self.assertEqual(forecast.call_args.args[1], [date(2026, 10, 23)])
        self.assertEqual({call.args[0] for call in search.call_args_list}, {"부산", "부산 관광지"})
        client.return_value.with_structured_output.assert_not_called()  # 변경 지역 재추출 불필요

    @patch("chatbot.infer_region_change")
    @patch("chatbot.load_settings", return_value=("openai-secret", "test-model"))
    @patch("chatbot.load_kakao_rest_api_key", return_value="")
    @patch("chatbot.ChatOpenAI")
    @patch("weather_agent.fetch_forecast")
    def test_explicit_places_only_does_not_refresh_weather(self, forecast, client, key, settings, infer):
        from langchain_core.messages import AIMessage
        client.return_value.invoke.return_value = AIMessage(content="부산 장소 안내")
        history = [{"role": "assistant", "content": "기존 결과", "runs": [{"request_context": {
            "region": "경주", "dates": ["2026-10-23"], "combined": True,
        }}]}]
        run = run_agent("날씨는 빼고 부산 장소만 추천해줘", history)
        self.assertEqual(run["answer"], "부산 장소 안내")
        forecast.assert_not_called()
        infer.assert_not_called()

    def test_old_run_weather_context_can_be_recovered(self):
        from weather_agent import previous_weather_context
        run = {"sections": {"weather": "날씨", "places": "장소"}, "execution_log": [
            {"tool": "search_kakao_places", "arguments": {"purpose": "weather_coordinates", "query": "경주"}},
            {"tool": "open_meteo_forecast", "arguments": {"dates": ["2026-10-23"]}},
        ]}
        self.assertEqual(previous_weather_context([{"role": "assistant", "runs": [run]}]), {
            "region": "경주", "dates": ["2026-10-23"], "combined": True,
        })

    @patch("weather_forecast.now_kst", return_value=NOW)
    @patch("chatbot.load_settings", return_value=("openai-secret", "test-model"))
    @patch("chatbot.load_kakao_rest_api_key", return_value="kakao-secret")
    @patch("chatbot.ChatOpenAI")
    @patch("weather_agent.search_places")
    @patch("weather_agent.fetch_forecast")
    def test_weather_and_recommendations_search_in_parallel(self, forecast, search, client, key, settings, now):
        client.return_value.with_structured_output.return_value.invoke.return_value = {"region": "경주"}
        both_started = Barrier(2)
        def search_reply(query, api_key, **kwargs):
            # 순차 호출이면 첫 요청이 여기서 실패합니다. 두 검색이 실제로 동시에 시작돼야 통과합니다.
            both_started.wait(timeout=3)
            place = {**PLACE, "name": "추천 관광지", "map_url": "https://place.map.kakao.com/456"} if "관광지" in query else PLACE
            return {"status": "ok", "message": "검색 결과", "places": [place]}
        search.side_effect = search_reply
        forecast.return_value = {"status": "ok", "source": "Open-Meteo", "retrieved_at": NOW.isoformat(), "place": PLACE,
                                 "days": [{"date": "2026-10-23", "max_c": 21, "min_c": 9, "precipitation_probability": 35}]}
        run = run_agent("3일뒤 경주 여행 가려는데 날씨랑 장소 추천 해줘")
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["call_count"], 3)
        self.assertIn("### 날씨", run["answer"])
        self.assertIn("21 · 9", run["answer"])
        self.assertIn("### 추천 장소", run["answer"])
        self.assertIn("추천 관광지", run["answer"])
        self.assertEqual({entry["branch"] for entry in run["execution_log"]}, {"weather", "recommendations"})
        self.assertEqual(len(run["events"][-1]["evidence_calls"]), 2)
        self.assertEqual(len({event["step"] for event in run["events"]}), len(run["events"]))
        self.assertEqual(run["events"][-1]["reason"], "parallel_completed")
        calls = {event["branch"]: event["step"] for event in run["events"] if event["event"] == "tool_call" and event["tool"] == "search_kakao_places"}
        returns = [event["step"] for event in run["events"] if event["event"] == "tool_return"]
        self.assertLess(max(calls.values()), min(returns))
        self.assertEqual(forecast.call_args.args[0]["x"], PLACE["x"])
        self.assertIn("추천 관광지", run["sections"]["places"])
        self.assertIn("21 · 9", run["sections"]["weather"])

    def test_ui_shows_weather_and_places_in_separate_equal_columns(self):
        from pathlib import Path
        from streamlit.testing.v1 import AppTest
        run = {"status": "completed", "answer": "날씨와 장소", "mode": "retry", "limit": 3, "call_count": 3,
               "sections": {"weather": "날씨 전용 결과", "places": "장소 전용 결과"}, "events": [], "execution_log": [
                   {"tool": "search_kakao_places", "branch": "weather", "status": "ok"},
                   {"tool": "open_meteo_forecast", "branch": "weather", "status": "ok"},
                   {"tool": "search_kakao_places", "branch": "recommendations", "status": "ok"},
               ]}
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=20)
        with patch("chatbot.run_agent", return_value=run), patch("chatbot.summarize_conversation", return_value="경주 여행"):
            app.run()
            app.text_area[0].set_value("경주 내일 날씨와 장소 추천")
            next(button for button in app.button if button.label == "답변 받기").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.columns), 2)
        self.assertEqual(len(app.columns[0].markdown), 0)
        self.assertEqual(len(app.columns[1].markdown), 0)
        self.assertEqual(sum(item.value == "날씨와 장소" for item in app.markdown), 1)
        self.assertIn("날씨 조회", app.columns[0].expander[0].label)
        self.assertIn("지역·장소 검색", app.columns[1].expander[0].label)
        self.assertIn("도구 호출 2회", app.columns[0].expander[0].label)
        self.assertIn("도구 호출 1회", app.columns[1].expander[0].label)

    @patch("weather_forecast.now_kst", return_value=NOW)
    @patch("chatbot.load_settings", return_value=("openai-secret", "test-model"))
    @patch("chatbot.load_kakao_rest_api_key", return_value="kakao-secret")
    @patch("chatbot.ChatOpenAI")
    @patch("chatbot.search_places")
    @patch("weather_agent.fetch_forecast")
    def test_invalid_weather_date_does_not_block_separate_place_request(self, forecast, search, client, key, settings, now):
        from langchain_core.messages import AIMessage
        client.return_value.bind_tools.return_value.invoke.return_value = AIMessage(content="", tool_calls=[{
            "name": "search_kakao_places", "args": {"query": "경주 관광지"}, "id": "places",
        }])
        client.return_value.invoke.return_value = AIMessage(content="장소 안내")
        search.return_value = {"status": "ok", "message": "검색 결과", "places": [PLACE]}
        run = run_agent("한 달 뒤 경주 날씨랑 장소 추천해줘")
        self.assertIn("예보 없음", run["sections"]["weather"])
        self.assertIn("경주시청", run["sections"]["places"])
        forecast.assert_not_called()
        search.assert_called_once()

    def test_relative_dates_use_korean_calendar(self):
        self.assertEqual(resolve_relative_dates("내일 경주 날씨", NOW.date()), [date(2026, 10, 21)])
        self.assertEqual(resolve_relative_dates("이번 주말 날씨", NOW.date()), [date(2026, 10, 24), date(2026, 10, 25)])
        self.assertEqual(resolve_relative_dates("다음 주 월요일", NOW.date()), [date(2026, 10, 26)])
        self.assertEqual(resolve_relative_dates("내일부터 모레까지", NOW.date()), [date(2026, 10, 21), date(2026, 10, 22)])
        self.assertEqual(resolve_relative_dates("내일", date(2026, 12, 31)), [date(2027, 1, 1)])
        self.assertEqual(resolve_relative_dates("이번 주말", date(2026, 10, 25)), [date(2026, 10, 25)])
        self.assertEqual(resolve_relative_dates("한달뒤", NOW.date()), [date(2026, 11, 20)])
        self.assertEqual(resolve_relative_dates("두 주 뒤", NOW.date()), [date(2026, 11, 3)])
        self.assertEqual(resolve_relative_dates("일주일 후", NOW.date()), [date(2026, 10, 27)])
        self.assertEqual(resolve_relative_dates("한 달 뒤", date(2027, 1, 31)), [date(2027, 2, 28)])
        self.assertEqual(resolve_relative_dates("다음 달 초", NOW.date()), [date(2026, 11, 1)])
        self.assertEqual(resolve_relative_dates("3일뒤 2박 3일 제주도 여행 날씨", NOW.date()), [date(2026, 10, 23), date(2026, 10, 24), date(2026, 10, 25)])
        self.assertEqual(resolve_relative_dates("내일 1박2일 여행", date(2026, 12, 30)), [date(2026, 12, 31), date(2027, 1, 1)])

    @patch("weather_forecast.now_kst", return_value=NOW)
    @patch("chatbot.ChatOpenAI")
    @patch("weather_agent.search_places")
    @patch("weather_forecast.httpx.get")
    def test_missing_dates_and_out_of_range_never_call_any_api(self, get, search, client, now):
        self.assertIn("어느 날짜", answer_question("경주 날씨 알려줘"))
        for question in ("경주 어제 날씨", "경주 지난주 월요일 날씨", "경주 3일 전 날씨", "경주 16일 뒤 날씨", "한달뒤 경주 날씨 어때?", "경주 한 달 후 날씨", "경주 1개월 뒤 날씨", "경주 두달뒤 날씨", "경주 세 주 뒤 날씨", "경주 다음 달 날씨", "경주 내년 날씨", "경주 2026-10-01 날씨", "경주 2026년 12월 1일 날씨", "경주 10월 32일 날씨"):
            run = run_agent(question)
            self.assertIn("예보 없음", run["answer"])
            self.assertNotIn("out_of_range", run["answer"])
            self.assertEqual(run["call_count"], 0)
            self.assertEqual(run["events"][0]["status"], "out_of_range")
            self.assertIsNone(run["events"][0]["retrieved_at"])
        get.assert_not_called()
        search.assert_not_called()
        client.assert_not_called()

    @patch("weather_forecast.now_kst", return_value=NOW)
    @patch("weather_forecast.httpx.get")
    def test_forecast_uses_y_as_latitude_x_as_longitude_and_requested_dates(self, get, now):
        get.return_value = httpx.Response(200, request=httpx.Request("GET", ENDPOINT), json={"daily": {
            "time": ["2026-10-21"], "temperature_2m_max": [23.4], "temperature_2m_min": [12.1], "precipitation_probability_max": [30],
        }})
        result = fetch_forecast(PLACE, [date(2026, 10, 21)])
        params = get.call_args.kwargs["params"]
        self.assertEqual(params["latitude"], 35.856)
        self.assertEqual(params["longitude"], 129.224)
        self.assertEqual(params["timezone"], "Asia/Seoul")
        self.assertEqual(params["start_date"], "2026-10-21")
        self.assertEqual(result["source"], "Open-Meteo")
        self.assertTrue(result["retrieved_at"].endswith("+09:00"))
        rendered = render_forecast(result)
        self.assertIn("2026.10.21(수)", rendered)
        self.assertIn("23.4 · 12.1", rendered)
        self.assertIn("30", rendered)

    @patch("weather_forecast.now_kst", return_value=NOW)
    @patch("weather_forecast.httpx.get")
    def test_null_or_missing_forecast_is_not_filled_from_current_weather(self, get, now):
        for daily in ({"time": []}, {"time": ["2026-10-21"], "temperature_2m_max": [None], "temperature_2m_min": [None], "precipitation_probability_max": [None]}):
            get.return_value = httpx.Response(200, request=httpx.Request("GET", ENDPOINT), json={"daily": daily, "current": {"temperature_2m": 99}})
            result = fetch_forecast(PLACE, [date(2026, 10, 21)])
            self.assertEqual(result["status"], "out_of_range")
            self.assertIn("예보 없음", render_forecast(result))
            self.assertNotIn("99", render_forecast(result))
        self.assertEqual(get.call_count, 2)  # 응답 누락 뒤 추가 조회하지 않음

    @patch("weather_forecast.now_kst", return_value=NOW)
    @patch("weather_forecast.httpx.get")
    def test_partial_values_and_errors_do_not_invent_forecast(self, get, now):
        get.return_value = httpx.Response(200, request=httpx.Request("GET", ENDPOINT), json={"daily": {"time": ["2026-10-21"], "temperature_2m_max": [20], "temperature_2m_min": [None]}})
        result = fetch_forecast(PLACE, [date(2026, 10, 21), date(2026, 10, 22)])
        self.assertEqual(result["status"], "partial")
        self.assertIn("20 · 정보 없음", render_forecast(result))
        self.assertIn("예보 없음", render_forecast(result))
        self.assertNotIn("out_of_range", render_forecast(result))
        get.side_effect = httpx.TimeoutException("sensitive error")
        result = fetch_forecast(PLACE, [date(2026, 10, 21)])
        self.assertEqual(result["status"], "unavailable")
        self.assertNotIn("sensitive error", str(result))

    @patch("weather_forecast.now_kst", return_value=NOW)
    @patch("weather_forecast.httpx.get")
    def test_invalid_coordinates_and_past_dates_make_no_request(self, get, now):
        self.assertEqual(fetch_forecast({**PLACE, "x": "nan"}, [date(2026, 10, 21)])["status"], "invalid_coordinates")
        self.assertEqual(fetch_forecast(PLACE, [date(2026, 10, 19)])["status"], "out_of_range")
        get.assert_not_called()

    @patch("weather_forecast.now_kst", return_value=NOW)
    @patch("chatbot.load_settings", return_value=("openai-secret", "test-model"))
    @patch("chatbot.load_kakao_rest_api_key", return_value="kakao-secret")
    @patch("chatbot.ChatOpenAI")
    @patch("weather_agent.search_places")
    @patch("weather_forecast.httpx.get")
    def test_agent_chains_place_coordinates_to_forecast_and_provenance(self, get, search, client, key, settings, now):
        client.return_value.with_structured_output.return_value.invoke.return_value = {"region": "경주"}
        search.return_value = {"status": "ok", "places": [PLACE]}
        get.return_value = httpx.Response(200, request=httpx.Request("GET", ENDPOINT), json={"daily": {
            "time": ["2026-10-21"], "temperature_2m_max": [22], "temperature_2m_min": [11], "precipitation_probability_max": [0],
        }})
        run = run_agent("경주 내일 날씨 알려줘")
        self.assertEqual(run["call_count"], 2)
        self.assertEqual([entry["tool"] for entry in run["execution_log"]], ["search_kakao_places", "open_meteo_forecast"])
        self.assertEqual(run["execution_log"][-1]["source"], "Open-Meteo")
        self.assertIn("retrieved_at", run["execution_log"][-1])
        self.assertEqual(run["execution_log"][-1]["arguments"]["longitude"], float(PLACE["x"]))
        self.assertIn("22 · 11", run["answer"])
        self.assertNotIn("kakao-secret", str(run))
        self.assertNotIn("openai-secret", str(run))
        search.assert_called_once_with("경주", "kakao-secret", allow_fallback=False)

    @patch("weather_forecast.now_kst", return_value=NOW)
    def test_ui_out_of_range_does_not_call_title_summary_api(self, now):
        from pathlib import Path
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=20)
        with patch("chatbot.summarize_conversation") as summary:
            app.run()
            app.text_area[0].set_value("경주 어제 날씨 알려줘")
            next(button for button in app.button if button.label == "답변 받기").click().run()
        summary.assert_not_called()
        self.assertEqual(len(app.exception), 0)
        active = app.session_state.conversations[app.session_state.active_conversation]
        self.assertIn("예보 없음", active["messages"][-1]["content"])
        self.assertNotIn("out_of_range", active["messages"][-1]["content"])
