# Django Migration Architecture

## 목적

기존 프로토타입을 유지한 채로 Django REST Framework 기반 백엔드를 병행 구축한다.

핵심 원칙은 두 가지다.

1. 기존 추천 엔진과 HTTP 브리지를 즉시 폐기하지 않는다.
2. Django는 사용자 관리, 세션 영속화, 운영 기능을 먼저 가져간다.

## 현재 상태

- 레거시 HTTP 브리지: [3. in_out/in_out.py](3.%20in_out/in_out.py)
- 레거시 추천 엔진: [2. analysis/analysis.py](2.%20analysis/analysis.py)
- 신규 Django 프로젝트: [backend/manage.py](backend/manage.py)
- 신규 Django 설정: [backend/config/settings.py](backend/config/settings.py)

## 권장 병행 구조

### 1단계

- 인증과 사용자 관리는 Django로 이관한다.
- 프론트는 로그인 관련 호출부터 Django API를 사용한다.
- 기존 SQLite `user_tracking.db`는 읽기 전용 참조 대상으로 두고, 신규 데이터는 Django DB에 적재한다.

### 2단계

- 분석 세션과 스와이프 이벤트를 Django 모델로 저장한다.
- 실제 추천 계산은 당분간 [2. analysis/analysis.py](2.%20analysis/analysis.py)를 서비스 레이어에서 호출한다.
- 즉, 추천 알고리즘은 유지하고 세션 저장소만 메모리에서 DB로 바꾼다.

### 3단계

- [3. in_out/in_out.py](3.%20in_out/in_out.py)의 엔드포인트를 Django API로 하나씩 대체한다.
- 교체 완료 후 레거시 브리지는 제거하거나 내부 fallback 용도로만 남긴다.

## 새 backend 폴더의 역할

- `backend/config`: Django project 설정
- `backend/apps/accounts`: 사용자/프로필 관리
- `backend/apps/recommendation`: 세션, 스와이프, 추천 API 진입점

## 추천 흐름 목표 아키텍처

1. 프론트 요청이 Django API에 들어온다.
2. Django가 User, Project, Session, SwipeEvent 를 읽고 쓴다.
3. Django service layer가 레거시 분석 엔진을 호출한다.
4. 결과를 Django serializer 또는 DRF Response로 프론트에 반환한다.

## 왜 이 방식이 맞는가

- 추천 코어를 재작성하지 않아도 된다.
- 개인화/유저 관리/운영 툴은 Django가 즉시 해결한다.
- 마이그레이션 중에도 기존 프로토타입이 계속 동작한다.

## 지금 바로 가능한 URL

- `GET /api/health/`
- `GET /api/migration-status/`

구현 위치:

- [backend/apps/recommendation/views.py](backend/apps/recommendation/views.py)
- [backend/apps/recommendation/urls.py](backend/apps/recommendation/urls.py)