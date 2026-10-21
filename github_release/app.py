import streamlit as st
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timedelta, timezone
from html import escape
from chatbot import ChatbotError, run_agent, summarize_conversation
from config import load_kakao_rest_api_key, configuration_status, APP_BUILD
from travel_plan import PLAN_FORMAT_VERSION, build_travel_plan, collect_plan_evidence, recommend_travel_plan
from weather_forecast import trip_duration_days
from plan_actions import handle_plan_question
from plan_state import update_current, PlanChangeError
from plan_view import schedule_cards_html, preparation_markdown
from place_map import plan_map_places, show_place_map
from copy import deepcopy
import json

st.set_page_config(page_title="여행 챗봇", page_icon="✈️", layout="wide", initial_sidebar_state="expanded")
KST = timezone(timedelta(hours=9))
st.markdown("<style>" + (Path(__file__).resolve().parent / "static" / "travel_theme.css").read_text(encoding="utf-8") + "</style>", unsafe_allow_html=True)
st.markdown("""
<style>
/* Cloud에서 외부 CSS 파일이 이전 버전이어도 읽을 수 있도록 보정합니다. */
html body .stApp [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"],
html body .stApp [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] p,
html body .stApp [data-testid="stChatMessage"] .question-text,
html body .stApp [data-testid="stWidgetLabel"] p,
html body .stApp [data-testid="stTextArea"] label p {
    color: #edf5f0 !important;
}
html body .stApp [data-testid="stTextArea"] textarea {
    color: #edf5f0 !important;
    -webkit-text-fill-color: #edf5f0 !important;
}
/* 비교표의 메뉴/유형 열을 한 줄로 유지합니다. */
[data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] table th:first-child,
[data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] table td:first-child {
    min-width: 120px;
    white-space: nowrap;
    word-break: keep-all;
    overflow-wrap: normal;
}
[data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] table {
    display: block;
    max-width: 100%;
    overflow-x: auto;
}
.question-row {
    display: flex;
    align-items: flex-start;
    gap: 12px;
    flex-wrap: wrap;
    width: 100%;
}
.question-text {
    flex: 1 1 180px;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
}
.question-time {
    margin-left: auto;
    padding-top: 3px;
    font-size: 11px;
    opacity: 0.65;
    white-space: nowrap;
    text-align: right;
}
/* 제목과 시간을 같은 버튼 안에서 두 줄로 표시합니다. */
[data-testid="stSidebar"] [class*="st-key-chat_item_"] {
    gap: 0 !important;
}
[data-testid="stSidebar"] [class*="st-key-chat_item_"] button {
    padding: 8px 12px;
}
[data-testid="stSidebar"] [class*="st-key-chat_item_"] button [data-testid="stMarkdownContainer"] {
    display: flex;
    flex-direction: column;
    gap: 2px;
}
[data-testid="stSidebar"] [class*="st-key-chat_item_"] button p {
    margin: 0;
}
[data-testid="stSidebar"] [class*="st-key-chat_item_"] button p + p {
    font-size: 11px;
    line-height: 1.2;
    opacity: 0.8;
}
</style>
""", unsafe_allow_html=True)

def show_feature_result(run, key, title, branch):
    tools = [entry for entry in run.get("execution_log", []) if entry.get("branch", "recommendations") == branch]
    events = [event for event in run.get("events", []) if event.get("branch") == branch or (
        branch == "recommendations" and not event.get("branch") and event.get("tool") == "search_kakao_places"
    )]
    with st.expander(f"실행 결과 (IPO) · {title} · 도구 호출 {len(tools)}회", expanded=False):
        if tools or events:
            st.json({"실행 순서": events, "도구 실행 결과": tools})
        else:
            st.caption("해당 기능의 외부 API를 호출하지 않았습니다.")


def new_conversation():
    conversation_id = uuid4().hex
    st.session_state.conversations[conversation_id] = {
        "title": "새로운 대화", "messages": [],
        "created_at": datetime.now(KST), "last_question_at": None,
    }
    st.session_state.active_conversation = conversation_id


