# ArchiTinder 프론트엔드 문서

## 1. 프로젝트 구조

```
archithon-app/
├── src/
│   ├── App.jsx               # 루트 컴포넌트 · 전체 상태 관리
│   ├── LoginPage.jsx         # 로그인 화면
│   ├── SetupPage.jsx         # 폴더 생성/업데이트 설정 화면
│   ├── SwipePage.jsx         # 스와이프 카드 화면
│   ├── FavoritesPage.jsx     # 폴더 목록 + 이미지 보드
│   └── buildings_master.json # 건물 데이터 (정적 파일, 빌드에 포함)
server/
├── server.js                 # Express 인증 서버 (포트 3001)
└── users.json                # 유저 계정 저장소 (ID + bcrypt 해시 비밀번호)
```

---

## 2. 현재 데이터 저장 방식

### 인증 (Auth)
| 항목 | 저장 위치 | 형식 |
|------|-----------|------|
| 로그인 상태 | `sessionStorage` | `archithon_user` = `"userId"` (탭 닫으면 삭제) |
| 계정 정보 | `server/users.json` | `[{ id, password(bcrypt hash), createdAt }]` |

### 프로젝트 데이터
| 항목 | 저장 위치 | 키 형식 |
|------|-----------|---------|
| 프로젝트 목록 | `localStorage` | `archithon_projects_{userId}` |
| 마지막 활성 프로젝트 | `localStorage` | `archithon_activeId_{userId}` |

> 유저별로 키가 분리되어 있어 계정마다 독립된 데이터를 가짐.

---

## 3. 건물 데이터 (buildings_master.json)

### 현재 구조
```json
{
  "Buildings": [
    {
      "building_id": "B0001",
      "building_name": "2024 Paris Olympics' Aquatic Center",
      "architects": "MAD",
      "area_m2": null,
      "capacity": null,
      "imageUrl": "/images/B0001.jpg",
      "url": "https://archello.com/...",
      "typology": "Aquatic Center",
      "country": "France"
    },
    ...
  ]
}
```

### 프론트에서 가공 후 사용하는 필드
```js
{
  building_id,       // 고유 ID (e.g. "B0001")
  building_name,     // 원본 이름
  title,             // = building_name (표시용 alias)
  architects,        // 건축사무소
  area_m2,           // 면적 (null 허용)
  capacity,          // 수용 인원 (null 허용)
  imageUrl,          // 이미지 경로 (/images/B0001.jpg)
  url,               // 참고 링크
  typology,          // 건물 유형 (e.g. "Stadium", "Arena")
  country,           // 국가
  tags,              // 자동 생성 태그 배열 (이름/건축사 기반, 최대 3개)
}
```

- 현재 총 **65개** 건물 (추후 ~3000개로 확장 예정)
- `imageUrl`은 `/images/B0001.jpg` 형태의 로컬 경로
- `imageUrl`이 없으면 `picsum.photos` 랜덤 이미지로 fallback

---

## 4. 프로젝트(폴더) 데이터 구조

`localStorage`에 JSON 배열로 저장됨.

```js
{
  id: "proj_1710000000000",       // timestamp 기반 고유 ID
  projectName: "졸업 작품 리서치",
  filters: {
    typologies: ["Stadium", "Arena"],  // 선택한 건물 유형 (빈 배열 = 전체)
    minArea: 0,                         // 최소 면적 (m²)
    maxArea: 500000,                    // 최대 면적 (m²)
  },
  likedBuildings: [                 // 좋아요한 건물 객체 배열 (전체 필드 포함)
    { building_id, title, imageUrl, typology, country, ... },
    ...
  ],
  swipedIds: ["B0001", "B0003"],   // 스와이프 완료한 building_id 배열
  createdAt: "2026-03-14T08:00:00.000Z",
}
```

---

## 5. 인증 API

**서버**: `http://localhost:3001`

### POST `/api/auth/login`
- **요청**:
  ```json
  { "id": "user123", "password": "1234" }
  ```
- **응답 (성공)**:
  ```json
  { "success": true, "userId": "user123", "isNew": false }
  ```
  - `isNew: true` = 신규 계정 자동 생성
  - `isNew: false` = 기존 계정 로그인
