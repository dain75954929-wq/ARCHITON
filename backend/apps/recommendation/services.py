"""
report/services.py
좋아요한 건축물 데이터를 분석하여 취향 리포트를 생성합니다.
- Gemini LLM으로 텍스트 분석 (한줄 요약 + 설명)
- Gemini Image Generation으로 페르소나 이미지 생성
"""
import json
import base64
import traceback
import os
from collections import Counter
from django.utils import timezone
import psycopg2

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None
    types = None

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')
_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client

    if genai is None or types is None:
        raise RuntimeError('google-genai package is required. Install it with pip install google-genai')

    _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client

def _get_db_connection():
    return psycopg2.connect(
        dbname=os.getenv('ARCHITON_DB_NAME', 'into_database'),
        host=os.getenv('ARCHITON_DB_HOST', 'localhost'),
        port=int(os.getenv('ARCHITON_DB_PORT', '5432')),
        user=os.getenv('ARCHITON_DB_USER', 'postgres'),
        password=os.getenv('ARCHITON_DB_PASSWORD', ''),
    )


def _normalize_building_ids(liked_buildings: list) -> list[int]:
    normalized_ids: list[int] = []
    seen_ids: set[int] = set()

    for item in liked_buildings:
        raw_id = None
        if isinstance(item, dict):
            raw_id = item.get('image_id') or item.get('building_id')
        else:
            raw_id = item

        try:
            image_id = int(raw_id)
        except (TypeError, ValueError):
            continue

        if image_id in seen_ids:
            continue
        seen_ids.add(image_id)
        normalized_ids.append(image_id)

    return normalized_ids


def _lookup_buildings(liked_buildings: list) -> list[dict]:
    """
    liked_buildings (image_id 리스트 또는 card dict 리스트)에서
    architecture_vectors의 속성 정보를 조회합니다.
    """
    image_ids = _normalize_building_ids(liked_buildings)
    if not image_ids:
        return []

    table_name = os.getenv('ARCHITON_DB_TABLE', 'architecture_vectors')
    query = f"""
        SELECT
            id,
            url,
            project_name,
            architect,
            location_country,
            area,
            program,
            year,
            mood,
            material
        FROM {table_name}
        WHERE id = ANY(%s::bigint[])
    """

    with _get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (image_ids,))
            rows = cur.fetchall()

    by_id = {
        int(row[0]): {
            'id': int(row[0]),
            'url': row[1] or '',
            'project_name': row[2] or '',
            'architect': row[3] or '',
            'location_country': row[4] or '',
            'area': row[5] or '',
            'program': row[6] or '',
            'year': row[7],
            'mood': row[8] or '',
            'material': row[9] or '',
        }
        for row in rows
    }

    return [by_id[image_id] for image_id in image_ids if image_id in by_id]


def _aggregate_attributes(buildings: list[dict]) -> dict:
    """건축물 속성을 집계하여 요약합니다."""
    programs = Counter()
    moods = Counter()
    materials = Counter()
    countries = Counter()
    architects = Counter()
    years = []

    for b in buildings:
        if b.get('program'):
            programs[b['program']] += 1
        if b.get('mood'):
            moods[b['mood']] += 1
        if b.get('material'):
            for m in b['material'].replace('/', ',').split(','):
                m = m.strip()
                if m:
                    materials[m] += 1
        if b.get('location_country'):
            countries[b['location_country']] += 1
        if b.get('architect'):
            architects[b['architect'].split('+')[0].split(',')[0].strip()] += 1
        if b.get('year'):
            try:
                years.append(int(b['year']))
            except (ValueError, TypeError):
                pass

    return {
        'total': len(buildings),
        'top_programs': programs.most_common(5),
        'top_moods': moods.most_common(5),
        'top_materials': materials.most_common(5),
        'top_countries': countries.most_common(5),
        'top_architects': architects.most_common(3),
        'year_range': (min(years), max(years)) if years else None,
    }


