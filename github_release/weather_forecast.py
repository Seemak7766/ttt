"""한국 시간의 상대 날짜와 Open-Meteo 일별 예보 처리."""

from datetime import date, datetime, timedelta, timezone
from html import escape
import math
import re
from calendar import monthrange

import httpx
from observability import observed

KST = timezone(timedelta(hours=9))
ENDPOINT = "https://api.open-meteo.com/v1/forecast"
SOURCE = "Open-Meteo"
WEEKDAYS = "월화수목금토일"


def now_kst():
    return datetime.now(KST)


def is_weather_question(question):
    return bool(re.search(r"날씨|기온|강수|비\s*(?:가\s*)?(?:와|올|오나|오니|오는|내리|내릴)", question))


def trip_duration_days(question):
    match = re.search(r"\d+\s*박\s*(\d+)\s*일", question)
    if not match:
        match = re.search(r"(\d+)\s*일\s*(?:간|동안|여행|일정)", question)
    return max(1, int(match.group(1))) if match else None


def resolve_relative_dates(question: str, today: date) -> list[date]:
    pattern = r"내일모레|그제|어제|오늘|내일|모레|글피|\d+\s*일\s*(?:후|뒤)|(?:이번|다음)\s*주말|(?:(?:이번|다음)\s*주\s*)?[월화수목금토일]요일"
    dates = set()
    def shift_months(months):
        total = today.year * 12 + today.month - 1 + months
        year, month = divmod(total, 12)
        return date(year, month + 1, min(today.day, monthrange(year, month + 1)[1]))

    # 숫자와 한국어 수량 표현을 모두 처리합니다. '한 달'은 30일이 아닌 달력 기준입니다.
    counts = {"한": 1, "두": 2, "세": 3, "네": 4, "다섯": 5, "여섯": 6, "일곱": 7, "여덟": 8, "아홉": 9, "열": 10,
              "일": 1, "이": 2, "삼": 3, "사": 4, "오": 5, "육": 6, "칠": 7, "팔": 8, "구": 9, "십": 10,
              "스무": 20, "서른": 30, "마흔": 40}
    count_pattern = r"\d+|" + "|".join(sorted(counts, key=len, reverse=True))
    for match in re.finditer(rf"({count_pattern})\s*(주일|개월|일|주|달|년)\s*(?:정도|쯤)?\s*(후|뒤|전)", question):
        count, unit, direction = match.groups()
        amount = int(count) if count.isdigit() else counts[count]
        amount *= -1 if direction == "전" else 1
        if unit in {"개월", "달", "년"}:
            dates.add(shift_months(amount * (12 if unit == "년" else 1)))
        else:
            dates.add(today + timedelta(days=amount * (7 if unit in {"주", "주일"} else 1)))
    for match in re.finditer(r"(다다음|다음)\s*달(?:\s*(초|말|\d{1,2}\s*일))?|내년|다음\s*해", question):
        token = re.sub(r"\s", "", match.group())
        months = 12 if token in {"내년", "다음해"} else 2 if token.startswith("다다음") else 1
        shifted = shift_months(months)
        suffix = match.group(2)
        if suffix:
            day = 1 if suffix == "초" else monthrange(shifted.year, shifted.month)[1] if suffix == "말" else int(re.search(r"\d+", suffix).group())
            shifted = shifted.replace(day=day)
        dates.add(shifted)
    for match in re.finditer(r"(?:(\d{4})\s*년\s*)?(\d{1,2})\s*월\s*(\d{1,2})\s*일|(?<!\d)(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)", question):
        year, month, day, iso_year, iso_month, iso_day = match.groups()
        dates.add(date(int(iso_year or year or today.year), int(iso_month or month), int(iso_day or day)))
    monday = today - timedelta(days=today.weekday())
    for match in re.finditer(pattern, question):
        token = re.sub(r"\s", "", match.group())
        offsets = {"그제": -2, "어제": -1, "오늘": 0, "내일": 1, "모레": 2, "내일모레": 2, "글피": 3}
        if token in offsets:
            dates.add(today + timedelta(days=offsets[token]))
        elif "주말" in token:
            saturday = monday + timedelta(days=12 if token.startswith("다음") else 5)
            dates.update(day for day in (saturday, saturday + timedelta(days=1)) if day >= today)
        elif "요일" in token:
            weekday = WEEKDAYS.index(token[-3])
            if token.startswith("다음주"):
                day = monday + timedelta(days=7 + weekday)
            elif token.startswith("이번주"):
                day = monday + timedelta(days=weekday)
            else:
                day = today + timedelta(days=(weekday - today.weekday()) % 7)
            dates.add(day)
        else:
            dates.add(today + timedelta(days=int(re.search(r"\d+", token).group())))
    if len(dates) > 1 and re.search(r"부터|까지|~|∼", question):
        first, last = min(dates), max(dates)
        # 지원 범위를 훨씬 넘는 입력은 대량 날짜 생성을 피합니다.
        if (last - first).days <= 31:
            dates = {first + timedelta(days=i) for i in range((last-first).days + 1)}
    duration = trip_duration_days(question)
    if dates and duration:
        first = min(dates)
        if duration <= 31:
            dates = {first + timedelta(days=index) for index in range(duration)}
        else:
            # 한도를 벗어난 기간은 끝 날짜로 판정하고 불필요한 날짜 목록 생성을 피합니다.
            dates = {first, first + timedelta(days=duration-1)}
    return sorted(dates)


