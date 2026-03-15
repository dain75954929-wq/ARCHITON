# Django Target Models

## 목적

병행 전환에서 먼저 옮길 모델의 최소 집합을 정의한다.

## 1. User

기본 사용자 모델은 Django 내장 `auth.User` 를 그대로 사용한다.

이유:

- 관리자 페이지와 인증 흐름을 바로 쓸 수 있다.
- 지금 단계에서 커스텀 유저 모델까지 들어가면 초기 전환 비용이 커진다.

## 2. UserProfile

구현 위치: [backend/apps/accounts/models.py](backend/apps/accounts/models.py)

필드:

- `user`: Django User 와 1:1 연결
- `display_name`: 프론트 표기 이름
- `preference_summary`: 요약된 취향 텍스트
- `created_at`, `updated_at`

역할:

- 장기 개인화 요약 저장
- 온보딩 상태와 사용자 표시 정보 저장

## 3. AnalysisSession

구현 위치: [backend/apps/recommendation/models.py](backend/apps/recommendation/models.py)

필드:

- `session_id`: 외부 노출용 UUID
- `user`: 세션 소유자
- `legacy_project_id`: 기존 프론트의 프로젝트 식별자
- `status`: `active`, `report_ready`, `completed`
- `total_rounds`, `current_round`
- `is_analysis_completed`
- `created_at`, `updated_at`

역할:

- 기존 메모리 세션 저장소 대체
- 세션 재개, 감사 추적, 운영 조회 기반 확보

## 4. SwipeEvent

구현 위치: [backend/apps/recommendation/models.py](backend/apps/recommendation/models.py)

필드:

- `session`: 소속 세션
- `image_id`: architecture_vectors.id
- `action`: `like` 또는 `dislike`
- `idempotency_key`: 중복 방지 키
- `created_at`

역할:

- 피드백 이벤트 영속화
- 중복 전송 방지
- 나중에 리포트/랭킹 학습 데이터로 재사용

## 다음 우선순위 모델

초기 3개 모델 다음에는 아래 순서를 권장한다.

1. `ProjectBoard`: 프론트의 폴더/프로젝트 개념 이관
2. `SavedRecommendation`: 결과 스냅샷 저장
3. `UserEmbeddingProfile`: 장기 개인화 벡터 캐시

## 레거시 매핑

- `user_credentials` → Django `User`
- `liked_projects` → `SwipeEvent` + 결과 스냅샷 모델 조합으로 분리
- 메모리 세션 딕셔너리 → `AnalysisSession`