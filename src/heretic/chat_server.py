# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025-2026  Philipp Emanuel Weidmann <pew@worldwidemann.com> + contributors

import json
import logging
import os
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    TomlConfigSettingsSource,
)

from .config import Settings
from .model import Model

logger = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parent.parent.parent / "web"


class ChatSettings(Settings):
    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            TomlConfigSettingsSource(settings_cls, toml_file="config.toml"),
        )


def load_chat_settings() -> Settings:
    model_id = os.environ.get("HERETIC_MODEL")
    if not model_id:
        raise RuntimeError(
            "HERETIC_MODEL environment variable is required for heretic-chat"
        )

    return ChatSettings(model=model_id)


model: Model | None = None
settings: Settings | None = None
model_error: str | None = None
model_loading = False
_model_lock = threading.Lock()


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1)


def get_api_key() -> str | None:
    return os.environ.get("CHAT_API_KEY")


def verify_api_key(request: Request) -> None:
    expected = get_api_key()
    if expected is None:
        return

    provided = request.headers.get("x-api-key")
    if provided != expected:
        raise HTTPException(status_code=401, detail="Invalid API key")


def require_ready_model() -> Model:
    if model_error is not None:
        raise HTTPException(status_code=503, detail=model_error)

    if model is None or model_loading:
        raise HTTPException(status_code=503, detail="Model is still loading")

    return model


def load_model_in_background() -> None:
    global model, settings, model_error, model_loading

    with _model_lock:
        model_loading = True
        model_error = None

    try:
        loaded_settings = load_chat_settings()
        logger.info("Downloading and loading model %s...", loaded_settings.model)
        loaded_model = Model(loaded_settings)
    except Exception as exc:  # noqa: BLE001 - surface startup failures via /api/health
        logger.exception("Failed to load model")
        with _model_lock:
            model_error = str(exc)
            model_loading = False
        return

    with _model_lock:
        settings = loaded_settings
        model = loaded_model
        model_loading = False

    logger.info("Model %s is ready", loaded_settings.model)


@asynccontextmanager
async def lifespan(_: FastAPI):
    thread = threading.Thread(target=load_model_in_background, daemon=True)
    thread.start()

    yield

    global model, settings, model_error, model_loading
    with _model_lock:
        model = None
        settings = None
        model_error = None
        model_loading = False


app = FastAPI(title="Heretic Chat", lifespan=lifespan)


@app.get("/api/health")
def health() -> dict[str, str | bool]:
    if model_error is not None:
        return {
            "status": "error",
            "model_loaded": False,
            "model": settings.model
            if settings
            else os.environ.get("HERETIC_MODEL", ""),
            "detail": model_error,
        }

    if model_loading or model is None:
        return {
            "status": "loading",
            "model_loaded": False,
            "model": settings.model
            if settings
            else os.environ.get("HERETIC_MODEL", ""),
        }

    return {
        "status": "ready",
        "model_loaded": True,
        "model": settings.model if settings else "",
    }


@app.get("/api/config")
def config() -> dict[str, str]:
    if settings is None:
        model_name = os.environ.get("HERETIC_MODEL", "")
        system_prompt = os.environ.get(
            "HERETIC_SYSTEM_PROMPT",
            "You are a helpful assistant.",
        )
        return {
            "model": model_name,
            "system_prompt": system_prompt,
            "status": "loading" if model_loading or model is None else "ready",
        }

    return {
        "model": settings.model,
        "system_prompt": settings.system_prompt,
        "status": "ready",
    }


@app.post("/api/chat")
def chat(request: Request, body: ChatRequest) -> dict[str, str]:
    verify_api_key(request)

    loaded_model = require_ready_model()
    messages = [message.model_dump() for message in body.messages]
    response = loaded_model.stream_chat_response(messages)

    return {"message": response}


async def stream_chat_events(messages: list[dict[str, str]]) -> AsyncIterator[str]:
    try:
        loaded_model = require_ready_model()
    except HTTPException as exc:
        yield f"data: {json.dumps({'error': exc.detail})}\n\n"
        return

    try:
        for chunk in loaded_model.iter_chat_response(messages):
            yield f"data: {json.dumps({'content': chunk})}\n\n"
    except Exception as exc:  # noqa: BLE001 - surface generation errors to the client
        yield f"data: {json.dumps({'error': str(exc)})}\n\n"
    finally:
        yield "data: [DONE]\n\n"


@app.post("/api/chat/stream")
async def chat_stream(request: Request, body: ChatRequest) -> StreamingResponse:
    verify_api_key(request)

    messages = [message.model_dump() for message in body.messages]

    return StreamingResponse(
        stream_chat_events(messages),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


if WEB_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=WEB_DIR), name="assets")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))

    uvicorn.run(
        "heretic.chat_server:app",
        host=host,
        port=port,
        log_level=os.environ.get("LOG_LEVEL", "info").lower(),
    )
