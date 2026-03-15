import argparse
import math
import os
import random
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

import psycopg2


INITIAL_IMAGE_ID = 1
INITIAL_DIVERSE_COUNT = 10
INITIAL_ANALYSIS_START_ROUNDS = 10
PENDING_INITIAL_INJECTION_PROB = 0.0
TOTAL_ROUNDS = 20
LIKE_WEIGHT = 0.5
DISLIKE_WEIGHT = -1.0
EPSILON = 0.30
EPSILON_MIN = 0.05
EPSILON_DECAY = 0.995
DISTANCE_METRIC = "cosine"
ALLOW_DUPLICATE_IN_SESSION = False
FINAL_RECOMMENDATION_COUNT = 20
REPORT_KEYWORD_COUNT = 5

DEFAULT_DB_HOST = os.getenv("PGHOST", "localhost")
DEFAULT_DB_PORT = int(os.getenv("PGPORT", "5432"))
DEFAULT_DB_USER = os.getenv("PGUSER", "postgres")
DEFAULT_DB_PASSWORD = os.getenv("PGPASSWORD", "")
DEFAULT_DB_NAME = "into_database"
DEFAULT_TABLE = "architecture_vectors"


@dataclass
class DbConfig:
	host: str
	port: int
	user: str
	password: str
	db_name: str
	table: str


@dataclass
class AnalysisOptions:
	initial_image_id: int = INITIAL_IMAGE_ID
	initial_diverse_count: int = INITIAL_DIVERSE_COUNT
	initial_analysis_start_rounds: int = INITIAL_ANALYSIS_START_ROUNDS
	pending_initial_injection_prob: float = PENDING_INITIAL_INJECTION_PROB
	total_rounds: int = TOTAL_ROUNDS
	like_weight: float = LIKE_WEIGHT
	dislike_weight: float = DISLIKE_WEIGHT
	epsilon: float = EPSILON
	epsilon_min: float = EPSILON_MIN
	epsilon_decay: float = EPSILON_DECAY
	distance_metric: str = DISTANCE_METRIC
	final_recommendation_count: int = FINAL_RECOMMENDATION_COUNT
	report_keyword_count: int = REPORT_KEYWORD_COUNT


@dataclass
class SessionState:
	session_id: str
	user_id: str
	project_id: str
	options: AnalysisOptions
	initial_candidate_ids: set[int] | None = None
	current_round: int = 0
	epsilon: float = EPSILON
	session_status: str = "active"
	is_analysis_completed: bool = False
	exposed_image_ids: set[int] = field(default_factory=set)
	liked_image_ids: set[int] = field(default_factory=set)
	disliked_image_ids: set[int] = field(default_factory=set)
	swiped_image_ids: set[int] = field(default_factory=set)
	seen_event_keys: set[str] = field(default_factory=set)
	pending_initial_queue: list[int] = field(default_factory=list)
	user_pref_vector: list[float] | None = None


def parse_vector_text(vector_text: str) -> list[float]:
	text = vector_text.strip()
	if not text.startswith("[") or not text.endswith("]"):
		return []
	body = text[1:-1].strip()
	if not body:
		return []
	return [float(v) for v in body.split(",")]


def normalize_vector(vec: list[float]) -> list[float]:
	norm = math.sqrt(sum(x * x for x in vec))
	if norm == 0.0:
		return vec
	return [x / norm for x in vec]


def add_weighted(base: list[float] | None, vec: list[float], weight: float) -> list[float]:
	if base is None:
		return normalize_vector([weight * x for x in vec])
	if len(base) != len(vec):
		raise ValueError("Vector dimension mismatch.")
	mixed = [b + weight * v for b, v in zip(base, vec)]
	return normalize_vector(mixed)


def to_vector_literal(vec: list[float]) -> str:
	return "[" + ",".join(f"{x:.8f}" for x in vec) + "]"


def prompt_feedback() -> str:
	return input("Action [like/dislike/quit]: ").strip().lower()


