# ARCHITON In/Out API Contract

이 문서는 현재 서버 구현인 [3. in_out/in_out.py](3.%20in_out/in_out.py)를 기준으로 정리한 프론트엔드 연동용 API 계약 문서다.

기존 [3. in_out/frontend.md](3.%20in_out/frontend.md)는 과거 구조 설명이 일부 섞여 있으므로, 실제 요청/응답 스펙은 이 문서를 기준으로 본다.

## Base URL

- 기본 실행: `http://127.0.0.1:3001`
- 예시 실행: `python in_out.py --host 127.0.0.1 --port 8010` 이면 `http://127.0.0.1:8010`

## 공통 사항

- Content-Type: `application/json`
- CORS 허용: `*`
- 지원 메서드: `GET`, `POST`, `PATCH`, `OPTIONS`
- 에러 응답 기본 형태:

```json
{
  "error_code": "INVALID_INPUT",
  "message": "..."
}
```

## 핵심 데이터 구조

### FrontendImageCard

서버가 프론트로 내려주는 카드 구조다.

```json
{
  "image_id": 123,
  "building_id": "123",
  "image_title": "Project Name",
  "title": "Project Name",
  "image_url": "https://...",
  "imageUrl": "https://...",
  "source_url": "https://...",
  "metadata": {
    "axis_typology": "Museum",
    "axis_architects": "OMA",
    "axis_country": "France",
    "axis_area_m2": null,
    "axis_capacity": null,
    "axis_year": "2024",
    "axis_mood": "Minimal",
    "axis_material": "Concrete"
  },
  "gallery": []
}
```

### Progress

```json
{
  "current_round": 0,
  "total_rounds": 20,
  "like_count": 0,
  "dislike_count": 0
}
```

### AnalysisReport

```json
{
  "dominant_axes": ["axis_source_oma", "axis_source_sanaa"],
  "keywords": ["concrete", "minimal", "gallery"],
  "keyword_count": 3,
  "summary_text": "User preference is concentrated around: concrete, minimal, gallery"
}
```

## 1. Health Check

### GET `/health`

백엔드 연결 상태와 프론트 계약 추출 결과를 확인한다.

### Response 200

```json
{
  "ok": true,
  "backend": {
    "ok": true,
    "validation": {
      "db_name": "into_database",
      "has_vector_extension": true,
      "total_rows": 100,
      "embedding_rows": 100,
      "embedding_null_rows": 0,
      "min_dim": 384,
      "max_dim": 384
    }
  },
  "frontend_contract": {
    "frontend_exists": true,
    "app_api_functions": ["login", "startSession", "submitSwipe"],
    "swipe_required_fields": [
      "next_image.image_id",
      "next_image.image_url",
      "next_image.image_title",
      "next_image.metadata.axis_typology",
      "next_image.metadata.axis_architects",
      "next_image.metadata.axis_country"
    ]
  }
}
```

## 2. Login

### POST `/api/auth/login`

호환 경로: `POST /api/v1/auth/login`

신규 유저면 자동 생성, 기존 유저면 비밀번호 검증 후 로그인 처리한다.

### Request

```json
{
  "id": "user123",
  "password": "1234"
}
```

서버는 `id` 또는 `user_id` 둘 다 받는다.

### Success Response 200

```json
{
  "success": true,
  "user_id": "user123",
  "is_new": false
}
```

### New User Response 200

```json
{
  "success": true,
  "user_id": "user123",
  "is_new": true
}
```

### Invalid Password Response 401

```json
{
  "success": false,
  "error_code": "UNAUTHORIZED",
  "message": "invalid password"
}
```

## Django Migration Login

병행 전환 중인 Django backend에서도 로그인 엔드포인트를 제공한다.

- Django 로그인은 세션 쿠키 기반이다.
- 프론트 fetch 요청에는 반드시 `credentials: 'include'` 가 들어가야 한다.
- 로그인, `auth/me`, `analysis/sessions` 호출은 같은 host를 써야 한다.
- 예: 전부 `http://127.0.0.1:8001` 로 맞추고, `localhost` 와 `127.0.0.1` 를 섞지 않는다.

### POST `/api/auth/login/`

