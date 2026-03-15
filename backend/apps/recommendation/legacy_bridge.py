from __future__ import annotations

import math
import os
import random
import statistics
import sys
from pathlib import Path
from threading import Lock
from typing import Any

from django.contrib.auth import get_user_model

from .models import AnalysisSession, PreferenceBatchSession, Project


PROJECT_ROOT = Path(__file__).resolve().parents[3]
ANALYSIS_DIR = PROJECT_ROOT / '2. analysis'

if str(ANALYSIS_DIR) not in sys.path:
	sys.path.insert(0, str(ANALYSIS_DIR))

from analysis import AnalysisOptions, DbConfig  # type: ignore[import-not-found]
from analysis_service import AnalysisService  # type: ignore[import-not-found]


User = get_user_model()

_SERVICE_LOCK = Lock()
_SERVICE: AnalysisService | None = None

LIKE_WEIGHT = 1.0
DISLIKE_WEIGHT = 0.3
MIN_SWIPES = 10
MAX_SWIPES = 25
CONVERGENCE_THRESHOLD = 0.70
STABILITY_THRESHOLD = 0.03
STABILITY_NORMALIZATION = 0.1
COHERENCE_MARGIN = 0.3
RECENT_WINDOW = 5
TOP_K_DENSITY_K = 10
BASELINE_SAMPLE_PAIRS = 500
DEFAULT_BATCH_SIZE = 5


def map_backend_card_to_frontend(card: dict[str, Any] | None) -> dict[str, Any] | None:
	if not card:
		return None

	image_id = int(card.get('image_id'))
	image_title = str(card.get('image_title') or 'untitled')
	metadata = card.get('metadata') or {}
	image_url = card.get('image_url') or f'https://picsum.photos/seed/architon-{image_id}/800/1000'

	return {
		'image_id': image_id,
		'building_id': str(image_id),
		'image_title': image_title,
		'title': image_title,
		'image_url': image_url,
		'imageUrl': image_url,
		'source_url': card.get('source_url'),
		'metadata': {
			'axis_typology': metadata.get('program'),
			'axis_architects': metadata.get('architect'),
			'axis_country': metadata.get('axis_location'),
			'axis_area_m2': None,
			'axis_capacity': None,
			'axis_year': metadata.get('axis_year'),
			'axis_mood': metadata.get('mood'),
			'axis_material': metadata.get('material'),
		},
		'gallery': [],
	}


def get_analysis_service() -> AnalysisService:
	global _SERVICE
	with _SERVICE_LOCK:
		if _SERVICE is None:
			cfg = DbConfig(
				host=os.getenv('ARCHITON_DB_HOST', 'localhost'),
				port=int(os.getenv('ARCHITON_DB_PORT', '5432')),
				user=os.getenv('ARCHITON_DB_USER', 'postgres'),
				password=os.getenv('ARCHITON_DB_PASSWORD', ''),
				db_name=os.getenv('ARCHITON_DB_NAME', 'into_database'),
				table=os.getenv('ARCHITON_DB_TABLE', 'architecture_vectors'),
			)
			options = AnalysisOptions(
				total_rounds=int(os.getenv('ARCHITON_TOTAL_ROUNDS', '20')),
			)
			_SERVICE = AnalysisService(cfg=cfg, options=options)
		return _SERVICE


def clamp(value: float, lower: float, upper: float) -> float:
	return max(lower, min(upper, value))


def dedupe_preserve_order(image_ids: list[int]) -> list[int]:
	seen: set[int] = set()
	result: list[int] = []
	for image_id in image_ids:
		if image_id in seen:
			continue
		seen.add(image_id)
		result.append(image_id)
	return result


def merge_project_feedback(project: Project, *, liked_ids: list[int] | None = None, hated_ids: list[int] | None = None) -> None:
	liked_updates = dedupe_preserve_order([int(image_id) for image_id in (liked_ids or [])])
	hated_updates = dedupe_preserve_order([int(image_id) for image_id in (hated_ids or [])])

	liked_state = dedupe_preserve_order([int(image_id) for image_id in project.liked_building_ids])
	hated_state = dedupe_preserve_order([int(image_id) for image_id in project.hated_building_ids])

	if liked_updates:
		hated_state = [image_id for image_id in hated_state if image_id not in set(liked_updates)]
		liked_state = dedupe_preserve_order(liked_state + liked_updates)

	if hated_updates:
		liked_state = [image_id for image_id in liked_state if image_id not in set(hated_updates)]
		hated_state = dedupe_preserve_order(hated_state + hated_updates)

	project.liked_building_ids = liked_state
	project.hated_building_ids = hated_state
	project.save(update_fields=['liked_building_ids', 'hated_building_ids', 'updated_at'])


