# ARCHITON 벡터DB 검증 및 이미지 기반 취향 분석 방법론

## 1. 문서 목적

이 문서는 ARCHITON 프로젝트에서 CSV 기반 원천 데이터를 PostgreSQL + pgvector로 벡터DB화한 이후,
다음 단계인 벡터DB 품질 검증과 이미지 기반 취향 분석/추천 알고리즘 운영 방법을 정의한다.

상위 목표와 원칙은 ARCHITON_KMS 스펙 문서(ARCHITON/spec_refined.md)를 따른다.

---

## 2. 전제 조건

- 벡터DB 저장소: PostgreSQL
- 벡터DB 이름: into_database
- 확장: pgvector
- 주요 테이블: public.architecture_vectors
- 조회용 뷰: public.into_database
- 검증/추천 대상 단위: image 레벨
- 기본 시작 이미지: id = 1
- 벡터 컬럼: embedding (현재 384차원)

연동 명명 규칙:

- 분석/추천 단위 식별자는 `image_id`를 사용한다.
- 기존 frontend의 `building_id`는 backend 연동 시 `image_id`와 동일 의미로 매핑한다.
- frontend는 backend 응답의 `next_image`, `liked_images`, `predicted_like_images`를 단일 렌더링 소스로 사용한다.
- frontend는 취향 가중치 계산 및 선호 벡터 계산을 수행하지 않는다(backend 단일 소스).

운영 연결 기준:

- Host: localhost
- Port: 5432
- Database: into_database
- Schema/Table: public.architecture_vectors
- Distance Metric: cosine (`<=>`)

참고:

- 본 문서의 모든 검증 SQL과 추천 알고리즘은 PostgreSQL의 `into_database`를 기준으로 작성한다.
- CSV/JSON 원천 파일은 적재 입력원이며, 취향 분석 시점의 단일 소스 오브 트루스는 `public.architecture_vectors`이다.

---

## 3. 벡터DB 검증 프로토콜

### 3.1 구조 검증

검증 항목:

1. vector 확장 활성화 여부
2. embedding 컬럼 존재 및 타입 확인
3. 벡터 NULL 여부 확인
4. 벡터 차원 일관성 확인

예시 SQL:

- 확장 확인
  - SELECT current_database() AS db_name;
  - SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';
- 컬럼 확인
  - SELECT column_name, data_type, udt_name
    FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'architecture_vectors' AND column_name = 'embedding';
- NULL 확인
  - SELECT COUNT(*) AS total_rows,
           COUNT(embedding) AS embedding_rows,
           COUNT(*) - COUNT(embedding) AS embedding_null_rows
    FROM public.architecture_vectors;
- 차원 확인
  - SELECT MIN(vector_dims(embedding)) AS min_dim,
           MAX(vector_dims(embedding)) AS max_dim
    FROM public.architecture_vectors;

합격 기준:

- extname = vector 존재
- embedding 컬럼 존재
- embedding_null_rows = 0
- min_dim = max_dim = 기대 차원(기본 384)

### 3.2 검색 동작 검증

검증 항목:

1. 자기 자신 최근접 탐색 일치 여부
2. 거리 정렬 정상 여부

예시 SQL:

- WITH q AS (
    SELECT id, embedding FROM public.architecture_vectors WHERE id = 1
  )
  SELECT a.id, a.title, (a.embedding <=> q.embedding) AS cosine_distance
  FROM public.architecture_vectors a, q
  ORDER BY a.embedding <=> q.embedding
  LIMIT 5;

합격 기준:

- 1위 결과 id가 기준 id와 동일
- 1위 distance가 0 또는 0에 매우 근접

### 3.3 권장 품질 지표

필수 지표:

1. Precision@K
- 샘플 질의 세트 기준 Top-K 관련도 측정

2. Diversity@K
- Top-K 결과의 source, location, style 편중 확인

3. Feedback Agreement
- 좋아요 이후 유사 추천의 체감 일치율
- 싫어요 이후 비유사 추천 전환 성공률

권장 기준 예시:

