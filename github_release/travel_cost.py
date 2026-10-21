"""실제 요금 조회와 구분하는, 장소 유형별 1인 예산 제안입니다."""
import re

# 서비스 요금표나 시장 평균이 아닌, 앱에서 정한 예산 계획용 범위입니다.
BUDGETS = {
    "식사": (10000, 25000),
    "카페": (5000, 10000),
    "문화시설": (0, 20000),
    "야외 산책": (0, 10000),
    "체험시설": (15000, 50000),
}


def estimated_cost(place):
    category = place.get("category", "")
    code = place.get("category_group_code", "")
    kind = None
    if re.search(r"주차장|숙박|호텔|리조트|기념품", category):
        return "확인 필요 (예산 추정 제외)"
    if code == "CE7" or re.search(r"카페|커피|찻집", category):
        kind = "카페"
    elif code == "FD6" or re.search(r"음식점|식당|한식|양식|중식|일식|분식|뷔페", category):
        kind = "식사"
    elif re.search(r"박물관|미술관|전시관|기념관|문화시설", category):
        kind = "문화시설"
    elif re.search(r"공원|해수욕장|둘레길|올레길|산책", category):
        kind = "야외 산책"
    elif re.search(r"수족관|아쿠아리움|테마파크|놀이공원|체험", category):
        kind = "체험시설"
    if kind is None:
        return "확인 필요 (분류 정보 부족)"
    low, high = BUDGETS[kind]
    return f"약 {low:,}~{high:,}원 / 1인 · {kind} 예산 제안"


COST_NOTICE = "장소 유형별 예상 비용은 앱의 예산 제안이며 실제 요금을 조회한 값이 아닙니다. 입장권·전시·메뉴 선택에 따라 달라질 수 있고, 교통·주차·숙박·쇼핑 비용은 제외합니다."