# ============================================================
# LLM Text Analysis
# ============================================================
def _generate_text_report(aggregated: dict) -> dict:
    """Gemini LLM을 사용하여 취향 분석 텍스트를 생성합니다."""
    prompt = f"""당신은 건축 취향 분석 전문가입니다.
사용자가 좋아요한 건축물 {aggregated['total']}개의 속성을 분석하여 취향 리포트를 작성하세요.

## 데이터
- 선호 프로그램: {aggregated['top_programs']}
- 선호 분위기: {aggregated['top_moods']}
- 선호 재료: {aggregated['top_materials']}
- 선호 국가: {aggregated['top_countries']}
- 선호 건축가: {aggregated['top_architects']}
- 연도 범위: {aggregated['year_range']}

## 응답 형식 (반드시 JSON으로)
{{
  "title": "한줄 요약 (예: '열정적이고 사색을 좋아하는 철학가'). 이 사람의 성격을 사람 유형에 비유. 15자 이내.",
  "description": "2-3문장으로 이 사람의 건축 취향을 설명. 어떤 건축물을 좋아하는지, 그 취향이 어떤 성격의 사람과 닮았는지. 한국어로."
}}

주의사항:
- title은 반드시 사람에 비유 (예: 철학가, 모험가, 시인, 과학자 등)
- description은 건축 속성과 연결지어 설명
- 친근하지만 전문적인 톤
"""

    client = _get_client()
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type='application/json',
            temperature=0.7,
        ),
    )
    return json.loads(response.text)


# ============================================================
# Image Generation (Nano Banana = Gemini native image gen)
# ============================================================
def _generate_persona_image(title: str, description: str) -> str | None:
    """Gemini Image Generation으로 페르소나 이미지를 생성합니다."""
    try:
        prompt = f"""Create an artistic, abstract portrait illustration representing an architectural taste persona.
The persona is: "{title}"
Description: "{description}"

Style guidelines:
- Abstract, artistic illustration style (NOT photorealistic)
- Use architectural elements and building forms integrated into the portrait
- Modern, sophisticated color palette
- Clean, minimalist composition
- No text in the image
- Professional, gallery-quality artwork
- Square format
"""
        client = _get_client()
        response = client.models.generate_content(
            model='gemini-2.0-flash-exp',
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=['TEXT', 'IMAGE'],
            ),
        )

        # Extract image from response
        for part in response.candidates[0].content.parts:
            if part.inline_data and part.inline_data.mime_type.startswith('image/'):
                img_bytes = part.inline_data.data
                mime = part.inline_data.mime_type
                b64 = base64.b64encode(img_bytes).decode('utf-8')
                return f'data:{mime};base64,{b64}'

        print('[Report] No image generated in response')
        return None

    except Exception as e:
        print(f'[Report] Image generation failed: {e}')
        traceback.print_exc()
        return None


# ============================================================
# Public API
# ============================================================
def generate_report(project) -> dict:
    """
    프로젝트의 liked_building_ids를 분석하여 리포트를 생성합니다.

    Args:
        project: Project 모델 인스턴스
    Returns:
        dict: {title, description, persona_image}
    """
    liked = project.liked_building_ids or []
    if not liked:
        return {
            'title': '아직 탐험 중인 여행자',
            'description': '아직 충분한 건축물을 선택하지 않았습니다. 더 많은 건축물을 스와이프해보세요!',
            'persona_image': None,
        }

    # 1. DB에서 건축물 속성 조회
    buildings = _lookup_buildings(liked)
    print(f'[Report] Found {len(buildings)}/{len(liked)} buildings in DB')

    if not buildings:
        return {
            'title': '자유로운 영혼의 탐험가',
            'description': '선택하신 건축물의 상세 정보를 찾을 수 없었지만, 당신의 독특한 안목은 분명합니다!',
            'persona_image': None,
        }

    # 2. 속성 집계
    aggregated = _aggregate_attributes(buildings)
    print(f'[Report] Aggregated: {aggregated}')

    # 3. LLM 텍스트 분석
    text_report = _generate_text_report(aggregated)
    title = text_report.get('title', '건축을 사랑하는 탐험가')
    description = text_report.get('description', '')
    print(f'[Report] Title: {title}')

    # 4. 이미지 생성
    persona_image = _generate_persona_image(title, description)
    print(f'[Report] Image generated: {bool(persona_image)}')

    report = {
        'title': title,
        'description': description,
        'persona_image': persona_image,
        'stats': {
            'total_liked': len(liked),
            'matched_in_db': len(buildings),
            'top_programs': aggregated['top_programs'],
            'top_moods': aggregated['top_moods'],
            'top_materials': aggregated['top_materials'],
        },
    }

    # 5. DB에 저장
    project.analysis_report = report
    project.final_report = json.dumps(report, ensure_ascii=False)
    project.last_report_created_at = timezone.now()
    project.status = 'report_ready'
    project.save(update_fields=['analysis_report', 'final_report', 'last_report_created_at', 'status'])

    return report
