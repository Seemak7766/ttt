"""시작 코드의 현재 계획·조건 변경 개념을 여러 날 일정에 맞게 적용합니다."""
from copy import deepcopy
from datetime import datetime
import re

from travel_plan import text
from weather_forecast import KST
from travel_cost import estimated_cost
from observability import observed


class PlanChangeError(ValueError):
    pass


def normalize_time(value):
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", str(value).strip())
    if not match or int(match[1]) > 23 or int(match[2]) > 59:
        raise PlanChangeError("시간은 00:00부터 23:59 사이의 HH:MM 형식으로 입력해 주세요.")
    return f"{int(match[1]):02d}:{int(match[2]):02d}"


def render_current(plan):
    lines = ["### 방문 순서", "", "아래 방문 시각과 순서는 제안입니다.", ""]
    for day in sorted({v["day"] for v in plan["visits"]}):
        visits = [v for v in plan["visits"] if v["day"] == day]
        lines += [f"#### {day}일차" + (f" · {visits[0]['date']}" if visits[0].get("date") else ""), ""]
        for i, v in enumerate(visits, 1):
            candidate = next((p for p in plan.get("candidates", []) if p.get("map_url") == v.get("map_url")), v)
            lines += [f"{i}. **{text(v['slot'])} · {text(v['name'])}**", "",
                      f"   - **주소:** {text(v['address'])}", f"   - [지도 링크]({v['map_url']})",
                      f"   - **제안:** {v['time']} 방문",
                      f"   - **예상 비용(추정):** {estimated_cost(candidate)}", ""]
    if not plan["visits"]:
        lines += ["조건에 맞는 방문지가 없어 일정을 비워 두었습니다.", ""]
    original = plan["content"]
    if "### 준비물 / 제안" in original:
        lines += ["### 준비물 / 제안" + original.split("### 준비물 / 제안", 1)[1]]
    return "\n".join(lines)


@observed("update_travel_plan", run_type="tool")
def update_current(plan, *, start_time=None, end_time=None, visit_count=None, exclude_places=None, restore_places=None):
    """검증된 후보만 사용하며 실패하면 기존 계획을 전혀 변경하지 않습니다."""
    p = deepcopy(plan)
    c = p.setdefault("constraints", {"exclude": []})
    start = normalize_time(start_time) if start_time else c.get("start_time")
    end = normalize_time(end_time) if end_time else c.get("end_time")
    count = visit_count if visit_count is not None else c.get("visit_count")
    if count is not None and (isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 12):
        raise PlanChangeError("하루 방문 수는 1~12곳으로 지정해 주세요.")
    def minutes(t):
        return int(t[:2])*60 + int(t[3:])
    if (start or end) and minutes(end or "20:00") <= minutes(start or "09:00"):
        raise PlanChangeError("끝 시간은 시작 시간보다 늦어야 합니다.")
    names = [v["name"] for v in p["candidates"]]
    def match(terms):
        found = []
        for term in terms or []:
            compact = re.sub(r"\s+", "", term)
            hits = [n for n in names if re.sub(r"\s+", "", n) == compact]
            hits = hits or [n for n in names if compact and compact in re.sub(r"\s+", "", n)]
            if len(hits) != 1:
                raise PlanChangeError(f"‘{term}’에 해당하는 장소가 없거나 여러 곳입니다. 조회된 장소의 정확한 이름을 알려 주세요.")
            found.extend(hits)
        return found
    excluded = (set(c.get("exclude", [])) | set(match(exclude_places))) - set(match(restore_places))
    restored = set(match(restore_places))
    if restored:
        existing = {v["map_url"] for v in p["visits"]}
        p["visits"] += [deepcopy(v) for v in p.get("original_visits", []) if v["name"] in restored and v["map_url"] not in existing]
        p["visits"].sort(key=lambda v: (v["day"], v["time"]))
    used = set()
    visits = []
    # 남은 방문은 보존하고 제외된 자리는 같은 유형의 미사용 후보로만 대체합니다.
    for old in p["visits"]:
        if old["name"] not in excluded:
            used.add(old["map_url"])
    from travel_plan import is_restaurant
    for old in p["visits"]:
        v = dict(old)
        if v["name"] in excluded:
            meal = v["slot"] in {"점심", "저녁"}
            replacement = next((x for x in p["candidates"] if x["name"] not in excluded and x["map_url"] not in used and is_restaurant(x) == meal), None)
            if not replacement:
                continue
            v.update({k: replacement.get(k, "") for k in ("name", "address", "map_url")})
        used.add(v["map_url"])
        visits.append(v)
    days = sorted({v["day"] for v in plan["visits"]})
    result = []
    for day in days:
        daily = [v for v in visits if v["day"] == day]
        if count:
            daily = daily[:count]
            for x in p["candidates"]:
                if len(daily) >= count:
                    break
                if x["name"] not in excluded and x["map_url"] not in used:
                    daily.append({"day": day, "date": next(v["date"] for v in plan["visits"] if v["day"] == day), "slot": "추가 일정", "time": "10:00", **{k: x.get(k, "") for k in ("name", "address", "map_url")}, "edited": False})
                    used.add(x["map_url"])
            if len(daily) < count:
                raise PlanChangeError("조회된 후보가 부족해 요청한 방문 수를 적용하지 않았습니다. 장소를 추가로 추천받아 주세요.")
        if daily and (start or end or count):
            lo, hi = minutes(start or "09:00"), minutes(end or "20:00")
            if (hi-lo)//len(daily) < 30:
                raise PlanChangeError("시간 범위가 너무 짧습니다. 장소당 제안 간격이 30분 이상이 되도록 조정해 주세요.")
            for i, v in enumerate(daily):
                t = lo + (hi-lo)*i//len(daily)
                v["time"] = f"{t//60:02d}:{t%60:02d}"
        result += daily
    p["visits"] = result
    p["constraints"] = {"start_time": start, "end_time": end, "visit_count": count, "exclude": sorted(excluded)}
    if p["visits"] == plan["visits"] and p["constraints"] == plan.get("constraints"):
        return None
    p["version"] = plan.get("version", 1)+1
    p["content"] = render_current(p)
    p["updated_at"] = datetime.now(KST).isoformat(timespec="seconds")
    return p


