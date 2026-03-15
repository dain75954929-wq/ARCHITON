"""ARCHITON 오프라인 평가 스크립트

가상 사용자 시뮬레이션 / 가중치 그리드 탐색 / 로그 리플레이를 지원한다.

실행 예시:
  python analysis_eval.py --mode simulate
  python analysis_eval.py --mode grid
  python analysis_eval.py --mode replay --log replay_log.json
  python analysis_eval.py --mode simulate --top-k 10
"""

import argparse
import itertools
import json
import math
import os
import random
import sys
import uuid
from dataclasses import dataclass, field
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from analysis import (
	DEFAULT_DB_HOST,
	DEFAULT_DB_NAME,
	DEFAULT_DB_PASSWORD,
	DEFAULT_DB_PORT,
	DEFAULT_DB_USER,
	DEFAULT_TABLE,
	AnalysisOptions,
	DbConfig,
	PreferenceAnalyzer,
	VectorDbClient,
)

# ── 설정 ─────────────────────────────────────────────────────────────────────

TOP_K_DEFAULT = 10

# 그리드 탐색 파라미터 공간
GRID_LIKE_WEIGHTS   = [0.5, 1.0, 1.5]
GRID_DISLIKE_WEIGHTS = [-0.3, -0.6, -1.0]
GRID_EPSILONS        = [0.05, 0.18, 0.30]
GRID_INITIAL_DIVERSE_COUNTS = [6, 10, 14, 18, 24, 30]

# 복합 점수 가중치 (합계 = 1.0)
COMPOSITE_W = {"precision": 0.5, "diversity": 0.3, "completion": 0.2}
COMPOSITE_DIVERSE_W = {"precision": 0.45, "ndcg": 0.35, "diversity": 0.20}


def parse_int_csv(raw: str) -> list[int]:
	values: list[int] = []
	for token in raw.split(","):
		t = token.strip()
		if not t:
			continue
		values.append(int(t))
	if not values:
		raise ValueError("빈 후보 목록입니다. 예: 6,10,14,18")
	return values


# ── 메타데이터 preload ────────────────────────────────────────────────────────

def load_all_projects(db: VectorDbClient) -> dict[int, dict[str, Any]]:
	"""architecture_vectors 테이블의 9개 필드 메타데이터를 id → dict 로 반환."""
	query = (
		f"SELECT id, project_name, architect, location_country, "
		f"area, program, year, mood, material "
		f"FROM {db.cfg.table} ORDER BY id"
	)
	with db.conn.cursor() as cur:
		cur.execute(query)
		rows = cur.fetchall()
	return {
		int(row[0]): {
			"id": int(row[0]),
			"project_name":      row[1] or "",
			"architect":         row[2] or "",
			"location_country":  row[3] or "",
			"area":              row[4] or "",
			"program":           row[5] or "",
			"year":              row[6] or "",
			"mood":              row[7] or "",
			"material":          row[8] or "",
		}
		for row in rows
	}


# ── 가상 사용자 ───────────────────────────────────────────────────────────────

@dataclass
class VirtualUserProfile:
	name: str
	# 필드명 → 선호 키워드 목록 (소문자 부분 일치 기준)
	keywords: dict[str, list[str]] = field(default_factory=dict)
	# 랜덤 피드백 비율 (0.0 = 키워드 기반, 1.0 = 완전 랜덤)
	noise_rate: float = 0.0

	def decide(self, project: dict[str, Any]) -> str:
		"""프로젝트 메타데이터를 보고 like / dislike 를 결정한다."""
		if self.noise_rate > 0 and random.random() < self.noise_rate:
			return random.choice(["like", "dislike"])
		score = 0
		for fld, kws in self.keywords.items():
			value = (project.get(fld) or "").lower()
			for kw in kws:
				if kw in value:
					score += 1
		return "like" if score > 0 else "dislike"

	def true_like_ids(self, projects: dict[int, dict[str, Any]]) -> set[int]:
		"""키워드 기준(noise 없이)으로 '진짜' 선호할 프로젝트 id 집합을 반환."""
		liked: set[int] = set()
		for pid, p in projects.items():
			score = 0
			for fld, kws in self.keywords.items():
				value = (p.get(fld) or "").lower()
				for kw in kws:
					if kw in value:
						score += 1
			if score > 0:
				liked.add(pid)
		return liked