if "conversations" not in st.session_state:
    st.session_state.conversations = {}
    new_conversation()

if "sidebar_compact" not in st.session_state:
    st.session_state.sidebar_compact = False

def toggle_sidebar():
    st.session_state.sidebar_compact = not st.session_state.sidebar_compact

sidebar_tooltips = []
def sidebar_tooltip(key, label):
    # CSS 호버만 사용해 클릭 후 남는 Streamlit 포커스 툴팁을 방지합니다.
    content = json.dumps(label, ensure_ascii=False).replace("<", r"\3c ").replace(">", r"\3e ")
    selector = f'[data-testid="stSidebar"] .st-key-{key}'
    anchor = f'--sidebar-tip-{key}'
    sidebar_tooltips.append(f'''{selector} button {{ anchor-name: {anchor}; }}
{selector}::after {{ content: {content}; position-anchor: {anchor}; }}''')

with st.sidebar:
    compact = st.session_state.sidebar_compact
    st.markdown('<span class="sidebar-compact-marker"></span>' if compact else '<span class="sidebar-expanded-marker"></span>', unsafe_allow_html=True)
    st.button("사이드바 펼치기" if compact else "사이드바 접기", key="toggle_sidebar", on_click=toggle_sidebar,
              icon=":material/chevron_right:" if compact else ":material/chevron_left:")
    sidebar_tooltip("toggle_sidebar", "사이드바 펼치기" if compact else "사이드바를 두 글자 메뉴로 접기")
    with st.container(key="sidebar_heading", gap=None):
        st.header("내 여행 대화")
    st.button("새글" if compact else "＋ 새로운 대화", key="sidebar_new_conversation", on_click=new_conversation, use_container_width=True)
    sidebar_tooltip("sidebar_new_conversation", "새로운 대화 시작")
    conversations_by_recency = sorted(
        st.session_state.conversations.items(),
        key=lambda item: (
            item[1].get("last_question_at")
            or item[1].get("created_at")
            or datetime.min.replace(tzinfo=KST)
        ),
        reverse=True,
    )
    for conversation_id, conversation in conversations_by_recency:
        last_question_at = conversation.get("last_question_at")
        timestamp = last_question_at.astimezone(KST).strftime("%Y.%m.%d %H:%M") if last_question_at else "아직 질문이 없습니다."
        with st.container(key=f"chat_item_{conversation_id}", gap=None):
            if st.button(
                "".join(conversation["title"].split())[:2] if compact else f'{conversation["title"]}\n\n{timestamp}', key=conversation_id,
                type="primary" if conversation_id == st.session_state.active_conversation else "secondary",
                use_container_width=True,
            ):
                st.session_state.active_conversation = conversation_id
                st.rerun()
        sidebar_tooltip(conversation_id, f'{conversation["title"]} · {timestamp}')
    if not compact:
        st.caption("대화는 현재 브라우저 세션 동안 유지됩니다. 새로고침하면 초기화될 수 있습니다.")
        st.caption("카카오맵 장소 검색 사용 가능" if load_kakao_rest_api_key() else "카카오맵 장소 검색 키가 설정되지 않았습니다.")
        with st.expander("배포 설정 확인", expanded=False):
            st.caption(f"앱 버전: {APP_BUILD}")
            for variable, status in configuration_status().items():
                st.write(f"{variable}: {status}")
            st.caption("키 값은 표시하지 않습니다. 설정 여부는 인증 성공 여부와 다릅니다.")

st.markdown("<style>" + "\n".join(sidebar_tooltips) + "</style>", unsafe_allow_html=True)

