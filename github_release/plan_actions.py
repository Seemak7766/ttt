"""현재 계획을 대화 실행과 연결합니다. 재조사와 로컬 수정을 구분합니다."""
import re
from copy import deepcopy

from plan_state import PlanChangeError, parse_change, update_current, local_run
from travel_plan import build_travel_plan
from weather_forecast import weather_preflight


def handle_plan_question(question, active, runner):
    current = active.get("current_plan")
    change = parse_change(question)
    check = weather_preflight(question)
    new_date = check.get("dates")
    # 날짜·지역·취향이 함께 바뀌는 요청은 로컬 수정으로 삼키지 않습니다.
    research = bool(re.search(r"지역|날짜|대신.*(?:여행|추천)|실내|야외|박물관|미술관|날씨|(?:서울|부산|경주|제주|인천|대구|대전|광주|울산|강릉|속초|여수|전주)|[가-힣]+에서", question)) or bool(new_date)
    if current and change and not research:
        try:
            updated = update_current(current, **change)
            if updated:
                active["current_plan"] = updated
                return local_run("조회된 후보 안에서 여행 계획을 수정했습니다.\n\n" + updated["content"], updated), None
            return local_run("바뀐 조건이 없어 현재 계획을 유지했습니다.", current, "no_change"), None
        except PlanChangeError as error:
            return local_run(str(error) + " 현재 계획은 변경하지 않았습니다.", current, "not_applied"), None
    wants_plan = bool(re.search(r"계획\s*해|(?:계획|일정).*(?:만들|짜|추천|변경|바꿔|수정)|(?:만들|짜|추천).*(?:계획|일정)", question))
    if current and re.search(r"날짜|지역|실내|야외|바꿔|변경", question) and (not change or research):
        wants_plan = True
    sent = question
    if wants_plan:
        if check["status"] == "out_of_range" and not new_date:
            return local_run(check["message"], current or {}, "out_of_range"), None
        dates = new_date or (current or {}).get("basis", {}).get("request_context", {}).get("dates", [])
        if not dates:
            empty = current or {}
            return local_run("여행 날짜와 지역을 알려 주세요. 예: 모레 경주에서 박물관 중심으로 하루 여행 계획을 만들어 줘.", empty, "need_info"), None
        sent += "\n여행 계획을 위한 날씨와 장소 추천을 함께 조회해 주세요."
        if not new_date:
            sent += "\n기존 여행 날짜: " + " ".join(str(x) for x in dates)
    history = active["messages"]
    if wants_plan and current:
        history = history + [{"role": "assistant", "content": "현재 여행 계획의 조회 조건입니다.", "runs": [{"request_context": current.get("basis", {}).get("request_context", {})}]}]
        kind = current.get("basis", {}).get("request_context", {}).get("preferences", "")
        if kind and not re.search(r"실내|야외|실외|박물관|미술관|공원|해수욕장", question):
            sent += "\n기존 장소 취향 유지: " + kind
    run = runner(sent, history, mode="retry")
    plan = build_travel_plan(run) if wants_plan else None
    if plan:
        if current or change:
            c = (current or {}).get("constraints", {})
            same_region = (current or {}).get("basis", {}).get("request_context", {}).get("region") == plan.get("basis", {}).get("request_context", {}).get("region")
            try:
                params = {"start_time": c.get("start_time"), "end_time": c.get("end_time"), "visit_count": c.get("visit_count"), "exclude_places": c.get("exclude", []) if same_region else []}
                params.update(change)
                preserved = update_current(plan, **params)
                plan = preserved or plan
            except PlanChangeError as error:
                run["answer"] += "\n\n" + str(error) + " 새 조건을 기존 계획에 적용하지 않았습니다."
                return run, None
        active["current_plan"] = deepcopy(plan)
        run["answer"] += "\n\n" + plan["content"]
    elif wants_plan:
        run["answer"] += "\n\n장소 조회 결과가 없어 새 여행 계획을 확정하지 않았습니다."
    return run, plan
