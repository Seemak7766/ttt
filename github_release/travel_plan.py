"""조회 근거만 사용하는 계획 렌더링과 부족한 후보의 추가 검색."""

from datetime import date, datetime, timedelta
from html import escape
import re
from copy import deepcopy
from config import load_kakao_rest_api_key
from kakao_places import ENDPOINT, search_places

from weather_forecast import KST
from travel_cost import estimated_cost
from observability import observed
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from weather_forecast import weather_preflight, fetch_forecast, valid_coordinates

PLAN_FORMAT_VERSION = 7


def is_restaurant(place):
    return place.get("category_group_code") == "FD6" or bool(re.search(r"음식점|식당|한식|양식|중식|일식|분식|뷔페", place.get("category", "")))


def collect_plan_evidence(run):
    records = run.get("execution_log", [])
    places, weather, calls = [], None, []
    for index, entry in enumerate(records, start=1):
        result = entry.get("result", {})
        if entry.get("tool") == "search_kakao_places" and entry.get("arguments", {}).get("purpose") != "weather_coordinates":
            # 앞선 후보를 섞지 않고 이 기능의 마지막 반환 결과만 사용합니다.
            places = result.get("places", []) if entry.get("status") == "ok" else []
            calls = [entry.get("call_index", index)] if places else []
        elif entry.get("tool") == "open_meteo_forecast":
            weather = result if result.get("status") in {"ok", "partial"} else None
    weather_entry = next(((index, entry) for index, entry in reversed(list(enumerate(records, start=1))) if entry.get("tool") == "open_meteo_forecast"), None)
    if weather and weather_entry:
        calls.append(weather_entry[1].get("call_index", weather_entry[0]))
    unique = {place["map_url"]: place for place in places if place.get("name") and place.get("map_url")}
    if "plan_places" in run:
        unique = {place["map_url"]: place for place in run["plan_places"] if place.get("name") and place.get("map_url")}
        calls += [entry["call_id"] for entry in run.get("plan_search_log", []) if entry.get("status") == "ok"]
        return {"places": list(unique.values()), "weather": weather, "source_calls": calls}
    return {"places": list(unique.values())[:3], "weather": weather, "source_calls": calls}


def text(value):
    value = escape(str(value), quote=False).replace("\n", " ").replace("\r", " ")
    return re.sub(r"([\\`*_\[\]|])", r"\\\1", value)


def recommend_travel_plan(run):
    evidence = collect_plan_evidence(run)
    places, weather = evidence["places"], evidence["weather"]
    if not places:
        return None
    lines = ["### 방문 순서", "", "아래 방문 시각은 일정 배치를 위한 제안입니다.", ""]
    context = run.get("request_context", {})
    dates = context.get("dates") or [day["date"] for day in (weather or {}).get("days", [])]
    duration = min(31, max(1, context.get("trip_days") or len(dates) or 1))
    first_date = date.fromisoformat(dates[0]) if dates else None
    restaurants = [place for place in places if is_restaurant(place)]
    activities = [place for place in places if not is_restaurant(place)]
    visits = []
    for day_index in range(duration):
        if duration > 1:
            day_label = f" · {first_date + timedelta(days=day_index):%Y.%m.%d}" if first_date else ""
            lines.extend([f"#### {day_index+1}일차{day_label}", ""])
        # 한 번 조회한 후보를 여러 날에 중복 배정하거나 새 장소를 만들지 않습니다.
        def portion(pool):
            start = (len(pool) * day_index + duration - 1) // duration
            end = (len(pool) * (day_index+1) + duration - 1) // duration
            return pool[start:end]
        day_restaurants, day_activities = portion(restaurants), portion(activities)
        morning_count = (len(day_activities)+1) // 2
        slots = [
            ("오전 일정", day_activities[:morning_count], ["오전 10시", "오전 11시"]),
            ("점심", day_restaurants[:1], ["오후 12시"]),
            ("오후 일정", day_activities[morning_count:], ["오후 2시", "오후 3시"]),
            ("저녁", day_restaurants[1:], ["오후 6시", "오후 7시"]),
        ]
        for slot_index, (label, candidates, times) in enumerate(slots, start=1):
            lines.extend([f"{slot_index}. **{label}**", ""])
            if not candidates:
                missing = "식당" if label in {"점심", "저녁"} else "방문지"
                message = f"   추가 검색에서도 적합한 {missing}을 확보하지 못해 이 구간은 비워 두었습니다." if run.get("plan_search_attempted") else f"   조회된 {missing}이 없어 추가 장소 검색이 필요합니다."
                lines.extend([message, ""])
            for index, place in enumerate(candidates):
                visits.append({"day": day_index+1, "date": (first_date + timedelta(days=day_index)).isoformat() if first_date else "",
                               "slot": label, "time": ["10:00", "11:00"][index] if label == "오전 일정" else (["14:00", "15:00"][index] if label == "오후 일정" else (["12:00"][index] if label == "점심" else ["18:00", "19:00"][index])),
                               "name": place["name"], "address": place.get("address", ""), "map_url": place["map_url"], "edited": False})
                lines.extend([
                    f'   **{text(place["name"])}**', "",
                    f'   - **주소:** {text(place.get("address") or "정보 없음")}',
                    f'   - [지도 링크]({place["map_url"]})',
                    f'   - **제안:** {times[index]} 방문', "",
                    f'   - **예상 비용(추정):** {estimated_cost(place)}', "",
                ])
    if duration > 1:
        lines.extend([f"조회로 확인한 {len(places)}곳을 {duration}일에 나눈 일정 초안입니다.", ""])
    lines.extend(["", "### 준비물 / 제안", "", "- 물과 편한 신발을 준비해 주세요."])
    days = weather.get("days", []) if weather else []
    rain = [day["precipitation_probability"] for day in days if isinstance(day.get("precipitation_probability"), (int, float))]
    lows = [day["min_c"] for day in days if isinstance(day.get("min_c"), (int, float))]
    highs = [day["max_c"] for day in days if isinstance(day.get("max_c"), (int, float))]
    if rain and max(rain) >= 40:
        lines.append("- 비가 올 가능성이 있으니 접이식 우산이나 우비를 챙겨 주세요.")
    if lows and min(lows) <= 15:
        lines.append("- 서늘한 시간대에 대비해 가벼운 겉옷을 챙겨 주세요.")
    if highs and max(highs) >= 30:
        lines.append("- 더위로 인한 온열질환에 주의하고, 물과 모자를 챙겨 그늘에서 자주 쉬어 주세요.")
    elif highs and max(highs) >= 25:
        lines.append("- 더운 시간대에 대비해 모자와 여분의 물을 챙겨 주세요.")
    lines.extend(["", "위 순서·시간대·준비물은 제안이며 방문 가능 여부를 보장하지 않습니다. 영업시간과 이동시간은 조회되지 않아 계획에서 제외했습니다."])
    return {"content": "\n".join(lines), "source_calls": evidence["source_calls"], "created_at": datetime.now(KST).isoformat(timespec="seconds"), "format_version": PLAN_FORMAT_VERSION, "version": 1, "visits": visits, "original_visits": deepcopy(visits), "basis": deepcopy(run), "candidates": deepcopy(places), "constraints": {"exclude": []}}


