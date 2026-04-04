"""FastAPI 应用入口"""

import uuid
import logging
from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .ws_handler import handle_connection

logging.basicConfig(level=logging.INFO)

app = FastAPI()

PUBLIC_DIR = Path(__file__).parent.parent / "public"

# 挂载静态文件（css/js/assets 等子目录）
app.mount("/static", StaticFiles(directory=str(PUBLIC_DIR)), name="static")


@app.get("/")
async def index():
    return FileResponse(str(PUBLIC_DIR / "index.html"))


@app.get("/room")
async def room():
    return FileResponse(str(PUBLIC_DIR / "room.html"))


@app.get("/game")
async def game():
    return FileResponse(str(PUBLIC_DIR / "game.html"))


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    player_id = str(uuid.uuid4())
    await handle_connection(player_id, ws)
