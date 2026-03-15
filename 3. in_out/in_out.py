"""ARCHITON in/out bridge.

This module bridges:
1) backend analysis service in `2. analysis/analysis.py`
2) frontend JSX contract in `dist/frontend/*.jsx`

Main interaction sequence in one file:
- POST /api/auth/login
- POST /api/v1/analysis/sessions
- POST /api/v1/analysis/sessions/{session_id}/swipes
- GET|POST /api/v1/analysis/sessions/{session_id}/result

Run:
  python in_out.py --host 127.0.0.1 --port 8010
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import re
import shutil
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from typing import Any


# ---------------------------------------------------------------------------
# Paths and imports
# ---------------------------------------------------------------------------

ROOT_DIR = Path(__file__).resolve().parents[1]
ANALYSIS_DIR = ROOT_DIR / "2. analysis"
FRONTEND_DIR = ROOT_DIR / "dist" / "frontend"
DIST_DIR = ROOT_DIR / "dist"
TRACKING_DIR = ROOT_DIR / "3. in_out"
TRACKING_DB_PATH = TRACKING_DIR / "user_tracking.db"
TRACKING_SCHEMA_SQL_PATH = TRACKING_DIR / "user_tracking.sql"
LEGACY_TRACKING_DB_PATH = TRACKING_DIR / "user_tracking"

if str(ANALYSIS_DIR) not in sys.path:
	sys.path.insert(0, str(ANALYSIS_DIR))

from analysis import AnalysisOptions, DbConfig  # noqa: E402 # type: ignore[import-not-found]
from analysis_service import AnalysisService  # noqa: E402 # type: ignore[import-not-found]


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def utc_now_iso() -> str:
	return datetime.now(timezone.utc).isoformat()


def migrate_legacy_tracking_db() -> None:
	if TRACKING_DB_PATH.exists():
		return
	if LEGACY_TRACKING_DB_PATH.exists() and LEGACY_TRACKING_DB_PATH.is_file():
		shutil.copy2(LEGACY_TRACKING_DB_PATH, TRACKING_DB_PATH)


def ensure_tracking_tables(db_path: Path) -> None:
	conn = sqlite3.connect(str(db_path))
	try:
		cur = conn.cursor()

		# Optional schema source of truth for SQL-based management.
		if TRACKING_SCHEMA_SQL_PATH.exists():
			sql_script = TRACKING_SCHEMA_SQL_PATH.read_text(encoding="utf-8")
			if sql_script.strip():
				conn.executescript(sql_script)

		# 1) user_credentials table (create or migrate columns)
		cur.execute(
			"""
			CREATE TABLE IF NOT EXISTS user_credentials (
				user_id TEXT PRIMARY KEY,
				password TEXT NOT NULL,
				created_at TEXT
			)
			"""
		)
		cur.execute("PRAGMA table_info(user_credentials)")
		creds_cols = {r[1] for r in cur.fetchall()}
		if "created_at" not in creds_cols:
			cur.execute("ALTER TABLE user_credentials ADD COLUMN created_at TEXT")

		# 2) liked_projects table (create or migrate columns)
		cur.execute(
			"""
			CREATE TABLE IF NOT EXISTS liked_projects (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				user_id TEXT,
				project_id TEXT,
				image_id INTEGER,
				project_name TEXT,
				url TEXT,
				architect TEXT,
				location_country TEXT,
				program TEXT,
				year TEXT,
				mood TEXT,
				material TEXT,
				liked_at TEXT
			)
			"""
		)
		cur.execute("PRAGMA table_info(liked_projects)")
		liked_cols = {r[1] for r in cur.fetchall()}
		required = {
			"user_id": "TEXT",
			"project_id": "TEXT",
			"image_id": "INTEGER",
			"project_name": "TEXT",
			"url": "TEXT",
			"architect": "TEXT",
			"location_country": "TEXT",
			"program": "TEXT",
			"year": "TEXT",
			"mood": "TEXT",
			"material": "TEXT",
			"liked_at": "TEXT",
		}
		for col, col_type in required.items():
			if col not in liked_cols:
				cur.execute(f"ALTER TABLE liked_projects ADD COLUMN {col} {col_type}")

		# Try to enforce dedup index if existing data allows it.
		try:
			cur.execute("DROP INDEX IF EXISTS ux_liked_projects_user_image")
			cur.execute(
				"CREATE UNIQUE INDEX IF NOT EXISTS ux_liked_projects_user_image ON liked_projects(user_id, project_id, image_id)"
			)
		except sqlite3.Error:
			pass

		# Backfill created_at for legacy rows if missing.
		now = utc_now_iso()
		cur.execute("UPDATE user_credentials SET created_at = COALESCE(created_at, ?)", (now,))
		cur.execute("UPDATE liked_projects SET liked_at = COALESCE(liked_at, ?)", (now,))
		conn.commit()
	finally:
		conn.close()


def map_backend_card_to_frontend(card: dict[str, Any] | None) -> dict[str, Any] | None:
	if not card:
		return None
	image_id = int(card.get("image_id"))
	metadata = card.get("metadata") or {}

	# Frontend SwipePage expects axis_typology/axis_architects/axis_country keys.
	frontend_meta = {
		"axis_typology": metadata.get("program"),
		"axis_architects": metadata.get("architect"),
		"axis_country": metadata.get("axis_location"),
		"axis_area_m2": None,
		"axis_capacity": None,
		"axis_year": metadata.get("axis_year"),
		"axis_mood": metadata.get("mood"),
		"axis_material": metadata.get("material"),
	}

	image_url = card.get("image_url")
	if not image_url:
		image_url = f"https://picsum.photos/seed/architon-{image_id}/800/1000"

	return {
		"image_id": image_id,
		"building_id": str(image_id),
		"image_title": card.get("image_title") or "untitled",
		"title": card.get("image_title") or "untitled",
		"image_url": image_url,
		"imageUrl": image_url,
		"source_url": card.get("source_url"),
		"metadata": frontend_meta,
		"gallery": [],
	}


def extract_frontend_contract(frontend_dir: Path) -> dict[str, Any]:
	app_path = frontend_dir / "App.jsx"
	swipe_path = frontend_dir / "SwipePage.jsx"
	login_path = frontend_dir / "LoginPage.jsx"

	contract: dict[str, Any] = {
		"frontend_exists": app_path.exists() and swipe_path.exists() and login_path.exists(),
		"app_api_functions": [],
		"swipe_required_fields": [
			"next_image.image_id",
			"next_image.image_url",
			"next_image.image_title",
			"next_image.metadata.axis_typology",
			"next_image.metadata.axis_architects",
			"next_image.metadata.axis_country",
		],
	}
	if not app_path.exists():
		return contract

	app_text = app_path.read_text(encoding="utf-8", errors="ignore")
	contract["app_api_functions"] = sorted(set(re.findall(r"api\.([a-zA-Z_][a-zA-Z0-9_]*)\(", app_text)))
	return contract


# ---------------------------------------------------------------------------
# Bridge service
# ---------------------------------------------------------------------------

class InOutBridge:
	def __init__(self, analysis_service: AnalysisService, tracking_db: Path, frontend_dir: Path):
		self.analysis_service = analysis_service
		self.tracking_db = tracking_db
		self.frontend_contract = extract_frontend_contract(frontend_dir)
		self.session_project_owner: dict[str, tuple[str, str]] = {}

	def close(self) -> None:
		self.analysis_service.close()

	def _resolve_candidate_ids_from_preloaded_images(self, preloaded_images: list[dict[str, Any]]) -> list[int]:
		if not preloaded_images:
			return []

		resolved_ids: list[int] = []
		db = self.analysis_service.db
		query_by_url = f"SELECT id FROM {db.cfg.table} WHERE url = %s LIMIT 1"
		query_by_project_name = f"SELECT id FROM {db.cfg.table} WHERE project_name = %s LIMIT 1"

		with db.conn.cursor() as cur:
			for card in preloaded_images:
				image_title = str(card.get("image_title") or card.get("title") or "").strip()
				source_url = str(card.get("source_url") or card.get("url") or "").strip()
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

	# ---- auth ----
	def login(self, user_id: str, password: str) -> dict[str, Any]:
		if len(user_id.strip()) < 2:
			raise ValueError("user_id must be at least 2 chars")
		if len(password) < 4:
			raise ValueError("password must be at least 4 chars")

		conn = sqlite3.connect(str(self.tracking_db))
		try:
			cur = conn.cursor()
			cur.execute("SELECT password FROM user_credentials WHERE user_id = ?", (user_id,))
			row = cur.fetchone()
			if row is None:
				cur.execute(
					"INSERT INTO user_credentials (user_id, password, created_at) VALUES (?, ?, ?)",
					(user_id, password, utc_now_iso()),
				)
				conn.commit()
				return {"success": True, "user_id": user_id, "is_new": True}

			if row[0] != password:
				return {
					"success": False,
					"error_code": "UNAUTHORIZED",
					"message": "invalid password",
				}

			return {"success": True, "user_id": user_id, "is_new": False}
		finally:
			conn.close()

	# ---- analysis session ----
	def start_session(self, payload: dict[str, Any]) -> dict[str, Any]:
		user_id = str(payload.get("user_id", "")).strip()
		project_id = str(payload.get("project_id", "")).strip()
		if not user_id or not project_id:
			raise ValueError("user_id and project_id are required")

		candidate_ids_raw = payload.get("candidate_ids") or []
		candidate_ids = [int(image_id) for image_id in candidate_ids_raw if isinstance(image_id, int)]
		preloaded_images = payload.get("preloaded_images") or []
		if not candidate_ids and isinstance(preloaded_images, list):
			candidate_ids = self._resolve_candidate_ids_from_preloaded_images(preloaded_images)

		result = self.analysis_service.start_session(
			user_id=user_id,
			project_id=project_id,
			candidate_ids=candidate_ids or None,
		)
		session_id = result.get("session_id")
		if session_id:
			self.session_project_owner[str(session_id)] = (user_id, project_id)

		return {
			**result,
			"next_image": map_backend_card_to_frontend(result.get("next_image")),
		}

	def submit_swipe(self, session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
		image_id = payload.get("image_id")
		action = str(payload.get("action", "")).strip().lower()
		if not isinstance(image_id, int):
			raise ValueError("image_id(int) is required")
		if action not in {"like", "dislike"}:
			raise ValueError("action must be like or dislike")

		result = self.analysis_service.submit_swipe(
			session_id=session_id,
			image_id=image_id,
			action=action,
			idempotency_key=payload.get("idempotency_key") or f"evt_{uuid.uuid4().hex[:10]}",
		)
		if result.get("accepted") and action == "like":
			liked_card = self.analysis_service.db.get_image_card(image_id)
			mapped_card = map_backend_card_to_frontend(liked_card)
			if mapped_card is not None:
				self._persist_liked_projects(session_id, [mapped_card])
		if result.get("next_image") is not None:
			result["next_image"] = map_backend_card_to_frontend(result.get("next_image"))
		return result

	def get_result(self, session_id: str) -> dict[str, Any]:
		result = self.analysis_service.get_result(session_id)
		if "error_code" in result:
			return result

		liked = [map_backend_card_to_frontend(c) for c in result.get("liked_images", [])]
		pred = [map_backend_card_to_frontend(c) for c in result.get("predicted_like_images", [])]
		liked = [x for x in liked if x is not None]
		pred = [x for x in pred if x is not None]

		result["liked_images"] = liked
		result["predicted_like_images"] = pred
		return result

	def _persist_liked_projects(self, session_id: str, liked_cards: list[dict[str, Any]]) -> None:
		owner = self.session_project_owner.get(session_id)
		if owner is None:
			return
		user_id, project_id = owner

		conn = sqlite3.connect(str(self.tracking_db))
		try:
			cur = conn.cursor()
			for card in liked_cards:
				md = card.get("metadata") or {}
				cur.execute(
					"""
					INSERT OR IGNORE INTO liked_projects (
						user_id, project_id, image_id, project_name, url,
						architect, location_country, program,
						year, mood, material, liked_at
					) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
					""",
					(
						user_id,
						project_id,
						int(card.get("image_id")),
						card.get("image_title"),
						card.get("source_url"),
						md.get("axis_architects"),
						md.get("axis_country"),
						md.get("axis_typology"),
						md.get("axis_year"),
						md.get("axis_mood"),
						md.get("axis_material"),
						utc_now_iso(),
					),
				)
			conn.commit()
		finally:
			conn.close()


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class InOutHandler(BaseHTTPRequestHandler):
	bridge: InOutBridge

	def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
		body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
		self.send_response(status)
		self.send_header("Content-Type", "application/json; charset=utf-8")
		self.send_header("Content-Length", str(len(body)))
		self.send_header("Access-Control-Allow-Origin", "*")
		self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Request-Id, Authorization")
		self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, OPTIONS")
		self.end_headers()
		self.wfile.write(body)

	def _read_json(self) -> dict[str, Any]:
		length = int(self.headers.get("Content-Length", "0") or "0")
		if length <= 0:
			return {}
		raw = self.rfile.read(length)
		return json.loads(raw.decode("utf-8"))

	def _send_file(self, file_path: Path) -> None:
		content = file_path.read_bytes()
		content_type, _ = mimetypes.guess_type(str(file_path))
		self.send_response(200)
		self.send_header("Content-Type", content_type or "application/octet-stream")
		self.send_header("Content-Length", str(len(content)))
		self.end_headers()
		self.wfile.write(content)

	def _serve_frontend(self, route_path: str) -> bool:
		if not DIST_DIR.exists():
			return False

		request_path = route_path or "/"
		if request_path == "/":
			candidate = DIST_DIR / "index.html"
			if candidate.exists():
				self._send_file(candidate)
				return True
			return False

		rel = request_path.lstrip("/")
		candidate = (DIST_DIR / rel).resolve()
		try:
			candidate.relative_to(DIST_DIR.resolve())
		except ValueError:
			return False

		if candidate.is_dir():
			candidate = candidate / "index.html"

		if candidate.exists() and candidate.is_file():
			self._send_file(candidate)
			return True

		# SPA fallback for frontend routes like /swipe or /folders.
		if "." not in rel:
			index_file = DIST_DIR / "index.html"
			if index_file.exists():
				self._send_file(index_file)
				return True

		return False

	def do_OPTIONS(self) -> None:
		self._send_json({}, 200)

	def do_GET(self) -> None:
		parsed = urlparse(self.path)
		route_path = parsed.path

		if route_path == "/health":
			data = self.bridge.analysis_service.health()
			return self._send_json(
				{
					"ok": True,
					"backend": data,
					"frontend_contract": self.bridge.frontend_contract,
				},
				200,
			)

		m_result = re.fullmatch(r"/api/v1/analysis/sessions/([^/]+)/result", route_path)
		if m_result:
			result = self.bridge.get_result(m_result.group(1))
			code = HTTPStatus.OK if "error_code" not in result else HTTPStatus.NOT_FOUND
			return self._send_json(result, int(code))

		m_debug = re.fullmatch(r"/api/v1/analysis/sessions/([^/]+)/debug", route_path)
		if m_debug:
			result = self.bridge.analysis_service.get_session_debug(m_debug.group(1))
			code = HTTPStatus.OK if "error_code" not in result else HTTPStatus.NOT_FOUND
			return self._send_json(result, int(code))

		if self._serve_frontend(route_path):
			return

		return self._send_json({"error_code": "NOT_FOUND", "message": "route not found"}, 404)

	def do_POST(self) -> None:
		try:
			body = self._read_json()
			if self.path in {"/api/auth/login", "/api/v1/auth/login"}:
				data = self.bridge.login(
					user_id=str(body.get("id") or body.get("user_id") or "").strip(),
					password=str(body.get("password") or ""),
				)
				if data.get("success"):
					return self._send_json(data, 200)
				return self._send_json(data, 401)

			if self.path == "/api/v1/analysis/sessions":
				result = self.bridge.start_session(body)
				return self._send_json(result, 201)

			m_swipe = re.fullmatch(r"/api/v1/analysis/sessions/([^/]+)/swipes", self.path)
			if m_swipe:
				result = self.bridge.submit_swipe(m_swipe.group(1), body)
				code = HTTPStatus.OK if result.get("accepted", False) else HTTPStatus.NOT_FOUND
				return self._send_json(result, int(code))

			# Supports both GET and POST for frontend API wrapper flexibility.
			m_result = re.fullmatch(r"/api/v1/analysis/sessions/([^/]+)/result", self.path)
			if m_result:
				result = self.bridge.get_result(m_result.group(1))
				code = HTTPStatus.OK if "error_code" not in result else HTTPStatus.NOT_FOUND
				return self._send_json(result, int(code))

			return self._send_json({"error_code": "NOT_FOUND", "message": "route not found"}, 404)
		except ValueError as e:
			return self._send_json({"error_code": "INVALID_INPUT", "message": str(e)}, 400)
		except Exception as e:  # pragma: no cover
			return self._send_json({"error_code": "INTERNAL_ERROR", "message": str(e)}, 500)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="ARCHITON in/out bridge server")
	parser.add_argument("--host", type=str, default="127.0.0.1")
	parser.add_argument("--port", type=int, default=3001)
	parser.add_argument("--db-host", type=str, default="localhost")
	parser.add_argument("--db-port", type=int, default=5432)
	parser.add_argument("--db-user", type=str, default="postgres")
	parser.add_argument("--db-password", type=str, default="")
	parser.add_argument("--db-name", type=str, default="into_database")
	parser.add_argument("--table", type=str, default="architecture_vectors")
	parser.add_argument("--total-rounds", type=int, default=20)
	return parser.parse_args()


def build_bridge(args: argparse.Namespace) -> InOutBridge:
	migrate_legacy_tracking_db()
	ensure_tracking_tables(TRACKING_DB_PATH)
	cfg = DbConfig(
		host=args.db_host,
		port=args.db_port,
		user=args.db_user,
		password=args.db_password,
		db_name=args.db_name,
		table=args.table,
	)
	options = AnalysisOptions(total_rounds=args.total_rounds)
	service = AnalysisService(cfg=cfg, options=options)
	return InOutBridge(service, TRACKING_DB_PATH, FRONTEND_DIR)


def run() -> None:
	args = parse_args()
	bridge = build_bridge(args)

	InOutHandler.bridge = bridge
	server = ThreadingHTTPServer((args.host, args.port), InOutHandler)
	print("ARCHITON in/out bridge started")
	print(f"- listen: http://{args.host}:{args.port}")
	print("- web   : GET /")
	print("- health: GET /health")
	print("- auth  : POST /api/auth/login")
	print("- start : POST /api/v1/analysis/sessions")
	print("- swipe : POST /api/v1/analysis/sessions/{session_id}/swipes")
	print("- result: GET|POST /api/v1/analysis/sessions/{session_id}/result")
	print("- debug : GET /api/v1/analysis/sessions/{session_id}/debug")

	try:
		server.serve_forever()
	except KeyboardInterrupt:
		pass
	finally:
		server.server_close()
		bridge.close()


if __name__ == "__main__":
	run()
