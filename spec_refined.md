# ARCHITON_KMS Product Specification

## 1. 문서 목적

본 문서는 ARCHITON_KMS 서비스의 상위 제품/시스템 스펙이다.
하위 spec 문서들은 본 문서의 목표, 엔티티 정의, 상태 모델, 인터페이스 원칙을 기준으로 작성한다.

이 문서의 역할은 다음과 같다.

- 서비스의 목표와 범위를 명확히 정의한다.
- 오프라인 데이터 파이프라인과 온라인 추천/피드백 루프를 하나의 시스템으로 연결한다.
- 하위 spec 문서가 따라야 할 공통 계약을 정의한다.
- MVP와 이후 확장 범위를 구분한다.

---

## 2. 제품 목표

### 2.1 핵심 목표

ARCHITON_KMS는 사용자의 자연어 취향 입력과 이미지 기반 선호 피드백을 결합하여,
사용자의 취향에 맞는 건축 프로젝트 레퍼런스를 점점 더 정확하게 찾아주는 검색 서비스다.

### 2.2 서비스가 해결해야 하는 문제

기존 건축 레퍼런스 검색은 다음 한계가 있다.

- 사용자가 원하는 분위기나 재료감, 공간 감각을 자연어만으로 표현하기 어렵다.
- 프로젝트 단위 정보와 이미지 단위 정보가 분리되어 있지 않아 검색 정밀도가 낮다.
- 사용자의 반응이 다음 추천에 충분히 반영되지 않는다.
- 레퍼런스 사이트별 정보 포맷이 달라 중복과 정규화 문제가 크다.

### 2.3 성공 기준

MVP 기준 성공 조건은 다음과 같다.

- 사용자가 한 세션 안에서 유의미한 건축 레퍼런스 후보를 얻을 수 있어야 한다.
- 취향이 모호한 사용자도 swipe를 통해 점차 선호 축이 좁혀져야 한다.
- 최종 결과는 단순 카드 나열이 아니라, "왜 이 프로젝트들이 추천되었는지" 설명 가능해야 한다.
- 축적된 피드백은 추천 품질 개선에는 사용되되, 데이터베이스 수정은 별도 검증 절차를 거쳐야 한다.

### 2.4 비목표

MVP 범위에서 아래 항목은 제외한다.

- 범용 검색엔진 수준의 전체 웹 크롤링
- 완전 자동 데이터 수정 시스템
- 로그인/협업/공유 기능
- 생성형 이미지 제작 기능
- 법규 검토나 설계 판단 자동화

---

## 3. 현재 문서에서 확정해야 하는 핵심 원칙

### 3.1 검색 단위와 피드백 단위를 분리한다

서비스의 최종 추천 단위는 `project`다.
그러나 사용자가 즉시 반응하는 대상은 대부분 `image`다.
따라서 swipe 이벤트는 반드시 아래 두 레벨을 모두 기록해야 한다.

- project-level signal
- image-level signal

즉, 카드 1장은 `project`를 대표하지만, 실제 반응은 `page_image_id`와 함께 저장되어야 한다.
같은 프로젝트라도 어떤 이미지를 보여줬는지에 따라 반응이 달라질 수 있기 때문이다.

### 3.2 부정 피드백은 곧바로 데이터 오류로 간주하지 않는다

사용자의 `No`는 우선적으로 `현재 세션의 선호 불일치`로 해석한다.
곧바로 `라벨 오류`로 간주하면 안 된다.

예를 들어 사용자가 벽돌 프로젝트에 `No`를 눌렀다고 해서,
해당 프로젝트의 `벽돌` 라벨이 틀렸다고 결론내릴 수는 없다.
이유는 다음과 같다.

- 벽돌은 맞지만 색감이 싫을 수 있다.
- 벽돌은 맞지만 프로그램이나 스케일이 다를 수 있다.
- 해당 이미지는 벽돌이 잘 보이지 않는 컷일 수 있다.
- 사용자가 프로젝트 전체가 아니라 특정 이미지에만 부정 반응했을 수 있다.

따라서 데이터베이스 수정은 별도 정책을 따라야 한다.

### 3.3 오프라인 파이프라인과 온라인 추천 시스템을 분리한다

오프라인 파이프라인은 데이터 수집/정제/분석/인덱싱을 담당한다.
온라인 서비스는 세션 생성, 질의 해석, 카드 제공, swipe 반영, 리포트 생성을 담당한다.

