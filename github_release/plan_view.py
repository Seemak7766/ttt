"""현재 계획의 필수 일정표와 선택적으로 확인할 상세 내용을 분리합니다."""
from travel_plan import text
from travel_plan import collect_plan_evidence
from html import escape
from urllib.parse import urlparse
from travel_cost import estimated_cost, COST_NOTICE


def weather_appearance(code):
    if isinstance(code, bool) or not isinstance(code, (int, float)):
        return "neutral", "상태 정보 없음"
    if code in {0, 1}:
        return "sunny", "화창"
    if code == 2:
        return "partly-cloudy", "구름 조금"
    if code == 3:
        return "cloudy", "흐림"
    if code in {45, 48}:
        return "fog", "안개"
    if code in {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82}:
        return "rain", "비"
    if code in {71, 73, 75, 77, 85, 86}:
        return "snow", "눈"
    if code in {95, 96, 97, 99}:
        return "storm", "뇌우"
    return "neutral", "상태 정보 없음"


def weather_illustration(kind):
    """외부 이미지 전송 없이 표시하는 작은 SVG 배경 일러스트."""
    shapes = []
    if kind in {"sunny", "partly-cloudy"}:
        shapes.append('<g stroke="#f6d581" stroke-width="4" stroke-linecap="round"><circle cx="202" cy="62" r="28" fill="#f6d581"/><path d="M202 18v-9m0 106v-9m44-44h9m-106 0h9m76-32 7-7m-78 78 7-7m64 0 7 7m-78-78 7 7"/></g>')
    if kind in {"partly-cloudy", "cloudy", "rain", "snow", "storm", "fog"}:
        shapes.append('<path d="M138 105c-35 0-36-43-8-49 2-38 56-45 70-10 35-6 51 43 16 57Z" fill="#b5cbd0"/>')
    if kind == "rain":
        shapes.append('<path d="m149 119-8 18m37-18-8 18m37-18-8 18" stroke="#90d0e9" stroke-width="5" stroke-linecap="round"/>')
    if kind == "snow":
        for x in (146, 177, 208):
            shapes.append(f'<path d="M{x} 117v20m-9-15 18 10m-18 0 18-10" stroke="#edf8fc" stroke-width="3" stroke-linecap="round"/>')
    if kind == "storm":
        shapes.append('<path d="m179 96-18 32h18l-10 28 36-44h-20l9-16Z" fill="#f2d27c"/>')
    if kind == "fog":
        shapes.append('<path d="M114 118h119m-104 14h120m-136 14h105" stroke="#d3e2df" stroke-width="5" stroke-linecap="round"/>')
    if not shapes:
        shapes.append('<path d="M100 144Q160 95 220 144T320 140" stroke="#a1c2b5" stroke-width="2" fill="none"/>')
    return '<div class="trip-weather-scene" aria-hidden="true"><svg viewBox="0 0 280 180" xmlns="http://www.w3.org/2000/svg">' + ''.join(shapes) + '</svg></div>'


