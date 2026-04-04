from __future__ import annotations

import hashlib
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import verify_function_key
from app.core.config import get_config
from app.core.storage import get_storage

router = APIRouter()


def _get_chat_storage_mode() -> str:
    mode = str(get_config("app.function_chat_storage", "browser") or "browser")
    return "server" if mode.strip().lower() == "server" else "browser"


def _get_session_namespace(auth_token: Optional[str]) -> str:
    token = str(auth_token or "").strip()
    if not token:
        return "public"
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return f"function-{digest}"


def _normalize_snapshot(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid session payload")

    sessions = payload.get("sessions")
    if sessions is None:
        sessions = []
    if not isinstance(sessions, list):
        raise HTTPException(status_code=400, detail="Invalid sessions payload")

    active_id = payload.get("activeId")
    if active_id is None:
        active_id = ""
    if not isinstance(active_id, str):
        active_id = str(active_id)

    return {
        "activeId": active_id,
        "sessions": sessions,
    }


@router.get("/chat/sessions")
async def get_chat_sessions(
    auth_token: Optional[str] = Depends(verify_function_key),
):
    mode = _get_chat_storage_mode()
    if mode != "server":
        return {"mode": "browser", "snapshot": None}

    storage = get_storage()
    namespace = _get_session_namespace(auth_token)
    snapshot = await storage.load_function_chat_sessions(namespace)
    return {"mode": "server", "snapshot": snapshot}


@router.put("/chat/sessions")
async def save_chat_sessions(
    payload: dict[str, Any],
    auth_token: Optional[str] = Depends(verify_function_key),
):
    mode = _get_chat_storage_mode()
    if mode != "server":
        return {"status": "ignored", "mode": "browser"}

    storage = get_storage()
    namespace = _get_session_namespace(auth_token)
    await storage.save_function_chat_sessions(namespace, _normalize_snapshot(payload))
    return {"status": "success", "mode": "server"}