# 5가지 가상 사용자 타입
VIRTUAL_USERS: list[VirtualUserProfile] = [
	VirtualUserProfile(
		name="minimal_lover",
		keywords={"mood": ["minimal", "minimalist", "clean", "simple", "pure", "quiet"]},
	),
	VirtualUserProfile(
		name="material_lover",
		keywords={"material": ["wood", "timber", "concrete", "brick", "stone", "steel"]},
	),
	VirtualUserProfile(
		name="cultural_program",
		keywords={"program": ["museum", "gallery", "library", "cultural", "civic", "art"]},
	),
	VirtualUserProfile(
		name="residential",
		keywords={"program": ["house", "housing", "residential", "apartment", "villa", "home"]},
	),
	VirtualUserProfile(
		name="noisy_user",  # 완전 랜덤 피드백 - 노이즈 내성 테스트용
		noise_rate=1.0,
	),
]


# ── 지표 계산 ─────────────────────────────────────────────────────────────────

def calc_precision(predicted: list[int], relevant: set[int], k: int) -> float:
	top = predicted[:k]
	if not top:
		return 0.0
	return sum(1 for p in top if p in relevant) / k


def calc_recall(predicted: list[int], relevant: set[int], k: int) -> float:
	if not relevant:
		return 0.0
	top = predicted[:k]
	return sum(1 for p in top if p in relevant) / len(relevant)


def calc_ndcg(predicted: list[int], relevant: set[int], k: int) -> float:
	top = predicted[:k]
	dcg  = sum(1 / math.log2(i + 2) for i, p in enumerate(top) if p in relevant)
	idcg = sum(1 / math.log2(i + 2) for i in range(min(k, len(relevant))))
	return dcg / idcg if idcg > 0 else 0.0


def calc_diversity(predicted: list[int], projects: dict[int, dict], k: int) -> float:
	"""program 과 location_country 의 고유 값 비율로 다양성을 측정."""
	top = predicted[:k]
	if not top:
		return 0.0
	meta = [projects[p] for p in top if p in projects]
	unique_prog = len({(m.get("program") or "").lower() for m in meta} - {""})
	unique_loc  = len({(m.get("location_country") or "").lower() for m in meta} - {""})
	return min(1.0, (unique_prog + unique_loc) / (2 * k))


def calc_novelty(predicted: list[int], exposed_ids: set[int], k: int) -> float:
	"""예측 추천 중 세션 내 한 번도 보지 않은 항목의 비율."""
	top = predicted[:k]
	if not top:
		return 0.0
	return sum(1 for p in top if p not in exposed_ids) / k


# ── 1회 시뮬레이션 ─────────────────────────────────────────────────────────────

def run_simulation(
	db: VectorDbClient,
	user: VirtualUserProfile,
	all_projects: dict[int, dict[str, Any]],
	options: AnalysisOptions,
	top_k: int = TOP_K_DEFAULT,
) -> dict[str, Any]:
	"""가상 사용자로 1 세션을 시뮬레이션하고 지표 딕셔너리를 반환한다."""
	analyzer = PreferenceAnalyzer(db, options)
	state, response = analyzer.start_session(user.name, "eval")

	rounds_done = 0
	while not state.is_analysis_completed:
		next_img = response.get("next_image")
		if next_img is None:
			break
		image_id = int(next_img["image_id"])
		action   = user.decide(all_projects.get(image_id, {}))
		event_key = f"evt_{uuid.uuid4().hex[:10]}"
		response = analyzer.apply_swipe(state, image_id, action, event_key)
		rounds_done += 1

	result       = analyzer.build_result(state)
	predicted_ids = [img["image_id"] for img in result.get("predicted_like_images", [])]
	true_like_set = user.true_like_ids(all_projects)
	exposed       = state.exposed_image_ids | state.swiped_image_ids

	return {
		"user_type":        user.name,
		"rounds_completed": rounds_done,
		"total_rounds":     options.total_rounds,
		"like_count":       len(state.liked_image_ids),
		"dislike_count":    len(state.disliked_image_ids),
		"true_like_count":  len(true_like_set),
		"precision_at_k":   round(calc_precision(predicted_ids, true_like_set, top_k), 3),
		"recall_at_k":      round(calc_recall   (predicted_ids, true_like_set, top_k), 3),
		"ndcg_at_k":        round(calc_ndcg     (predicted_ids, true_like_set, top_k), 3),
		"diversity_at_k":   round(calc_diversity (predicted_ids, all_projects,  top_k), 3),
		"novelty_at_k":     round(calc_novelty   (predicted_ids, exposed,        top_k), 3),
		"completion_rate":  round(rounds_done / options.total_rounds, 3),
	}