def schedule_cards_html(plan):
    """저장된 일정과 같은 날짜의 예보만 카드에 표시하며 새 API는 호출하지 않습니다."""
    def e(value):
        return escape(str(value or ""), quote=True)
    def number(value, unit):
        return f"{value:g}{unit}" if isinstance(value, (int, float)) and not isinstance(value, bool) else "정보 없음"
    context = plan.get("basis", {}).get("request_context", {})
    weather = collect_plan_evidence(plan.get("basis", {})).get("weather") or {}
    forecasts = {day["date"]: day for day in weather.get("days", [])}
    visits = plan.get("visits", [])
    candidates = {place["map_url"]: place for place in plan.get("candidates", []) if place.get("map_url")}
    output = ['<section class="trip-overview" aria-label="여행 계획 요약">',
              f'<div class="trip-summary-bar"><span class="trip-check">✓</span><span>여행 계획 · 장소 {len(visits)}곳</span><span class="trip-version">v{e(plan.get("version", 1))}</span></div>',
              f'<p class="trip-conditions"><strong>지역</strong> {e(context.get("region") or "조회 지역")}<span>·</span><strong>취향</strong> {e(context.get("preferences") or "기본 여행")}</p>']
    if not visits:
        output.append('<p class="trip-muted">조건에 맞는 조회 장소가 없어 작성된 일정이 없습니다.</p>')
    for day_index in sorted({visit["day"] for visit in visits}):
        daily = [v for v in visits if v["day"] == day_index]
        date_value = daily[0].get("date", "")
        forecast = forecasts.get(date_value)
        output += [f'<section class="trip-day"><h4>{day_index}일차 <span>{e(date_value)}</span></h4>', '<div class="trip-day-summary"><div class="trip-schedule-panel"><h5>일정</h5>',
                   '<table class="trip-mini-schedule"><thead><tr><th>제안 시각</th><th>장소</th></tr></thead><tbody>']
        for visit in daily:
            output.append(f'<tr><td>{e(visit.get("time"))}<span>{e(visit.get("slot"))}</span></td><td>{e(visit.get("name"))}</td></tr>')
        appearance, weather_label = weather_appearance((forecast or {}).get("weather_code"))
        output += ['</tbody></table></div>', f'<div class="trip-weather-panel weather-{appearance}">', weather_illustration(appearance), f'<h5>날씨 <span>{e(date_value)}</span></h5>']
        if forecast:
            output.append(f'<p class="trip-weather-label">{weather_label}</p>')
            output.append('<div class="trip-weather-metrics">')
            for label, value, unit in (("최고", forecast.get("max_c"), "°C"), ("최저", forecast.get("min_c"), "°C"), ("강수확률", forecast.get("precipitation_probability"), "%")):
                output.append(f'<div><span>{label}</span><strong>{e(number(value, unit))}</strong></div>')
            output.append('</div>')
            rain, high, low = forecast.get("precipitation_probability"), forecast.get("max_c"), forecast.get("min_c")
            advice = []
            if isinstance(rain, (int, float)) and rain >= 40:
                advice.append("우산을 챙겨 주세요")
            if isinstance(high, (int, float)) and high >= 30:
                advice.append("더위에 주의하고 자주 쉬어 주세요")
            if isinstance(low, (int, float)) and low <= 15:
                advice.append("가벼운 겉옷을 준비해 주세요")
            output.append(f'<p class="trip-muted">{e(" · ".join(advice) or "예보는 달라질 수 있습니다.")}</p>')
        else:
            basis = plan.get("basis", {})
            state = basis.get("plan_weather_state") or next((entry.get("result", {}) for entry in reversed(basis.get("execution_log", [])) if entry.get("tool") == "open_meteo_forecast"), {})
            if state.get("status") == "date_required":
                reason = "날씨 조회에 필요한 여행 날짜를 알려 주세요."
            elif state.get("status") == "out_of_range":
                reason = "예보 없음. 과거 날짜 또는 예보 범위 밖이거나 해당 날짜의 자료가 없습니다."
            elif state.get("status") == "invalid_coordinates":
                reason = "추천 장소의 좌표가 없어 날씨를 조회하지 못했습니다."
            elif state.get("status") == "unavailable":
                reason = "날씨 서버 연결에 실패했습니다. 잠시 후 다시 조회해 주세요."
            else:
                reason = "해당 날짜에 조회된 예보가 없습니다."
            output.append(f'<p class="trip-muted">{e(reason)}</p>')
        output += ['</div></div><div class="trip-place-grid">']
        for order, visit in enumerate(daily, 1):
            url = visit.get("map_url", "")
            parsed = urlparse(url)
            link = f'<a href="{e(url)}" target="_blank" rel="noopener noreferrer">지도 보기 ↗</a>' if parsed.scheme == "https" and parsed.hostname == "place.map.kakao.com" else ""
            output += ['<article class="trip-place-card">',
                       f'<div class="trip-card-label"><span>{order:02d}</span>{e(visit.get("slot"))}</div>',
                       f'<h5>{e(visit.get("name"))}</h5>', f'<p class="trip-card-time">{e(visit.get("time"))} 방문 제안</p>',
                       f'<p class="trip-card-address">{e(visit.get("address") or "주소 정보 없음")}</p>',
                       f'<p class="trip-card-cost"><span>예상 비용 · 추정</span>{e(estimated_cost(candidates.get(visit.get("map_url"), visit)))}</p>', link, '</article>']
        output += ['</div></section>']
    output += [f'<p class="trip-footnote">{e(COST_NOTICE)}</p>', '<p class="trip-footnote">방문 순서·시각은 제안입니다. 조회되지 않은 영업시간·이동시간은 포함하지 않았습니다.</p>', '</section>']
    return "\n".join(output)


def schedule_markdown(plan):
    lines = ["### 시간대별 스케줄", "", "방문 시각과 순서는 제안입니다.", "",
             "| 일차 · 날짜 | 시간대 | 제안 시각 | 방문 장소 | 상세 주소 | 지도 |",
             "| --- | --- | --- | --- | --- | --- |"]
    for visit in plan.get("visits", []):
        day = f"{visit['day']}일차" + (f" · {visit['date']}" if visit.get("date") else "")
        values = [day, visit.get("slot", ""), visit.get("time", ""), visit.get("name", ""), visit.get("address") or "정보 없음"]
        row = " | ".join(text(value) for value in values)
        link = f"[지도 보기]({visit['map_url']})" if visit.get("map_url") else "정보 없음"
        lines.append(f"| {row} | {link} |")
    if not plan.get("visits"):
        return "### 시간대별 스케줄\n\n조건에 맞는 조회 장소가 없어 확정된 일정이 없습니다."
    lines += ["", "영업시간과 이동시간은 조회되지 않아 포함하지 않았습니다."]
    return "\n".join(lines)


def preparation_markdown(plan):
    content = plan.get("content", "")
    if "### 준비물 / 제안" in content:
        return "### 준비물 / 제안" + content.split("### 준비물 / 제안", 1)[1]
    return "준비물 제안이 없습니다."