호환 경로: `POST /api/v1/auth/login/`

### Request

```json
{
  "id": "admin",
  "password": "your-password"
}
```

또는

```json
{
  "user_id": "admin",
  "password": "your-password"
}
```

### Success Response 200

```json
{
  "success": true,
  "user_id": "admin",
  "is_new": false,
  "is_superuser": true,
  "is_staff": true
}
```

### Fail Response 401

```json
{
  "success": false,
  "error_code": "UNAUTHORIZED",
  "message": "invalid username or password"
}
```

### Session Check

`GET /api/auth/me/`

성공 시 현재 로그인한 사용자의 기본 정보를 반환한다.

### Django Login Fetch Example

```js
const API_BASE_URL = 'http://127.0.0.1:8001';

export async function loginWithDjango(userId, password) {
  const response = await fetch(`${API_BASE_URL}/api/auth/login/`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      id: userId,
      password,
    }),
  });

  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.message || `HTTP ${response.status}`);
  }

  return data;
}

export async function fetchMe() {
  const response = await fetch(`${API_BASE_URL}/api/auth/me/`, {
    method: 'GET',
    credentials: 'include',
  });

  return response.json();
}
```

### Invalid Input Response 400

```json
{
  "error_code": "INVALID_INPUT",
  "message": "user_id must be at least 2 chars"
}
```

## 3. Start Analysis Session

### POST `/api/v1/analysis/sessions`

스와이프 세션을 시작하고 첫 카드를 반환한다.

### Request

```json
{
  "user_id": "user123",
  "project_id": "proj_1710000000000",
  "candidate_ids": [101, 205, 333]
}
```

### Optional Request Variant

`candidate_ids` 대신 `preloaded_images`를 보낼 수 있다. 서버는 각 항목의 `source_url` 또는 `image_title` 기준으로 DB의 실제 `id`를 찾는다.

```json
{
  "user_id": "user123",
  "project_id": "proj_1710000000000",
  "preloaded_images": [
    {
      "image_title": "Project A",
      "source_url": "https://example.com/project-a"
    }
  ]
}
```

### Success Response 201

```json
{
  "session_id": "sess_ab12cd34ef56gh78",
  "session_status": "active",
  "total_rounds": 20,
  "next_image": {
    "image_id": 123,
    "building_id": "123",
    "image_title": "Project Name",
    "title": "Project Name",
    "image_url": "https://...",
    "imageUrl": "https://...",
    "source_url": "https://...",
    "metadata": {
      "axis_typology": "Museum",
      "axis_architects": "OMA",
      "axis_country": "France",
      "axis_area_m2": null,
      "axis_capacity": null,
      "axis_year": "2024",
      "axis_mood": "Minimal",
      "axis_material": "Concrete"
    },
    "gallery": []
  },
  "progress": {
    "current_round": 0,
    "total_rounds": 20,
    "like_count": 0,
    "dislike_count": 0
  }
}
```

## Django Migration Start Session

병행 전환 중인 Django backend에서도 세션 시작 엔드포인트를 제공한다.

### POST `/api/v1/analysis/sessions`

호환 경로: `POST /api/analysis/sessions/`

- 로그인된 Django 세션 쿠키가 필요하다.
- 프론트 fetch 요청에는 반드시 `credentials: 'include'` 가 필요하다.
- 요청의 `user_id` 는 생략 가능하다.
- `user_id` 를 보낼 경우 현재 로그인 사용자와 같아야 한다.

### Request

```json
{
  "project_id": "proj_1710000000000",
  "candidate_ids": [101, 205, 333]
}
```

또는

```json
{
  "project_id": "proj_1710000000000",
  "preloaded_images": [
    {
      "image_title": "Project A",
      "source_url": "https://example.com/project-a"
    }
  ]
}
```

### Success Response 201

기존 프론트 계약과 동일한 `next_image`, `progress`, `session_status` 를 반환한다. 외부에 노출되는 `session_id` 는 Django 레코드 기준 UUID이고, 내부적으로는 레거시 분석 엔진 세션과 매핑된다.

### Django Start Session Fetch Example