# ── 모드 1: 시뮬레이션 ────────────────────────────────────────────────────────

def mode_simulate(
	db:           VectorDbClient,
	all_projects: dict[int, dict[str, Any]],
	top_k:        int,
	options:      AnalysisOptions,
) -> None:
	print(f"\n{'='*70}")
	print(f"[시뮬레이션] 가상 사용자 {len(VIRTUAL_USERS)}명  |  top_k={top_k}")
	print(f"{'='*70}")
	header = (
		f"  {'사용자 타입':<22} "
		f"P@K    R@K    NDCG@K Div@K  Nov@K  완료율  like/round"
	)
	print(header)
	print(f"  {'-'*68}")
	for user in VIRTUAL_USERS:
		m = run_simulation(db, user, all_projects, options, top_k)
		print(
			f"  {m['user_type']:<22} "
			f"{m['precision_at_k']:.3f}  "
			f"{m['recall_at_k']:.3f}  "
			f"{m['ndcg_at_k']:.3f}  "
			f"{m['diversity_at_k']:.3f}  "
			f"{m['novelty_at_k']:.3f}  "
			f"{m['completion_rate']:.3f}   "
			f"{m['like_count']}/{m['rounds_completed']}"
		)


# ── 모드 2: 가중치 그리드 탐색 ──────────────────────────────────────────────────

def mode_grid(
	db:           VectorDbClient,
	all_projects: dict[int, dict[str, Any]],
	top_k:        int,
) -> None:
	# noisy_user 는 신호 없음 → signal-based 사용자만 평가
	eval_users = [u for u in VIRTUAL_USERS if u.noise_rate == 0.0]
	combos     = list(itertools.product(GRID_LIKE_WEIGHTS, GRID_DISLIKE_WEIGHTS, GRID_EPSILONS))

	print(f"\n{'='*70}")
	print(
		f"[그리드 탐색] {len(combos)}개 조합 × {len(eval_users)}명 사용자 "
		f"= {len(combos) * len(eval_users)}회 시뮬레이션"
	)
	print(f"{'='*70}")

	results: list[dict[str, Any]] = []
	for idx, (lw, dw, ep) in enumerate(combos, 1):
		options = AnalysisOptions(like_weight=lw, dislike_weight=dw, epsilon=ep)
		p_list, d_list, c_list = [], [], []
		for user in eval_users:
			m = run_simulation(db, user, all_projects, options, top_k)
			p_list.append(m["precision_at_k"])
			d_list.append(m["diversity_at_k"])
			c_list.append(m["completion_rate"])

		avg_p = sum(p_list) / len(p_list)
		avg_d = sum(d_list) / len(d_list)
		avg_c = sum(c_list) / len(c_list)
		score = (
			avg_p * COMPOSITE_W["precision"]
			+ avg_d * COMPOSITE_W["diversity"]
			+ avg_c * COMPOSITE_W["completion"]
		)
		results.append({
			"like_weight":     lw,
			"dislike_weight":  dw,
			"epsilon":         ep,
			"avg_precision":   round(avg_p, 3),
			"avg_diversity":   round(avg_d, 3),
			"avg_completion":  round(avg_c, 3),
			"composite_score": round(score, 3),
		})
		print(
			f"  [{idx:3d}/{len(combos)}] "
			f"lw={lw:+.1f} dw={dw:+.1f} ep={ep:.2f}  "
			f"P={avg_p:.3f} D={avg_d:.3f} C={avg_c:.3f}  score={score:.3f}"
		)

	results.sort(key=lambda x: x["composite_score"], reverse=True)
	print(f"\n{'─'*70}")
	print(f"상위 3개 가중치 조합  (복합점수 = P×{COMPOSITE_W['precision']} + D×{COMPOSITE_W['diversity']} + C×{COMPOSITE_W['completion']}):")
	for rank, r in enumerate(results[:3], 1):
		print(
			f"  {rank}위: like_weight={r['like_weight']:+.1f}  "
			f"dislike_weight={r['dislike_weight']:+.1f}  "
			f"epsilon={r['epsilon']:.2f}  "
			f"→ composite={r['composite_score']:.3f}  "
			f"(P={r['avg_precision']} D={r['avg_diversity']} C={r['avg_completion']})"
		)