- Precision@5 >= 0.60 (초기 MVP 기준)
- 단일 source 편중 비율 <= 0.70
- 좋아요 피드백 후 3스텝 내 체감 일치율 상승

### 3.4 성능 검증

검증 항목:

1. Top-K 질의 지연시간
2. 실행 계획(인덱스 사용 여부)
3. 데이터 규모 증가 시 응답 저하 추이

예시 SQL:

- EXPLAIN (ANALYZE, BUFFERS)
  SELECT id, title
  FROM public.architecture_vectors
  ORDER BY embedding <=> (
      SELECT embedding FROM public.architecture_vectors WHERE id = 1
  )
  LIMIT 10;

합격 기준 예시:

- 기준 데이터셋에서 P95 응답시간 목표 충족
- 벡터 검색 연산이 설계 의도대로 수행됨

---

## 4. 이미지 기반 취향 분석 알고리즘 설계

### 4.1 핵심 변수 정의

아래 변수는 운영 중 튜닝 가능하도록 코드 상수로 관리한다.

- INITIAL_IMAGE_ID = 1
- INITIAL_DIVERSE_COUNT = 10
- TOTAL_ROUNDS = 100
- LIKE_WEIGHT = 1.0
- DISLIKE_WEIGHT = -0.6
- EPSILON = 0.18
- EPSILON_MIN = 0.05
- EPSILON_DECAY = 0.995
- DISTANCE_METRIC = cosine
- ALLOW_DUPLICATE_IN_SESSION = false
- FINAL_RECOMMENDATION_COUNT = 20

설계 의도:

- LIKE_WEIGHT는 긍정 피드백을 강하게 반영
- DISLIKE_WEIGHT는 배제는 하되 과도한 반작용 방지
- EPSILON은 초기 탐색 확보를 위해 0.18로 시작, 점진 감소
- 최종 추천 개수와 리포트 키워드 개수는 운영 중 튜닝 가능

### 4.2 단계 1: 초기 탐색 세트 구성

목표:

- 필터링된 후보 집합 안에서 시작 이미지를 먼저 1장 제시하고, 나머지 9장은 서로 최대한 다른 이미지를 구성하여 취향 공간을 빠르게 탐색

절차:

1. 사용자가 면적 입력과 LLM 기반 질의 해석을 거쳐 후보 이미지를 먼저 필터링한다.
2. 필터링된 집합에서 시작 이미지를 랜덤하게 1장 선택한다.
3. 나머지 9장은 시작 이미지 및 이미 선택된 탐색 이미지들과의 거리 차이가 최대가 되도록 선택한다.
4. 결과적으로 총 10장의 초기 탐색 세트를 구성한다.
5. 초기 탐색 이후에는 누적된 좋아요/싫어요 피드백을 바탕으로 분석 추천 단계로 전환한다.

필터링 후보 수 부족 시 규칙:

1. 필터링된 이미지 수가 INITIAL_DIVERSE_COUNT(기본 10)보다 적으면, 해당 필터링 결과 전체를 초기 탐색 세트로 사용한다.
2. 이 경우에도 취향 분석은 정상적으로 수행하며, 필터링 결과 안에서 수집된 좋아요/싫어요 피드백으로 user_pref_vector를 계산한다.
3. 최종 추천 단계에서는 필터와 완전히 일치하지 않더라도, 사용자가 좋아요를 누른 이미지와 유사도가 높은 이미지를 우선 추천한다.
4. 즉, 필터는 초기 후보 축소에 사용하되, 최종 추천은 좋아요 기반 유사도 신호를 우선한다.

거리 선택:

- 코사인 거리 또는 유클리드 거리 중 선택 가능
- 기본값은 코사인 거리

### 4.3 단계 2: 100라운드 반복 추천

목표:

- 초기 10개 탐색 피드백을 시작점으로 사용자 취향 벡터를 점진적으로 수렴

절차:

