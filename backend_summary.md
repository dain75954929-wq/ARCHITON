# 백엔드 구조 요약

기준 코드:

- `backend/config/urls.py`
- `backend/apps/accounts/views.py`
- `backend/apps/recommendation/models.py`
- `backend/apps/recommendation/views.py`
- `backend/apps/recommendation/urls.py`
- `backend/apps/recommendation/legacy_bridge.py`
- `backend/apps/recommendation/services.py`

이 문서는 현재 ARCHITON 백엔드가 어떤 구조로 돌아가는지, 어떤 책임이 어디에 배치되어 있는지, 그리고 프론트 요청이 어떤 흐름으로 처리되는지를 요약한 문서다.

## 1. 전체 구조

현재 백엔드는 Django 기반으로 구성되어 있고, URL 진입점은 매우 단순하다.

`backend/config/urls.py` 기준으로 API는 크게 두 축으로 나뉜다.

- `apps.accounts`: 로그인 및 현재 사용자 확인
- `apps.recommendation`: 프로젝트, 분석 세션, 추천 이미지, 리포트

즉, 현재 백엔드는 "인증 레이어 + 추천/분석 레이어"의 2단 구조라고 보면 된다.

## 2. 백엔드의 핵심 역할

이 백엔드는 단순 CRUD 서버가 아니라, 아래 4가지 역할을 동시에 담당한다.

1. 사용자 세션 로그인 처리
2. 프로젝트 상태 저장
3. 벡터 기반 취향 분석 및 배치 추천 오케스트레이션
4. 최종 취향 리포트 생성

## 3. 앱별 역할

## 3-1. accounts 앱

주요 파일:

- `backend/apps/accounts/views.py`

역할:

- Django 인증 시스템을 이용해 로그인 처리
- 세션 쿠키 기반 인증 상태 유지
- 현재 로그인 사용자 정보 반환

핵심 엔드포인트:

- `POST /api/auth/login/`
- `POST /api/v1/auth/login/`
- `GET /api/auth/me/`

동작 요약:

- 프론트가 `id` 또는 `user_id` 또는 `username`과 `password`를 보낸다.
- `authenticate()`로 사용자 검증을 수행한다.
- 성공하면 `login()`으로 Django 세션을 생성한다.
- 이후 recommendation API는 이 세션을 기반으로 현재 사용자를 식별한다.

즉, 현재 인증 구조의 중심은 JWT가 아니라 Django 세션 로그인이다.

## 3-2. recommendation 앱

주요 파일:

- `backend/apps/recommendation/models.py`
- `backend/apps/recommendation/views.py`
- `backend/apps/recommendation/urls.py`
- `backend/apps/recommendation/legacy_bridge.py`
- `backend/apps/recommendation/services.py`

역할:

- 프로젝트 생성 및 조회
- 다양한 초기 탐색 이미지 제공
- 분석 세션 시작
- 배치 피드백 누적 및 수렴 계산
- 최종 취향 리포트 생성 및 조회

## 4. 데이터 모델 구조

핵심 모델은 4개다.

### 4-1. Project

프로젝트 단위의 누적 상태를 저장한다.

중요 필드:

- `project_id`
- `user`
- `name`
- `description`
- `liked_building_ids`
- `hated_building_ids`
- `analysis_report`
- `predicted_building_ids`
- `last_report_created_at`
- `latest_convergence`
- `latest_feedback_summary`
- `status`
- `final_report`

의미:

- 유저가 어떤 건축물을 좋아하고 싫어했는지 누적 기록
- 현재 프로젝트 분석이 어느 단계인지 저장
- 최종 리포트를 JSON과 문자열 형태로 모두 저장

즉, `Project`는 프론트가 보는 장기 상태의 중심 객체다.

### 4-2. PreferenceBatchSession

실시간 분석 세션 상태를 저장한다.

중요 필드:

- `session_id`
- `project`
- `status`
- `batch_size`
- `batch_index`
- `swipe_count`
- `seed_image_ids`
- `liked_image_ids`
- `disliked_image_ids`
- `shown_image_ids`
- `current_batch_ids`
- `preference_vector`
- `prev_preference_vector`
- `baseline_similarity`
- `pref_change`
- `stability_score`
- `coherence_score`
- `recent_coherence_score`
- `top_k_density_score`
- `convergence_score`
- `is_converged`

