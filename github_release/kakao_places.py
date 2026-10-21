"""카카오 로컬 장소 검색. 키와 원본 API 오류는 외부로 반환하지 않습니다."""

import re

import httpx
from observability import observed

ENDPOINT = "https://dapi.kakao.com/v2/local/search/keyword.json"
MAX_PLACES_PER_ITEM = 3


@observed("search_kakao_places", run_type="tool")
def search_places(query: str, api_key: str, *, allow_fallback: bool = True, page: int = 1, category_group_code: str = "") -> dict:
    query = query.strip()
    if not query:
        return {"status": "empty_query", "message": "검색할 지역과 장소를 알려 주세요.", "places": []}
    if not api_key:
        return {"status": "missing_key", "message": "카카오 장소 검색 키가 설정되지 않았습니다.", "places": []}
    try:
        params = {"query": query[:100], "size": MAX_PLACES_PER_ITEM, "page": max(1, min(45, page))}
        if category_group_code in {"FD6", "AT4", "CT1"}:
            params["category_group_code"] = category_group_code
        response = httpx.get(
            ENDPOINT,
            headers={"Authorization": f"KakaoAK {api_key}"},
            params=params,
            timeout=10,
            follow_redirects=False,
        )
        if response.status_code in (401, 403):
            return {"status": "auth_error", "message": "카카오 장소 검색 인증 또는 권한을 확인해 주세요.", "places": []}
        if response.status_code == 429:
            return {"status": "quota_error", "message": "카카오 장소 검색 사용 한도에 도달했습니다.", "places": []}
        response.raise_for_status()
        data = response.json()
        # '해운대 맛집' 같은 포괄적 표현은 상호명과 매칭되지 않을 수 있습니다.
        # 빈 결과일 때 지역명과 음식점 분류로 한 번만 넓혀 검색합니다.
        if allow_fallback and not data.get("documents") and re.search(r"맛집|식당|음식점", query):
            region_query = re.sub(r"맛집|식당|음식점|추천|근처|주변|찾아줘|알려줘|검색", " ", query)
            region_query = " ".join(region_query.split())
            if region_query:
                response = httpx.get(
                    ENDPOINT,
                    headers={"Authorization": f"KakaoAK {api_key}"},
                    params={"query": region_query[:100], "category_group_code": "FD6", "size": MAX_PLACES_PER_ITEM},
                    timeout=10,
                    follow_redirects=False,
                )
                if response.status_code in (401, 403):
                    return {"status": "auth_error", "message": "카카오 장소 검색 인증 또는 권한을 확인해 주세요.", "places": []}
                if response.status_code == 429:
                    return {"status": "quota_error", "message": "카카오 장소 검색 사용 한도에 도달했습니다.", "places": []}
                response.raise_for_status()
                data = response.json()
        places = []
        for item in data.get("documents", [])[:MAX_PLACES_PER_ITEM]:
            # URL을 그대로 믿지 않고 공식 장소 ID로만 지도 링크를 만듭니다.
            place_id = str(item.get("id", ""))
            if not re.fullmatch(r"[0-9]+", place_id):
                continue
            place = {
                "name": str(item.get("place_name", "")),
                "address": str(item.get("road_address_name") or item.get("address_name", "")),
                "category": str(item.get("category_name", "")),
                "category_group_code": str(item.get("category_group_code", "")),
                "phone": str(item.get("phone", "")),
                "map_url": f"https://place.map.kakao.com/{place_id}",
                "x": str(item.get("x", "")),
                "y": str(item.get("y", "")),
            }
            places.append({key: value.replace(api_key, "[비공개]") for key, value in place.items()})
        return {
            "status": "ok" if places else "no_results",
            "message": "카카오맵 장소 검색 결과입니다." if places else "검색 결과가 없습니다. 지역이나 검색어를 구체적으로 알려 주세요.",
            "places": places,
        }
    except Exception:
        return {"status": "unavailable", "message": "카카오 장소 검색에 실패했습니다. 잠시 후 다시 시도해 주세요.", "places": []}


def render_search_sources(results: list[dict]) -> str:
    """모델이 링크를 생략해도 실제 조회한 출처를 제공합니다."""
    from travel_cost import estimated_cost, COST_NOTICE
    def text(value):
        value = value.replace("\n", " ").replace("\r", " ").replace("<", "&lt;").replace(">", "&gt;")
        return re.sub(r"([\\`*_\[\]])", r"\\\1", value)

    groups = {}
    seen_urls = set()
    for result in results:
        group = groups.setdefault(result.get("item") or "추천 장소", [])
        for place in result.get("places", []):
            if place["map_url"] not in seen_urls and len(group) < MAX_PLACES_PER_ITEM:
                group.append(place)
                seen_urls.add(place["map_url"])
    groups = {name: places for name, places in groups.items() if places}
    successful_items = {result.get("item") or "추천 장소" for result in results if result.get("places")}
    notices = []
    for result in results:
        if result["status"] == "ok":
            continue
        item = result.get("item") or "추천 장소"
        if result["status"] == "no_results" and groups:
            if item in successful_items:
                # 동일 항목은 재검색 성공으로 해결된 상태입니다.
                continue
            notice = f"추가 안내: **{text(item)}** 항목은 이번 검색에서 찾지 못해, 검색된 장소를 먼저 안내드립니다."
        else:
            notice = result["message"]
        if notice not in notices:
            notices.append(notice)
    sections = []
    if groups:
        for name, places in groups.items():
            if len(groups) > 1:
                sections.append(f"### {text(name)}")
            for number, place in enumerate(places, start=1):
                sections.append(
                    f'{number}. **{text(place["name"])}**\n\n'
                    f'   - 주소: {text(place.get("address") or "정보 없음")}\n'
                    f'   - 분류: {text(place.get("category") or "정보 없음")}\n'
                    f'   - 예상 비용(추정): {estimated_cost(place)}\n'
                    f'   - [지도 링크]({place["map_url"]})'
                )
        sections.append("영업시간, 가격, 휴무는 방문 전 확인이 필요합니다. 관심 있는 장소의 상세 정보를 확인해 주세요.")
        sections.append(COST_NOTICE)
    sections.extend(notices)
    if groups:
        sections.append("추가적으로 필요한 정보가 있으면 말씀해 주세요.")
    return "\n\n".join(sections)