def mode_diverse_grid(
	db: VectorDbClient,
	all_projects: dict[int, dict[str, Any]],
	top_k: int,
	diverse_candidates: list[int],
) -> None:
	# noisy_user 는 신호 없음 → signal-based 사용자만 평가
	eval_users = [u for u in VIRTUAL_USERS if u.noise_rate == 0.0]

	print(f"\n{'='*70}")
	print(
		f"[초기 탐색 개수 탐색] 후보={diverse_candidates} "
		f"× {len(eval_users)}명 사용자"
	)
	print("(시간/라운드 페널티 미적용: precision, ndcg, diversity만 반영)")
	print(f"{'='*70}")

	results: list[dict[str, Any]] = []
	for idx, init_count in enumerate(diverse_candidates, 1):
		options = AnalysisOptions(initial_diverse_count=init_count)
		p_list, n_list, d_list = [], [], []
		for user in eval_users:
			m = run_simulation(db, user, all_projects, options, top_k)
			p_list.append(m["precision_at_k"])
			n_list.append(m["ndcg_at_k"])
			d_list.append(m["diversity_at_k"])

		avg_p = sum(p_list) / len(p_list)
		avg_n = sum(n_list) / len(n_list)
		avg_d = sum(d_list) / len(d_list)
		score = (
			avg_p * COMPOSITE_DIVERSE_W["precision"]
			+ avg_n * COMPOSITE_DIVERSE_W["ndcg"]
			+ avg_d * COMPOSITE_DIVERSE_W["diversity"]
		)
		results.append(
			{
				"initial_diverse_count": init_count,
				"avg_precision": round(avg_p, 3),
				"avg_ndcg": round(avg_n, 3),
				"avg_diversity": round(avg_d, 3),
				"composite_score": round(score, 3),
			}
		)
		print(
			f"  [{idx:2d}/{len(diverse_candidates)}] initial_diverse_count={init_count:2d}  "
			f"P={avg_p:.3f} NDCG={avg_n:.3f} D={avg_d:.3f}  score={score:.3f}"
		)

	results.sort(key=lambda x: x["composite_score"], reverse=True)
	print(f"\n{'─'*70}")
	print(
		"상위 3개 초기 탐색 개수 "
		f"(복합점수 = P×{COMPOSITE_DIVERSE_W['precision']} + "
		f"NDCG×{COMPOSITE_DIVERSE_W['ndcg']} + "
		f"D×{COMPOSITE_DIVERSE_W['diversity']}):"
	)
	for rank, r in enumerate(results[:3], 1):
		print(
			f"  {rank}위: initial_diverse_count={r['initial_diverse_count']}  "
			f"→ composite={r['composite_score']:.3f}  "
			f"(P={r['avg_precision']} NDCG={r['avg_ndcg']} D={r['avg_diversity']})"
		)


# ── 모드 3: 로그 리플레이 ─────────────────────────────────────────────────────

