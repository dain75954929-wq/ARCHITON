# ARCHITON Frontend-Backend 연동 규격서

## 1. 문서 목적

이 문서는 ARCHITON 서비스에서 frontend와 backend가 동일한 데이터 구조와 변수명을 사용해 원활히 연동되도록 계약을 정의한다.

본 문서는 아래 문서를 기반으로 작성한다.
- ARCHITON/spec_refined.md
- ARCHITON/2. analysis/analysis_method.md
- ARCHITON/3. in_out/frontend.md

핵심 원칙:
1. frontend는 화면/입력/피드백 수집을 담당한다.
2. backend는 벡터DB 조회, 취향 분석, 추천, 리포트 생성을 담당한다.
3. 취향 가중치, 선호 벡터 계산 로직은 backend를 단일 진실 소스로 사용한다.

---

## 2. 연동 범위

### 2.1 포함 범위
1. 계정 생성 및 로그인
2. 신규 프로젝트 생성
3. 기존 프로젝트 업데이트
4. 이미지 필터링 요청/응답
5. 취향 분석 세션 시작/진행/완료
6. 스와이프 이벤트 전송
7. 분석 완료 후 최종 추천 및 리포트 수신

### 2.2 제외 범위
1. frontend 자체 가중치 계산
2. frontend 자체 선호 벡터 계산
3. 데이터베이스 직접 접근

---

## 3. 공통 엔티티 및 변수명 통일

### 3.1 기본 엔티티
1. user_id: 사용자 식별자
2. project_id: 프로젝트 식별자
3. session_id: 분석 세션 식별자
4. image_id: 이미지 식별자 (기존 frontend building_id와 동일 개념)
5. action: like 또는 dislike

### 3.2 frontend 필드 매핑 규칙

기존 frontend Buildings 구조는 벡터DB 축에 맞춰 아래처럼 매핑한다.

1. building_id -> image_id
2. building_name 또는 title -> image_title
3. architects -> axis_architects
4. typology -> axis_typology
5. country -> axis_country
6. area_m2 -> axis_area_m2
7. capacity -> axis_capacity
8. imageUrl -> image_url
9. url -> source_url
10. tags -> axis_tags

원칙:
1. frontend에서 가공 필드 생성 시에도 위 공통 이름을 우선 사용한다.
2. backend 응답 필드명과 frontend 상태 필드명을 동일하게 유지한다.

### 3.3 분석 파라미터 공통 변수

모든 파라미터는 backend가 소유하며, frontend는 요청 시 옵션으로 전달 가능하다.

1. initial_image_id (기본 1)
2. initial_diverse_count (기본 14)
3. total_rounds (기본 100)
4. like_weight (기본 1.0)
5. dislike_weight (기본 -0.6)
6. epsilon (기본 0.18)
7. epsilon_min (기본 0.05)
8. epsilon_decay (기본 0.995)
9. distance_metric (cosine 또는 euclidean)
10. final_recommendation_count (기본 20)
11. report_keyword_count (기본 5)

---

## 4. 화면 흐름별 API 계약

## 4.1 로그인

요청
- endpoint: POST /api/auth/login
- body
  - user_id
  - password

응답
- success
- user_id
- is_new

## 4.2 프로젝트 선택

요청
- endpoint: POST /api/projects/select-mode
- body
  - user_id
  - mode: new 또는 update
  - project_id (update일 때 필수)

응답
- project_state
- allowed_actions

## 4.3 신규 프로젝트 생성

요청
- endpoint: POST /api/projects
- body
  - user_id
  - project_name
  - filters
    - typologies
    - min_area
    - max_area
    - countries
    - scale

응답
- project_id
- normalized_filters

## 4.4 기존 프로젝트 업데이트

요청
- endpoint: PATCH /api/projects/{project_id}
- body
  - user_id
  - filter_mode: keep 또는 modify
  - filters (modify일 때만)

응답
- project_id
- applied_filters
- filter_mode

## 4.5 분석 세션 시작

요청
- endpoint: POST /api/analysis/sessions
- body
  - user_id
  - project_id
  - is_new_project
  - filter_mode
  - analysis_options
    - initial_image_id
    - initial_diverse_count
    - total_rounds
    - distance_metric

응답
- session_id
- total_rounds
- next_image
  - image_id
  - image_url
  - image_title
  - metadata
- progress

동작 규칙
1. 신규 프로젝트는 필터 결과 집합에서 초기 탐색 세트 구성 후 next_image 반환
2. 기존 프로젝트는 이전 분석의 추천 집합을 우선 후보로 사용
3. 이미 피드백한 image_id는 재노출 금지

## 4.6 스와이프 피드백 전송

요청
- endpoint: POST /api/analysis/sessions/{session_id}/swipes
- body
  - user_id
  - project_id
  - image_id
  - action: like 또는 dislike
  - exposed_image_ids
  - swiped_image_ids
  - timestamp