1. 현재 사용자 취향 벡터 user_pref_vector 계산
2. `public.architecture_vectors`에서 미노출 이미지 집합을 SQL로 조회하고 점수 상위 이미지 추천
3. 사용자 피드백 반영
4. user_pref_vector 업데이트
5. TOTAL_ROUNDS까지 반복

구현 가이드(SQL + 애플리케이션 연동):

1. 애플리케이션 레이어에서 `liked_image_ids`, `disliked_image_ids`, `exposed_image_ids`를 세션 상태로 유지
2. PostgreSQL에서 후보군을 조회할 때 `WHERE id <> ALL(%s)` 또는 `NOT IN (...)`으로 이미 노출된 id 제외
3. 추천 점수 계산은 다음 두 방식 중 택 1
  - SQL 중심: 코사인 거리 기반 사전 정렬 후 앱에서 가중치 재랭킹
  - 앱 중심: 후보 벡터를 조회해 앱에서 user_pref_vector와 직접 점수 계산
4. 최종 추천 id 목록을 다시 SQL로 조회해 화면 출력용 메타데이터(title, image, location 등) 구성
5. 초기 탐색 세트가 10장 미만으로 구성된 경우에도, 탐색 종료 직후 user_pref_vector를 기반으로 연속 추천 단계를 그대로 이어간다.

세션 API 상태 규칙:

1. 세션 시작 시 `session_status=active`, `progress.current_round=0`, `next_image`를 반환
2. 스와이프 처리 중에는 `accepted`, `progress`, `next_image`, `is_analysis_completed`를 함께 반환
3. 라운드 종료 시 `session_status=completed`로 전환
4. 완료 후 결과 API에서 `liked_images`, `predicted_like_images`를 반환

취향 범위 축소 전략:

- 좋아요 누적 시 유사 영역의 탐색 밀도 증가
- 싫어요 누적 시 해당 방향에 페널티 부여
- epsilon-greedy로 주기적 탐색 삽입

### 4.4 단계 3: 좋아요/싫어요 가중치 반영

점수 함수 개요:

- candidate_score = similarity(candidate, user_pref_vector)
                  + like_influence
                  - dislike_penalty

업데이트 규칙 예시:

- 좋아요: user_pref_vector <- user_pref_vector + LIKE_WEIGHT * embedding
- 싫어요: user_pref_vector <- user_pref_vector + DISLIKE_WEIGHT * embedding

PostgreSQL 연동 포인트:

- 피드백 입력 시 해당 id의 embedding은 `SELECT embedding FROM public.architecture_vectors WHERE id = :id`로 조회
- 조회된 embedding을 앱 메모리의 user_pref_vector에 누적 반영
- 업데이트 후 user_pref_vector는 정규화(normalize)하여 스케일 안정성 유지

보정 원칙:

- LIKE_WEIGHT > abs(DISLIKE_WEIGHT)로 설정해 긍정 신호 중심 추천
- DISLIKE_WEIGHT가 너무 크면 추천 다양성 상실 가능

### 4.5 단계 4: epsilon-greedy 탐색

목표:

- 과도한 수렴으로 인한 취향 고착 방지

정책:

1. 확률 epsilon으로 탐색(explore):
   - 아직 덜 노출된 영역에서 후보 선택
2. 확률 (1 - epsilon)으로 활용(exploit):
   - 현재 취향 벡터와 유사한 후보 선택
3. 라운드 진행에 따라 epsilon 감소:
   - epsilon = max(EPSILON_MIN, epsilon * EPSILON_DECAY)

### 4.6 단계 5: 중복 노출 방지

필수 규칙:

1. 같은 세션에서 이미 노출된 이미지 id는 재추천 금지
2. 추천 후보 생성 시 exposed_image_ids 집합에서 제외
3. 초기 탐색 10개도 중복 검사 대상 포함

자료구조 권장:

- exposed_image_ids: Set[int]
- liked_image_ids: Set[int]
- disliked_image_ids: Set[int]

SQL 적용 규칙:

- 추천 질의에 `WHERE id <> ALL(:exposed_image_ids)`를 적용해 세션 중복 노출을 원천 차단
- 최종 추천 시에도 동일한 제외 조건을 재적용해 중복 누락 방지

