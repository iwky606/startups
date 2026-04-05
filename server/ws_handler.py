"""WebSocket 消息路由与处理"""

import json
import logging
from fastapi import WebSocket, WebSocketDisconnect

from .room_manager import room_manager, Room
from .game.state import GameState

logger = logging.getLogger(__name__)


# ─── 发送辅助 ────────────────────────────────────────────────────────

async def send_to_player(ws: WebSocket, message: dict):
    try:
        await ws.send_text(json.dumps(message, ensure_ascii=False))
    except Exception:
        pass


async def broadcast_to_room(room: Room, message: dict):
    for info in list(room.players.values()):
        await send_to_player(info.ws, message)


async def broadcast_room_update(room: Room):
    await broadcast_to_room(room, {
        "type": "room_update",
        "room_code": room.room_code,
        "players": room.player_list(),
    })


async def broadcast_game_state(room: Room):
    """向每位玩家发送各自私有视角的游戏状态（信息隐藏核心）"""
    for pid, info in room.players.items():
        state = room.game_state.get_state_for_player(pid)
        await send_to_player(info.ws, {"type": "game_state", "state": state})


# ─── your_turn 构造 ───────────────────────────────────────────────────

def _build_your_turn(gs: GameState, player_id: str) -> dict:
    phase = gs.turn_phase
    actions = gs.get_playable_actions(player_id)

    if phase == "draw":
        market_size = len(gs._market)
        pickable = set(actions.get("can_pick_market", []))
        blocked = [i for i in range(market_size) if i not in pickable]
        return {
            "type": "your_turn",
            "phase": "draw",
            "draw_cost": gs.get_draw_cost(player_id),
            "can_draw": gs.can_draw(player_id),
            "blocked_market": blocked,
        }
    else:
        hand_size = len(gs._hands[player_id])
        playable = set(actions.get("can_play_to_market", []))
        blocked = [i for i in range(hand_size) if i not in playable]
        return {
            "type": "your_turn",
            "phase": "play",
            "blocked_play_to_market": blocked,
        }


# ─── 游戏结束处理 ──────────────────────────────────────────────────────

async def handle_game_end(room: Room):
    gs = room.game_state
    scores = gs._scores  # 已在 _end_turn 中计算完毕

    # 手牌全公开
    revealed_hands = {pid: list(gs._hands[pid]) for pid in gs._player_ids}
    player_names = {pid: info.name for pid, info in room.players.items()}

    await broadcast_to_room(room, {
        "type": "game_end",
        "scores": scores["final_coins"],
        "company_details": scores["company_details"],
        "winner": scores["winner"],
        "winner_name": scores["winner_name"],
        "revealed_hands": revealed_hands,
        "player_names": player_names,
    })


# ─── 打出阶段共用逻辑 ─────────────────────────────────────────────────

async def _after_play(player_id: str, room: Room):
    """play_to_market / play_to_area 后的共用后处理"""
    gs = room.game_state
    await broadcast_game_state(room)

    if gs.phase == "ended":
        await handle_game_end(room)
    else:
        next_pid = gs.current_player_id
        next_ws = room.players[next_pid].ws
        await send_to_player(next_ws, _build_your_turn(gs, next_pid))


# ─── 房间阶段消息处理 ─────────────────────────────────────────────────

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

    await send_to_player(ws, {
        "type": "room_created",
        "room_code": room.room_code,
        "player_id": player_id,
    })
    await broadcast_room_update(room)


async def handle_player_ready(player_id: str):
    room = room_manager.get_player_room(player_id)
    if room is None:
        return
    info = room.players.get(player_id)
    if info and player_id != room.host_id:
        info.is_ready = not info.is_ready
        await broadcast_room_update(room)


async def handle_start_game(player_id: str, ws: WebSocket):
    try:
        room = room_manager.start_game(player_id)
    except ValueError as e:
        await send_to_player(ws, {"type": "error", "message": str(e)})
        return

    gs = room.game_state
    for pid, info in room.players.items():
        await send_to_player(info.ws, {
            "type": "game_start",
            "player_id": pid,
            "game_state": gs.get_state_for_player(pid),
        })

    # 通知第一个行动的玩家
    first_pid = gs.current_player_id
    first_ws = room.players[first_pid].ws
    await send_to_player(first_ws, _build_your_turn(gs, first_pid))


# ─── 游戏内消息处理 ───────────────────────────────────────────────────