의미:

- 현재 세션에서 사용자가 어떤 이미지를 보고 어떤 반응을 했는지 저장
- preference vector가 얼마나 안정화되었는지 계산값 보관
- 다음 배치 5장을 만들지, 최종 추천으로 넘어갈지 결정하는 상태 저장

즉, `PreferenceBatchSession`은 실시간 취향 수렴 로직의 작업 메모리다.

### 4-3. AnalysisSession

기존 legacy 분석 엔진과 연결되는 세션 상태를 저장한다.

주요 역할:

- Django 세션과 legacy 분석 세션 id 연결
- 전체 라운드 수 및 완료 여부 저장

이 모델은 배치 피드백 중심 구조와 함께 legacy 호환을 위해 유지되는 브리지 성격이 강하다.

### 4-4. SwipeEvent

사용자 스와이프 이벤트를 기록한다.

주요 역할:

- 어떤 세션에서 어떤 이미지에 like/dislike를 했는지 저장
- idempotency key 기반 중복 처리 방지 기반 제공

## 5. 인증 방식과 API 보호 방식

현재 recommendation API는 `CsrfExemptSessionAuthentication`을 사용한다.

의미:

- 기본 기반은 Django SessionAuthentication
- 하지만 API POST 호출에서 CSRF 검사를 강제로 통과시키지 않도록 완화

이 구조가 필요한 이유는 프론트가 세션 쿠키 기반으로 로그인한 뒤, SPA 방식으로 API를 호출하기 때문이다.

즉, 보호 전략은 아래처럼 정리된다.

- 로그인 자체는 Django 세션 생성
- 보호된 API는 세션에 의존
- API 호출은 CSRF-exempt session auth로 처리

## 6. 주요 API 구성

`backend/apps/recommendation/urls.py` 기준 주요 API는 다음과 같다.

### 상태 확인

- `GET /api/health/`
- `GET /api/migration-status/`

### 탐색 이미지

- `GET /api/images/diverse-random/`
- `GET /api/v1/images/diverse-random`

역할:

- 초기 선택을 위한 서로 멀리 떨어진 다양한 건축 이미지 카드 제공

### 프로젝트

- `GET /api/projects/`
- `POST /api/projects/`
- `GET /api/projects/{project_id}/`
- `GET /api/v1/projects`
- `POST /api/v1/projects`
- `GET /api/v1/projects/{project_id}`

역할:

- 프로젝트 생성
- 현재 로그인 유저의 프로젝트 목록 조회
- 특정 프로젝트 상세 조회

### 분석 세션

- `POST /api/v1/analysis/sessions`
- `POST /api/v1/analysis/sessions/{session_id}/feedback-batch`

역할:

- seed 이미지 기반 분석 시작
- 5장 단위 batch 피드백 반영
- convergence 계산 갱신
- 수렴 시 최종 추천 반환

### 리포트

- `GET /api/v1/projects/{project_id}/report`
- `POST /api/v1/projects/{project_id}/report/generate`

역할:

- 이미 생성된 취향 리포트 조회
- Gemini 기반 종합 리포트 생성 및 저장

## 7. View 계층의 실제 책임

`backend/apps/recommendation/views.py`의 책임은 생각보다 명확하다.

### 7-1. 입력 검증

예:

- 로그인 여부 확인
- `project_id` 존재 여부 확인
- `selected_image_ids`, `selected_images`, `rejected_image_ids` 타입 확인
- 프로젝트 소유권 확인

즉, view는 요청을 바로 계산에 넘기지 않고 최소한의 계약 검증을 수행한다.

### 7-2. 직렬화

예:

- `serialize_project()`
- `serialize_project_report()`

즉, 모델 인스턴스를 프론트가 바로 쓸 수 있는 JSON 형태로 바꾸는 역할을 view가 맡고 있다.

### 7-3. 서비스/브리지 호출

예:

- 리포트 생성은 `generate_report(project)` 호출
- 배치 추천은 `start_preference_batch_session()` 호출
- 배치 피드백은 `apply_feedback_batch()` 호출
- diverse random 이미지는 `get_diverse_random_cards()` 호출

즉, view는 계산 로직을 직접 들고 있기보다 오케스트레이션 계층에 가깝다.

## 8. legacy_bridge의 역할