```js
const API_BASE_URL = 'http://127.0.0.1:8001';

export async function startAnalysisSession(projectId, candidateIds = []) {
  const response = await fetch(`${API_BASE_URL}/api/v1/analysis/sessions`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      project_id: projectId,
      candidate_ids: candidateIds,
    }),
  });

  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.message || `HTTP ${response.status}`);
  }

  return data;
}
```

### Invalid Input Response 400

```json
{
  "error_code": "INVALID_INPUT",
  "message": "user_id and project_id are required"
}
```

## 3-A. Preference Batch Narrowing

선택된 초기 10장의 이미지를 기반으로 5장씩 추천을 좁혀 가는 배치 피드백 흐름이다.

### POST `/api/v1/analysis/sessions`

다음 요청 형태로 호출하면 기존 단건 스와이프 세션이 아니라 배치 좁히기 세션이 시작된다.

### Request

```json
{
  "project_id": "a8d3c0d8-4477-4b4c-a884-b0a30a0c9e3b",
  "selected_image_ids": [58, 83, 23, 12, 47, 96, 48, 53, 88, 32]
}
```

또는

```json
{
  "project_id": "a8d3c0d8-4477-4b4c-a884-b0a30a0c9e3b",
  "selected_images": [
    {
      "image_title": "Museum_Passage._Extension_of_the_MNAC",
      "source_url": "https://www.metalocus.es/en/news/museum-passage-extension-mnac-harquitectes-and-christ-gantenbein"
    }
  ]
}
```

### Start Response 201

```json
{
  "session_id": "b8d0fa8e-75ca-4674-be7f-764342672ff4",
  "project_id": "a8d3c0d8-4477-4b4c-a884-b0a30a0c9e3b",
  "session_status": "active",
  "batch_index": 1,
  "batch_size": 5,
  "images": [
    {
      "image_id": 101,
      "building_id": "101",
      "image_title": "Suggested_Project_01",
      "title": "Suggested_Project_01",
      "image_url": "https://...",
      "imageUrl": "https://...",
      "source_url": "https://...",
      "metadata": {
        "axis_typology": "museum",
        "axis_architects": "OMA",
        "axis_country": "France",
        "axis_area_m2": null,
        "axis_capacity": null,
        "axis_year": 2024,
        "axis_mood": "minimal",
        "axis_material": "concrete"
      },
      "gallery": []
    }
  ],
  "feedback_summary": {
    "swipe_count": 10,
    "seed_count": 10,
    "liked_count": 10,
    "disliked_count": 0,
    "like_ratio": 1.0
  },
  "convergence": {
    "is_converged": false,
    "convergence_score": 0.62,
    "pref_change": 0.0,
    "baseline_similarity": 0.24,
    "stability_score": 1.0,
    "coherence_score": 0.51,
    "recent_coherence_score": 0.66,
    "top_k_density_score": 0.57,
    "warning": "",
    "terminated_reason": ""
  },
  "final_recommendations": []
}
```

### POST `/api/v1/analysis/sessions/{session_id}/feedback-batch`

현재 내려온 5장에 대한 좋아요/싫어요를 한 번에 보낸다.

### Request

```json
{
  "feedback": [
    { "image_id": 101, "action": "like" },
    { "image_id": 102, "action": "dislike" },
    { "image_id": 103, "action": "like" },
    { "image_id": 104, "action": "dislike" },
    { "image_id": 105, "action": "like" }
  ]
}
```

### Continue Response 200

```json
{
  "session_id": "b8d0fa8e-75ca-4674-be7f-764342672ff4",
  "project_id": "a8d3c0d8-4477-4b4c-a884-b0a30a0c9e3b",
  "session_status": "active",
  "batch_index": 2,
  "batch_size": 5,
  "images": [
    {
      "image_id": 201,
      "building_id": "201",
      "image_title": "Suggested_Project_06",
      "title": "Suggested_Project_06",
      "image_url": "https://...",
      "imageUrl": "https://...",
      "source_url": "https://...",
      "metadata": {
        "axis_typology": "gallery",
        "axis_architects": "SANAA",
        "axis_country": "Japan",
        "axis_area_m2": null,
        "axis_capacity": null,
        "axis_year": 2021,
        "axis_mood": "soft",
        "axis_material": "glass"
      },
      "gallery": []
    }
  ],
  "feedback_summary": {
    "swipe_count": 5,
    "seed_count": 10,
    "liked_count": 13,
    "disliked_count": 2,
    "like_ratio": 0.6
  },
  "convergence": {
    "is_converged": false,
    "convergence_score": 0.46,
    "pref_change": 0.08,
    "baseline_similarity": 0.24,
    "stability_score": 0.2,
    "coherence_score": 0.52,
    "recent_coherence_score": 0.61,
    "top_k_density_score": 0.43,
    "warning": "",
    "terminated_reason": ""
  },
  "final_recommendations": []
}
```