이벤트 중복 방지 규칙:

- 스와이프 입력 이벤트는 `idempotency_key`(또는 `swipe_event_id`)를 받아 동일 이벤트 중복 저장을 차단한다.
- 네트워크 재시도 시 동일 키는 한 번만 반영하고 기존 처리 결과를 반환한다.

### 4.7 단계 6: 분석 완료 후 결과 제시

목표:

- 사용자가 취향 학습 과정에서 실제로 긍정 반응한 근거와 최종 추천 결과를 함께 제시

결과 제시 순서:

1. 사용자가 좋아요를 누른 이미지 목록 표시
2. 사용자가 좋아요를 누를 것으로 예상되는 이미지 추천

응답 구조 준수:

1. `liked_images`: 사용자가 like한 이미지 카드 배열
2. `predicted_like_images`: 미피드백 후보 기반 추천 이미지 카드 배열

최종 추천 후보 규칙:

1. 추천 후보는 반드시 사용자가 피드백하지 않은 이미지 집합에서만 선택
2. 세션 내 이미 노출된 이미지 및 피드백 완료 이미지는 추천에서 제외
3. 추천 목표 개수는 FINAL_RECOMMENDATION_COUNT(기본 20)
4. 추천 가능 이미지가 20개 미만이면 가능한 최대 개수만 반환

후보 집합 정의 예시:

- candidate_pool = all_image_ids - exposed_image_ids - feedback_image_ids

PostgreSQL 조회 예시 개념:

- all_image_ids는 `public.architecture_vectors` 전체 id 집합
- exposed/feedback id는 앱 세션 상태
- 최종 후보는 SQL WHERE 절에서 제외 조건으로 구현

점수화 원칙:

1. user_pref_vector와의 유사도(코사인 또는 유클리드 기반)를 기본 점수로 사용
2. 좋아요 피드백 누적 방향과의 정렬도를 가산
3. 싫어요 피드백 방향과의 정렬도는 감산

### 4.8 사용자 데이터 관리 DB

목표:

- 사용자 로그인 정보와 취향 분석 과정에서 수집된 '좋아요' 피드백 이미지를 별도 데이터베이스에 저장하여 LLM 기반 분석 리포트 생성의 입력 데이터로 활용

데이터베이스 구성:

- DB 종류: SQLite (로컬 운영 기준)
- DB 경로: `3. in_out/user_tracking.db`
- 스키마 SQL: `3. in_out/user_tracking.sql`
- 주요 테이블: `user_credentials`, `liked_projects`

테이블 스키마:

1. `user_credentials` 테이블
   - `user_id` TEXT PRIMARY KEY: 사용자 식별자
   - `password` TEXT NOT NULL: 비밀번호
   - `created_at` TEXT: 계정 생성 일시

2. `liked_projects` 테이블
   - `id` INTEGER PRIMARY KEY AUTOINCREMENT
   - `user_id` TEXT NOT NULL: 사용자 식별자 (user_credentials 참조)
   - `image_id` INTEGER NOT NULL: 좋아요한 이미지의 architecture_vectors.id
   - `project_name` TEXT: 프로젝트명
   - `url` TEXT: 이미지 URL
   - `architect` TEXT: 건축가
   - `location_country` TEXT: 위치
   - `program` TEXT: 프로그램
   - `year` TEXT: 연도
   - `mood` TEXT: 무드
   - `material` TEXT: 재료
   - `liked_at` TEXT: 좋아요 기록 일시

저장 시점:

- 세션 완료(`is_analysis_completed = true`) 후 liked_image_ids를 순회하여 `liked_projects` 테이블에 저장
- 저장 레코드에는 최소 `user_id`, `image_id`, `project_name`이 반드시 포함되어야 한다.
- 동일 user_id + image_id 조합의 중복 저장 방지 (UNIQUE 제약 또는 INSERT OR IGNORE 적용)

LLM 리포트 생성 연계:

