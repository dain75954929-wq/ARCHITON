# ARCHITON API Specification Draft (v1)

본 문서는 frontend-backend 연동 규격서(ARCHITON/3. in_out/back_front.md)를 기준으로 작성한 실제 API 명세 초안이다.
기존 문서/코드와 분리된 독립 초안이며, 기존 구현에 직접적인 변경을 가하지 않는다.

## 1. 기본 정보

- Base URL: /api/v1
- Content-Type: application/json
- Auth: Bearer 토큰 (초기 단계에서는 optional)
- Timezone: UTC
- Timestamp format: ISO-8601

## 2. 공통 스키마

### 2.1 ErrorResponse

```json
{
  "error_code": "INVALID_INPUT",
  "message": "Validation failed",
  "details": {
    "field": "project_name",
    "reason": "required"
  },
  "request_id": "req_20260314_001"
}
```

### 2.2 ImageCard

```json
{
  "image_id": "img_000123",
  "image_title": "Unscripted Pavilion",
  "image_url": "https://cdn.example.com/images/000123.jpg",
  "source_url": "https://www.designboom.com/...",
  "metadata": {
    "axis_typology": "pavilion",
    "axis_architects": "Abin Design Studio",
    "axis_country": "India",
    "axis_area_m2": 375,
    "axis_capacity": null,
    "axis_tags": ["grid", "warm material", "open space"]
  }
}
```

### 2.3 Progress

```json
{
  "current_round": 12,
  "total_rounds": 100,
  "like_count": 5,
  "dislike_count": 7
}
```

### 2.4 AnalysisOptions

```json
{
  "initial_image_id": 1,
  "initial_diverse_count": 14,
  "total_rounds": 100,
  "like_weight": 1.0,
  "dislike_weight": -0.6,
  "epsilon": 0.18,
  "epsilon_min": 0.05,
  "epsilon_decay": 0.995,
  "distance_metric": "cosine",
  "final_recommendation_count": 20,
  "report_keyword_count": 5
}
```

## 3. 인증 API

## 3.1 POST /auth/login

설명:
- 사용자 로그인 또는 신규 계정 생성

Request Body:

```json
{
  "user_id": "user123",
  "password": "1234"
}
```

Response 200:

```json
{
  "success": true,
  "user_id": "user123",
  "is_new": false,
  "access_token": "<optional>",
  "refresh_token": "<optional>"
}
```

Errors:
- 400 INVALID_INPUT
- 401 UNAUTHORIZED
- 500 INTERNAL_ERROR

## 4. 프로젝트 API

## 4.1 POST /projects

설명:
- 신규 프로젝트 생성

Request Body:

```json
{
  "user_id": "user123",
  "project_name": "졸업 작품 리서치",
  "filters": {
    "typologies": ["museum", "gallery"],
    "min_area": 0,
    "max_area": 500000,
    "countries": ["KR", "JP"],
    "scale": "medium"
  }
}
```

Response 201:

```json
{
  "project_id": "proj_1710000000000",
  "normalized_filters": {
    "typologies": ["museum", "gallery"],
    "min_area": 0,
    "max_area": 500000,
    "countries": ["KR", "JP"],
    "scale": "medium"
  },
  "created_at": "2026-03-14T09:00:00Z"
}
```

## 4.2 PATCH /projects/{project_id}

설명:
- 기존 프로젝트 업데이트 (필터 유지 또는 수정)

Request Body:

```json
{
  "user_id": "user123",
  "filter_mode": "modify",
  "filters": {
    "typologies": ["museum", "cultural"],
    "min_area": 1000,
    "max_area": 300000,
    "countries": ["KR"],
    "scale": "large"
  }
}
```

Response 200:

```json
{
  "project_id": "proj_1710000000000",
  "filter_mode": "modify",
  "applied_filters": {
    "typologies": ["museum", "cultural"],
    "min_area": 1000,
    "max_area": 300000,
    "countries": ["KR"],
    "scale": "large"
  },
  "updated_at": "2026-03-14T09:05:00Z"
}
```

## 5. 분석 세션 API

## 5.1 POST /analysis/sessions

설명:
- 분석 세션 시작
- 신규 프로젝트: 필터 집합 기반 초기 탐색 세트 생성
- 기존 프로젝트: 이전 추천 결과를 우선 후보로 분석 재개

Request Body:

```json
{
  "user_id": "user123",
  "project_id": "proj_1710000000000",
  "is_new_project": true,
  "filter_mode": "keep",
  "analysis_options": {
    "initial_image_id": 1,
    "initial_diverse_count": 14,
    "total_rounds": 100,
    "distance_metric": "cosine"
  }
}
```

Response 201:

```json
{
  "session_id": "sess_1710000100000",
  "session_status": "active",
  "total_rounds": 100,
  "next_image": {
    "image_id": "img_000001",
    "image_title": "Initial Anchor",
    "image_url": "https://cdn.example.com/images/000001.jpg",
    "source_url": "https://example.com/source/1",
    "metadata": {
      "axis_typology": "pavilion",
      "axis_country": "KR"
    }
  },
  "progress": {
    "current_round": 0,
    "total_rounds": 100,
    "like_count": 0,
    "dislike_count": 0
  }
}
```