active_id = st.session_state.active_conversation
active = st.session_state.conversations[active_id]
st.markdown('<div class="travel-eyebrow">YOUR NEXT JOURNEY</div>', unsafe_allow_html=True)
st.title("여행 챗봇")
st.caption("여행 대화를 기억하며, 국내 장소는 카카오맵에서 검색할 수 있습니다.")
st.subheader(active["title"])
for message_index, message in enumerate(active["messages"]):
    with st.chat_message(message["role"]):
        if message["role"] == "user":
            st.markdown(
                '<div class="question-row">'
                f'<div class="question-text">{escape(message["content"])}</div>'
                f'<time class="question-time">{escape(message.get("sent_at", "시간 기록 없음"))}</time>'
                '</div>',
                unsafe_allow_html=True,
            )
        else:
            summary, separator, plan_details = message["content"].partition("### 방문 순서")
            if summary.strip():
                st.write(summary)
            if separator:
                with st.expander("이 답변의 여행 계획 상세", expanded=False):
                    st.markdown(separator + plan_details)
            runs = message.get("runs", [])
            entries = message.get("execution_log", [])
            run = runs[-1] if runs else None
            if run and run.get("sections"):
                weather_column, places_column = st.columns([1, 1], gap="medium")
                with weather_column:
                    show_feature_result(run, "weather", "날씨 조회", "weather")
                with places_column:
                    show_feature_result(run, "places", "지역·장소 검색", "recommendations")
            if (runs or "execution_log" in message) and not (run and run.get("sections")):
                run = runs[-1] if runs else None
                count = run["call_count"] if run else len(entries)
                limit = run["limit"] if run else 3
                with st.expander(f"실행 결과 (IPO) · 도구 호출 {count}/{limit}회", expanded=False):
                    if run:
                        st.caption(f'실행 상태: {run["status"]}')
                        if count:
                            evidence = run.get("events", [])[-1].get("evidence_calls", []) if run.get("events") else []
                            st.caption("답변 근거: 도구 반환 " + ", ".join(f"#{index}" for index in evidence) if evidence else f"답변 근거: 마지막 도구 반환 #{count}")
                        st.json({"실행 순서": run.get("events", []), "도구 실행 결과": run.get("execution_log", [])})
                    elif entries:
                        st.json(entries)
                    else:
                        st.caption("장소 검색 도구를 호출하지 않고 답변했습니다.")
            if run and collect_plan_evidence(run)["places"]:
                with st.expander("추천 장소 지도 보기", expanded=False):
                    show_place_map(collect_plan_evidence(run)["places"], f"answer_map_{active_id}_{message_index}")
                if message_index > 0:
                    duration = trip_duration_days(active["messages"][message_index-1]["content"])
                    if duration:
                        run.setdefault("request_context", {})["trip_days"] = duration
                if message.get("travel_plan") and message["travel_plan"].get("format_version") != PLAN_FORMAT_VERSION:
                    message["travel_plan"] = recommend_travel_plan(run)
                if st.button("검색 정보로 여행 계획 추천", key=f"plan_{active_id}_{message_index}"):
                    with st.spinner("부족한 방문지와 식당을 검색해 여행 계획을 구성하고 있습니다..."):
                        message["travel_plan"] = build_travel_plan(run)
                        active["current_plan"] = deepcopy(message["travel_plan"])
                if message.get("travel_plan"):
                    with st.expander("이 답변에서 생성한 계획 보기", expanded=False):
                        st.markdown(message["travel_plan"]["content"])
                    plan = message["travel_plan"]
                    if "execution_log" in plan:
                        with st.expander(f'여행 계획 추가 검색 결과 · {plan["additional_search_count"]}/{plan["search_limit"]}회', expanded=False):
                            st.json({"status": plan["search_stop_reason"], "도구 실행 결과": plan["execution_log"]})