- LLM 모델은 특정 user_id의 `liked_projects` 레코드를 조회하여 취향 분석 리포트를 생성
- 리포트 생성은 별도 LLM 파이프라인으로 운영하며, 본 문서(analysis_method.md) 범위 밖
- analysis 백엔드는 `liked_projects` 저장까지만 담당하며, 리포트 내용 생성에 관여하지 않음

---

## 5. 운영 검증 체크리스트

### 5.1 데이터/구조 체크

- current_database() = into_database 확인
- vector 확장 활성화
- 벡터 차원 일치
- NULL 벡터 없음
- 중복 record_key 없음

### 5.2 추천 로직 체크

- 초기 10개 구성 규칙 준수
- 필터링 결과가 10개 미만일 때 전체 필터 결과만으로 분석이 이어지는지 검증
- 필터 조건과 완전히 일치하지 않더라도 좋아요 기반 유사 이미지 추천이 동작하는지 검증
- TOTAL_ROUNDS 변수 변경 시 정상 동작
- epsilon 감소 로직 동작
- 세션 중복 노출 0건
- 최종 추천이 미피드백 이미지 집합에서만 생성되는지 검증
- 추천 가능 수가 부족할 때 최대 개수 반환 로직 검증
- API 응답에 `session_status`, `progress`, `is_analysis_completed`가 누락 없이 포함되는지 검증
- `next_image`가 frontend 표시 필드(`image_id`, `image_url`, `image_title`, `metadata`)를 충족하는지 검증
- 스와이프 중복 전송 시 `idempotency_key` 기반 중복 반영 방지 동작 검증

### 5.3 품질 체크

- Precision@5, Diversity@5, Feedback Agreement 수집
- LIKE/DISLIKE 가중치별 A/B 비교 가능 상태 유지
- 최종 추천 Top-N(기본 20)의 사용자 만족도 추적

### 5.4 성능 체크

- Top-K 질의 시간 기록
- 데이터 증가 시 P95 모니터링
- 필요 시 ANN 인덱스(HNSW/IVFFlat) 적용

---

## 6. 구현 시 권장 구성

### 6.1 모듈 분리

1. data_validation.py
- 구조 검증 및 합격 판정

2. preference_engine.py
- user_pref_vector 업데이트
- epsilon-greedy 의사결정

3. recommender.py
- 후보 검색, 중복 제거, 점수 계산

4. evaluator.py
- 지표 산출(Precision, Diversity, Feedback Agreement, latency)

5. user_tracking.py
- 세션 완료 후 user_id, password 관리 및 liked_projects 저장
- SQLite user_tracking DB 연동 (user_credentials, liked_projects)

### 6.2 실험 설정 파일 분리

- config.yaml 또는 환경변수로 아래 항목 외부화
  - INITIAL_DIVERSE_COUNT
  - TOTAL_ROUNDS
  - LIKE_WEIGHT
  - DISLIKE_WEIGHT
  - EPSILON 계열
  - DISTANCE_METRIC
  - FINAL_RECOMMENDATION_COUNT

---

## 7. 리스크 및 대응

1. 리스크: 라벨/메타데이터 결손으로 품질 저하
- 대응: NULL 보정 규칙 + 저신뢰 레코드 플래그

2. 리스크: 피드백 편향으로 과수렴
- 대응: epsilon-greedy + 최소 탐색 비율 유지

3. 리스크: 중복 노출로 사용자 피로 증가
- 대응: 세션 단위 strict dedup 강제

4. 리스크: 데이터 증가에 따른 질의 지연
- 대응: 인덱스 전략 및 EXPLAIN 기반 튜닝

---

## 8. 결론

본 방법론은 벡터DB 구축 이후 단계에서

- 검증 가능성(구조/품질/성능)
- 추천 가능성(좋아요/싫어요 반영)
- 탐색 가능성(epsilon-greedy)
- 운영 가능성(변수 외부화, 중복 방지)

을 동시에 확보하기 위한 실행 기준 문서다.

초기 운영 시에는 기본 파라미터를 사용하고, 피드백 로그 축적 후 가중치 및 epsilon을 재조정한다.
