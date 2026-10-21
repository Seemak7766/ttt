# GitHub 업로드용 파일 모음

이 폴더의 **내용물**을 GitHub 저장소 루트에 올리세요. 실제 원격 업로드는 수행하지 않았습니다.

## 제외한 항목

- `.env` 및 실제 인증 정보: OpenAI·Kakao·LangSmith API 키 보호
- `.venv/`: 로컬 가상환경 (requirements.txt로 새로 설치)
- `data/`, 데이터베이스: 대화·개인 데이터
- `*.log`, `__pycache__/`, `*.pyc`: 실행 로그와 생성 캐시
- `.streamlit/secrets.toml`, `.git/`: 배포 비밀 설정과 기존 Git 이력
- `server.py`, `tests/test_server.py`, `static/index.html`, `static/app.js`, `static/style.css`: 현재 Streamlit 앱이 사용하지 않는 이전 구현

`.env.example`에는 변수 이름만 포함되어 있습니다. 실행할 환경에서 본인의 `.env` 또는 배포 플랫폼의 비밀 설정을 따로 작성하세요. `.streamlit/config.toml`은 공개 가능한 색상·테마 설정이므로 포함했습니다.

## 포함 파일

- `.env.example`
- `.gitignore`
- `.python-version`
- `.streamlit/config.toml`
- `app.py`
- `chatbot.py`
- `config.py`
- `IPO.md`
- `kakao_places.py`
- `LANGSMITH_SETUP.md`
- `observability.py`
- `place_map.py`
- `plan_actions.py`
- `plan_state.py`
- `plan_view.py`
- `prompts/travel_system.md`
- `README.md`
- `requirements.txt`
- `start_chatbot.ps1`
- `static/keyboard_shortcuts.html`
- `static/travel_theme.css`
- `tests/test_agent_runs.py`
- `tests/test_chatbot.py`
- `tests/test_kakao_places.py`
- `tests/test_observability.py`
- `tests/test_place_map.py`
- `tests/test_plan_state.py`
- `tests/test_plan_view.py`
- `tests/test_travel_cost.py`
- `tests/test_travel_plan.py`
- `tests/test_weather.py`
- `travel_cost.py`
- `travel_plan.py`
- `verify_langsmith.py`
- `weather_agent.py`
- `weather_forecast.py`