def weather_preflight(question):
    checked_at = now_kst()
    metadata = {"source": SOURCE, "source_url": ENDPOINT, "checked_at": checked_at.isoformat(timespec="seconds"), "retrieved_at": None}
    if re.search(r"그저께|어제|그제|지난\s*(?:주|달|해|[월화수목금토일]요일)|작년|재작년|\d+\s*일\s*전|전날", question):
        return {**metadata, "status": "out_of_range", "message": "예보 없음. 과거 날짜는 조회하지 않습니다.", "dates": []}
    try:
        dates = resolve_relative_dates(question, checked_at.date())
    except (ValueError, OverflowError):
        return {**metadata, "status": "out_of_range", "message": "예보 없음. 올바른 날짜를 알려 주세요.", "dates": []}
    if not dates:
        return {**metadata, "status": "date_required", "message": "어느 날짜의 날씨를 확인할까요? 예: 내일, 모레, 이번 주말.", "dates": []}
    if min(dates) < checked_at.date() or max(dates) > checked_at.date() + timedelta(days=15):
        return {**metadata, "status": "out_of_range", "message": "예보 없음. 오늘부터 16일 예보 범위를 벗어난 날짜는 조회할 수 없습니다.", "dates": dates}
    return {**metadata, "status": "ready", "dates": dates}


def valid_coordinates(place):
    try:
        longitude, latitude = float(place["x"]), float(place["y"])
        return math.isfinite(longitude) and math.isfinite(latitude) and -180 <= longitude <= 180 and -90 <= latitude <= 90
    except (KeyError, TypeError, ValueError):
        return False


@observed("open_meteo_forecast", run_type="tool")
def fetch_forecast(place: dict, dates: list[date]) -> dict:
    metadata = {"source": SOURCE, "source_url": ENDPOINT, "retrieved_at": now_kst().isoformat(timespec="seconds"), "timezone": "Asia/Seoul"}
    if not valid_coordinates(place):
        return {**metadata, "status": "invalid_coordinates", "message": "장소 검색 결과의 좌표를 확인하지 못해 날씨를 조회할 수 없습니다.", "days": []}
    today = now_kst().date()
    if not dates or min(dates) < today or max(dates) > today + timedelta(days=15):
        return {**metadata, "status": "out_of_range", "message": "예보 없음. 과거 날짜 또는 예보 범위를 벗어난 날짜입니다.", "days": []}
    params = {
        "latitude": float(place["y"]), "longitude": float(place["x"]),
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
        "temperature_unit": "celsius", "timezone": "Asia/Seoul",
        "start_date": min(dates).isoformat(), "end_date": max(dates).isoformat(),
    }
    try:
        response = httpx.get(ENDPOINT, params=params, timeout=15, follow_redirects=False)
        response.raise_for_status()
        daily = response.json()["daily"]
        wanted = {day.isoformat() for day in dates}
        rows = []
        for index, day in enumerate(daily["time"]):
            if day not in wanted:
                continue
            def value(field):
                values = daily.get(field, [])
                number = values[index] if index < len(values) else None
                return number if isinstance(number, (int, float)) and not isinstance(number, bool) and math.isfinite(number) else None
            probability = value("precipitation_probability_max")
            rows.append({"date": day, "max_c": value("temperature_2m_max"), "min_c": value("temperature_2m_min"), "precipitation_probability": probability if probability is not None and 0 <= probability <= 100 else None, "weather_code": value("weather_code")})
        for day in sorted(wanted - {row["date"] for row in rows}):
            rows.append({"date": day, "max_c": None, "min_c": None, "precipitation_probability": None})
        rows.sort(key=lambda row: row["date"])
        for row in rows:
            row["status"] = "out_of_range" if all(row[key] is None for key in ("max_c", "min_c", "precipitation_probability")) else "ok"
        if not any(row["status"] == "ok" for row in rows):
            return {**metadata, "status": "out_of_range", "message": "예보 없음. 요청한 날짜의 예보 자료가 없습니다.", "days": rows}
        return {**metadata, "status": "partial" if any(row["status"] != "ok" for row in rows) else "ok", "days": rows, "coordinates": {"x": place["x"], "y": place["y"]}, "place": {key: place.get(key, "") for key in ("name", "address", "map_url")}}
    except Exception:
        return {**metadata, "status": "unavailable", "message": "날씨 조회에 실패했습니다. 잠시 후 다시 시도해 주세요.", "days": []}


def render_forecast(result):
    if result["status"] not in {"ok", "partial"}:
        return result["message"]
    place = result["place"]
    label = escape(place["name"], quote=False).replace("|", "\\|")
    rows = [f'**{label} 기준 날씨 예보**', "", "| 날짜(요일) | 최고 · 최저 °C | 강수확률 % |", "| --- | --- | --- |"]
    def number(value):
        return f"{value:g}" if value is not None else "정보 없음"
    for day in result["days"]:
        parsed = date.fromisoformat(day["date"])
        if day.get("status") == "out_of_range":
            rows.append(f'| {parsed:%Y.%m.%d}({WEEKDAYS[parsed.weekday()]}) | 예보 없음 | 예보 없음 |')
        else:
            rows.append(f'| {parsed:%Y.%m.%d}({WEEKDAYS[parsed.weekday()]}) | {number(day["max_c"])} · {number(day["min_c"])} | {number(day["precipitation_probability"])} |')
    rows += ["", "강수확률은 해당 날짜의 시간대별 강수확률 중 최댓값입니다. 예보는 달라질 수 있습니다.", "", "출처: [Open-Meteo](https://open-meteo.com/) · 상대 날짜 기준: 한국 시간"]
    return "\n".join(rows)
