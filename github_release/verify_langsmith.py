"""키를 출력하거나 OpenAI를 호출하지 않고 LangSmith 쓰기·조회 연결을 확인합니다."""
from time import sleep
from uuid import uuid4

from langsmith import traceable, tracing_context
from config import load_langsmith_settings
from observability import configured_client


def main():
    settings = load_langsmith_settings()
    if not settings["enabled"] or not settings["api_key"]:
        print(".env에 LANGSMITH_TRACING=true와 LANGSMITH_API_KEY를 설정해 주세요.")
        return 1
    run_id = uuid4()
    try:
        client = configured_client(settings)
        @traceable(name="travel_chatbot_connection_test", run_type="chain")
        def probe():
            return {"status": "ok", "message": "LangSmith connection test"}
        with tracing_context(enabled=True, client=client, project_name=settings["project"]):
            probe(langsmith_extra={"run_id": run_id})
        client.flush()
        for attempt in range(3):
            try:
                saved = client.read_run(run_id)
                if str(saved.id) == str(run_id):
                    print(f"연결 성공: 테스트 실행 저장·조회 확인 (run_id: {run_id})")
                    return 0
            except Exception:
                if attempt < 2:
                    sleep(1)
        print("테스트 실행을 조회하지 못했습니다. 프로젝트 권한·리전·API 키와 잠시 후 생성되는 실행 기록을 확인해 주세요.")
    except Exception:
        print("LangSmith 연결을 확인하지 못했습니다. API 키, 리전별 ENDPOINT, WORKSPACE_ID와 네트워크를 확인해 주세요.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