`backend/apps/recommendation/legacy_bridge.py`는 현재 백엔드에서 가장 중요한 연결층이다.

이 파일은 Django와 기존 `2. analysis` 코드 사이를 연결한다.

핵심 역할:

- 기존 `AnalysisService`를 lazy singleton으로 로드
- 벡터 연산 유틸 함수 제공
- Project 누적 선호 상태 갱신
- PreferenceBatchSession 상태 갱신
- convergence 계산
- 다음 batch 카드 생성
- legacy analysis 엔진과 현재 Django 모델을 연결

즉, 이 파일은 단순 helper가 아니라 현재 추천 시스템의 핵심 오케스트레이터다.

## 9. 분석 알고리즘 처리 방식

분석 세션이 시작되면 대략 아래 순서로 처리된다.

1. 사용자가 초기 seed 이미지를 선택한다.
2. 해당 이미지 id가 프로젝트의 `liked_building_ids`에 반영된다.
3. seed / like / dislike 임베딩을 기준으로 `preference_vector`를 만든다.
4. 전체 벡터 DB 기준 baseline similarity를 계산한다.
5. coherence, recent coherence, density, stability를 계산한다.
6. 이 점수들을 조합해 `convergence_score`를 계산한다.
7. 아직 active 상태이면 다음 5개 이미지를 추천한다.
8. 충분히 수렴하면 세션 상태를 converged로 바꾸고 final recommendations를 반환한다.

즉, 현재 추천은 단순 nearest neighbor 한 번이 아니라, 사용자 반응을 통해 preference vector를 점차 안정화시키는 구조다.

## 10. 리포트 생성 구조

`backend/apps/recommendation/services.py`는 최종 취향 리포트 생성을 담당한다.

흐름은 다음과 같다.

1. `Project.liked_building_ids`를 읽는다.
2. id 목록을 정규화한다.
3. PostgreSQL의 `architecture_vectors`에서 직접 해당 건축물 행을 조회한다.
4. `program`, `mood`, `material`, `country`, `architect`, `year`를 집계한다.
5. 이 집계 결과를 Gemini 프롬프트에 넣는다.
6. Gemini가 `title`, `description`을 JSON으로 생성한다.
7. 필요 시 persona image도 생성한다.
8. 결과를 `project.analysis_report`, `project.final_report`, `project.last_report_created_at`, `project.status`에 저장한다.

중요한 점은 이 서비스가 더 이상 로컬 JSON 파일을 읽지 않는다는 것이다.

지금은 실제 운영 데이터 소스인 `architecture_vectors`를 직접 조회한다.

## 11. 벡터 DB와 백엔드의 연결 방식

현재 backend는 자체적으로 벡터를 생성하지 않는다.

벡터 생성은 `1. into_database/into_database.py`가 담당하고, backend는 이미 만들어진 `architecture_vectors`를 활용한다.

즉 역할 분리는 아래와 같다.

- 데이터 적재와 임베딩 생성: `into_database.py`
- 실시간 추천 계산과 리포트 생성: Django backend

이 분리는 운영상 꽤 중요하다.

이유:

- 적재 파이프라인과 서빙 파이프라인이 분리됨
- 추천 API는 빠르게 응답하고, 무거운 재적재 작업은 별도 실행 가능
- report 생성도 같은 `architecture_vectors`를 기준으로 일관되게 동작함

## 12. 현재 백엔드의 성격을 한 문장으로 정리하면

현재 ARCHITON 백엔드는 Django 세션 인증 위에 프로젝트 상태 저장, 벡터 기반 취향 수렴 분석, 그리고 Gemini 기반 종합 리포트 생성을 얹은 하이브리드 추천 백엔드다.

## 13. 핵심 읽기 순서 추천

처음 보는 사람이 읽기 좋은 순서는 아래와 같다.

1. `backend/config/urls.py`
2. `backend/apps/accounts/views.py`
3. `backend/apps/recommendation/urls.py`
4. `backend/apps/recommendation/views.py`
5. `backend/apps/recommendation/models.py`
6. `backend/apps/recommendation/legacy_bridge.py`
7. `backend/apps/recommendation/services.py`

이 순서로 보면 "요청이 어디로 들어와서, 어떤 상태를 읽고, 어떤 계산을 거쳐, 무엇을 저장하는지"가 가장 빨리 잡힌다.
