"""WebSocket 消息路由与处理"""

import json
import logging
from fastapi import WebSocket, WebSocketDisconnect

from .room_manager import room_manager, Room

logger = logging.getLogger(__name__)


# ─── 发送辅助 ────────────────────────────────────────────────────────

async def send_to_player(ws: WebSocket, message: dict):
    """向单个玩家发送 JSON 消息"""
    try:
        await ws.send_text(json.dumps(message, ensure_ascii=False))
    except Exception:
        pass  # 连接已断开，忽略


async def broadcast_to_room(room: Room, message: dict):
    """向房间所有人发送相同消息"""
    for info in list(room.players.values()):
        await send_to_player(info.ws, message)


async def broadcast_room_update(room: Room):
    """构造 room_update 并广播"""
    msg = {
        "type": "room_update",
        "room_code": room.room_code,
        "players": room.player_list(),
    }
    await broadcast_to_room(room, msg)


# ─── 消息处理函数 ─────────────────────────────────────────────────────

async def handle_create_room(player_id: str, data: dict, ws: WebSocket):
    player_name = data.get("player_name", "").strip()
    if not player_name:
        await send_to_player(ws, {"type": "error", "message": "昵称不能为空"})
        return

    room = room_manager.create_room(player_id, player_name, ws)
    await send_to_player(ws, {
        "type": "room_created",
        "room_code": room.room_code,
        "player_id": player_id,
    })
    await broadcast_room_update(room)


async def handle_join_room(player_id: str, data: dict, ws: WebSocket):
    room_code = data.get("room_code", "").strip().upper()
    player_name = data.get("player_name", "").strip()

    if not room_code or not player_name:
        await send_to_player(ws, {"type": "error", "message": "房间码和昵称不能为空"})
        return

    try:
        room = room_manager.join_room(room_code, player_id, player_name, ws)
    except ValueError as e:
        await send_to_player(ws, {"type": "error", "message": str(e)})
        return

    # 先告知自己 player_id 和房间码
    await send_to_player(ws, {
        "type": "room_created",
        "room_code": room.room_code,
        "player_id": player_id,
    })
    await broadcast_room_update(room)


async def handle_leave_room(player_id: str):
    room = room_manager.leave_room(player_id)
    if room is not None:
        await broadcast_room_update(room)


async def handle_player_ready(player_id: str):
    room = room_manager.get_player_room(player_id)
    if room is None:
        return

    info = room.players.get(player_id)
    if info is None:
        return

    # 切换准备状态（房主不需要准备，忽略）
    if player_id != room.host_id:
        info.is_ready = not info.is_ready
        await broadcast_room_update(room)


async def handle_start_game(player_id: str, ws: WebSocket):
    try:
        room = room_manager.start_game(player_id)
    except ValueError as e:
        await send_to_player(ws, {"type": "error", "message": str(e)})
        return

    # 向每位玩家单独发送各自私有视角的 game_start
    game_state = room.game_state
    for pid, info in room.players.items():
        state_view = game_state.get_state_for_player(pid)
        await send_to_player(info.ws, {
            "type": "game_start",
            "player_id": pid,
            "game_state": state_view,
        })


# ─── 主连接处理 ───────────────────────────────────────────────────────

async def handle_connection(player_id: str, ws: WebSocket):
    """处理单个 WebSocket 连接的生命周期"""
    try:
        while True:
            raw = await ws.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await send_to_player(ws, {"type": "error", "message": "消息格式错误，须为 JSON"})
                continue

            msg_type = data.get("type", "")

            if msg_type == "create_room":
                await handle_create_room(player_id, data, ws)
            elif msg_type == "join_room":
                await handle_join_room(player_id, data, ws)
            elif msg_type == "leave_room":
                await handle_leave_room(player_id)
            elif msg_type == "player_ready":
                await handle_player_ready(player_id)
            elif msg_type == "start_game":
                await handle_start_game(player_id, ws)
            else:
                await send_to_player(ws, {"type": "error", "message": f"未知消息类型：{msg_type}"})

    except WebSocketDisconnect:
        logger.info(f"玩家 {player_id} 断线，清理房间")
        await handle_leave_room(player_id)
