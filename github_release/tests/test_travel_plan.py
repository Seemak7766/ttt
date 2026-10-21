import unittest
from unittest.mock import patch

from travel_plan import build_travel_plan, collect_plan_evidence, recommend_travel_plan


def sample_run(weather=True):
    places = [{"name": f"조회 장소 {index}", "address": f"경주시 주소 {index}", "map_url": f"https://place.map.kakao.com/{index}", "opening_hours": "09:00~18:00", "travel_minutes": 17} for index in range(1, 4)]
    log = [{"tool": "search_kakao_places", "status": "ok", "branch": "recommendations", "arguments": {"query": "경주 관광지"}, "result": {"places": places}, "call_index": 1}]
    if weather:
        log.append({"tool": "open_meteo_forecast", "status": "ok", "call_index": 2, "result": {
            "status": "ok", "place": places[0], "source": "Open-Meteo", "retrieved_at": "2026-10-20T15:00:00+09:00",
            "days": [{"date": "2026-10-23", "max_c": 26, "min_c": 10, "precipitation_probability": 60}],
        }})
    return {"status": "completed", "answer": "조회 결과", "mode": "retry", "limit": 3,
            "call_count": len(log), "events": [], "execution_log": log, "sections": {"places": "조회 결과"}}


class TravelPlanTests(unittest.TestCase):
    @patch("travel_plan.load_kakao_rest_api_key", return_value="")
    @patch("travel_plan.fetch_forecast")
    def test_button_plan_enriches_weather_using_existing_place_coordinates(self, forecast, key):
        from datetime import timedelta
        from weather_forecast import now_kst
        from plan_view import schedule_cards_html
        day = (now_kst().date()+timedelta(days=1)).isoformat()
        run = sample_run(False)
        run["request_context"] = {"dates": [day], "region": "화성 동탄"}
        run["execution_log"][0]["result"]["places"][0].update(x="127.1", y="37.2")
        forecast.return_value = {"status": "ok", "days": [{"date": day, "max_c": 20, "min_c": 10, "precipitation_probability": 30, "weather_code": 2}]}
        plan = build_travel_plan(run)
        forecast.assert_called_once()
        self.assertEqual(plan["basis"]["execution_log"][-1]["tool"], "open_meteo_forecast")
        self.assertIn("trip-weather-metrics", schedule_cards_html(plan))
        self.assertEqual(len(run["execution_log"]), 1)

    @patch("travel_plan.load_kakao_rest_api_key", return_value="")
    @patch("travel_plan.fetch_forecast")
    def test_plan_does_not_query_weather_outside_forecast_range(self, forecast, key):
        run = sample_run(False)
        run["request_context"] = {"dates": ["2099-01-01"]}
        plan = build_travel_plan(run)
        forecast.assert_not_called()
        self.assertEqual(plan["basis"]["plan_weather_state"]["status"], "out_of_range")

    @patch("travel_plan.load_kakao_rest_api_key", return_value="test-secret")
    @patch("travel_plan.search_places")
    def test_auto_search_fills_every_three_day_slot_without_duplicate_places(self, search, key):
        run = sample_run()
        run["request_context"] = {"region": "경주", "trip_days": 3, "dates": ["2026-10-23", "2026-10-24", "2026-10-25"]}
        def reply(query, api_key, *, page, category_group_code, **kwargs):
            restaurant = category_group_code == "FD6"
            start = 100 + (page-1)*3 if restaurant else 4
            return {"status": "ok", "message": "검색 결과", "places": [{
                "name": f"{'식당' if restaurant else '방문지'}{index}", "address": f"경주시 주소{index}",
                "category": "음식점 > 한식" if restaurant else "여행 > 관광지", "category_group_code": category_group_code,
                "map_url": f"https://place.map.kakao.com/{index}",
            } for index in range(start, start+3)]}
        search.side_effect = reply
        plan = build_travel_plan(run)
        self.assertEqual(plan["additional_search_count"], 3)
        self.assertEqual(plan["search_stop_reason"], "sufficient_candidates")
        self.assertNotIn("비워 두었습니다", plan["content"])
        self.assertNotIn("추가 장소 검색이 필요", plan["content"])
        self.assertEqual(plan["content"].count("[지도 링크]"), 12)
        for day in range(1, 4):
            section = plan["content"].split(f"#### {day}일차")[1].split("#### ")[0]
            self.assertEqual(section.count("[지도 링크]"), 4)
            self.assertIn("식당", section)
        self.assertEqual(len({entry.args[0] for entry in search.call_args_list}), 1)
        self.assertEqual(search.call_args_list[-1].kwargs["page"], 2)
        self.assertNotIn("plan_places", run)  # 기존 답변 근거를 바꾸지 않음
        self.assertNotIn("test-secret", str(plan))

    @patch("travel_plan.load_kakao_rest_api_key", return_value="test-secret")
    @patch("travel_plan.search_places")
    def test_search_failure_is_bounded_and_does_not_fabricate_places(self, search, key):
        search.return_value = {"status": "no_results", "message": "검색 결과가 없습니다.", "places": []}
        plan = build_travel_plan(sample_run(False))
        self.assertLessEqual(search.call_count, plan["search_limit"])
        self.assertIn("추가 검색에서도", plan["content"])
        self.assertEqual(plan["content"].count("[지도 링크]"), 3)

    def test_three_day_trip_has_three_days_with_addresses_and_links(self):
        run = sample_run()
        run["request_context"] = {"trip_days": 3, "dates": ["2026-10-23", "2026-10-24", "2026-10-25"]}
        content = recommend_travel_plan(run)["content"]
        for day, date_text in ((1, "2026.10.23"), (2, "2026.10.24"), (3, "2026.10.25")):
            self.assertIn(f"#### {day}일차 · {date_text}", content)
            section = content.split(f"#### {day}일차")[1].split("#### ")[0]
            self.assertIn(f"조회 장소 {day}", section)
            self.assertIn("**주소:**", section)
            self.assertIn("[지도 링크]", section)
        self.assertEqual(content.count("1. **오전 일정**"), 3)
        for slot in ("점심", "오후 일정", "저녁"):
            self.assertEqual(content.count(f"**{slot}**"), 3)

    def test_extra_days_are_not_filled_with_unqueried_or_repeated_places(self):
        run = sample_run(False)
        run["request_context"] = {"trip_days": 4}
        content = recommend_travel_plan(run)["content"]
        self.assertIn("#### 4일차", content)
        self.assertIn("추가 장소 검색이 필요", content)
        self.assertEqual(content.count("[지도 링크]"), 3)

    def test_facts_and_suggestions_are_separate_and_only_use_queried_places(self):
        plan = recommend_travel_plan(sample_run())
        suggestions = plan["content"]
        self.assertNotIn("### 조회 사실", suggestions)
        self.assertIn("**주소:** 경주시 주소 1", suggestions)
        self.assertIn("[지도 링크](https://place.map.kakao.com/1)", suggestions)
        self.assertNotIn("26 · 10", suggestions)
        self.assertNotIn("| ---", suggestions)
        self.assertIn("방문 순서", suggestions)
        self.assertIn("1. **오전 일정**", suggestions)
        self.assertIn("**조회 장소 1**", suggestions)
        self.assertIn("**제안:** 오전 10시 방문", suggestions)
        self.assertIn("**제안:** 오전 11시 방문", suggestions)
        self.assertIn("준비물 / 제안", suggestions)
        self.assertIn("우산", suggestions)
        self.assertIn("겉옷", suggestions)
        self.assertIn("모자", suggestions)
        self.assertNotIn("09:00~18:00", plan["content"])
        self.assertNotIn("17분", plan["content"])
        self.assertEqual(plan["source_calls"], [1, 2])

    def test_queried_restaurants_are_assigned_to_meals_only(self):
        run = sample_run(False)
        places = run["execution_log"][0]["result"]["places"]
        places[0]["category"] = "문화시설 > 박물관"
        places[1]["category"] = "음식점 > 한식"
        places[2]["category"] = "음식점 > 일식"
        content = recommend_travel_plan(run)["content"]
        lunch = content.split("2. **점심**")[1].split("3. **오후 일정**")[0]
        dinner = content.split("4. **저녁**")[1].split("### 준비물")[0]
        self.assertIn("**조회 장소 2**", lunch)
        self.assertIn("**조회 장소 3**", dinner)
        self.assertNotIn("**조회 장소 1**", lunch + dinner)

    def test_only_latest_recommendation_places_are_used(self):
        run = sample_run(False)
        run["execution_log"].insert(0, {"tool": "search_kakao_places", "status": "ok", "result": {"places": [{"name": "오래된 장소", "map_url": "https://place.map.kakao.com/9"}]}})
        self.assertNotIn("오래된 장소", recommend_travel_plan(run)["content"])

    def test_weather_coordinate_place_is_not_treated_as_a_recommendation(self):
        run = sample_run(False)
        run["execution_log"][0]["arguments"]["purpose"] = "weather_coordinates"
        self.assertEqual(collect_plan_evidence(run)["places"], [])
        self.assertIsNone(recommend_travel_plan(run))

    def test_missing_weather_does_not_invent_rain_or_temperatures(self):
        content = recommend_travel_plan(sample_run(False))["content"]
        self.assertIn("물과 편한 신발", content)
        self.assertNotIn("우산", content)
        self.assertNotIn("겉옷", content)
        self.assertNotIn("최고 · 최저", content)

    def test_hot_weather_adds_short_heat_safety_comment(self):
        run = sample_run()
        day = run["execution_log"][-1]["result"]["days"][0]
        day.update(max_c=33, min_c=25, precipitation_probability=0)
        content = recommend_travel_plan(run)["content"]
        self.assertIn("온열질환", content)
        self.assertIn("그늘에서 자주 쉬어", content)
        self.assertNotIn("우산", content)
        self.assertNotIn("33", content)

    def test_button_generates_and_preserves_plan_without_api_calls(self):
        from pathlib import Path
        from streamlit.testing.v1 import AppTest
        run = sample_run()
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=20)
        with patch("chatbot.run_agent", return_value=run) as agent, patch("chatbot.summarize_conversation", return_value="경주 여행") as summary, patch("travel_plan.load_kakao_rest_api_key", return_value=""):
            app.run()
            app.text_area[0].set_value("경주 날씨와 장소 추천")
            next(button for button in app.button if button.label == "답변 받기").click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(agent.call_count, 1)
            self.assertEqual(summary.call_count, 1)
            next(button for button in app.button if button.label == "검색 정보로 여행 계획 추천").click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(agent.call_count, 1)
            self.assertEqual(summary.call_count, 1)
            active = app.session_state.conversations[app.session_state.active_conversation]
            self.assertIn("### 방문 순서", active["messages"][-1]["travel_plan"]["content"])
            app.run()
            self.assertTrue(any("### 방문 순서" in item.value for item in app.markdown))
            self.assertTrue(any('class="trip-place-card"' in item.value and '제안 시각' in item.value for item in app.markdown))
            self.assertEqual([tab.label for tab in app.tabs], ["준비물·제안", "추천 장소 지도", "계획 조건 수정", "조회 근거", "실행 기록"])
            details = next(item for item in app.expander if item.label == "여행 계획 상세 보기")
            self.assertFalse(details.proto.expanded)
            self.assertEqual(agent.call_count, 1)