def l2_norm(vector: list[float]) -> float:
	return math.sqrt(sum(value * value for value in vector))


def normalize(vector: list[float]) -> list[float]:
	norm = l2_norm(vector)
	if norm == 0:
		return vector
	return [value / norm for value in vector]


def mean_vectors(vectors: list[list[float]]) -> list[float] | None:
	if not vectors:
		return None
	dimension = len(vectors[0])
	totals = [0.0] * dimension
	for vector in vectors:
		for index, value in enumerate(vector):
			totals[index] += value
	return [value / len(vectors) for value in totals]


def subtract_vectors(left: list[float], right: list[float]) -> list[float]:
	return [left_value - right_value for left_value, right_value in zip(left, right)]


def cosine_similarity(left: list[float], right: list[float]) -> float:
	return sum(left_value * right_value for left_value, right_value in zip(left, right))


def l2_distance(left: list[float] | None, right: list[float] | None) -> float:
	if left is None or right is None:
		return 1.0
	return math.sqrt(sum((left_value - right_value) ** 2 for left_value, right_value in zip(left, right)))


def get_existing_embeddings(image_ids: list[int]) -> dict[int, list[float]]:
	service = get_analysis_service()
	return service.db.get_embeddings_for_ids(dedupe_preserve_order(image_ids))


