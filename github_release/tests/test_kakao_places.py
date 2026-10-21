import unittest
from unittest.mock import patch

import httpx

from kakao_places import ENDPOINT, search_places, render_search_sources


class KakaoPlacesTests(unittest.TestCase):
    def test_partial_success_names_only_the_unsuccessful_item(self):
        found = {"status": "ok", "item": "미술관", "message": "검색 결과", "places": [{
            "name": "우양미술관", "address": "경북 경주시", "map_url": "https://place.map.kakao.com/123",
        }]}
        empty = {"status": "no_results", "item": "전시관", "message": "검색 결과가 없습니다.", "places": []}
        for results in ([found, empty], [empty, found]):
            rendered = render_search_sources(results)
            self.assertIn("우양미술관", rendered)
            self.assertIn("**전시관** 항목은 이번 검색에서 찾지 못해", rendered)
            self.assertNotIn("검색 결과가 없습니다", rendered)
            self.assertTrue(rendered.endswith("추가적으로 필요한 정보가 있으면 말씀해 주세요."))
        empty["item"] = "미술관"
        self.assertNotIn("추가 안내:", render_search_sources([empty, found]))

    def test_successful_retry_does_not_show_earlier_no_results_notice(self):
        empty = {"status": "no_results", "message": "검색 결과가 없습니다. 지역이나 검색어를 구체적으로 알려 주세요.", "places": []}
        found = {"status": "ok", "message": "검색 결과", "places": [{
            "name": "우양미술관", "address": "경북 경주시 보문로", "category": "미술관", "map_url": "https://place.map.kakao.com/123",
        }]}
        for results in ([empty, found], [found, empty]):
            rendered = render_search_sources(results)
            self.assertIn("우양미술관", rendered)
            self.assertNotIn("검색 결과가 없습니다", rendered)
            self.assertNotIn("검색어를 구체적으로", rendered)
            self.assertTrue(rendered.endswith("추가적으로 필요한 정보가 있으면 말씀해 주세요."))
        self.assertIn("검색 결과가 없습니다", render_search_sources([empty]))
        self.assertNotIn("추가적으로 필요한 정보", render_search_sources([empty]))

    def test_each_item_is_limited_to_three_even_with_repeated_searches(self):
        def result(item, start, count):
            return {"status": "ok", "message": "검색 결과", "item": item, "places": [
                {"name": f"장소{i}", "address": "주소", "map_url": f"https://place.map.kakao.com/{i}"}
                for i in range(start, start + count)
            ]}
        rendered = render_search_sources([result("식당", 1, 5), result("식당", 6, 3), result("카페", 10, 5)])
        self.assertIn("### 식당", rendered)
        self.assertIn("### 카페", rendered)
        self.assertEqual(rendered.count("[지도 링크]"), 6)
        self.assertNotIn("**장소4**", rendered)
        self.assertNotIn("**장소6**", rendered)
        self.assertNotIn("4. **", rendered)

    def test_search_results_use_numbered_place_details(self):
        result = {"status": "ok", "message": "검색 결과", "places": [{
            "name": "국립경주박물관", "address": "경북 경주시 일정로 186",
            "category": "문화,예술 > 문화시설 > 박물관", "map_url": "https://place.map.kakao.com/123",
        }, {
            "name": "어린이박물관", "address": "경북 경주시 일정로 186",
            "category": "문화시설 > 박물관", "map_url": "https://place.map.kakao.com/456",
        }]}
        rendered = render_search_sources([result, result])
        self.assertIn("1. **국립경주박물관**", rendered)
        self.assertIn("2. **어린이박물관**", rendered)
        self.assertIn("   - 주소: 경북 경주시 일정로 186", rendered)
        self.assertIn("   - 분류:", rendered)
        self.assertIn("[지도 링크](https://place.map.kakao.com/123)", rendered)
        self.assertEqual(rendered.count("영업시간, 가격, 휴무"), 1)
        self.assertNotIn("3. **", rendered)
        self.assertNotIn("| ---", rendered)

    @patch("kakao_places.httpx.get")
    def test_restaurant_empty_result_retries_by_region_and_category(self, get):
        request = httpx.Request("GET", ENDPOINT)
        get.side_effect = [
            httpx.Response(200, request=request, json={"documents": []}),
            httpx.Response(200, request=request, json={"documents": [{"id": "123", "place_name": "식당", "address_name": "부산 해운대구"}]}),
        ]
        result = search_places("부산 해운대 근처 맛집 추천", "secret")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(get.call_count, 2)
        self.assertEqual(get.call_args.kwargs["params"]["query"], "부산 해운대")
        self.assertEqual(get.call_args.kwargs["params"]["category_group_code"], "FD6")

    @patch("kakao_places.httpx.get")
    def test_empty_query_and_missing_key_never_call_api(self, get):
        self.assertEqual(search_places("  ", "secret")["status"], "empty_query")
        self.assertEqual(search_places("제주", "")["status"], "missing_key")
        get.assert_not_called()

    @patch("kakao_places.httpx.get")
    def test_search_normalizes_places_and_uses_auth_header(self, get):
        get.return_value = httpx.Response(200, request=httpx.Request("GET", ENDPOINT), json={"documents": [{
            "id": "123", "place_name": "관광지", "road_address_name": "제주시 도로명", "address_name": "지번",
            "place_url": "https://untrusted.example", "category_name": "여행", "phone": "", "x": "129.224", "y": "35.856",
        }]})
        result = search_places("제주 관광지", "secret")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["places"][0]["map_url"], "https://place.map.kakao.com/123")
        self.assertEqual(result["places"][0]["address"], "제주시 도로명")
        self.assertEqual(result["places"][0]["x"], "129.224")
        self.assertEqual(result["places"][0]["y"], "35.856")
        self.assertEqual(get.call_args.kwargs["headers"], {"Authorization": "KakaoAK secret"})
        self.assertFalse(get.call_args.kwargs["follow_redirects"])

    @patch("kakao_places.httpx.get")
    def test_errors_and_empty_results_are_safe(self, get):
        for code, expected in [(401, "auth_error"), (403, "auth_error"), (429, "quota_error"), (500, "unavailable")]:
            get.return_value = httpx.Response(code, request=httpx.Request("GET", ENDPOINT), text="secret")
            result = search_places("제주", "secret")
            self.assertEqual(result["status"], expected)
            self.assertNotIn("secret", str(result))
        get.side_effect = httpx.TimeoutException("secret")
        self.assertEqual(search_places("제주", "secret")["status"], "unavailable")
        get.side_effect = None
        get.return_value = httpx.Response(200, request=httpx.Request("GET", ENDPOINT), json={"documents": []})
        self.assertEqual(search_places("제주", "secret")["status"], "no_results")
