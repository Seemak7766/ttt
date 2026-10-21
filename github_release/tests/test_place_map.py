import unittest
import folium
from place_map import build_place_map, plan_map_places


class PlaceMapTests(unittest.TestCase):
    def test_coordinates_center_and_fit_bounds(self):
        places = [{"name": "장소A", "x": "127.0", "y": "37.0", "map_url": "https://place.map.kakao.com/1"},
                  {"name": "장소B", "x": "129.0", "y": "35.0"}]
        result, info = build_place_map(places)
        self.assertEqual(info["center"], [36, 128])
        self.assertEqual(info["bounds"], [[35, 127], [37, 129]])
        self.assertEqual(info["marker_count"], 2)
        self.assertTrue(any(isinstance(x, folium.map.FitBounds) for x in result._children.values()))
        html = result.get_root().render()
        self.assertIn("카카오맵 상세 보기", html)
        self.assertIn("장소A", html)

    def test_bad_coordinates_are_skipped_and_no_fallback_location(self):
        result, info = build_place_map([{"x": "nan", "y": "37"}, {"x": "127", "y": "91"}, {}])
        self.assertIsNone(result)
        self.assertEqual(info["missing_count"], 3)

    def test_single_place_and_html_escape(self):
        result, info = build_place_map([{"x": "127", "y": "37", "name": "<script>bad()</script>", "map_url": "javascript:bad()"}])
        self.assertEqual(result.location, [37, 127])
        self.assertFalse(any(isinstance(x, folium.map.FitBounds) for x in result._children.values()))
        html = result.get_root().render()
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("javascript:bad", html)

    def test_map_uses_only_current_visits_after_exclusion(self):
        plan = {"candidates": [{"name": "A", "map_url": "a", "x": "127", "y": "37"}, {"name": "B", "map_url": "b", "x": "129", "y": "35"}],
                "visits": [{"name": "A", "map_url": "a", "time": "13:00"}]}
        places = plan_map_places(plan)
        self.assertEqual(len(places), 1)
        self.assertEqual(places[0]["x"], "127")
        self.assertEqual(places[0]["time"], "13:00")