def _build_place_plan(run):
    """기존 근거를 보존하면서 하루 방문지 2곳·식당 2곳까지 자동 보충합니다."""
    working = deepcopy(run)
    evidence = collect_plan_evidence(working)
    if not evidence["places"]:
        return None
    context = working.get("request_context", {})
    context = deepcopy(context)
    working["request_context"] = context
    duration = min(31, max(1, context.get("trip_days") or len(context.get("dates", [])) or len((evidence["weather"] or {}).get("days", [])) or 1))
    candidates = {place["map_url"]: place for place in evidence["places"]}
    logs = []
    api_key = load_kakao_rest_api_key()
    region = context.get("region", "")
    if not region:
        queries = [entry.get("arguments", {}) for entry in run.get("execution_log", []) if entry.get("tool") == "search_kakao_places"]
        arguments = queries[-1] if queries else {}
        region = arguments.get("region") or re.sub(r"관광지|맛집|식당|음식점|카페|추천|검색|박물관|미술관", " ", arguments.get("query", "")).strip()
    if not region:
        region = " ".join(evidence["places"][0].get("address", "").split()[:2])
    context["region"] = region
    args = [entry.get("arguments", {}) for entry in run.get("execution_log", []) if entry.get("tool") == "search_kakao_places" and entry.get("arguments", {}).get("purpose") != "weather_coordinates"]
    search_text = " ".join(str(a.get("query", "")) + " " + str(a.get("visit_conditions", "")) for a in args)
    preference = context.get("preferences") or next((k for k in ("박물관", "미술관", "전시관", "공원", "해수욕장") if k in search_text), "")
    context["preferences"] = preference
    if api_key:
        region = region.replace(api_key, "[비공개]")
    budget = min(12, max(4, duration * 2 + 2))
    stop_reason = "sufficient_candidates"
    working["plan_search_attempted"] = False
    if api_key and region:
        activity_queries = [(f"{region} {preference}", "")] if preference else [(region, "AT4"), (region, "CT1"), (f"{region} 관광지", "")]
        variants = (("activities", activity_queries),
                    ("restaurants", [(region, "FD6"), (f"{region} 음식점", ""), (f"{region} 맛집", "")]))
        for kind, queries in variants:
            kind_calls = 0
            for query, category in queries:
                for page in range(1, budget // 2 + 1):
                    pool = [place for place in candidates.values() if is_restaurant(place) == (kind == "restaurants")]
                    if len(pool) >= duration * 2 or len(logs) >= budget or kind_calls >= budget // 2:
                        break
                    result = search_places(query, api_key, allow_fallback=False, page=page, category_group_code=category)
                    working["plan_search_attempted"] = True
                    kind_calls += 1
                    logs.append({"call_id": f"plan_{len(logs)+1}", "tool": "search_kakao_places", "branch": "travel_plan", "arguments": {
                        "query": query, "category_group_code": category, "page": page, "purpose": kind,
                    }, "status": result["status"], "result_count": len(result.get("places", [])), "source": "Kakao Map", "source_url": ENDPOINT,
                        "retrieved_at": datetime.now(KST).isoformat(timespec="seconds"), "result": result})
                    before = len(candidates)
                    for place in result.get("places", []):
                        if not place.get("name") or not place.get("map_url"):
                            continue
                        if any(word in place.get("category", "") for word in ("주차장", "기념품")):
                            continue
                        if is_restaurant(place) == (kind == "restaurants"):
                            candidates.setdefault(place["map_url"], place)
                        pool = [place for place in candidates.values() if is_restaurant(place) == (kind == "restaurants")]
                        if len(pool) >= duration * 2:
                            break
                    if result["status"] in {"auth_error", "quota_error", "unavailable"}:
                        stop_reason = result["status"]
                        break
                    if result["status"] != "ok" or len(candidates) == before:
                        break
                if stop_reason in {"auth_error", "quota_error", "unavailable"}:
                    break
            if stop_reason in {"auth_error", "quota_error", "unavailable"}:
                break
    else:
        stop_reason = "missing_key" if not api_key else "region_required"
    working["plan_places"] = list(candidates.values())
    working["plan_search_log"] = logs
    enough = all(sum(is_restaurant(place) == (kind == "restaurants") for place in candidates.values()) >= duration * 2 for kind in ("activities", "restaurants"))
    if not enough and stop_reason == "sufficient_candidates":
        stop_reason = "search_limit" if len(logs) >= budget else "insufficient_results"
    plan = recommend_travel_plan(working)
    plan.update(execution_log=logs, search_limit=budget, additional_search_count=len(logs), search_stop_reason=stop_reason)
    if stop_reason == "missing_key":
        plan["content"] += "\n\n추가 장소 검색 키가 설정되지 않아 기존 조회 결과로만 작성했습니다."
    elif stop_reason == "region_required":
        plan["content"] += "\n\n추가 검색을 위한 지역 정보가 부족해 기존 조회 결과로만 작성했습니다."
    elif stop_reason in {"auth_error", "quota_error", "unavailable"}:
        plan["content"] += "\n\n추가 검색을 완료하지 못해 확보된 장소만으로 작성했습니다. 검색 실행 결과를 확인해 주세요."
    return plan


def _missing_plan_weather(run):
    """일반 장소 답변에서 계획 버튼을 눌러도 명시된 날짜의 예보를 보충합니다."""
    dates = run.get("request_context", {}).get("dates", [])
    check = weather_preflight(" ".join(dates))
    if check["status"] != "ready":
        return {"state": {"status": check["status"], "message": check["message"]}}
    place = next((p for p in collect_plan_evidence(run)["places"] if valid_coordinates(p)), None)
    if not place:
        return {"state": {"status": "invalid_coordinates", "message": "추천 장소의 좌표가 없어 날씨를 조회하지 못했습니다."}}
    result = fetch_forecast(place, check["dates"])
    entry = {"tool": "open_meteo_forecast", "branch": "weather", "status": result["status"],
             "call_index": len(run.get("execution_log", []))+1,
             "arguments": {"longitude": float(place["x"]), "latitude": float(place["y"]), "dates": dates, "purpose": "plan_weather_enrichment"},
             "result": result, "source": result.get("source", "Open-Meteo"), "retrieved_at": result.get("retrieved_at"), "result_count": len(result.get("days", []))}
    return {"entry": entry, "state": result}


@observed("build_travel_plan")
def build_travel_plan(run):
    if any(entry.get("tool") == "open_meteo_forecast" for entry in run.get("execution_log", [])):
        return _build_place_plan(run)
    with ThreadPoolExecutor(max_workers=1) as executor:
        weather_future = executor.submit(copy_context().run, _missing_plan_weather, deepcopy(run))
        plan = _build_place_plan(run)
        weather = weather_future.result()
    if not plan:
        return plan
    basis = plan["basis"]
    basis["plan_weather_state"] = weather["state"]
    if weather.get("entry"):
        basis.setdefault("execution_log", []).append(weather["entry"])
        basis["call_count"] = len(basis["execution_log"])
        basis.setdefault("events", []).append({"event": "tool_return", "branch": "weather", "tool": "open_meteo_forecast", "status": weather["entry"]["status"], "reason": "plan_weather_enrichment"})
    refreshed = recommend_travel_plan(basis)
    footer = "영업시간과 이동시간은 조회되지 않아 계획에서 제외했습니다."
    tail = plan["content"].partition(footer)[2]
    plan.update(content=refreshed["content"]+tail, basis=basis, source_calls=refreshed["source_calls"])
    return plan