이 둘은 같은 시스템이지만, 스펙과 책임 범위는 분리되어야 한다.

---

## 4. 서비스 범위

### 4.1 In Scope

- 건축 레퍼런스 사이트의 프로젝트 URL 수집
- 프로젝트 텍스트 정보 추출 및 정규화
- 이미지 URL 수집 및 이미지 자산 관리
- 프로젝트 중복 병합 및 canonical project 생성
- 이미지 분석 기반 시각 속성 추출
- 자연어 입력 기반 초기 선호 추정
- swipe 기반 실시간 선호 업데이트
- 프로젝트 추천 및 관련 프로젝트 보드 생성
- 세션 종료 후 요약 리포트 생성
- 피드백 로그 수집 및 리뷰 큐 운영

### 4.2 Out of Scope (MVP)

- 로그인 기반 개인화 장기 프로필
- 팀 보드/폴더/코멘트
- 사용자가 직접 이미지를 업로드하여 유사 프로젝트 검색
- 자동 번역 고도화
- 대규모 학습 기반 랭킹 모델 자동 배포

---

## 5. 주요 사용자 시나리오

### 5.1 Known Preference Mode

사용자가 어느 정도 원하는 취향을 언어로 설명할 수 있는 경우.

흐름:

1. 사용자가 자연어로 원하는 건축 레퍼런스를 입력한다.
2. 시스템이 입력을 구조화된 선호 조건으로 변환한다.
3. 부족한 정보가 있으면 clarification 질문을 한다.
4. 초기 후보 프로젝트/이미지 카드를 생성한다.
5. 사용자의 swipe 결과를 반영해 점차 후보를 좁힌다.
6. 최종 프로젝트 보드와 텍스트 리포트를 제공한다.

### 5.2 Unknown Preference Mode

사용자가 "내 취향을 잘 모르겠다"고 말하는 경우.

흐름:

1. 시스템은 탐색용 카드셋을 넓게 구성한다.
2. 초기 카드들은 서로 다른 속성 축을 의도적으로 분산 배치한다.
3. 사용자의 swipe 반응을 통해 선호 축을 추정한다.
4. 일정 신뢰도 이상이 되면 탐색보다 활용 중심으로 추천을 전환한다.
5. 최종 프로젝트 보드와 텍스트 리포트를 제공한다.

### 5.3 Clarification Mode

사용자 입력이 모호한 경우.

예시:

- "미니멀한데 따뜻한 느낌"
- "요즘 느낌 나는 전시 공간"
- "잘 모르겠는데 예쁜 거"

시스템은 바로 검색하지 않고 필요한 축을 1~3개 정도 질문한다.
질문은 검색 정밀도를 올리는 축만 다룬다.

예시 축:

- 프로그램/용도
- 실내 vs 외관
- 재료감
- 차분함 vs 강한 연출
- 지역/시대
- 소규모 vs 대규모

---

## 6. 시스템 아키텍처 개요

서비스는 크게 두 영역으로 구성된다.

### 6.1 Offline Data Pipeline

역할:

- source page 수집
- 텍스트 추출 및 정규화
- 이미지 수집 및 자산 저장
- 프로젝트 중복 병합
- 이미지 분석
- 검색/추천용 인덱스 생성

### 6.2 Online Recommendation Service

역할:

- 세션 생성
- 사용자 입력 해석
- 초기 후보 생성
- 카드 제공
- swipe 반영
- 선호 상태 업데이트
- 최종 리포트/추천 보드 생성

### 6.3 Admin / Review Layer

역할:

- low-confidence extraction 검토
- 중복 병합 검토
- 피드백 기반 라벨 수정 후보 검토
- taxonomy 관리
- 파이프라인 오류 모니터링

---

## 7. 핵심 엔티티

기존 `spec_image_analysis.md`의 오프라인 엔티티 정의는 유지한다.
상위 spec에서는 여기에 온라인 세션 엔티티를 추가한다.

### 7.1 Offline Canonical Data

- `projects`
- `source_pages`
- `project_fact_extractions`
- `project_fact_current`
- `image_assets`
- `page_images`
- `image_analysis_current`
- `image_drawing_attrs`
- `image_photo_rendering_attrs`
- `processing_runs`
- `review_queue`

### 7.2 Online Session Data

추가가 필요한 엔티티는 다음과 같다.

#### user_sessions

사용자 탐색 세션.

권장 컬럼:

