"""
Unit tests for app.common.body_limit.BodySizeLimitMiddleware (T7 spec §4.4).

Runs a small FastAPI app with a real multipart endpoint, so the "lying client"
case goes through FastAPI's own form parsing (which turns an aborted read into a
400 that the middleware must replace with 413).

Run with:
    cd tests/unit && PYTHONPATH=../../backend pytest test_body_limit.py -v
"""

from __future__ import annotations

from typing import Annotated

import pytest
import pytest_asyncio
from app.common.body_limit import BodySizeLimitMiddleware
from fastapi import FastAPI, File, UploadFile
from httpx import ASGITransport, AsyncClient

LIMIT = 1000


def _app() -> tuple[FastAPI, list[str]]:
    app = FastAPI()
    calls: list[str] = []

    @app.post("/api/upload")
    async def upload(file: Annotated[UploadFile, File()]) -> dict:
        calls.append("upload")
        return {"size": len(await file.read())}

    @app.get("/api/upload")
    async def get_upload() -> dict:
        return {"ok": True}

    @app.post("/api/other")
    async def other(file: Annotated[UploadFile, File()]) -> dict:
        return {"size": len(await file.read())}

    app.add_middleware(
        BodySizeLimitMiddleware, rules=[("POST", r"^/api/upload$", LIMIT)]
    )
    return app, calls


@pytest_asyncio.fixture
async def client():
    app, calls = _app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac, calls


def _files(n: int) -> dict:
    return {"file": ("f.bin", b"x" * n, "application/octet-stream")}


async def test_small_request_passes(client) -> None:
    ac, calls = client
    r = await ac.post("/api/upload", files=_files(100))
    assert r.status_code == 200
    assert r.json() == {"size": 100}
    assert calls == ["upload"]


async def test_declared_length_over_limit_rejected_without_calling_app(client) -> None:
    ac, calls = client
    r = await ac.post("/api/upload", files=_files(5000))
    assert r.status_code == 413
    assert r.json()["error"] == "REQUEST_TOO_LARGE"
    assert calls == []


async def test_chunked_body_over_limit_rejected(client) -> None:
    ac, calls = client

    async def chunks():
        yield b"--b\r\nContent-Disposition: form-data; name=file; filename=f\r\n\r\n"
        for _ in range(20):
            yield b"x" * 200
        yield b"\r\n--b--\r\n"

    r = await ac.post(
        "/api/upload",
        content=chunks(),
        headers={"Content-Type": "multipart/form-data; boundary=b"},
    )
    assert "content-length" not in r.request.headers
    assert r.status_code == 413
    assert r.json()["error"] == "REQUEST_TOO_LARGE"
    assert calls == []


async def test_understated_content_length_rejected(client) -> None:
    ac, calls = client
    body = b"--b\r\nContent-Disposition: form-data; name=file; filename=f\r\n\r\n"
    body += b"x" * 5000 + b"\r\n--b--\r\n"

    async def stream():
        yield body

    r = await ac.post(
        "/api/upload",
        content=stream(),
        headers={
            "Content-Type": "multipart/form-data; boundary=b",
            "Content-Length": "10",
        },
    )
    assert r.status_code == 413
    assert calls == []


@pytest.mark.parametrize(
    ("method", "path"), [("GET", "/api/upload"), ("POST", "/api/other")]
)
async def test_unmatched_requests_untouched(client, method: str, path: str) -> None:
    ac, _ = client
    if method == "GET":
        r = await ac.get(path)
    else:
        r = await ac.post(path, files=_files(5000))
    assert r.status_code == 200