async def handle_draw_card(player_id: str, ws: WebSocket):
    room = room_manager.get_player_room(player_id)
    if not room or not room.game_state:
        await send_to_player(ws, {"type": "error", "message": "当前不在游戏中"})
        return

    gs = room.game_state
    try:
        card = gs.draw_card(player_id)
    except ValueError as e:
        await send_to_player(ws, {"type": "error", "message": str(e)})
        return

    await send_to_player(ws, {
        "type": "action_result",
        "action": "draw_card",
        "success": True,
        "message": f"摸到了 {card}",
    })
    await broadcast_game_state(room)
    await send_to_player(ws, _build_your_turn(gs, player_id))


async def handle_pick_market(player_id: str, data: dict, ws: WebSocket):
    room = room_manager.get_player_room(player_id)
    if not room or not room.game_state:
        await send_to_player(ws, {"type": "error", "message": "当前不在游戏中"})
        return

    gs = room.game_state
    try:
        card_index = int(data["card_index"])
        result = gs.pick_market(player_id, card_index)
    except (KeyError, ValueError, TypeError) as e:
        await send_to_player(ws, {"type": "error", "message": str(e)})
        return

    await send_to_player(ws, {
        "type": "action_result",
        "action": "pick_market",
        "success": True,
        "message": f"取得 {result['card']}，获得 {result['coins_gained']} 资金",
    })
    await broadcast_game_state(room)
    await send_to_player(ws, _build_your_turn(gs, player_id))


async def handle_play_to_market(player_id: str, data: dict, ws: WebSocket):
    room = room_manager.get_player_room(player_id)
    if not room or not room.game_state:
        await send_to_player(ws, {"type": "error", "message": "当前不在游戏中"})
        return

    gs = room.game_state
    try:
        hand_index = int(data["hand_index"])
        gs.play_to_market(player_id, hand_index)
    except (KeyError, ValueError, TypeError) as e:
        await send_to_player(ws, {"type": "error", "message": str(e)})
        return

    await _after_play(player_id, room)


async def handle_play_to_area(player_id: str, data: dict, ws: WebSocket):
    room = room_manager.get_player_room(player_id)
    if not room or not room.game_state:
        await send_to_player(ws, {"type": "error", "message": "当前不在游戏中"})
        return

    gs = room.game_state
    try:
        hand_index = int(data["hand_index"])
        gs.play_to_area(player_id, hand_index)
    except (KeyError, ValueError, TypeError) as e:
        await send_to_player(ws, {"type": "error", "message": str(e)})
        return

    await _after_play(player_id, room)


# ─── 断线处理 ─────────────────────────────────────────────────────────

async def handle_disconnect(player_id: str):
    room = room_manager.get_player_room(player_id)
    if room is None:
        return

    gs = room.game_state
    if gs is not None and gs.phase not in ("ended",):
        # 游戏进行中断线：通知其余玩家，终止游戏
        player_name = room.players.get(player_id, None)
        name = player_name.name if player_name else "未知玩家"
        remaining = [(pid, info) for pid, info in room.players.items() if pid != player_id]

        room_manager.abort_room(room.room_code)

        for pid, info in remaining:
            await send_to_player(info.ws, {
                "type": "player_disconnected",
                "player_id": player_id,
                "player_name": name,
            })
            await send_to_player(info.ws, {
                "type": "game_aborted",
                "reason": f"玩家「{name}」断线，游戏终止",
            })
    else:
        # 等待阶段或游戏已结束：正常移除
        remaining_room = room_manager.leave_room(player_id)
        if remaining_room is not None:
            await broadcast_room_update(remaining_room)


# ─── 主连接处理 ───────────────────────────────────────────────────────

async def handle_connection(player_id: str, ws: WebSocket):
    try:
        while True:
            raw = await ws.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await send_to_player(ws, {"type": "error", "message": "消息须为合法 JSON"})
                continue

            msg_type = data.get("type", "")

            if msg_type == "create_room":
                await handle_create_room(player_id, data, ws)
            elif msg_type == "join_room":
                await handle_join_room(player_id, data, ws)
            elif msg_type == "leave_room":
                await handle_disconnect(player_id)
            elif msg_type == "player_ready":
                await handle_player_ready(player_id)
            elif msg_type == "start_game":
                await handle_start_game(player_id, ws)
            elif msg_type == "draw_card":
                await handle_draw_card(player_id, ws)
            elif msg_type == "pick_market":
                await handle_pick_market(player_id, data, ws)
            elif msg_type == "play_to_market":
                await handle_play_to_market(player_id, data, ws)
            elif msg_type == "play_to_area":
                await handle_play_to_area(player_id, data, ws)
            else:
                await send_to_player(ws, {"type": "error", "message": f"未知消息类型：{msg_type}"})

    except WebSocketDisconnect:
        logger.info(f"玩家 {player_id} 断线")
        await handle_disconnect(player_id)