### Terminated Response 200

종료 조건에 도달하면 `images` 는 비어 있고 `final_recommendations` 가 채워진다.

```json
{
  "session_id": "b8d0fa8e-75ca-4674-be7f-764342672ff4",
  "project_id": "a8d3c0d8-4477-4b4c-a884-b0a30a0c9e3b",
  "session_status": "converged",
  "batch_index": 3,
  "batch_size": 5,
  "images": [],
  "feedback_summary": {
    "swipe_count": 10,
    "seed_count": 10,
    "liked_count": 16,
    "disliked_count": 4,
    "like_ratio": 0.6
  },
  "convergence": {
    "is_converged": true,
    "convergence_score": 0.78,
    "pref_change": 0.018,
    "baseline_similarity": 0.24,
    "stability_score": 0.82,
    "coherence_score": 0.69,
    "recent_coherence_score": 0.88,
    "top_k_density_score": 0.73,
    "warning": "",
    "terminated_reason": "convergence_threshold_reached"
  },
  "final_recommendations": [
    {
      "image_id": 301,
      "building_id": "301",
      "image_title": "Final_Recommendation_01",
      "title": "Final_Recommendation_01",
      "image_url": "https://...",
      "imageUrl": "https://...",
      "source_url": "https://...",
      "metadata": {
        "axis_typology": "museum",
        "axis_architects": "Herzog & de Meuron",
        "axis_country": "Spain",
        "axis_area_m2": null,
        "axis_capacity": null,
        "axis_year": 2026,
        "axis_mood": "serene",
        "axis_material": "concrete"
      },
      "gallery": []
    }
  ]
}
```

## 3-1. Diverse Random Images

### GET `/api/v1/images/diverse-random`

호환 경로: `GET /api/images/diverse-random/`

architecture_vectors 전체 중에서 랜덤 anchor를 하나 잡고, 그 기준으로 서로 최대한 멀게 퍼진 카드 10개를 반환한다.

### Success Response 200

```json
{
  "items": [
    {
      "image_id": 123,
      "building_id": "123",
      "image_title": "Project Name",
      "title": "Project Name",
      "image_url": "https://...",
      "imageUrl": "https://...",
      "source_url": "https://...",
      "metadata": {
        "axis_typology": "Museum",
        "axis_architects": "OMA",
        "axis_country": "France",
        "axis_area_m2": null,
        "axis_capacity": null,
        "axis_year": "2024",
        "axis_mood": "Minimal",
        "axis_material": "Concrete"
      },
      "gallery": []
    }
  ],
  "count": 10
}
```

### Frontend Fetch Example

프론트에서는 아래처럼 바로 호출하면 된다.

```js
const API_BASE_URL = 'http://127.0.0.1:8001';

export async function fetchDiverseRandomImages() {
  const response = await fetch(`${API_BASE_URL}/api/v1/images/diverse-random`, {
    method: 'GET',
    headers: {
      'Content-Type': 'application/json',
    },
  });

  if (!response.ok) {
    throw new Error(`Failed to fetch diverse images: ${response.status}`);
  }

  const data = await response.json();
  return data.items;
}
```

### React Usage Example

```jsx
import { useEffect, useState } from 'react';

const API_BASE_URL = 'http://127.0.0.1:8001';

export default function DiverseImagePanel() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        setLoading(true);
        setError('');

        const response = await fetch(`${API_BASE_URL}/api/v1/images/diverse-random`);
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();
        if (!cancelled) {
          setItems(data.items || []);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'unknown error');
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return <div>Loading...</div>;
  }

  if (error) {
    return <div>{error}</div>;
  }

  return (
    <div>
      {items.map((item) => (
        <article key={item.image_id}>
          <img src={item.image_url} alt={item.title} width={240} />
          <h3>{item.title}</h3>
          <p>{item.metadata?.axis_architects}</p>
          <p>{item.metadata?.axis_typology} / {item.metadata?.axis_country}</p>
        </article>
      ))}
    </div>
  );
}
```