class VectorDbClient:
	def __init__(self, cfg: DbConfig):
		self.cfg = cfg
		self.conn = psycopg2.connect(
			dbname=cfg.db_name,
			host=cfg.host,
			port=cfg.port,
			user=cfg.user,
			password=cfg.password,
		)

	def close(self) -> None:
		self.conn.close()

	def validate(self) -> dict[str, Any]:
		with self.conn.cursor() as cur:
			cur.execute("SELECT current_database()")
			db_name = cur.fetchone()[0]

			cur.execute("SELECT extname FROM pg_extension WHERE extname = 'vector'")
			has_vector = cur.fetchone() is not None

			cur.execute(
				f"SELECT COUNT(*), COUNT(embedding), MIN(vector_dims(embedding)), MAX(vector_dims(embedding)) FROM {self.cfg.table}"
			)
			total, emb_rows, min_dim, max_dim = cur.fetchone()

		return {
			"db_name": db_name,
			"has_vector_extension": has_vector,
			"total_rows": int(total),
			"embedding_rows": int(emb_rows),
			"embedding_null_rows": int(total - emb_rows),
			"min_dim": int(min_dim) if min_dim is not None else None,
			"max_dim": int(max_dim) if max_dim is not None else None,
		}

	def get_image_card(self, image_id: int) -> dict[str, Any] | None:
		query = f"""
		SELECT id, project_name, url, architect, location_country, year, program, mood, material
		FROM {self.cfg.table}
		WHERE id = %s
		"""
		with self.conn.cursor() as cur:
			cur.execute(query, (image_id,))
			row = cur.fetchone()

		if not row:
			return None

		return {
			"image_id": row[0],
			"image_title": row[1],
			"project_name": row[1],
			"image_url": row[2],
			"source_url": row[2],
			"metadata": {
				"architect": row[3],
				"axis_location": row[4],
				"axis_year": row[5],
				"program": row[6],
				"mood": row[7],
				"material": row[8],
			},
		}

	def get_embedding(self, image_id: int) -> list[float] | None:
		query = f"SELECT embedding::text FROM {self.cfg.table} WHERE id = %s"
		with self.conn.cursor() as cur:
			cur.execute(query, (image_id,))
			row = cur.fetchone()
		if not row:
			return None
		return parse_vector_text(row[0])

	def get_all_image_ids(self) -> list[int]:
		query = f"SELECT id FROM {self.cfg.table} ORDER BY id"
		with self.conn.cursor() as cur:
			cur.execute(query)
			rows = cur.fetchall()
		return [int(r[0]) for r in rows]

	def get_existing_image_ids(self, image_ids: list[int]) -> list[int]:
		if not image_ids:
			return []
		query = f"SELECT id FROM {self.cfg.table} WHERE id = ANY(%s::bigint[]) ORDER BY id"
		with self.conn.cursor() as cur:
			cur.execute(query, (image_ids,))
			rows = cur.fetchall()
		return [int(r[0]) for r in rows]

	def get_embeddings_for_ids(self, image_ids: list[int]) -> dict[int, list[float]]:
		if not image_ids:
			return {}
		query = f"SELECT id, embedding::text FROM {self.cfg.table} WHERE id = ANY(%s::bigint[])"
		with self.conn.cursor() as cur:
			cur.execute(query, (image_ids,))
			rows = cur.fetchall()
		result: dict[int, list[float]] = {}
		for row in rows:
			result[int(row[0])] = normalize_vector(parse_vector_text(row[1]))
		return result

	def get_diverse_sample_ids(self, candidate_ids: list[int], target_count: int, anchor_id: int | None = None) -> list[int]:
		candidate_ids = list(dict.fromkeys(candidate_ids))
		if not candidate_ids or target_count <= 0:
			return []

		embeddings = self.get_embeddings_for_ids(candidate_ids)
		available_ids = [image_id for image_id in candidate_ids if image_id in embeddings]
		if not available_ids:
			return []

		if anchor_id is None or anchor_id not in embeddings:
			anchor_id = random.choice(available_ids)

		selected = [anchor_id]
		remaining = [image_id for image_id in available_ids if image_id != anchor_id]
		target_size = min(target_count, len(available_ids))

		def cosine_distance(left_id: int, right_id: int) -> float:
			left_vec = embeddings[left_id]
			right_vec = embeddings[right_id]
			return 1.0 - sum(l * r for l, r in zip(left_vec, right_vec))

		while remaining and len(selected) < target_size:
			best_id = max(
				remaining,
				key=lambda candidate_id: min(cosine_distance(candidate_id, selected_id) for selected_id in selected),
			)
			selected.append(best_id)
			remaining.remove(best_id)

		return selected

	def get_initial_diverse_ids(self, anchor_id: int, count: int, excluded_ids: set[int]) -> list[int]:
		query = f"""
		WITH anchor AS (
			SELECT embedding AS emb
			FROM {self.cfg.table}
			WHERE id = %s
		)
		SELECT t.id
		FROM {self.cfg.table} t, anchor
		WHERE t.id <> %s
		  AND NOT (t.id = ANY(%s::bigint[]))
		ORDER BY t.embedding <=> anchor.emb DESC
		LIMIT %s
		"""
		excluded = list(excluded_ids) if excluded_ids else []
		with self.conn.cursor() as cur:
			cur.execute(query, (anchor_id, anchor_id, excluded, count))
			rows = cur.fetchall()
		return [int(r[0]) for r in rows]

	def get_best_candidate_by_pref(self, pref_vector: list[float], excluded_ids: set[int]) -> int | None:
		query = f"""
		SELECT id
		FROM {self.cfg.table}
		WHERE NOT (id = ANY(%s::bigint[]))
		ORDER BY embedding <=> %s::vector
		LIMIT 1
		"""
		excluded = list(excluded_ids) if excluded_ids else []
		literal = to_vector_literal(pref_vector)
		with self.conn.cursor() as cur:
			cur.execute(query, (excluded, literal))
			row = cur.fetchone()
		return int(row[0]) if row else None

	def get_random_candidate(self, excluded_ids: set[int]) -> int | None:
		query = f"""
		SELECT id
		FROM {self.cfg.table}
		WHERE NOT (id = ANY(%s::bigint[]))
		ORDER BY random()
		LIMIT 1
		"""
		excluded = list(excluded_ids) if excluded_ids else []
		with self.conn.cursor() as cur:
			cur.execute(query, (excluded,))
			row = cur.fetchone()
		return int(row[0]) if row else None

	def get_top_candidates_by_pref(
		self,
		pref_vector: list[float],
		excluded_ids: set[int],
		limit: int,
	) -> list[int]:
		query = f"""
		SELECT id
		FROM {self.cfg.table}
		WHERE NOT (id = ANY(%s::bigint[]))
		ORDER BY embedding <=> %s::vector
		LIMIT %s
		"""
		excluded = list(excluded_ids) if excluded_ids else []
		literal = to_vector_literal(pref_vector)
		with self.conn.cursor() as cur:
			cur.execute(query, (excluded, literal, limit))
			rows = cur.fetchall()
		return [int(r[0]) for r in rows]

	def get_rows_for_report(self, image_ids: list[int]) -> list[dict[str, Any]]:
		if not image_ids:
			return []
		query = f"""
		SELECT id, architect, project_name, location_country, document_text
		FROM {self.cfg.table}
		WHERE id = ANY(%s::bigint[])
		"""
		with self.conn.cursor() as cur:
			cur.execute(query, (image_ids,))
			rows = cur.fetchall()
		result: list[dict[str, Any]] = []
		for row in rows:
			result.append(
				{
					"id": int(row[0]),
					"source": row[1] or "",
					"title": row[2] or "",
					"location": row[3] or "",
					"document_text": row[4] or "",
				}
			)
		return result