- `session_id`
- `user_id` nullable
- `session_mode` (`known_preference`, `unknown_preference`, `clarification`)
- `status` (`created`, `active`, `report_ready`, `completed`, `abandoned`)
- `locale`
- `started_at`
- `ended_at`

#### session_inputs

세션 내 사용자 입력 로그.

권장 컬럼:

- `input_id`
- `session_id`
- `raw_text`
- `input_type` (`initial_query`, `clarification_answer`, `free_text_feedback`)
- `created_at`

#### session_preference_state

현재 세션에서 추정한 사용자 취향 상태.

권장 컬럼:

- `session_id`
- `structured_preferences_json`
- `visual_preferences_json`
- `blocked_preferences_json`
- `confidence_score`
- `updated_at`

#### session_candidates

한 세션 안에서 생성된 후보 카드/프로젝트.

권장 컬럼:

- `candidate_id`
- `session_id`
- `project_id`
- `page_image_id`
- `candidate_source` (`query_match`, `visual_similarity`, `exploration`, `related_project`)
- `candidate_features_json`
- `rank_score`
- `shown_order`
- `shown_at`

#### swipe_events

사용자 반응 로그.

권장 컬럼:

- `swipe_event_id`
- `session_id`
- `candidate_id`
- `project_id`
- `page_image_id`
- `action` (`yes`, `no`, `skip`, `super_yes` optional)
- `explicit_reason_tags_json` nullable
- `response_time_ms`
- `created_at`

#### session_reports

세션 종료 후 생성된 결과.

권장 컬럼:

- `report_id`
- `session_id`
- `summary_text`
- `inferred_tags_json`
- `top_project_ids_json`
- `related_project_ids_json`
- `created_at`

---

## 8. 상태 모델

### 8.1 Session State

`created` → `awaiting_input` → `clarifying` → `browsing` → `swiping` → `report_ready` → `completed`

예외 상태:

- `abandoned`
- `error`

### 8.2 Data Processing State

`queued` → `running` → `succeeded`

예외 상태:

- `failed`
- `review_required`
- `skipped`

### 8.3 Review State

`pending` → `in_review` → `resolved`

예외 상태:

- `dismissed`
- `requeued`

---

## 9. 검색 및 추천 구조

온라인 추천은 3단계로 나눈다.

### 9.1 Query Parsing

사용자 자연어를 아래 두 형태로 변환한다.

1. 구조화 조건
2. 임베딩/의미 벡터

구조화 조건 예시:

- program
- architect
- country/city
- year range
- scale
- material
- mood
- drawing/photo 선호

### 9.2 Candidate Generation

후보 생성은 복수 채널에서 수행한다.

#### Structured Recall

정규화된 데이터 컬럼 기반 필터링.

예시:

- `program = museum`
- `country = japan`
- `completion_year >= 2015`

#### Semantic Recall

프로젝트 설명, 페이지 텍스트, 캡션, 정리된 태그를 대상으로 의미 기반 검색.

#### Visual Recall

사용자가 `Yes`를 누른 이미지들과 유사한 이미지/프로젝트를 찾는다.

#### Exploration Recall

취향을 모르는 초기 세션에서는 서로 다른 속성 축을 가진 카드를 일부 섞는다.

### 9.3 Re-ranking

최종 카드 노출 순서는 아래 신호를 조합해 계산한다.

- query match score
- session preference match score
- liked image similarity score
- data confidence score
- diversity score
- duplicate penalty
- over-exposure penalty

초기 세션은 탐색 비율을 높이고,
후반 세션은 이미 반응이 좋았던 축에 가중치를 높인다.

---

## 10. 카드 설계 원칙

### 10.1 카드의 본질

카드는 `project recommendation unit`이지만,
실제 사용자 판단은 대체로 `image impression unit`이다.

따라서 카드에는 최소 아래 정보가 필요하다.

- 대표 이미지 1장
- 프로젝트 이름
- 핵심 태그 2~5개
- 필요 시 보조 썸네일 2~3개

### 10.2 왜 보조 썸네일이 필요한가

대표 이미지 1장만 보여주면 다음 문제가 생긴다.

- 프로젝트 전체보다 특정 컷에 대한 반응이 과도하게 반영된다.
- interior / exterior mismatch가 발생한다.
- drawing 프로젝트인데 photo를 기대한 사용자가 바로 이탈할 수 있다.

따라서 카드 설계는 아래 두 옵션 중 하나를 따라야 한다.