응답
- accepted
- progress
  - current_round
  - total_rounds
  - like_count
  - dislike_count
- next_image
  - image_id
  - image_url
  - image_title
  - metadata
- is_analysis_completed

중요 규칙
1. backend는 swiped_image_ids를 기준으로 스와이프 완료 이미지 상태를 저장/업데이트한다.
2. frontend는 backend가 내려준 next_image를 그대로 표시한다.
3. frontend 내 가중치, 선호 벡터 계산은 사용하지 않는다.

## 4.7 분석 완료 결과 조회

요청
- endpoint: GET /api/analysis/sessions/{session_id}/result
- query
  - user_id
  - project_id

응답
- liked_images
  - 사용자가 like한 이미지 목록
- predicted_like_images
  - 사용자가 좋아할 것으로 예상되는 이미지 목록
  - 반드시 미피드백 이미지 집합에서만 선택
  - 최대 final_recommendation_count, 부족하면 가능한 최대 개수
- analysis_report
  - dominant_axes
  - keywords
  - keyword_count
  - summary_text

---

## 5. 데이터 형식 표준

### 5.1 공통 요청/응답 헤더

1. Content-Type: application/json
2. X-Request-Id: 추적용 요청 아이디
3. Authorization: 인증 토큰(도입 시)

### 5.2 에러 응답 표준

모든 에러는 아래 형식을 사용한다.
1. error_code
2. message
3. details
4. request_id

예시 코드
1. INVALID_INPUT
2. UNAUTHORIZED
3. NOT_FOUND
4. CONFLICT
5. ANALYSIS_STATE_ERROR
6. INTERNAL_ERROR

### 5.3 시간 형식

1. timestamp는 ISO-8601 UTC 문자열 사용
2. backend 저장은 UTC 기준

---

## 6. 중복 방지 및 상태 동기화 규칙

1. frontend는 세션 기준으로 exposed_image_ids를 관리한다.
2. backend는 서버 상태 기준으로 중복 노출 여부를 최종 판정한다.
3. 중복 판정 기준은 image_id 단위다.
4. 재요청/네트워크 재시도 시 동일 swipe 이벤트 중복 저장을 막기 위해 event_id(선택)를 사용한다.

권장 추가 필드
1. swipe_event_id
2. client_sent_at
3. idempotency_key

---

## 7. 필터링 및 후보군 생성 규칙

1. 신규 프로젝트
- 사용자 입력 필터를 먼저 적용
- 필터링된 집합 내에서 분석 로직 수행

2. 기존 프로젝트 업데이트
- keep: 이전 필터 유지 후 바로 분석 단계 진행
- modify: 기존 필터 값을 로드해 수정 후 재적용

3. 기존 프로젝트의 추가 분석
- 이전 분석에서 제안된 이미지 우선 반영
- 이전 피드백 이미지 재노출 금지

---

## 8. frontend 출력 의무 항목

분석 중간 과정에서 backend가 반드시 내려줘야 하는 항목
1. next_image

분석 완료 후 backend가 반드시 내려줘야 하는 항목
1. liked_images
2. predicted_like_images
3. analysis_report

frontend는 위 항목을 사용자 화면에 그대로 반영한다.

---

## 9. backend 출력 의무 항목

1. 상태값
- session_status
- progress
- is_analysis_completed

2. 추천 관련
- next_image
- predicted_like_images

3. 리포트 관련
- dominant_axes
- keywords
- summary_text

---

## 10. 버전 관리 정책

1. API 버전 prefix 사용: /api/v1
2. 필드 추가는 하위 호환 방식으로만 진행
3. 필드 삭제/이름 변경은 버전 업 후 진행

---

## 11. 최소 통합 테스트 체크리스트

1. 로그인 성공/실패 케이스
2. 신규 프로젝트 생성 후 분석 시작
3. 기존 프로젝트 keep/modify 분기 동작
4. 스와이프 전송 후 next_image 정상 갱신
5. 세션 중 중복 이미지 미노출
6. 분석 완료 후 liked_images 반환
7. predicted_like_images 최대 N개 반환 (기본 20)
8. 추천 후보 부족 시 가능한 최대 개수 반환
9. 리포트 keywords 최대 M개 반환 (기본 5)
10. 키워드 부족 시 가능한 최대 개수 반환

---

## 12. 결론

frontend와 backend의 안정적 연동을 위해서는

1. image_id 중심의 공통 식별자 사용
2. backend 단일 분석 로직 사용
3. 분석 중간/완료 출력 항목의 명확한 계약
4. 변수화된 파라미터의 명시적 전달

이 필수다.

본 규격을 기준으로 구현하면 신규 프로젝트 분석과 기존 프로젝트 업데이트 분석 모두에서 일관된 사용자 경험과 운영 안정성을 확보할 수 있다.
