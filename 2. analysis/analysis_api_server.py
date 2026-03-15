import argparse
import json
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from analysis import AnalysisOptions, DbConfig
from analysis_service import AnalysisService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ARCHITON analysis API server")
    parser.add_argument("--host", type=str, default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--db-host", type=str, default="localhost")
    parser.add_argument("--db-port", type=int, default=5432)
    parser.add_argument("--db-user", type=str, default="postgres")
    parser.add_argument("--db-password", type=str, default="")
    parser.add_argument("--db-name", type=str, default="into_database")
    parser.add_argument("--table", type=str, default="architecture_vectors")
    parser.add_argument("--total-rounds", type=int, default=100)
    return parser.parse_args()


def build_service(args: argparse.Namespace) -> AnalysisService:
    cfg = DbConfig(
        host=args.db_host,
        port=args.db_port,
        user=args.db_user,
        password=args.db_password,
        db_name=args.db_name,
        table=args.table,
    )
    options = AnalysisOptions(total_rounds=args.total_rounds)
    return AnalysisService(cfg, options)


class ApiHandler(BaseHTTPRequestHandler):
    service: AnalysisService

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def do_GET(self) -> None:
        if self.path == "/health":
            return self._send_json(self.service.health())

        m_debug = re.fullmatch(r"/api/v1/analysis/sessions/([^/]+)/debug", self.path)
        if m_debug:
            result = self.service.get_session_debug(m_debug.group(1))
            code = HTTPStatus.OK if "error_code" not in result else HTTPStatus.NOT_FOUND
            return self._send_json(result, int(code))

        m_result = re.fullmatch(r"/api/v1/analysis/sessions/([^/]+)/result", self.path)
        if m_result:
            result = self.service.get_result(m_result.group(1))
            code = HTTPStatus.OK if "error_code" not in result else HTTPStatus.NOT_FOUND
            return self._send_json(result, int(code))

        return self._send_json({"error_code": "NOT_FOUND", "message": "route not found"}, int(HTTPStatus.NOT_FOUND))

    def do_POST(self) -> None:
        if self.path == "/api/v1/analysis/sessions":
            body = self._read_json()
            user_id = str(body.get("user_id", "")).strip()
            project_id = str(body.get("project_id", "")).strip()
            if not user_id or not project_id:
                return self._send_json(
                    {
                        "error_code": "INVALID_INPUT",
                        "message": "user_id and project_id are required",
                    },
                    int(HTTPStatus.BAD_REQUEST),
                )

            result = self.service.start_session(user_id=user_id, project_id=project_id)
            return self._send_json(result, int(HTTPStatus.CREATED))

        m_swipe = re.fullmatch(r"/api/v1/analysis/sessions/([^/]+)/swipes", self.path)
        if m_swipe:
            body = self._read_json()
            image_id = body.get("image_id")
            action = str(body.get("action", "")).strip().lower()
            idempotency_key = body.get("idempotency_key")

            if not isinstance(image_id, int) or action not in {"like", "dislike"}:
                return self._send_json(
                    {
                        "error_code": "INVALID_INPUT",
                        "message": "image_id(int) and action(like|dislike) are required",
                    },
                    int(HTTPStatus.BAD_REQUEST),
                )

            result = self.service.submit_swipe(
                session_id=m_swipe.group(1),
                image_id=image_id,
                action=action,
                idempotency_key=idempotency_key,
            )
            code = HTTPStatus.OK if result.get("accepted", False) else HTTPStatus.NOT_FOUND
            return self._send_json(result, int(code))

        return self._send_json({"error_code": "NOT_FOUND", "message": "route not found"}, int(HTTPStatus.NOT_FOUND))


def run() -> None:
    args = parse_args()
    service = build_service(args)

    ApiHandler.service = service
    server = ThreadingHTTPServer((args.host, args.port), ApiHandler)

    print("ARCHITON analysis API server started")
    print(f"- listen: http://{args.host}:{args.port}")
    print("- health: GET /health")
    print("- start : POST /api/v1/analysis/sessions")
    print("- swipe : POST /api/v1/analysis/sessions/{session_id}/swipes")
    print("- result: GET /api/v1/analysis/sessions/{session_id}/result")
    print("- debug : GET /api/v1/analysis/sessions/{session_id}/debug")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        service.close()


if __name__ == "__main__":
    run()