### Frontend Notes

- 응답의 실제 카드 배열은 `items` 에 있다.
- 각 카드는 기존 swipe 화면과 같은 구조를 사용한다.
- 이미지 표시는 `image_url` 또는 `imageUrl` 중 하나를 사용하면 된다.
- 고유 key 는 `image_id` 를 사용하면 된다.

## 3-2. Projects

### POST `/api/v1/projects`

호환 경로: `POST /api/projects/`

- 로그인된 Django 세션 쿠키가 필요하다.
- 프론트 fetch 요청에는 반드시 `credentials: 'include'` 가 필요하다.
- 생성된 Project 는 현재 로그인한 User 에 귀속된다.
- 프론트 신규 프로젝트 이름 입력 페이지는 로그인 페이지와 별도 라우트로 분리해도 된다.
- 백엔드는 `name`, `project_name`, `projectName` 중 하나로 프로젝트 이름을 받을 수 있다.

### Request

```json
{
  "name": "졸업 작품 리서치",
  "description": "레퍼런스 수집용 프로젝트"
}
```

### Alternate Request

```json
{
  "projectName": "졸업 작품 리서치"
}
```

### Success Response 201

```json
{
  "project_id": "a8d3c0d8-4477-4b4c-a884-b0a30a0c9e3b",
  "id": "a8d3c0d8-4477-4b4c-a884-b0a30a0c9e3b",
  "user_id": "admin",
  "user": "admin",
  "name": "졸업 작품 리서치",
  "project_name": "졸업 작품 리서치",
  "projectName": "졸업 작품 리서치",
  "description": "레퍼런스 수집용 프로젝트",
  "liked_building_ids": [58, 83, 23],
  "hated_building_ids": [101, 104],
  "created_at": "2026-03-15T08:40:00+00:00",
  "updated_at": "2026-03-15T08:40:00+00:00"
}
```

### Conflict Response 409

```json
{
  "error_code": "CONFLICT",
  "message": "project name already exists for this user"
}
```

### GET `/api/v1/projects`

호환 경로: `GET /api/projects/`

현재 로그인한 User 의 Project 목록을 반환한다.

### Success Response 200

```json
{
  "items": [
    {
      "project_id": "a8d3c0d8-4477-4b4c-a884-b0a30a0c9e3b",
      "user_id": "admin",
      "name": "졸업 작품 리서치",
      "description": "레퍼런스 수집용 프로젝트",
      "liked_building_ids": [58, 83, 23],
      "hated_building_ids": [101, 104],
      "created_at": "2026-03-15T08:40:00+00:00",
      "updated_at": "2026-03-15T08:40:00+00:00"
    }
  ],
  "count": 1
}
```

- `liked_building_ids` 는 프로젝트 기준 누적 선호 이미지 id 목록이다.
- `hated_building_ids` 는 프로젝트 기준 누적 비선호 이미지 id 목록이다.
- 초기 선택 10장은 `liked_building_ids` 에 자동 반영된다.
- 이후 `feedback-batch` 의 like/dislike 도 프로젝트에 자동 누적된다.
- 프론트가 기존 로컬 상태 키로 `projectName` 을 사용 중이어도 응답 alias 로 그대로 매핑할 수 있다.

### GET `/api/v1/projects/{project_id}`

호환 경로: `GET /api/projects/{project_id}/`

현재 로그인한 User 의 특정 Project 하나를 반환한다.

- Project 응답에는 아래 필드도 포함된다.
- `analysis_report`: 저장된 종합 리포트 JSON
- `predicted_building_ids`: 최종 추천 후보 id 목록
- `last_report_created_at`: 마지막 리포트 생성 시각
- `latest_convergence`: 최근 수렴 메트릭
- `latest_feedback_summary`: 최근 배치 피드백 요약
- `status`: 프로젝트 상태 (`draft`, `report_ready` 등)

