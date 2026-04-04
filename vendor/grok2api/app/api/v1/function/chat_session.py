from __future__ import annotations

import hashlib
import re
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import verify_function_key
from app.core.config import get_config
from app.core.storage import get_storage

router = APIRouter()


def _get_function_state_storage_mode() -> str:
    mode = get_config("app.function_state_storage", None)
    if mode in (None, ""):
        mode = get_config("app.function_chat_storage", "browser")
    mode = str(mode or "browser")
    return "server" if mode.strip().lower() == "server" else "browser"


def _get_session_namespace(auth_token: Optional[str], state_name: str) -> str:
    token = str(auth_token or "").strip()
    if not token:
        return f"public:{state_name}"
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return f"function-{digest}:{state_name}"


def _normalize_state_name(value: str) -> str:
    text = str(value or "").strip().lower()
    if not text:
        raise HTTPException(status_code=400, detail="Missing state name")
    if not re.fullmatch(r"[a-z0-9_-]{1,32}", text):
        raise HTTPException(status_code=400, detail="Invalid state name")
    return text


def _normalize_snapshot(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid state payload")
    return payload


async def _get_state_impl(
    state_name: str,
    auth_token: Optional[str],
):
    mode = _get_function_state_storage_mode()
    if mode != "server":
        return {"mode": "browser", "snapshot": None}

    storage = get_storage()
    namespace = _get_session_namespace(auth_token, _normalize_state_name(state_name))
    snapshot = await storage.load_function_state(namespace)
    return {"mode": "server", "snapshot": snapshot}


async def _save_state_impl(
    state_name: str,
    payload: dict[str, Any],
    auth_token: Optional[str],
):
    mode = _get_function_state_storage_mode()
    if mode != "server":
        return {"status": "ignored", "mode": "browser"}

    storage = get_storage()
    namespace = _get_session_namespace(auth_token, _normalize_state_name(state_name))
    lock_name = f"function_state:{namespace}"
    async with storage.acquire_lock(lock_name, timeout=10):
        await storage.save_function_state(namespace, _normalize_snapshot(payload))
    return {"status": "success", "mode": "server"}


@router.get("/state/{state_name}")
async def get_function_state(
    state_name: str,
    auth_token: Optional[str] = Depends(verify_function_key),
):
    return await _get_state_impl(state_name, auth_token)


@router.put("/state/{state_name}")
async def save_function_state(
    state_name: str,
    payload: dict[str, Any],
    auth_token: Optional[str] = Depends(verify_function_key),
):
    return await _save_state_impl(state_name, payload, auth_token)


@router.get("/chat/sessions")
async def get_chat_sessions(
    auth_token: Optional[str] = Depends(verify_function_key),
):
    return await _get_state_impl("chat", auth_token)


@router.put("/chat/sessions")
async def save_chat_sessions(
    payload: dict[str, Any],
    auth_token: Optional[str] = Depends(verify_function_key),
):
    return await _save_state_impl("chat", payload, auth_token)