def parse_change(question):
    """확실히 읽을 수 있는 조건만 적용하고 미지원 표현은 성공한 것으로 답하지 않습니다."""
    args = {}
    number = r"(\d+|한|두|세|네|다섯|여섯)"
    n = re.search(number + r"\s*곳", question)
    if n:
        words = {"한": 1, "두": 2, "세": 3, "네": 4, "다섯": 5, "여섯": 6}
        args["visit_count"] = words[n[1]] if n[1] in words else int(n[1])
    times = list(re.finditer(r"(오전|오후)?\s*(\d{1,2}|한|두|세|네|다섯|여섯|일곱|여덟|아홉|열|열한|열두)\s*(?::(\d{2})|시(?:\s*(\d{1,2})분)?)\s*(부터|까지)?", question))
    period = None
    words = {"한": 1, "두": 2, "세": 3, "네": 4, "다섯": 5, "여섯": 6, "일곱": 7, "여덟": 8, "아홉": 9, "열": 10, "열한": 11, "열두": 12}
    for i, m in enumerate(times):
        period = m[1] or period
        h = words.get(m[2]) if m[2] in words else int(m[2])
        if period == "오후" and h < 12:
            h += 12
        elif period == "오전" and h == 12:
            h = 0
        args["end_time" if m[5] == "까지" or (len(times) > 1 and i == len(times)-1) else "start_time"] = f"{h:02d}:{int(m[3] or m[4] or 0):02d}"
    if not times:
        if "오후" in question:
            args.update(start_time="13:00", end_time="18:00")
        elif "오전" in question:
            args.update(start_time="09:00", end_time="12:00")
        elif "저녁" in question:
            args.update(start_time="18:00", end_time="21:00")
    place = re.search(r"^\s*(.+?)(?:은|는|을|를)?\s*(?:빼\s*줘|빼주세요|제외해\s*줘|제외해\s*주세요|다시\s*넣어\s*줘|다시\s*포함해\s*줘)[.!?\s]*$", question)
    if place:
        term = re.sub(r"(?:은|는|을|를)$", "", place[1].strip())
        args["restore_places" if "다시" in question else "exclude_places"] = [term]
    return args


def local_run(answer, plan, status="updated"):
    entry = {"tool": "update_plan", "status": status, "arguments": {}, "result": {"plan_version": plan.get("version"), "visits": plan.get("visits", [])}}
    return {"mode": "retry", "limit": 3, "call_count": 1, "answer": answer, "status": "completed", "execution_log": [entry],
            "events": [{"event": "tool_return", "tool": "update_plan", "status": status}, {"event": "answer", "reason": "date_required" if status == "need_info" else status if status == "out_of_range" else "plan_update", "status": "completed"}],
            "request_context": deepcopy(plan.get("basis", {}).get("request_context", {})), "sections": {}}
