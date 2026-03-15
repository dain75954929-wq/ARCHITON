from dataclasses import asdict
from typing import Any

from analysis import AnalysisOptions, DbConfig, PreferenceAnalyzer, SessionState, VectorDbClient


class AnalysisService:
    """In-memory session service for ARCHITON preference analysis."""

    def __init__(self, cfg: DbConfig, options: AnalysisOptions | None = None):
        self.cfg = cfg
        self.options = options or AnalysisOptions()
        self.db = VectorDbClient(cfg)
        self.analyzer = PreferenceAnalyzer(self.db, self.options)
        self.sessions: dict[str, SessionState] = {}

    def close(self) -> None:
        self.db.close()

    def health(self) -> dict[str, Any]:
        validation = self.db.validate()
        return {
            "ok": True,
            "validation": validation,
        }

    def start_session(
        self,
        user_id: str,
        project_id: str,
        candidate_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        state, response = self.analyzer.start_session(
            user_id=user_id,
            project_id=project_id,
            candidate_ids=candidate_ids,
        )
        self.sessions[state.session_id] = state
        return response

    def submit_swipe(
        self,
        session_id: str,
        image_id: int,
        action: str,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        state = self.sessions.get(session_id)
        if state is None:
            return {
                "accepted": False,
                "error_code": "NOT_FOUND",
                "message": "session not found",
            }

        return self.analyzer.apply_swipe(
            state=state,
            image_id=image_id,
            action=action,
            idempotency_key=idempotency_key,
        )

    def get_result(self, session_id: str) -> dict[str, Any]:
        state = self.sessions.get(session_id)
        if state is None:
            return {
                "error_code": "NOT_FOUND",
                "message": "session not found",
            }

        return self.analyzer.build_result(state)

    def get_session_debug(self, session_id: str) -> dict[str, Any]:
        state = self.sessions.get(session_id)
        if state is None:
            return {
                "error_code": "NOT_FOUND",
                "message": "session not found",
            }

        return {
            "session_id": state.session_id,
            "user_id": state.user_id,
            "project_id": state.project_id,
            "session_status": state.session_status,
            "is_analysis_completed": state.is_analysis_completed,
            "progress": {
                "current_round": state.current_round,
                "total_rounds": state.options.total_rounds,
                "like_count": len(state.liked_image_ids),
                "dislike_count": len(state.disliked_image_ids),
            },
            "exposed_image_ids": sorted(state.exposed_image_ids),
            "liked_image_ids": sorted(state.liked_image_ids),
            "disliked_image_ids": sorted(state.disliked_image_ids),
            "swiped_image_ids": sorted(state.swiped_image_ids),
            "options": asdict(state.options),
        }