### Not Found Response 404

```json
{
  "error_code": "NOT_FOUND",
  "message": "project not found"
}
```

### POST `/api/v1/projects/{project_id}/report/generate`

선택 결과가 누적된 Project 를 기준으로 Gemini 종합 리포트를 생성하고, Project 에 저장한 뒤 즉시 반환한다.

- 로그인된 Django 세션 쿠키가 필요하다.
- 프론트 fetch 요청에는 반드시 `credentials: 'include'` 가 필요하다.

### Success Response 200

```json
{
  "project_id": "a8d3c0d8-4477-4b4c-a884-b0a30a0c9e3b",
  "status": "report_ready",
  "last_report_created_at": "2026-03-15T09:10:00+00:00",
  "report": {
    "title": "도시를 산책하는 시인",
    "description": "재료와 분위기 선택이 절제되어 있고, 감성적이면서도 구조적인 공간을 선호합니다.",
    "persona_image": null,
    "stats": {
      "total_liked": 12,
      "matched_in_db": 12,
      "top_programs": [["Museum", 4]],
      "top_moods": [["Minimal", 5]],
      "top_materials": [["Concrete", 6]]
    }
  }
}
```

### GET `/api/v1/projects/{project_id}/report`

이미 생성되어 저장된 Project 종합 리포트를 반환한다.

### Not Found Response 404

```json
{
  "error_code": "NOT_FOUND",
  "message": "report not generated yet"
}
```

## 4. Submit Swipe

### POST `/api/v1/analysis/sessions/{session_id}/swipes`

현재 카드에 대해 like 또는 dislike 를 제출하고, 다음 카드를 받는다.

### Request

```json
{
  "image_id": 123,
  "action": "like",
  "idempotency_key": "evt_custom_001"
}
```

`idempotency_key`는 선택 사항이다. 없으면 서버가 자동 생성한다.

### Success Response 200

```json
{
  "accepted": true,
  "session_status": "active",
  "progress": {
    "current_round": 1,
    "total_rounds": 20,
    "like_count": 1,
    "dislike_count": 0
  },
  "next_image": {
    "image_id": 456,
    "building_id": "456",
    "image_title": "Next Project",
    "title": "Next Project",
    "image_url": "https://...",
    "imageUrl": "https://...",
    "source_url": "https://...",
    "metadata": {
      "axis_typology": "Gallery",
      "axis_architects": "SANAA",
      "axis_country": "Japan",
      "axis_area_m2": null,
      "axis_capacity": null,
      "axis_year": "2021",
      "axis_mood": "Soft",
      "axis_material": "Glass"
    },
    "gallery": []
  },
  "is_analysis_completed": false
}
```

### Final Swipe Response 200

마지막 라운드면 `next_image`는 `null` 이고 상태가 `report_ready` 로 바뀐다.

```json
{
  "accepted": true,
  "session_status": "report_ready",
  "progress": {
    "current_round": 20,
    "total_rounds": 20,
    "like_count": 8,
    "dislike_count": 12
  },
  "next_image": null,
  "is_analysis_completed": true
}
```

### Duplicate Event Response 200

이미 처리한 `idempotency_key`를 다시 보내면 중복 이벤트로 무시된다.

```json
{
  "accepted": true,
  "message": "duplicate event ignored",
  "session_status": "active",
  "progress": {
    "current_round": 1,
    "total_rounds": 20,
    "like_count": 1,
    "dislike_count": 0
  },
  "is_analysis_completed": false,
  "next_image": null
}
```

### Session Not Found Response 404

```json
{
  "accepted": false,
  "error_code": "NOT_FOUND",
  "message": "session not found"
}
```

### Invalid Input Response 400

```json
{
  "error_code": "INVALID_INPUT",
  "message": "image_id(int) is required"
}
```

## 5. Get Result

### GET `/api/v1/analysis/sessions/{session_id}/result`

호환 메서드: `POST /api/v1/analysis/sessions/{session_id}/result`

세션 종료 후 좋아요 이미지와 추천 이미지를 반환한다. 구현상 세션이 아직 진행 중이어도 호출 가능하며, 호출 시 결과를 생성하면서 세션 상태를 `completed` 로 바꾼다.