- **응답 (실패)**:
  ```json
  { "error": "비밀번호가 틀렸습니다." }
  ```
- **유효성 검사**: ID 2자 이상, 비밀번호 4자 이상
- **중복 ID**: 동일 ID 존재 시 비밀번호 검증 → 불일치면 에러 반환

---

## 6. 화면 전환 흐름

```
[LoginPage]
    ↓ 로그인/계정생성
[ProjectNamePage - 신규 프로젝트 이름 입력]
  ↓ 프로젝트 생성 API 호출
[SetupPage - choose]
  ├─ 신규 폴더 생성 → [SetupPage - new-form] → [SwipePage]
    └─ 기존 폴더 업데이트
            ├─ 폴더 선택 → 필터 유지 → [SwipePage]
            └─ 폴더 선택 → 필터 변경 → [SetupPage - update-form] → [SwipePage]

[SwipePage]
    ├─ View Results 버튼 (30% 이상 스와이프 시 노출) → [FavoritesPage - 해당 폴더 상세]
    └─ 모두 스와이프 완료 → "이미지 보드 보기" 버튼 → [FavoritesPage - 해당 폴더 상세]

[FavoritesPage - 폴더 목록]
    └─ 폴더 클릭 → [FavoritesPage - 폴더 상세 (이미지 보드)]

하단 탭바:
    ＋ New     → SetupPage (choose 화면으로 리셋)
    🃏 Swipe   → SwipePage (활성 프로젝트 없으면 비활성)
    📁 Folders → FavoritesPage 폴더 목록 (상세 화면에서 탭 누르면 목록으로 리셋)
```

### 신규 프로젝트 생성 라우트 분리

- 로그인 직후에는 별도 라우트 예: `/projects/new` 로 이동한다.
- 이 화면에서는 프로젝트 이름만 입력받는다.
- 이름 입력 후 `POST /api/v1/projects` 호출로 Django `Project` 를 생성한다.
- 생성 성공 후 응답의 `project_id` 를 활성 프로젝트로 저장하고 다음 화면으로 이동한다.
- 이후 분석 과정과 리포트 저장은 기존과 동일하게 해당 `Project` 에 누적된다.

### 신규 프로젝트 생성 요청 예시

```js
async function createProject(projectName) {
  const response = await fetch('http://127.0.0.1:8000/api/v1/projects', {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      projectName,
    }),
  });

  if (!response.ok) {
    throw new Error('프로젝트 생성 실패');
  }

  return response.json();
}
```

### 프론트 저장 기준

- 입력 필드명은 `projectName` 이어도 된다.
- 백엔드는 `name`, `project_name`, `projectName` 을 모두 허용한다.
- 응답에도 `name`, `project_name`, `projectName` 이 같이 포함되므로 기존 프론트 상태 구조에 바로 연결 가능하다.

---

## 7. Supabase 연결 시 교체 포인트

백엔드 연결 시 아래 항목들을 순서대로 교체하면 됩니다.

| 현재 | 교체 대상 | 교체 방법 |
|------|-----------|-----------|
| `server/users.json` | Supabase Auth | `LoginPage.jsx`의 fetch → Supabase `signInWithPassword` / `signUp` |
| `sessionStorage` (로그인 상태) | Supabase 세션 | Supabase SDK가 자동 관리 |
| `localStorage` (프로젝트 데이터) | Supabase DB | `App.jsx`의 `useEffect` → Supabase `upsert` / `select` |
| `buildings_master.json` (정적) | Supabase DB | `App.jsx` 상단 import → API fetch로 교체 |

---

## 8. 벡터 DB 연동 시 추가될 데이터

스와이프 이벤트를 서버에 전달할 때 아래 형태로 보내면 됩니다.

```json
{
  "userId": "user123",
  "buildingId": "B0001",
  "action": "like",           // "like" | "dislike"
  "timestamp": "2026-03-14T08:00:00.000Z",
  "projectId": "proj_1710000000000"
}
```

- 서버에서 해당 건물의 임베딩 벡터를 조회
- 사용자 선호도 벡터 = 좋아요 건물 벡터들의 **가중 평균** 
- 이 선호도 벡터로 유사 건물 추천

현재 `App.jsx` → `handleSwipeCard`에서 이 API 호출을 추가하면 됩니다.