class PreferenceAnalyzer:
	def __init__(self, db: VectorDbClient, options: AnalysisOptions):
		self.db = db
		self.options = options

	def start_session(
		self,
		user_id: str,
		project_id: str,
		candidate_ids: list[int] | None = None,
	) -> tuple[SessionState, dict[str, Any]]:
		session_id = f"sess_{uuid.uuid4().hex[:16]}"
		candidate_ids = [int(image_id) for image_id in (candidate_ids or [])]
		existing_candidate_ids = self.db.get_existing_image_ids(candidate_ids)

		state = SessionState(
			session_id=session_id,
			user_id=user_id,
			project_id=project_id,
			options=self.options,
			initial_candidate_ids=set(existing_candidate_ids) if existing_candidate_ids else None,
			epsilon=self.options.epsilon,
		)

		if existing_candidate_ids:
			anchor_id = random.choice(existing_candidate_ids)
			initial_ids = self.db.get_diverse_sample_ids(
				candidate_ids=existing_candidate_ids,
				target_count=self.options.initial_diverse_count,
				anchor_id=anchor_id,
			)
		else:
			all_image_ids = self.db.get_all_image_ids()
			anchor_id = self.options.initial_image_id if self.options.initial_image_id in all_image_ids else None
			initial_ids = self.db.get_diverse_sample_ids(
				candidate_ids=all_image_ids,
				target_count=self.options.initial_diverse_count,
				anchor_id=anchor_id,
			)

		if not initial_ids:
			raise ValueError("No available images for analysis session.")

		anchor_id = initial_ids[0]
		anchor_card = self.db.get_image_card(anchor_id)
		if anchor_card is None:
			raise ValueError(f"Initial image id not found: {anchor_id}")

		# Initial queue is deduplicated to avoid accidental repeated exposure.
		state.pending_initial_queue = list(dict.fromkeys(initial_ids))
		next_image = self._pick_next_image(state)

		response = {
			"session_id": state.session_id,
			"session_status": state.session_status,
			"total_rounds": self.options.total_rounds,
			"next_image": next_image,
			"progress": self._progress(state),
		}
		return state, response

	def apply_swipe(
		self,
		state: SessionState,
		image_id: int,
		action: str,
		idempotency_key: str | None = None,
	) -> dict[str, Any]:
		if state.is_analysis_completed:
			return {
				"accepted": False,
				"message": "analysis already completed",
				"session_status": state.session_status,
				"is_analysis_completed": True,
			}

		if idempotency_key and idempotency_key in state.seen_event_keys:
			return {
				"accepted": True,
				"message": "duplicate event ignored",
				"session_status": state.session_status,
				"progress": self._progress(state),
				"is_analysis_completed": state.is_analysis_completed,
				"next_image": None,
			}

		if action not in {"like", "dislike"}:
			return {"accepted": False, "message": "action must be like or dislike"}

		emb = self.db.get_embedding(image_id)
		if emb is None:
			return {"accepted": False, "message": "image_id not found"}

		state.exposed_image_ids.add(image_id)
		state.swiped_image_ids.add(image_id)
		state.current_round += 1
		if idempotency_key:
			state.seen_event_keys.add(idempotency_key)

		if action == "like":
			state.liked_image_ids.add(image_id)
			state.user_pref_vector = add_weighted(
				state.user_pref_vector,
				emb,
				self.options.like_weight,
			)
		else:
			state.disliked_image_ids.add(image_id)
			state.user_pref_vector = add_weighted(
				state.user_pref_vector,
				emb,
				self.options.dislike_weight,
			)

		state.epsilon = max(self.options.epsilon_min, state.epsilon * self.options.epsilon_decay)

		if state.current_round >= self.options.total_rounds:
			state.is_analysis_completed = True
			state.session_status = "report_ready"
			return {
				"accepted": True,
				"session_status": state.session_status,
				"progress": self._progress(state),
				"next_image": None,
				"is_analysis_completed": True,
			}

		next_image = self._pick_next_image(state)
		if next_image is None:
			state.is_analysis_completed = True
			state.session_status = "report_ready"

		return {
			"accepted": True,
			"session_status": state.session_status,
			"progress": self._progress(state),
			"next_image": next_image,
			"is_analysis_completed": state.is_analysis_completed,
		}

	def build_result(self, state: SessionState) -> dict[str, Any]:
		state.session_status = "completed"
		state.is_analysis_completed = True

		liked_ids = sorted(state.liked_image_ids)
		excluded = state.exposed_image_ids | state.swiped_image_ids
		predicted_ids: list[int]

		if state.user_pref_vector is None:
			predicted_ids = []
		else:
			predicted_ids = self.db.get_top_candidates_by_pref(
				pref_vector=state.user_pref_vector,
				excluded_ids=excluded,
				limit=self.options.final_recommendation_count,
			)

		liked_images = [self.db.get_image_card(i) for i in liked_ids]
		predicted_images = [self.db.get_image_card(i) for i in predicted_ids]

		liked_images = [x for x in liked_images if x is not None]
		predicted_images = [x for x in predicted_images if x is not None]

		report = self._build_report(liked_ids, sorted(state.disliked_image_ids), self.options.report_keyword_count)

		return {
			"session_id": state.session_id,
			"session_status": state.session_status,
			"liked_images": liked_images,
			"predicted_like_images": predicted_images,
			"predicted_like_count": len(predicted_images),
			"analysis_report": report,
		}

	def _pick_next_image(self, state: SessionState) -> dict[str, Any] | None:
		def pop_from_initial_queue() -> dict[str, Any] | None:
			while state.pending_initial_queue:
				image_id = state.pending_initial_queue.pop(0)
				if ALLOW_DUPLICATE_IN_SESSION or image_id not in state.exposed_image_ids:
					state.exposed_image_ids.add(image_id)
					return self.db.get_image_card(image_id)
			return None

		# Keep early rounds fully exploratory for stable preference bootstrapping.
		must_use_initial = len(state.swiped_image_ids) < state.options.initial_analysis_start_rounds
		if must_use_initial:
			card = pop_from_initial_queue()
			if card is not None:
				return card

		# After analysis starts, occasionally inject leftover initial cards for diversity.
		if state.pending_initial_queue and random.random() < state.options.pending_initial_injection_prob:
			card = pop_from_initial_queue()
			if card is not None:
				return card

		excluded = state.exposed_image_ids if not ALLOW_DUPLICATE_IN_SESSION else set()

		if state.user_pref_vector is None:
			candidate_id = self.db.get_random_candidate(excluded)
		else:
			should_explore = random.random() < state.epsilon
			if should_explore:
				candidate_id = self.db.get_random_candidate(excluded)
			else:
				candidate_id = self.db.get_best_candidate_by_pref(state.user_pref_vector, excluded)

		if candidate_id is None:
			# Fallback to any remaining initial card before terminating.
			return pop_from_initial_queue()

		state.exposed_image_ids.add(candidate_id)
		return self.db.get_image_card(candidate_id)

	def _build_report(self, liked_ids: list[int], disliked_ids: list[int], keyword_count: int) -> dict[str, Any]:
		liked_rows = self.db.get_rows_for_report(liked_ids)
		disliked_rows = self.db.get_rows_for_report(disliked_ids)

		liked_text = " ".join(r["document_text"] for r in liked_rows)
		disliked_text = " ".join(r["document_text"] for r in disliked_rows)

		stopwords = {
			"source",
			"title",
			"description",
			"author",
			"location",
			"architects",
			"year",
			"area",
			"photography",
			"client",
			"credits",
			"unknown",
		}

		def token_freq(text: str) -> dict[str, int]:
			freq: dict[str, int] = {}
			for token in re.findall(r"[A-Za-z]{3,}|[가-힣]{2,}", text.lower()):
				if token in stopwords:
					continue
				freq[token] = freq.get(token, 0) + 1
			return freq

		like_freq = token_freq(liked_text)
		dislike_freq = token_freq(disliked_text)

		scored: list[tuple[str, int]] = []
		for token, count in like_freq.items():
			score = count - dislike_freq.get(token, 0)
			if score > 0:
				scored.append((token, score))

		scored.sort(key=lambda x: x[1], reverse=True)
		keywords = [t for t, _ in scored[:keyword_count]]

		source_counter: dict[str, int] = {}
		for row in liked_rows:
			src = row["source"].strip().lower()
			if src:
				source_counter[src] = source_counter.get(src, 0) + 1

		dominant_axes = [f"axis_source_{k}" for k, _ in sorted(source_counter.items(), key=lambda x: x[1], reverse=True)[:3]]

		if keywords:
			summary_text = "User preference is concentrated around: " + ", ".join(keywords)
		else:
			summary_text = "Not enough strong positive signals to extract keywords."

		return {
			"dominant_axes": dominant_axes,
			"keywords": keywords,
			"keyword_count": len(keywords),
			"summary_text": summary_text,
		}

	@staticmethod
	def _progress(state: SessionState) -> dict[str, int]:
		return {
			"current_round": state.current_round,
			"total_rounds": state.options.total_rounds,
			"like_count": len(state.liked_image_ids),
			"dislike_count": len(state.disliked_image_ids),
		}


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="Run ARCHITON preference analysis using PostgreSQL vector DB."
	)
	parser.add_argument("--user-id", type=str, default="user_demo")
	parser.add_argument("--project-id", type=str, default="project_demo")
	parser.add_argument("--db-host", type=str, default=DEFAULT_DB_HOST)
	parser.add_argument("--db-port", type=int, default=DEFAULT_DB_PORT)
	parser.add_argument("--db-user", type=str, default=DEFAULT_DB_USER)
	parser.add_argument("--db-password", type=str, default=DEFAULT_DB_PASSWORD)
	parser.add_argument("--db-name", type=str, default=DEFAULT_DB_NAME)
	parser.add_argument("--table", type=str, default=DEFAULT_TABLE)
	parser.add_argument("--total-rounds", type=int, default=TOTAL_ROUNDS)
	return parser.parse_args()