### Success Response 200

```json
{
  "session_id": "sess_ab12cd34ef56gh78",
  "session_status": "completed",
  "liked_images": [
    {
      "image_id": 123,
      "building_id": "123",
      "image_title": "Liked Project",
      "title": "Liked Project",
      "image_url": "https://...",
      "imageUrl": "https://...",
      "source_url": "https://...",
      "metadata": {
        "axis_typology": "Museum",
        "axis_architects": "OMA",
        "axis_country": "France",
        "axis_area_m2": null,
        "axis_capacity": null,
        "axis_year": "2024",
        "axis_mood": "Minimal",
        "axis_material": "Concrete"
      },
      "gallery": []
    }
  ],
  "predicted_like_images": [
    {
      "image_id": 456,
      "building_id": "456",
      "image_title": "Recommended Project",
      "title": "Recommended Project",
      "image_url": "https://...",
      "imageUrl": "https://...",
      "source_url": "https://...",
      "metadata": {
        "axis_typology": "Gallery",
        "axis_architects": "SANAA",
        "axis_country": "Japan",
        "axis_area_m2": null,
        "axis_capacity": null,
        "axis_year": "2021",
        "axis_mood": "Soft",
        "axis_material": "Glass"
      },
      "gallery": []
    }
  ],
  "predicted_like_count": 1,
  "analysis_report": {
    "dominant_axes": ["axis_source_oma"],
    "keywords": ["concrete", "minimal"],
    "keyword_count": 2,
    "summary_text": "User preference is concentrated around: concrete, minimal"
  }
}
```

### Not Found Response 404

```json
{
  "error_code": "NOT_FOUND",
  "message": "session not found"
}
```

## 6. Debug Session

### GET `/api/v1/analysis/sessions/{session_id}/debug`

프론트 디버깅용 세션 내부 상태 조회 엔드포인트다.

### Success Response 200

```json
{
  "session_id": "sess_ab12cd34ef56gh78",
  "user_id": "user123",
  "project_id": "proj_1710000000000",
  "session_status": "active",
  "is_analysis_completed": false,
  "progress": {
    "current_round": 3,
    "total_rounds": 20,
    "like_count": 1,
    "dislike_count": 2
  },
  "exposed_image_ids": [11, 22, 33, 44],
  "liked_image_ids": [22],
  "disliked_image_ids": [11, 33],
  "swiped_image_ids": [11, 22, 33],
  "options": {
    "initial_image_id": 1,
    "initial_diverse_count": 10,
    "initial_analysis_start_rounds": 10,
    "pending_initial_injection_prob": 0.0,
    "total_rounds": 20,
    "like_weight": 0.5,
    "dislike_weight": -1.0,
    "epsilon": 0.3,
    "epsilon_min": 0.05,
    "epsilon_decay": 0.995,
    "distance_metric": "cosine",
    "final_recommendation_count": 20,
    "report_keyword_count": 5
  }
}
```

### Not Found Response 404

```json
{
  "error_code": "NOT_FOUND",
  "message": "session not found"
}
```

## 프론트 구현 메모

- 로그인 응답 필드명은 `userId`, `isNew` 가 아니라 `user_id`, `is_new` 다.
- 카드 객체는 `image_url` 과 `imageUrl` 를 둘 다 내려준다.
- 추천 결과 엔드포인트는 `GET`, `POST` 둘 다 지원하지만 프론트에서는 `GET` 으로 고정하는 편이 단순하다.
- `result` 호출은 세션 상태를 `completed` 로 바꾸므로, 실제 UX에서는 마지막 스와이프 이후 또는 결과 보기 버튼 클릭 시점에만 호출하는 편이 안전하다.
- `health`, `debug` 는 운영 기능이라기보다 개발 보조용이다.

## 프론트 AI에 보여줄 파일

- 1순위: [3. in_out/api_contract.md](3.%20in_out/api_contract.md)
- 참고용 원본 구현: [3. in_out/in_out.py](3.%20in_out/in_out.py)
- 과거 설명 문서: [3. in_out/frontend.md](3.%20in_out/frontend.md)