def mode_replay(
	db:       VectorDbClient,
	log_path: str,
	top_k:    int,
	options:  AnalysisOptions,
) -> None:
	"""과거 스와이프 로그를 재생하고 예측 추천의 품질을 평가한다.

	로그 파일 형식 (JSON 배열):
	  [{"image_id": 5, "action": "like"}, {"image_id": 12, "action": "dislike"}, ...]
	"""
	if not os.path.exists(log_path):
		print(f"[ERROR] 로그 파일을 찾을 수 없습니다: {log_path}")
		return

	with open(log_path, encoding="utf-8") as f:
		log: list[dict] = json.load(f)

	analyzer = PreferenceAnalyzer(db, options)
	state, response = analyzer.start_session("replay_user", "replay")

	replayed = 0
	for entry in log:
		if state.is_analysis_completed:
			break
		image_id = int(entry["image_id"])
		action   = entry.get("action", "")
		if action not in ("like", "dislike"):
			continue
		event_key = f"evt_{uuid.uuid4().hex[:10]}"
		response = analyzer.apply_swipe(state, image_id, action, event_key)
		replayed += 1

	result        = analyzer.build_result(state)
	predicted_ids = [img["image_id"] for img in result.get("predicted_like_images", [])]
	true_like_set = {int(e["image_id"]) for e in log if e.get("action") == "like"}

	p_k = calc_precision(predicted_ids, true_like_set, top_k)
	r_k = calc_recall   (predicted_ids, true_like_set, top_k)
	n_k = calc_ndcg     (predicted_ids, true_like_set, top_k)

	print(f"\n{'='*70}")
	print(f"[리플레이] 로그: {log_path}")
	print(f"{'='*70}")
	print(f"  재생 이벤트 수:   {replayed}")
	print(f"  로그 내 like 수:  {len(true_like_set)}")
	print(f"  최종 추천 수:     {len(predicted_ids)}")
	print(f"  Precision@{top_k}: {p_k:.3f}")
	print(f"  Recall@{top_k}:    {r_k:.3f}")
	print(f"  NDCG@{top_k}:      {n_k:.3f}")
	print(f"\n  -- liked during session --")
	for iid in sorted(state.liked_image_ids):
		print(f"     image_id={iid}")


# ── 진입점 ────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="ARCHITON 오프라인 평가 스크립트")
	parser.add_argument(
		"--mode", choices=["simulate", "grid", "diverse_grid", "replay"], default="simulate",
		help="실행 모드 (기본: simulate)",
	)
	parser.add_argument("--top-k",       type=int, default=TOP_K_DEFAULT,
	                    help="Precision/Recall/NDCG 계산 기준 K (기본: 10)")
	parser.add_argument(
		"--diverse-candidates",
		type=str,
		default=",".join(str(v) for v in GRID_INITIAL_DIVERSE_COUNTS),
		help="초기 탐색 개수 후보 리스트 (쉼표 구분, 예: 6,10,14,18,24,30)",
	)
	parser.add_argument("--log",          type=str, default="replay_log.json",
	                    help="--mode replay 시 사용할 로그 JSON 파일 경로")
	parser.add_argument("--db-host",      type=str, default=DEFAULT_DB_HOST)
	parser.add_argument("--db-port",      type=int, default=DEFAULT_DB_PORT)
	parser.add_argument("--db-user",      type=str, default=DEFAULT_DB_USER)
	parser.add_argument("--db-password",  type=str, default=DEFAULT_DB_PASSWORD)
	parser.add_argument("--db-name",      type=str, default=DEFAULT_DB_NAME)
	parser.add_argument("--table",        type=str, default=DEFAULT_TABLE)
	return parser.parse_args()


def main() -> None:
	args = parse_args()

	cfg = DbConfig(
		host=args.db_host, port=args.db_port,
		user=args.db_user, password=args.db_password,
		db_name=args.db_name, table=args.table,
	)
	db = VectorDbClient(cfg)

	try:
		print("[DB 검증 중...]")
		info = db.validate()
		print(
			f"  DB={info['db_name']}  rows={info['total_rows']}  "
			f"dim={info['min_dim']}  NULL_emb={info['embedding_null_rows']}"
		)

		all_projects = load_all_projects(db)
		print(f"  메타데이터 로드: {len(all_projects)}건\n")

		options = AnalysisOptions()

		if args.mode == "simulate":
			mode_simulate(db, all_projects, args.top_k, options)
		elif args.mode == "grid":
			mode_grid(db, all_projects, args.top_k)
		elif args.mode == "diverse_grid":
			candidates = parse_int_csv(args.diverse_candidates)
			mode_diverse_grid(db, all_projects, args.top_k, candidates)
		elif args.mode == "replay":
			mode_replay(db, args.log, args.top_k, options)
	finally:
		db.close()


if __name__ == "__main__":
	main()
