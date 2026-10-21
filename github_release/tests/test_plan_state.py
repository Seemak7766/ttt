import copy
import unittest
from unittest.mock import Mock, patch

from plan_actions import handle_plan_question
from plan_state import PlanChangeError, parse_change, update_current
from travel_plan import recommend_travel_plan


def plan():
    places = [{"name": f"박물관{i}", "address": f"경주 주소{i}", "map_url": f"https://place.map.kakao.com/{i}", "category": "문화 > 박물관"} for i in range(1, 4)]
    return recommend_travel_plan({"request_context": {"region": "경주", "dates": ["2026-10-23"]}, "execution_log": [{"tool": "search_kakao_places", "status": "ok", "result": {"places": places}}]})


class CurrentPlanTests(unittest.TestCase):
    def test_tomorrow_afternoon_plan_request_includes_weather(self):
        active = {"messages": []}
        runner = Mock(return_value={"execution_log": [], "answer": "조회 결과"})
        with patch("plan_actions.build_travel_plan", return_value=None) as build:
            handle_plan_question("서울에서 내일 오후에 갈 만한 실내 장소를 포함해서 반나절 여행을 계획해줘.", active, runner)
        self.assertIn("날씨와 장소 추천", runner.call_args.args[0])
        build.assert_called_once()
        self.assertEqual(parse_change("내일 오후 반나절 여행을 계획해줘"), {"start_time": "13:00", "end_time": "18:00"})

    def test_korean_count_and_time(self):
        self.assertEqual(parse_change("방문은 두 곳만, 오후 1시부터 5시까지로 바꿔 줘."), {"visit_count": 2, "start_time": "13:00", "end_time": "17:00"})
        self.assertEqual(parse_change("오후 세 시부터 여섯 시까지"), {"start_time": "15:00", "end_time": "18:00"})

    def test_atomic_update_and_grounding(self):
        original = plan()
        before = copy.deepcopy(original)
        changed = update_current(original, visit_count=2, start_time="13:00", end_time="17:00")
        self.assertEqual(original, before)
        self.assertEqual(len(changed["visits"]), 2)
        self.assertEqual(changed["visits"][0]["time"], "13:00")
        self.assertEqual(changed["version"], 2)
        self.assertIn("경주 주소1", changed["content"])
        for bad in ({"start_time": "25:00"}, {"start_time": "17:00", "end_time": "13:00"}, {"visit_count": 10}, {"exclude_places": ["박물관"]}):
            with self.assertRaises(PlanChangeError):
                update_current(original, **bad)
            self.assertEqual(original, before)

    def test_exclude_restore_and_ambiguous_name(self):
        original = plan()
        excluded = update_current(original, exclude_places=["박물관1"])
        self.assertNotIn("박물관1", [v["name"] for v in excluded["visits"]])
        restored = update_current(excluded, restore_places=["박물관1"])
        self.assertIn("박물관1", [v["name"] for v in restored["visits"]])
        self.assertEqual(parse_change("박물관1을 빼줘"), {"exclude_places": ["박물관1"]})

    def test_local_change_does_not_call_runner_or_search(self):
        active = {"current_plan": plan(), "messages": []}
        runner = Mock()
        with patch("plan_actions.build_travel_plan") as build:
            run, _ = handle_plan_question("방문은 두 곳만 오후 1시부터 5시까지로 바꿔 줘", active, runner)
        runner.assert_not_called()
        build.assert_not_called()
        self.assertEqual(run["execution_log"][0]["tool"], "update_plan")
        self.assertEqual(len(active["current_plan"]["visits"]), 2)

    def test_missing_date_no_model_call_or_fabricated_plan(self):
        active = {"messages": []}
        runner = Mock()
        run, result = handle_plan_question("여행 계획을 만들어 줘", active, runner)
        runner.assert_not_called()
        self.assertIsNone(result)
        self.assertIn("날짜와 지역", run["answer"])

    def test_date_change_refreshes_and_keeps_existing_context(self):
        current = plan()
        runner = Mock(return_value={"execution_log": [], "answer": "조회 실패"})
        with patch("plan_actions.build_travel_plan", return_value=None):
            handle_plan_question("모레로 바꿔줘", {"current_plan": current, "messages": []}, runner)
        self.assertIn("날씨와 장소", runner.call_args.args[0])
        self.assertEqual(runner.call_args.args[1][-1]["runs"][0]["request_context"]["region"], "경주")


if __name__ == "__main__":
    unittest.main()