## 5.2 POST /analysis/sessions/{session_id}/swipes

설명:
- 사용자 스와이프 피드백 반영
- backend가 swiped_image_ids를 저장 및 업데이트
- 중복 이미지 재노출 금지

Request Body:

```json
{
  "user_id": "user123",
  "project_id": "proj_1710000000000",
  "image_id": "img_000321",
  "action": "like",
  "exposed_image_ids": ["img_000001", "img_000221", "img_000321"],
  "swiped_image_ids": ["img_000001", "img_000221", "img_000321"],
  "timestamp": "2026-03-14T09:10:00Z",
  "idempotency_key": "swp_1710000200000"
}
```

Response 200:

```json
{
  "accepted": true,
  "session_status": "active",
  "progress": {
    "current_round": 3,
    "total_rounds": 100,
    "like_count": 2,
    "dislike_count": 1
  },
  "next_image": {
    "image_id": "img_000872",
    "image_title": "Suggested Next",
    "image_url": "https://cdn.example.com/images/000872.jpg",
    "source_url": "https://example.com/source/872",
    "metadata": {
      "axis_typology": "museum",
      "axis_country": "JP"
    }
  },
  "is_analysis_completed": false
}
```

Response 200 (완료 시):

```json
{
  "accepted": true,
  "session_status": "report_ready",
  "progress": {
    "current_round": 100,
    "total_rounds": 100,
    "like_count": 53,
    "dislike_count": 47
  },
  "next_image": null,
  "is_analysis_completed": true
}
```

## 5.3 GET /analysis/sessions/{session_id}/result

설명:
- 분석 완료 후 최종 결과 조회
- frontend 출력 의무 항목: liked_images, predicted_like_images, analysis_report

Query:
- user_id
- project_id

Response 200:

```json
{
  "session_id": "sess_1710000100000",
  "session_status": "completed",
  "liked_images": [
    {
      "image_id": "img_000321",
      "image_title": "Liked 1",
      "image_url": "https://cdn.example.com/images/000321.jpg",
      "source_url": "https://example.com/source/321",
      "metadata": {
        "axis_typology": "museum",
        "axis_country": "KR"
      }
    }
  ],
  "predicted_like_images": [
    {
      "image_id": "img_000901",
      "image_title": "Predicted Like 1",
      "image_url": "https://cdn.example.com/images/000901.jpg",
      "source_url": "https://example.com/source/901",
      "metadata": {
        "axis_typology": "museum",
        "axis_country": "JP"
      }
    }
  ],
  "predicted_like_count": 20,
  "analysis_report": {
    "dominant_axes": [
      "axis_material_warm",
      "axis_spatial_openness"
    ],
    "keywords": [
      "warm material",
      "open space",
      "soft daylight",
      "minimal facade",
      "neutral tone"
    ],
    "keyword_count": 5,
    "summary_text": "사용자는 따뜻한 재료감과 개방적 공간감을 중심으로 차분한 미니멀 톤을 선호합니다."
  },
  "generated_at": "2026-03-14T09:30:00Z"
}
```

반드시 보장할 서버 규칙:
1. predicted_like_images는 미피드백 이미지에서만 선택한다.
2. 개수는 최대 final_recommendation_count(기본 20)까지 반환한다.
3. 후보 부족 시 가능한 최대 개수만 반환한다.
4. report keywords는 최대 report_keyword_count(기본 5)까지 반환한다.
5. 키워드 부족 시 가능한 최대 개수만 반환한다.

## 6. 상태 코드 규약

- 200 OK: 조회/수정 성공
- 201 Created: 생성 성공
- 400 Bad Request: 입력값 오류
- 401 Unauthorized: 인증 실패
- 404 Not Found: 리소스 없음
- 409 Conflict: 상태 충돌 또는 중복 이벤트
- 422 Unprocessable Entity: 분석 상태상 처리 불가
- 500 Internal Server Error: 서버 오류

## 7. 유효성 규칙 (요약)

1. user_id: 2자 이상
2. password: 4자 이상
3. action: like 또는 dislike
4. distance_metric: cosine 또는 euclidean
5. filter_mode: keep 또는 modify
6. final_recommendation_count: 1 이상 정수
7. report_keyword_count: 1 이상 정수

## 8. 버전/호환 정책

1. 경로에 버전 포함: /api/v1
2. 필드 추가는 backward-compatible로 진행
3. 필드 제거 또는 타입 변경 시 /api/v2에서 반영

## 9. 구현 메모

1. frontend는 backend가 제공하는 next_image를 단일 소스로 렌더링한다.
2. frontend의 기존 building_id 배열은 image_id 배열로 통합 관리한다.
3. 기존 frontend.md의 가중치/선호벡터 계산 내용은 폐기하고 backend 결과를 사용한다.
4. 스와이프 API에는 idempotency_key 전송을 권장한다.