def compute_baseline_similarity() -> float:
	service = get_analysis_service()
	all_ids = service.db.get_all_image_ids()
	if len(all_ids) < 2:
		return 0.0

	embeddings = service.db.get_embeddings_for_ids(all_ids)
	available_ids = list(embeddings.keys())
	if len(available_ids) < 2:
		return 0.0

	target_samples = min(BASELINE_SAMPLE_PAIRS, (len(available_ids) * (len(available_ids) - 1)) // 2)
	seen_pairs: set[tuple[int, int]] = set()
	similarities: list[float] = []
	attempts = 0
	max_attempts = target_samples * 10 if target_samples > 0 else 0

	while len(similarities) < target_samples and attempts < max_attempts:
		left_id, right_id = random.sample(available_ids, 2)
		pair = (left_id, right_id) if left_id < right_id else (right_id, left_id)
		attempts += 1
		if pair in seen_pairs:
			continue
		seen_pairs.add(pair)
		similarities.append(cosine_similarity(embeddings[left_id], embeddings[right_id]))

	if not similarities:
		return 0.0
	return float(sum(similarities) / len(similarities))


def build_preference_vector(seed_image_ids: list[int], liked_image_ids: list[int], disliked_image_ids: list[int]) -> list[float] | None:
	liked_ids = dedupe_preserve_order(seed_image_ids + liked_image_ids)
	all_ids = dedupe_preserve_order(liked_ids + disliked_image_ids)
	embeddings = get_existing_embeddings(all_ids)
	liked_vectors = [embeddings[image_id] for image_id in liked_ids if image_id in embeddings]
	disliked_vectors = [embeddings[image_id] for image_id in disliked_image_ids if image_id in embeddings]

	liked_mean = mean_vectors(liked_vectors)
	disliked_mean = mean_vectors(disliked_vectors)

	if liked_mean is None and disliked_mean is None:
		return None
	if liked_mean is None and disliked_mean is not None:
		return normalize([-DISLIKE_WEIGHT * value for value in disliked_mean])
	if liked_mean is not None and disliked_mean is None:
		return normalize([LIKE_WEIGHT * value for value in liked_mean])

	assert liked_mean is not None
	assert disliked_mean is not None
	combined = [
		LIKE_WEIGHT * liked_value - DISLIKE_WEIGHT * disliked_value
		for liked_value, disliked_value in zip(liked_mean, disliked_mean)
	]
	return normalize(combined)


def compute_coherence_score(image_ids: list[int], baseline_similarity: float) -> float:
	ordered_ids = dedupe_preserve_order(image_ids)
	if len(ordered_ids) < 2:
		return 0.0

	embeddings = get_existing_embeddings(ordered_ids)
	available_ids = [image_id for image_id in ordered_ids if image_id in embeddings]
	if len(available_ids) < 2:
		return 0.0

	similarities: list[float] = []
	for left_index, left_id in enumerate(available_ids):
		for right_id in available_ids[left_index + 1:]:
			similarities.append(cosine_similarity(embeddings[left_id], embeddings[right_id]))

	if not similarities:
		return 0.0
	mean_similarity = sum(similarities) / len(similarities)
	return clamp((mean_similarity - baseline_similarity) / COHERENCE_MARGIN, 0.0, 1.0)


def compute_top_k_density(preference_vector: list[float] | None, excluded_ids: list[int]) -> float:
	if preference_vector is None:
		return 0.0

	service = get_analysis_service()
	top_ids = service.db.get_top_candidates_by_pref(
		pref_vector=preference_vector,
		excluded_ids=set(excluded_ids),
		limit=TOP_K_DENSITY_K,
	)
	if len(top_ids) < 2:
		return 0.0

	embeddings = get_existing_embeddings(top_ids)
	scores = [cosine_similarity(preference_vector, embeddings[image_id]) for image_id in top_ids if image_id in embeddings]
	if len(scores) < 2:
		return 0.0
	return clamp(1.0 - (statistics.pstdev(scores) / 0.1), 0.0, 1.0)


def build_batch_cards(preference_vector: list[float] | None, excluded_ids: list[int], limit: int) -> list[dict[str, Any]]:
	service = get_analysis_service()
	if preference_vector is None:
		remaining_ids = [image_id for image_id in service.db.get_all_image_ids() if image_id not in set(excluded_ids)]
		candidate_ids = service.db.get_diverse_sample_ids(candidate_ids=remaining_ids, target_count=limit)
	else:
		candidate_ids = service.db.get_top_candidates_by_pref(
			pref_vector=preference_vector,
			excluded_ids=set(excluded_ids),
			limit=limit,
		)

	cards = [service.db.get_image_card(image_id) for image_id in candidate_ids]
	return [mapped for mapped in (map_backend_card_to_frontend(card) for card in cards) if mapped is not None]


def summarize_feedback(session: PreferenceBatchSession) -> dict[str, Any]:
	liked_count = len(dedupe_preserve_order(session.seed_image_ids + session.liked_image_ids))
	disliked_count = len(dedupe_preserve_order(session.disliked_image_ids))
	like_ratio = 0.0 if session.swipe_count == 0 else len(session.liked_image_ids) / session.swipe_count
	return {
		'swipe_count': session.swipe_count,
		'seed_count': len(dedupe_preserve_order(session.seed_image_ids)),
		'liked_count': liked_count,
		'disliked_count': disliked_count,
		'like_ratio': like_ratio,
	}


def serialize_convergence(session: PreferenceBatchSession) -> dict[str, Any]:
	return {
		'is_converged': session.is_converged,
		'convergence_score': session.convergence_score,
		'pref_change': session.pref_change,
		'baseline_similarity': session.baseline_similarity,
		'stability_score': session.stability_score,
		'coherence_score': session.coherence_score,
		'recent_coherence_score': session.recent_coherence_score,
		'top_k_density_score': session.top_k_density_score,
		'warning': session.warning or '',
		'terminated_reason': session.terminated_reason or '',
	}


def serialize_preference_batch_response(
	session: PreferenceBatchSession,
	images: list[dict[str, Any]],
	*,
	final_recommendations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
	return {
		'session_id': str(session.session_id),
		'project_id': str(session.project.project_id),
		'session_status': session.status,
		'batch_index': session.batch_index,
		'batch_size': session.batch_size,
		'images': images,
		'feedback_summary': summarize_feedback(session),
		'convergence': serialize_convergence(session),
		'final_recommendations': final_recommendations or [],
	}


def build_final_recommendations(session: PreferenceBatchSession, limit: int = 5) -> list[dict[str, Any]]:
	excluded_ids = dedupe_preserve_order(session.seed_image_ids + session.liked_image_ids + session.disliked_image_ids)
	return build_batch_cards(session.preference_vector, excluded_ids=excluded_ids, limit=limit)


def start_preference_batch_session(
	*,
	user: Any,
	project: Project,
	selected_image_ids: list[int] | None = None,
	selected_images: list[dict[str, Any]] | None = None,
	rejected_image_ids: list[int] | None = None,
) -> tuple[PreferenceBatchSession, dict[str, Any]]:
	resolved_seed_ids = dedupe_preserve_order([int(image_id) for image_id in (selected_image_ids or [])])
	resolved_rejected_ids = dedupe_preserve_order([int(image_id) for image_id in (rejected_image_ids or [])])
	if not resolved_seed_ids and selected_images:
		resolved_seed_ids = resolve_candidate_ids_from_preloaded_images(selected_images)
	if not resolved_seed_ids:
		raise ValueError('selected_image_ids or selected_images are required')

	merge_project_feedback(project, liked_ids=resolved_seed_ids, hated_ids=resolved_rejected_ids)

	preference_vector = build_preference_vector(resolved_seed_ids, [], resolved_rejected_ids)
	baseline_similarity = compute_baseline_similarity()
	pref_change = 0.0
	liked_for_scoring = dedupe_preserve_order(resolved_seed_ids)
	coherence_score = compute_coherence_score(liked_for_scoring, baseline_similarity)
	recent_coherence_score = compute_coherence_score(liked_for_scoring[-RECENT_WINDOW:], baseline_similarity)
	top_k_density_score = compute_top_k_density(preference_vector, resolved_seed_ids + resolved_rejected_ids)
	stability_score = clamp(1.0 - (pref_change / STABILITY_NORMALIZATION), 0.0, 1.0)
	convergence_score = (
		0.25 * stability_score
		+ 0.25 * coherence_score
		+ 0.35 * recent_coherence_score
		+ 0.15 * top_k_density_score
	)
	shown_ids = dedupe_preserve_order(resolved_seed_ids + resolved_rejected_ids)
	batch_cards = build_batch_cards(preference_vector, excluded_ids=shown_ids, limit=DEFAULT_BATCH_SIZE)
	current_batch_ids = [int(card['image_id']) for card in batch_cards]

	session = PreferenceBatchSession.objects.create(
		user=user,
		project=project,
		status=PreferenceBatchSession.Status.ACTIVE,
		batch_size=DEFAULT_BATCH_SIZE,
		batch_index=1,
		seed_image_ids=resolved_seed_ids,
		disliked_image_ids=resolved_rejected_ids,
		swipe_count=len(shown_ids),
		shown_image_ids=dedupe_preserve_order(shown_ids + current_batch_ids),
		current_batch_ids=current_batch_ids,
		preference_vector=preference_vector,
		prev_preference_vector=preference_vector,
		baseline_similarity=baseline_similarity,
		pref_change=pref_change,
		stability_score=stability_score,
		coherence_score=coherence_score,
		recent_coherence_score=recent_coherence_score,
		top_k_density_score=top_k_density_score,
		convergence_score=convergence_score,
	)
	return session, serialize_preference_batch_response(session, batch_cards)


def apply_feedback_batch(session: PreferenceBatchSession, feedback_items: list[dict[str, Any]]) -> dict[str, Any]:
	if session.status != PreferenceBatchSession.Status.ACTIVE:
		return serialize_preference_batch_response(session, [], final_recommendations=build_final_recommendations(session))

	if not feedback_items:
		raise ValueError('feedback is required')

	allowed_ids = set(session.current_batch_ids)
	liked_updates: list[int] = []
	disliked_updates: list[int] = []

	for item in feedback_items:
		image_id = item.get('image_id')
		action = str(item.get('action') or '').strip().lower()
		if not isinstance(image_id, int):
			raise ValueError('feedback.image_id(int) is required')
		if image_id not in allowed_ids:
			raise ValueError(f'image_id {image_id} is not in current batch')
		if action not in {'like', 'dislike'}:
			raise ValueError('feedback.action must be like or dislike')
		if action == 'like':
			liked_updates.append(image_id)
		else:
			disliked_updates.append(image_id)

	liked_image_ids = dedupe_preserve_order(session.liked_image_ids + liked_updates)
	disliked_image_ids = dedupe_preserve_order(session.disliked_image_ids + disliked_updates)
	merge_project_feedback(session.project, liked_ids=liked_updates, hated_ids=disliked_updates)
	prev_preference_vector = session.preference_vector
	preference_vector = build_preference_vector(session.seed_image_ids, liked_image_ids, disliked_image_ids)
	pref_change = l2_distance(preference_vector, prev_preference_vector)
	liked_for_scoring = dedupe_preserve_order(session.seed_image_ids + liked_image_ids)
	coherence_score = compute_coherence_score(liked_for_scoring, session.baseline_similarity)
	recent_coherence_score = compute_coherence_score(liked_for_scoring[-RECENT_WINDOW:], session.baseline_similarity)
	top_k_density_score = compute_top_k_density(preference_vector, session.shown_image_ids)
	stability_score = clamp(1.0 - (pref_change / STABILITY_NORMALIZATION), 0.0, 1.0)
	convergence_score = (
		0.25 * stability_score
		+ 0.25 * coherence_score
		+ 0.35 * recent_coherence_score
		+ 0.15 * top_k_density_score
	)
	swipe_count = session.swipe_count + len(feedback_items)
	like_ratio = 0.0 if swipe_count == 0 else len(liked_image_ids) / swipe_count

	warning = ''
	terminated_reason = ''
	status = PreferenceBatchSession.Status.ACTIVE
	is_converged = (
		swipe_count >= MIN_SWIPES
		and len(liked_for_scoring) >= 3
		and convergence_score >= CONVERGENCE_THRESHOLD
		and pref_change < STABILITY_THRESHOLD
	)

	if swipe_count >= MAX_SWIPES:
		status = PreferenceBatchSession.Status.TERMINATED
		terminated_reason = 'max_swipes_reached'
	elif like_ratio > 0.9 and swipe_count >= MIN_SWIPES:
		status = PreferenceBatchSession.Status.TERMINATED
		terminated_reason = 'broad_preference_detected'
		warning = '다양한 프로젝트를 모두 좋아하시는군요!'
	elif is_converged:
		status = PreferenceBatchSession.Status.CONVERGED
		terminated_reason = 'convergence_threshold_reached'

	shown_image_ids = dedupe_preserve_order(session.shown_image_ids + session.current_batch_ids)

	session.liked_image_ids = liked_image_ids
	session.disliked_image_ids = disliked_image_ids
	session.prev_preference_vector = prev_preference_vector
	session.preference_vector = preference_vector
	session.pref_change = pref_change
	session.stability_score = stability_score
	session.coherence_score = coherence_score
	session.recent_coherence_score = recent_coherence_score
	session.top_k_density_score = top_k_density_score
	session.convergence_score = convergence_score
	session.swipe_count = swipe_count
	session.warning = warning
	session.terminated_reason = terminated_reason
	session.is_converged = status == PreferenceBatchSession.Status.CONVERGED
	session.status = status
	session.shown_image_ids = shown_image_ids

	if status == PreferenceBatchSession.Status.ACTIVE:
		next_batch_cards = build_batch_cards(
			preference_vector,
			excluded_ids=shown_image_ids,
			limit=session.batch_size,
		)
		next_batch_ids = [int(card['image_id']) for card in next_batch_cards]
		if not next_batch_ids:
			session.status = PreferenceBatchSession.Status.TERMINATED
			session.terminated_reason = 'no_more_candidates'
			session.current_batch_ids = []
			session.save(update_fields=[
				'liked_image_ids',
				'disliked_image_ids',
				'prev_preference_vector',
				'preference_vector',
				'pref_change',
				'stability_score',
				'coherence_score',
				'recent_coherence_score',
				'top_k_density_score',
				'convergence_score',
				'swipe_count',
				'warning',
				'terminated_reason',
				'is_converged',
				'status',
				'shown_image_ids',
				'current_batch_ids',
				'updated_at',
			])
			return serialize_preference_batch_response(session, [], final_recommendations=build_final_recommendations(session))

		session.current_batch_ids = next_batch_ids
		session.batch_index += 1
		session.shown_image_ids = dedupe_preserve_order(shown_image_ids + next_batch_ids)
		session.save(update_fields=[
			'liked_image_ids',
			'disliked_image_ids',
			'prev_preference_vector',
			'preference_vector',
			'pref_change',
			'stability_score',
			'coherence_score',
			'recent_coherence_score',
			'top_k_density_score',
			'convergence_score',
			'swipe_count',
			'warning',
			'terminated_reason',
			'is_converged',
			'status',
			'shown_image_ids',
			'current_batch_ids',
			'batch_index',
			'updated_at',
		])
		return serialize_preference_batch_response(session, next_batch_cards)

	session.current_batch_ids = []
	session.save(update_fields=[
		'liked_image_ids',
		'disliked_image_ids',
		'prev_preference_vector',
		'preference_vector',
		'pref_change',
		'stability_score',
		'coherence_score',
		'recent_coherence_score',
		'top_k_density_score',
		'convergence_score',
		'swipe_count',
		'warning',
		'terminated_reason',
		'is_converged',
		'status',
		'shown_image_ids',
		'current_batch_ids',
		'updated_at',
	])
	return serialize_preference_batch_response(session, [], final_recommendations=build_final_recommendations(session))


def resolve_candidate_ids_from_preloaded_images(preloaded_images: list[dict[str, Any]]) -> list[int]:
	if not preloaded_images:
		return []

	service = get_analysis_service()
	db = service.db
	query_by_url = f'SELECT id FROM {db.cfg.table} WHERE url = %s LIMIT 1'
	query_by_project_name = f'SELECT id FROM {db.cfg.table} WHERE project_name = %s LIMIT 1'
	resolved_ids: list[int] = []

	with db.conn.cursor() as cur:
		for card in preloaded_images:
			image_title = str(card.get('image_title') or card.get('title') or '').strip()
			source_url = str(card.get('source_url') or card.get('url') or '').strip()
			matched_id: int | None = None

			if source_url:
				cur.execute(query_by_url, (source_url,))
				row = cur.fetchone()
				if row:
					matched_id = int(row[0])

			if matched_id is None and image_title:
				cur.execute(query_by_project_name, (image_title,))
				row = cur.fetchone()
				if row:
					matched_id = int(row[0])

			if matched_id is not None:
				resolved_ids.append(matched_id)

	return list(dict.fromkeys(resolved_ids))


def start_analysis_session(
	*,
	user: Any,
	project_id: str,
	candidate_ids: list[int] | None = None,
	preloaded_images: list[dict[str, Any]] | None = None,
) -> tuple[AnalysisSession, dict[str, Any]]:
	service = get_analysis_service()
	resolved_candidate_ids = list(candidate_ids or [])
	if not resolved_candidate_ids and preloaded_images:
		resolved_candidate_ids = resolve_candidate_ids_from_preloaded_images(preloaded_images)

	result = service.start_session(
		user_id=user.username,
		project_id=project_id,
		candidate_ids=resolved_candidate_ids or None,
	)
	progress = result.get('progress') or {}
	legacy_session_id = str(result.get('session_id') or '').strip()
	if not legacy_session_id:
		raise ValueError('legacy analysis session id is missing')

	record = AnalysisSession.objects.create(
		user=user,
		legacy_project_id=project_id,
		legacy_session_id=legacy_session_id,
		status=str(result.get('session_status') or AnalysisSession.Status.ACTIVE),
		total_rounds=int(result.get('total_rounds') or 20),
		current_round=int(progress.get('current_round') or 0),
		is_analysis_completed=bool(result.get('is_analysis_completed') or False),
	)

	response = {
		'session_id': str(record.session_id),
		'session_status': record.status,
		'total_rounds': record.total_rounds,
		'project_id': record.legacy_project_id,
		'progress': progress,
		'next_image': map_backend_card_to_frontend(result.get('next_image')),
	}
	return record, response


def get_diverse_random_cards(count: int = 10) -> list[dict[str, Any]]:
	service = get_analysis_service()
	all_image_ids = service.db.get_all_image_ids()
	if not all_image_ids:
		return []

	selected_ids = service.db.get_diverse_sample_ids(
		candidate_ids=all_image_ids,
		target_count=count,
	)
	cards = [service.db.get_image_card(image_id) for image_id in selected_ids]
	return [mapped for mapped in (map_backend_card_to_frontend(card) for card in cards) if mapped is not None]