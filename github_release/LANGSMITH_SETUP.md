# LangSmith 연결

기존 `.env`의 OpenAI·Kakao 설정은 유지하고 아래 항목을 추가하세요.

```dotenv
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=발급받은_LangSmith_API_키
LANGSMITH_PROJECT=travel-chatbot
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_WORKSPACE_ID=
```

- API 키는 OpenAI 키와 별개입니다. 코드나 채팅에 키를 넣지 마세요.
- ENDPOINT 예시는 기본 US 리전입니다. EU는 `https://eu.api.smith.langchain.com`, 그 밖의 리전은 계정의 공식 연결 안내 주소를 사용하세요. 리전이 다르면 인증이 실패할 수 있습니다.
- 여러 워크스페이스에 연결된 키는 WORKSPACE_ID도 입력하세요. 그 외에는 비워 둘 수 있습니다.
- PROJECT는 사용할 프로젝트 이름입니다. 기존 프로젝트의 쓰기 권한이나 새 프로젝트 생성 권한이 필요합니다.
- 활성화하면 질문·대화·모델 응답·도구 입출력·실행 시간이 지정 프로젝트에 전송됩니다. API 키 인자와 환경의 OpenAI/Kakao/LangSmith 키 문자열은 마스킹합니다.
- 중지하려면 `LANGSMITH_TRACING=false`로 바꾸세요. 키가 없어도 앱에서 추가한 추적은 비활성화됩니다.

## 설치 및 연결 점검

작업 폴더의 PowerShell에서 실행합니다.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe verify_langsmith.py
```

점검 스크립트는 OpenAI·카카오를 호출하지 않고 `travel_chatbot_connection_test`라는 작은 테스트 기록을 전송한 뒤 조회합니다. 성공하면 run_id를 출력하며, 키와 원본 오류 문자열은 출력하지 않습니다. 쓰기 전용 키는 기록 전송 후 조회 단계가 실패할 수 있으므로 이 경우 대시보드에서 직접 확인하세요.

## 앱에서 확인

기존 서버를 중지하고 다시 실행합니다.

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

`내일 서울 날씨와 장소 추천해줘`라고 질문한 뒤 LangSmith에서 `travel-chatbot` 프로젝트를 열어 확인하세요.

| 실행 이름 | 내용 |
| --- | --- |
| travel_chatbot_request | 질문 처리 전체와 하위 ChatOpenAI 호출 |
| search_kakao_places | 카카오 장소 검색 인자·결과 |
| open_meteo_forecast | 날짜·좌표와 날씨 조회 결과 |
| build_travel_plan | 계획 생성과 후보 추가 검색 |
| update_travel_plan | 재검색 없는 조건 수정 |
| summarize_conversation | 대화 제목 요약 |

날씨·장소 병행 작업에도 추적 컨텍스트를 전달해 같은 질문의 하위 실행으로 연결합니다. 추적 설정 오류가 있어도 질문을 중복 실행하지 않습니다. 업로드 성공은 앱 응답이 아닌 점검 스크립트나 대시보드에서 확인하세요.

## 참고

- [LangChain 애플리케이션 추적](https://docs.langchain.com/langsmith/trace-with-langchain)
- [tracing_context와 사용자 지정 클라이언트](https://docs.langchain.com/langsmith/trace-without-env-vars)
