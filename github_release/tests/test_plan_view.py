import unittest

from plan_view import schedule_cards_html, weather_appearance, weather_illustration


class PlanCardTests(unittest.TestCase):
    def test_weather_codes_and_missing_information(self):
        for code, expected in ((0, "sunny"), (2, "partly-cloudy"), (3, "cloudy"), (45, "fog"), (61, "rain"), (71, "snow"), (95, "storm"), (None, "neutral"), (True, "neutral"), (999, "neutral")):
            with self.subTest(code=code):
                kind, _ = weather_appearance(code)
                self.assertEqual(kind, expected)
                self.assertIn('<svg', weather_illustration(kind))

    def test_cards_escape_content_and_use_only_matching_forecast(self):
        plan = {"version": 2, "basis": {"execution_log": [{"tool": "open_meteo_forecast", "result": {"status": "ok", "days": [
            {"date": "2026-10-24", "max_c": 19, "min_c": 14, "precipitation_probability": 63, "weather_code": 61}]} } ]}, "visits": [
                {"day": 1, "date": "2026-10-24", "slot": "오전 일정", "time": "10:00", "name": '<script>alert(1)</script>', "address": "경주 주소", "map_url": "javascript:alert(1)"},
                {"day": 2, "date": "2026-10-25", "slot": "오전 일정", "time": "10:00", "name": "박물관", "address": "경주 주소", "map_url": "https://place.map.kakao.com/123"},
            ]}
        html = schedule_cards_html(plan)
        self.assertIn('weather-rain', html)
        self.assertEqual(html.count('19°C'), 1)
        self.assertIn('해당 날짜에 조회된 예보가 없습니다.', html)
        self.assertNotIn('<script>', html)
        self.assertNotIn('javascript:', html)
        self.assertEqual(html.count('class="trip-place-card"'), 2)