if active.get("current_plan"):
    current = active["current_plan"]
    st.divider()
    st.subheader(f'현재 여행 계획 · v{current.get("version", 1)}')
    with st.container(key="travel_schedule"):
        st.markdown(schedule_cards_html(current), unsafe_allow_html=True)
    with st.expander("여행 계획 상세 보기", expanded=False):
        preparation_tab, map_tab, edit_tab, evidence_tab, execution_tab = st.tabs(["준비물·제안", "추천 장소 지도", "계획 조건 수정", "조회 근거", "실행 기록"])
        with preparation_tab:
            st.markdown(preparation_markdown(current))
        with map_tab:
            show_place_map(plan_map_places(current), f"plan_map_{active_id}")
    with edit_tab:
        st.caption("날짜와 지역은 유지합니다. 하루 방문 수에는 식사 장소도 포함됩니다. 비워 둔 시간은 기존 조건을 유지합니다.")
        with st.form(f'edit_plan_{active_id}_{current.get("version", 1)}'):
            c1, c2 = st.columns(2)
            start = c1.text_input("시작 시간 (HH:MM)", value=current.get("constraints", {}).get("start_time") or "")
            end = c2.text_input("끝 시간 (HH:MM)", value=current.get("constraints", {}).get("end_time") or "")
            count = st.number_input("하루 방문 수 (0: 기존 유지)", min_value=0, max_value=12, value=current.get("constraints", {}).get("visit_count") or 0)
            excluded = st.multiselect("제외할 장소", options=list(dict.fromkeys(p["name"] for p in current["candidates"])), default=current.get("constraints", {}).get("exclude", []))
            if st.form_submit_button("계획 수정 적용"):
                try:
                    old_excluded = set(current.get("constraints", {}).get("exclude", []))
                    revised = update_current(current, start_time=start or None, end_time=end or None, visit_count=count or None,
                                             exclude_places=excluded, restore_places=list(old_excluded-set(excluded)))
                    if revised:
                        active["current_plan"] = revised
                        st.rerun()
                    st.info("바뀐 조건이 없어 현재 계획을 유지했습니다.")
                except PlanChangeError as error:
                    st.error(str(error))
    with evidence_tab:
        st.json({"원래 조회": current.get("basis", {}).get("execution_log", []), "추가 검색": current.get("execution_log", []), "수정 조건": current.get("constraints", {})})
    with execution_tab:
        weather_column, places_column = st.columns([1, 1], gap="medium")
        with weather_column:
            show_feature_result(current.get("basis", {}), "plan_weather", "날씨 조회", "weather")
        with places_column:
            show_feature_result(current.get("basis", {}), "plan_places", "지역·장소 검색", "recommendations")
        st.caption("여행 계획 구성 시 추가 검색")
        st.json({"호출 수": current.get("additional_search_count", 0), "호출 한도": current.get("search_limit", 0),
                 "종료 상태": current.get("search_stop_reason", "추가 검색 없음"), "도구 실행 결과": current.get("execution_log", [])})

if not active["messages"]:
    st.info("여행지, 예산, 일정 등 궁금한 내용을 입력해 주세요.")

with st.form(f"question_{active_id}", clear_on_submit=True):
    question = st.text_area("여행 질문", placeholder="제주도 2박 3일 일정을 추천해줘", help="Enter: 답변 받기 · Alt+Enter: 줄바꿈")
    submitted = st.form_submit_button("답변 받기")
st.caption("Enter로 답변 받기 · Alt+Enter로 줄바꿈")
st.iframe(
    Path(__file__).resolve().parent / "static" / "keyboard_shortcuts.html",
    height=1, tab_index=-1,
)
if submitted:
    if not question.strip():
        st.info("질문을 입력해 주세요.")
    else:
        question_time = datetime.now(KST)
        try:
            with st.spinner("답변을 작성하고 있습니다..."):
                selected_run, generated_plan = handle_plan_question(question, active, run_agent)
                runs = [selected_run]
                answer = selected_run["answer"]
            # 성공한 질문과 답변을 함께 저장해 실패 시 기록이 어긋나지 않게 합니다.
            fallback_title = active["title"] if active["messages"] else question.strip()[:24]
            active["messages"].extend([
                {"role": "user", "content": question.strip(), "sent_at": question_time.strftime("%Y.%m.%d %H:%M")},
                {"role": "assistant", "content": answer, "execution_log": selected_run["execution_log"], "runs": runs},
            ])
            active["last_question_at"] = question_time
            stop_reason = selected_run["events"][-1].get("reason") if selected_run["events"] else None
            active["title"] = fallback_title if stop_reason in {"date_required", "out_of_range"} else summarize_conversation(active["messages"], fallback_title)
            st.rerun()
        except ChatbotError as error:
            st.error(str(error))
