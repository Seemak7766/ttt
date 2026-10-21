import unittest
from travel_cost import estimated_cost


class CostTests(unittest.TestCase):
    def test_category_budgets_are_labeled_as_proposals(self):
        for place, amount in (({"category_group_code": "FD6"}, "10,000~25,000"), ({"category_group_code": "CE7"}, "5,000~10,000"), ({"category": "문화시설 > 박물관"}, "0~20,000")):
            result = estimated_cost(place)
            self.assertIn(amount, result)
            self.assertIn("1인", result)
            self.assertIn("예산 제안", result)

    def test_unknown_or_excluded_places_do_not_invent_prices(self):
        for place in ({"name": "박물관", "price": 3000}, {"category": "교통 > 주차장"}, {"category": "숙박 > 호텔"}):
            self.assertIn("확인 필요", estimated_cost(place))