def run_cli() -> None:
	args = parse_args()
	user_id = args.user_id

	cfg = DbConfig(
		host=args.db_host,
		port=args.db_port,
		user=args.db_user,
		password=args.db_password,
		db_name=args.db_name,
		table=args.table,
	)

	options = AnalysisOptions(total_rounds=args.total_rounds)

	db = VectorDbClient(cfg)
	try:
		validation = db.validate()
		print("[DB Validation]")
		for k, v in validation.items():
			print(f"- {k}: {v}")

		analyzer = PreferenceAnalyzer(db, options)
		state, started = analyzer.start_session(user_id, args.project_id)

		print("\n[Session Started]")
		print(started)

		while not state.is_analysis_completed:
			card = started.get("next_image")
			if not card:
				break

			image_id = int(card["image_id"])
			title = card.get("image_title") or "untitled"
			print(f"\nRound {state.current_round + 1}/{state.options.total_rounds}")
			print(f"image_id={image_id}, title={title}")
			print("피드백 입력: like / dislike / quit")

			action = prompt_feedback()
			if action == "quit":
				break
			if action not in {"like", "dislike"}:
				print("Invalid action. Try again.")
				continue

			event_key = f"evt_{uuid.uuid4().hex[:10]}"
			started = analyzer.apply_swipe(
				state=state,
				image_id=image_id,
				action=action,
				idempotency_key=event_key,
			)
			print(started)

		result = analyzer.build_result(state)
		print("\n[Final Result]")
		print(result)
	finally:
		db.close()


if __name__ == "__main__":
	run_cli()