#### Option A: 단일 대표 이미지 카드

- 구현이 단순하다.
- 대신 swipe signal의 노이즈가 크다.

#### Option B: 대표 이미지 + 보조 썸네일 카드

- 구현 복잡도는 조금 높다.
- 하지만 project-level 판단 품질이 높다.

MVP에서는 Option B를 권장한다.

### 10.3 카드별 저장 원칙

카드 노출 시점에 아래 값을 함께 저장한다.

- `project_id`
- `page_image_id`
- `shown_order`
- `candidate_source`
- `rank_score`
- `session_preference_snapshot`

이 값이 있어야 추천 품질 회고와 디버깅이 가능하다.

---

## 11. 피드백 해석 정책

이 항목은 현재 상위 spec에 반드시 들어가야 한다.

### 11.1 기본 원칙

`No`는 우선적으로 아래 중 하나로 해석한다.

- 현재 세션 취향과의 불일치
- 노출된 이미지와의 불일치
- 프로젝트 정보의 불충분성
- 카드 노출 순서/맥락 문제

즉, `No = 데이터 라벨 오류`가 아니다.

### 11.2 데이터 수정이 가능한 조건

특정 라벨을 수정 후보로 올리려면 아래 조건을 만족해야 한다.

1. 동일 속성에 대한 반복 부정 반응이 여러 사용자에게서 관찰될 것
2. 해당 반응이 다른 속성 차이로 설명되기 어렵도록 통제된 비교가 있을 것
3. 명시적 이유 태그 또는 반사실 비교 결과가 있을 것
4. 신뢰도 기준을 넘으면 `review_queue`로 보낼 것
5. 자동 수정이 아니라 검토 후 반영할 것

### 11.3 속성별 부정 이유를 분리하는 방법

이를 위해 다음 장치가 필요하다.

#### A. Explicit Reason Tag

사용자가 `No`를 누른 뒤 선택적으로 이유를 고를 수 있게 한다.

예시 태그:

- 재료가 다름
- 너무 차가움
- 너무 장식적임
- 규모가 다름
- 프로그램이 다름
- 실내가 아님
- 도면은 원하지 않음
- 잘 모르겠음

#### B. Controlled Pair Test

서로 대부분 비슷하지만 하나의 속성만 다른 카드 쌍을 제시한다.
예를 들어 같은 프로그램/스케일/분위기인데 재료만 콘크리트 vs 벽돌인 카드 쌍이다.

이 경우 특정 속성 선호를 더 강하게 추정할 수 있다.

#### C. Aggregate Evidence

단일 세션이 아니라 다수 세션 누적 결과를 봐야 한다.

#### D. Review Queue

충분한 근거가 쌓인 경우에만 데이터 수정 후보를 review queue로 올린다.

### 11.4 결론

- 세션 반영은 실시간으로 한다.
- 데이터 수정은 지연/검토 기반으로 한다.

이 둘을 분리해야 서비스 품질이 안정적이다.

---

## 12. 세션 선호 추정 로직

### 12.1 선호 상태는 실시간 갱신한다

세션 동안 시스템은 아래 두 종류의 선호를 동시에 업데이트한다.

- structured preference
- visual preference

### 12.2 Structured Preference 예시

- museum 선호
- Japan 선호
- brick 선호
- small-scale 선호
- warm mood 선호

### 12.3 Visual Preference 예시

- 채도 낮음 선호
- 외관보다 실내 선호
- 자연광 선호
- drawing보다 photo 선호
- plan/section 도면 선호

### 12.4 Unknown Preference 세션의 운영 원칙

초기 카드셋은 정보 획득량이 큰 축 위주로 구성한다.

예시 축:

- interior vs exterior
- concrete vs brick vs wood
- calm vs dramatic
- minimal vs expressive
- photo vs drawing
- small scale vs large scale

초반 5~8장의 카드는 정답을 맞히기보다,
사용자가 어떤 축에 민감한지 파악하는 데 집중한다.

---

## 13. 리포트 설계 원칙

최종 리포트는 단순 요약문이 아니다.
리포트는 세션 결과를 사용자에게 설명하고, 추천 결과를 정당화하는 기능을 가진다.

### 13.1 리포트에 포함되어야 하는 내용

- 사용자의 초기 입력 요약
- 시스템이 추정한 핵심 취향 태그
- swipe 과정에서 강화된 선호/배제된 선호
- 최종 추천 프로젝트 목록
- 각 프로젝트가 선택된 이유
- 관련 프로젝트 묶음

