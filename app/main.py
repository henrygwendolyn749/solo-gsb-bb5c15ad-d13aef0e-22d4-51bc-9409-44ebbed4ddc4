"""直流网络校核器 —— FastAPI 入口。"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .solver import NetworkError, analyze, validate_payload

app = FastAPI(title="直流网络校核器", version="1.0.0")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/analyze")
async def analyze_network(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": {"code": "bad_json",
                                            "message": "请求体不是合法的 JSON", "items": []}},
        )
    if not isinstance(payload, dict):
        return JSONResponse(
            status_code=422,
            content={"ok": False, "error": {"code": "validation_failed",
                                            "message": "请求体必须为对象", "items": []}},
        )
    try:
        net = validate_payload(payload)
        result = analyze(net)
        return JSONResponse(result)
    except NetworkError as exc:
        return JSONResponse(
            status_code=422,
            content={"ok": False,
                     "error": {"code": exc.code, "message": exc.message,
                               "items": exc.items}},
        )


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0",
                port=int(os.environ.get("PORT", "8000")))
