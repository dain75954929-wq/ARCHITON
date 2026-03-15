# Django API Migration Map

## 목적

현재 레거시 API를 Django REST Framework API로 어떤 순서로 옮길지 정의한다.

레거시 계약 기준 문서:

- [3. in_out/api_contract.md](3.%20in_out/api_contract.md)

## 1차 전환 대상

### Login

레거시:

- `POST /api/auth/login`
- `POST /api/v1/auth/login`

신규 Django 제안:

- `POST /api/auth/login/`

전환 이유:

- 사용자 관리는 가장 먼저 Django로 옮겨야 한다.
- 현재 평문 비밀번호 저장 구조를 제거할 수 있다.

## 2차 전환 대상

### Start Session

레거시:

- `POST /api/v1/analysis/sessions`

신규 Django 제안:

- `POST /api/analysis/sessions/`

전환 방식:

- request/response shape 는 기존 계약과 최대한 동일하게 유지
- 내부에서는 `AnalysisSession` 생성 후 레거시 분석 엔진 호출

## 3차 전환 대상

### Submit Swipe

레거시:

- `POST /api/v1/analysis/sessions/{session_id}/swipes`

신규 Django 제안:

- `POST /api/analysis/sessions/{session_id}/swipes/`

전환 방식:

- `SwipeEvent` 저장
- `idempotency_key` 기준 중복 차단
- 추천 계산은 레거시 엔진 호출

## 4차 전환 대상

### Result

레거시:

- `GET /api/v1/analysis/sessions/{session_id}/result`
- `POST /api/v1/analysis/sessions/{session_id}/result`

신규 Django 제안:

- `GET /api/analysis/sessions/{session_id}/result/`

전환 메모:

- 신규 API는 `GET` 하나로 고정하는 편이 낫다.
- 결과 생성 시 세션 종료 부작용이 있다면 명시적으로 문서화해야 한다.

## 5차 전환 대상

### Debug

레거시:

- `GET /api/v1/analysis/sessions/{session_id}/debug`

신규 Django 제안:

- `GET /api/analysis/sessions/{session_id}/debug/`

전환 메모:

- 운영 환경에서는 staff 권한으로 제한하는 것이 맞다.

## URL 설계 원칙

1. 새 Django API는 끝에 슬래시를 붙인다.
2. 프론트 호환이 필요하면 transition 기간 동안 레거시 경로 alias 를 둔다.
3. 응답 필드명은 기존 프론트 계약과 최대한 맞춘다.

## 실제 시작점

지금 생성된 최소 엔드포인트:

- [backend/apps/recommendation/urls.py](backend/apps/recommendation/urls.py)

지금 가능한 확인용 경로:

- `GET /api/health/`
- `GET /api/migration-status/`