### 13.2 리포트의 금지 사항

- 근거 없는 확신형 문장
- 사용자가 말하지 않은 요구를 임의로 단정
- 데이터베이스에 없는 속성의 환각 생성

### 13.3 리포트와 태그의 관계

리포트 문장은 반드시 구조화 태그와 연결 가능해야 한다.
즉, 설명 가능한 결과여야 한다.

---

## 14. API 관점의 최소 기능 계약

상위 spec에서는 최소 엔드포인트 수준만 정의한다.
상세 request/response는 별도 하위 spec으로 분리한다.

### 14.1 세션 시작

`POST /sessions`

역할:

- 세션 생성
- mode 초기화
- locale 설정

### 14.2 첫 입력 처리

`POST /sessions/{session_id}/input`

역할:

- 자연어 입력 저장
- query parsing 수행
- clarification 필요 여부 반환

### 14.3 카드 조회

`GET /sessions/{session_id}/cards/next`

역할:

- 다음 카드 반환
- 카드 메타데이터 포함

### 14.4 swipe 반영

`POST /sessions/{session_id}/swipes`

역할:

- swipe 저장
- 선호 상태 업데이트
- 다음 카드 후보 재정렬

### 14.5 최종 리포트 조회

`GET /sessions/{session_id}/report`

역할:

- 세션 리포트 반환
- 최종 추천 프로젝트와 관련 프로젝트 제공

---

## 15. 비기능 요구사항

### 15.1 응답 속도

MVP 권장 목표:

- 첫 입력 해석: 5초 이내
- 다음 카드 반환: 1초 이내
- swipe 반영 후 재정렬: 1초 이내
- 최종 리포트 생성: 8초 이내

### 15.2 데이터 처리 안정성

- 크롤링/분석 작업은 idempotent 해야 한다.
- 동일 source page 재처리 시 중복 생성이 없어야 한다.
- 실패 작업은 재시도 가능해야 한다.
- 모든 파이프라인 단계는 run id로 추적 가능해야 한다.

### 15.3 관측 가능성

최소한 아래 로그/메트릭이 필요하다.

- crawl success rate
- extraction success rate
- duplicate merge count
- image analysis failure rate
- session completion rate
- swipe positive ratio
- report generation success rate

### 15.4 비용 관리

- 이미지 분석은 가능한 한 오프라인 선계산한다.
- 임베딩 생성도 배치 처리한다.
- 온라인 요청에서는 precomputed feature를 우선 사용한다.

### 15.5 법적/운영 주의사항

- robots.txt 및 사이트 정책 확인이 필요하다.
- 원본 URL과 source attribution을 유지해야 한다.
- 이미지 원본 저장 여부는 별도 운영 정책으로 명시해야 한다.

---

## 16. MVP 범위 제안

### 16.1 MVP에서 반드시 구현할 것

- 승인된 소수 레퍼런스 사이트 크롤링
- canonical project 생성
- 텍스트 필드 정규화
- 이미지 분석 기본 taxonomy 적용
- 자연어 입력 → 초기 카드 추천
- swipe yes/no/skip 수집
- 세션 선호 상태 실시간 업데이트
- 최종 리포트 + 관련 프로젝트 보드
- review queue 기본 운영

### 16.2 MVP에서 단순화해도 되는 것

- explicit reason tag는 optional UI로 시작
- 장기 사용자 프로필 없음
- 추천 랭킹은 heuristic 기반으로 시작
- 데이터 수정은 자동 반영 없이 리뷰 큐만 생성

### 16.3 Post-MVP

- 사용자 계정/저장된 취향
- cross-session personalization
- learning-to-rank 고도화
- attribute-specific active learning
- 관리자 검수 도구 고도화

---

## 17. 하위 spec 문서 구성 원칙

모든 하위 spec 문서는 아래 공통 형식을 가져야 한다.

1. 목적
2. 범위 / 비범위
3. 입력
4. 출력
5. 데이터 스키마
6. 처리 흐름
7. 상태 전이
8. API 또는 job contract
9. 예외 처리
10. acceptance criteria
11. open questions

---

## 18. 기존 하위 spec 정리 및 보완 포인트

### 18.1 spec_ref_url_crawling.md

정의해야 할 것:

- 승인된 source site 목록
- 프로젝트 URL 발견 규칙
- 제외할 URL 패턴
- canonical URL 규칙
- recrawl 정책
- robots / throttle 정책
- 실패/중복 처리

### 18.2 spec_ref_text_crawling.md

정의해야 할 것:

- 추출 대상 필드
- evidence 저장 방식
- 단위 정규화 규칙
- 언어별 파싱 처리
- low-confidence 처리 기준

### 18.3 spec_image_url_crawling.md

정의해야 할 것:

- 이미지 URL 추출 규칙
- hero image 판별 기준
- caption/alt 보존 규칙
- 이미지 다운로드/중복 제거 규칙
- broken image 처리 기준

### 18.4 spec_data_refine.md

정의해야 할 것:

- project canonicalization 규칙
- source 우선순위
- 필드 병합 점수
- duplicate merge review 기준
- conflict resolution 정책

### 18.5 spec_image_analysis.md

이미 구조가 가장 구체적이다.
추가로 보완할 것:

- taxonomy versioning 정책
- low-confidence fallback 규칙
- 이미지별 분석 프롬프트/모델 정책
- 재분석 조건
- search index로 전달되는 feature subset

### 18.6 spec_data_feedback.md

반드시 보완할 것:

- `No`의 해석 정책
- explicit reason tag schema
- controlled pair test 설계
- aggregate evidence 기준
- review queue 생성 조건
- 자동 수정 금지/허용 범위

### 18.7 spec_user_input.md

정의해야 할 것:

- 자연어 입력 파싱 결과 schema
- clarification 질문 생성 조건
- 취향 모름 모드 진입 규칙
- 구조화 preference로 치환하는 규칙
- 금지 질문/불필요 질문 기준

### 18.8 spec_card_swipe.md

반드시 보완할 것:

- 카드 1장의 데이터 contract
- project-level vs image-level signal 저장 규칙
- front/back data exchange schema
- prefetch 전략
- optimistic UI 여부
- skip, back, undo 정책

### 18.9 spec_find_favorite.md

반드시 보완할 것:

- session preference state schema
- candidate generation 전략
- reranking 공식
- exploration vs exploitation 규칙
- 다양성 제어 기준
- 세션 종료 조건

### 18.10 spec_report_text.md

정의해야 할 것:

- report schema
- 태그 생성 규칙
- 설명 문장 생성 규칙
- 추천 근거 연결 방식
- hallucination 방지 규칙

---

## 19. 필수로 추가할 하위 spec

현재 상위 spec만으로는 온라인 서비스 개발 계약이 부족하므로,
아래 문서는 새로 추가하는 것을 권장한다.

### 19.1 spec_api_contract.md

프론트엔드와 백엔드 간 request/response 계약.

### 19.2 spec_session_state.md

세션, candidate, swipe event, report 저장 구조 정의.

### 19.3 spec_retrieval_ranking.md

candidate generation, reranking, exploration 정책 정의.

### 19.4 spec_admin_review.md

review queue 처리 흐름과 관리자 검수 정책 정의.

---

## 20. 오픈 이슈

개발 전에 아래 항목은 확정이 필요하다.

1. 카드 UI는 단일 대표 이미지 방식인가, 보조 썸네일까지 포함할 것인가?
2. 초기 MVP는 anonymous session만 지원할 것인가?
3. 크롤링 대상 사이트와 저장 정책은 어디까지 허용되는가?
4. 최종 추천은 프로젝트 5개 고정인가, 가변 개수인가?
5. explicit reason tag를 MVP에 포함할 것인가?
6. 실내/외관/도면의 노출 비율을 어떻게 제어할 것인가?
7. 관련 프로젝트는 동일 속성 기반인지, 의외성 기반까지 허용할 것인가?

---

## 21. 최종 정리

현재 `spec.md`는 서비스 방향과 하위 문서 목록을 잡는 데는 유효하지만,
개발용 상위 spec으로 쓰기에는 다음이 부족하다.

- 온라인 세션 데이터 모델
- 검색/추천/랭킹 구조
- swipe signal 해석 정책
- front/back API 경계
- 리뷰/운영 정책
- MVP 범위와 비범위

반면 `spec_image_analysis.md`는 오프라인 데이터 계층을 꽤 구체적으로 정의하고 있으므로,
상위 spec은 이 오프라인 데이터 계층을 재사용하고,
그 위에 온라인 세션/추천 계약을 덧씌우는 방향으로 정리하는 것이 가장 효율적이다.

# End