"""WebSocket message routing and game flow."""

import asyncio
import json
import logging
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect

from .game.ai import choose_draw_action, choose_play_action
from .game.state import GameState
from .room_manager import Room, room_manager

logger = logging.getLogger(__name__)

BOT_ACTION_DELAY_SECONDS = 0.35


async def send_to_player(ws: Optional[WebSocket], message: dict):
    if ws is None:
        return
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
    for pid, info in room.players.items():
        if info.is_bot and info.ws is None:
            continue
        state = room.game_state.get_state_for_player(pid)
        await send_to_player(info.ws, {"type": "game_state", "state": state})


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

    hand_size = len(gs._hands[player_id])
    playable = set(actions.get("can_play_to_market", []))
    blocked = [i for i in range(hand_size) if i not in playable]
    return {
        "type": "your_turn",
        "phase": "play",
        "blocked_play_to_market": blocked,
    }


async def handle_game_end(room: Room):
    gs = room.game_state
    scores = gs._scores
    revealed_hands = {pid: list(gs._hands[pid]) for pid in gs._player_ids}
    player_names = {pid: info.name for pid, info in room.players.items()}
    pre_coins = {pid: gs._coins[pid] for pid in gs._player_ids}
    areas = {pid: dict(gs._areas[pid]) for pid in gs._player_ids}

    await broadcast_to_room(room, {
        "type": "game_end",
        "scores": scores["final_coins"],
        "pre_coins": pre_coins,
        "company_details": scores["company_details"],
        "winner": scores["winner"],
        "winner_name": scores["winner_name"],
        "revealed_hands": revealed_hands,
        "areas": areas,
        "player_names": player_names,
        "room_code": room.room_code,
    })


async def _prompt_current_player(room: Room):
    gs = room.game_state
    if gs is None:
        return
    if gs.phase == "ended":
        await handle_game_end(room)
        return

    current_player_id = gs.current_player_id
    current_player = room.players[current_player_id]
    if current_player.is_bot:
        await _schedule_bot_turn(room)
        return

    await send_to_player(current_player.ws, _build_your_turn(gs, current_player_id))


async def _after_play(room: Room):
    await broadcast_game_state(room)
    await _prompt_current_player(room)


def _clear_bot_task(room: Room):
    room.bot_task = None
    room.bot_task_player_id = None
    room.bot_task_phase = None


async def _execute_bot_turn(room: Room, player_id: str, phase: str):
    try:
        await asyncio.sleep(BOT_ACTION_DELAY_SECONDS)

        gs = room.game_state
        if gs is None or gs.phase != "playing":
            return
        if gs.current_player_id != player_id or gs.turn_phase != phase:
            return

        if phase == "draw":
            action = choose_draw_action(gs, player_id)
            if action["action"] == "draw_card":
                gs.draw_card(player_id)
            else:
                gs.pick_market(player_id, action["card_index"])
            await broadcast_game_state(room)
            await _prompt_current_player(room)
            return

        action = choose_play_action(gs, player_id)
        if action["action"] == "play_to_market":
            gs.play_to_market(player_id, action["hand_index"])
        else:
            gs.play_to_area(player_id, action["hand_index"])
        await _after_play(room)
    except Exception:
        logger.exception("bot turn failed", extra={"room_code": room.room_code, "player_id": player_id})
        gs = room.game_state
        if gs and gs.phase == "playing" and gs.current_player_id == player_id:
            try:
                if gs.turn_phase == "draw":
                    fallback = gs.get_playable_actions(player_id)
                    pickable = fallback.get("can_pick_market", [])
                    if pickable:
                        gs.pick_market(player_id, pickable[0])
                    else:
                        gs.draw_card(player_id)
                    await broadcast_game_state(room)
                    await _prompt_current_player(room)
                else:
                    gs.play_to_area(player_id, 0)
                    await _after_play(room)
            except Exception:
                logger.exception("bot fallback failed", extra={"room_code": room.room_code, "player_id": player_id})
    finally:
        _clear_bot_task(room)
        gs = room.game_state
        if gs and gs.phase == "playing" and room.players[gs.current_player_id].is_bot:
            await _schedule_bot_turn(room)


async def _schedule_bot_turn(room: Room):
    gs = room.game_state
    if gs is None or gs.phase != "playing":
        return

    current_player_id = gs.current_player_id
    current_player = room.players[current_player_id]
    if not current_player.is_bot:
        return

    if room.bot_task and not room.bot_task.done():
        if room.bot_task_player_id == current_player_id and room.bot_task_phase == gs.turn_phase:
            return
        return

    room.bot_task_player_id = current_player_id
    room.bot_task_phase = gs.turn_phase
    room.bot_task = asyncio.create_task(
        _execute_bot_turn(room, current_player_id, gs.turn_phase)
    )


async def handle_create_room(player_id: str, data: dict, ws: WebSocket):
    player_name = data.get("player_name", "").strip()
    if not player_name:
        await send_to_player(ws, {"type": "error", "message": "昵称不能为空"})
        return

    remove_count = int(data.get("remove_count", 5))
    remove_count = max(0, min(remove_count, 40))
    room = room_manager.create_room(player_id, player_name, ws, remove_count=remove_count)
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
        return None

    try:
        room = room_manager.join_room(room_code, player_id, player_name, ws)
        await send_to_player(ws, {
            "type": "room_created",
            "room_code": room.room_code,
            "player_id": player_id,
        })
        await broadcast_room_update(room)
        return None
    except ValueError as join_err:
        original_err = join_err

    try:
        old_pid = room_manager.rejoin_room(room_code, player_name, ws)
        room = room_manager.get_room(room_code)
        gs = room.game_state
        await send_to_player(ws, {
            "type": "game_start",
            "player_id": old_pid,
            "room_code": room_code,
        })
        await send_to_player(ws, {
            "type": "game_state",
            "state": gs.get_state_for_player(old_pid),
        })
        if gs.current_player_id == old_pid:
            await send_to_player(ws, _build_your_turn(gs, old_pid))
        return old_pid
    except ValueError:
        pass

    try:
        old_pid = room_manager.rejoin_lobby(room_code, player_name, ws)
        room = room_manager.get_room(room_code)
        await send_to_player(ws, {
            "type": "room_created",
            "room_code": room_code,
            "player_id": old_pid,
        })
        await broadcast_room_update(room)
        return old_pid
    except ValueError:
        pass

    await send_to_player(ws, {"type": "error", "message": str(original_err)})
    return None


async def handle_player_ready(player_id: str):
    room = room_manager.get_player_room(player_id)
    if room is None:
        return

    info = room.players.get(player_id)
    if info and player_id != room.host_id and not info.is_bot:
        info.is_ready = not info.is_ready
        await broadcast_room_update(room)


async def handle_add_bot(player_id: str, ws: WebSocket):
    try:
        room = room_manager.add_bot(player_id)
    except ValueError as exc:
        await send_to_player(ws, {"type": "error", "message": str(exc)})
        return

    await broadcast_room_update(room)


async def handle_remove_bot(player_id: str, ws: WebSocket):
    try:
        room = room_manager.remove_bot(player_id)
    except ValueError as exc:
        await send_to_player(ws, {"type": "error", "message": str(exc)})
        return

    await broadcast_room_update(room)


async def handle_start_game(player_id: str, ws: WebSocket):
    try:
        room = room_manager.start_game(player_id)
    except ValueError as exc:
        await send_to_player(ws, {"type": "error", "message": str(exc)})
        return

    gs = room.game_state
    for pid, info in room.players.items():
        await send_to_player(info.ws, {
            "type": "game_start",
            "player_id": pid,
            "game_state": gs.get_state_for_player(pid),
        })

    await _prompt_current_player(room)


async def handle_draw_card(player_id: str, ws: WebSocket):
    room = room_manager.get_player_room(player_id)
    if not room or not room.game_state:
        await send_to_player(ws, {"type": "error", "message": "当前不在游戏中"})
        return

    gs = room.game_state
    try:
        card = gs.draw_card(player_id)
    except ValueError as exc:
        await send_to_player(ws, {"type": "error", "message": str(exc)})
        return

    await send_to_player(ws, {
        "type": "action_result",
        "action": "draw_card",
        "success": True,
        "message": f"摸到 {card}",
    })
    await broadcast_game_state(room)
    await _prompt_current_player(room)


async def handle_pick_market(player_id: str, data: dict, ws: WebSocket):
    room = room_manager.get_player_room(player_id)
    if not room or not room.game_state:
        await send_to_player(ws, {"type": "error", "message": "当前不在游戏中"})
        return

    gs = room.game_state
    try:
        card_index = int(data["card_index"])
        result = gs.pick_market(player_id, card_index)
    except (KeyError, ValueError, TypeError) as exc:
        await send_to_player(ws, {"type": "error", "message": str(exc)})
        return

    await send_to_player(ws, {
        "type": "action_result",
        "action": "pick_market",
        "success": True,
        "message": f"取得 {result['card']}，获得 {result['coins_gained']} 资金",
    })
    await broadcast_game_state(room)
    await _prompt_current_player(room)


async def handle_play_to_market(player_id: str, data: dict, ws: WebSocket):
    room = room_manager.get_player_room(player_id)
    if not room or not room.game_state:
        await send_to_player(ws, {"type": "error", "message": "当前不在游戏中"})
        return

    gs = room.game_state
    try:
        hand_index = int(data["hand_index"])
        gs.play_to_market(player_id, hand_index)
    except (KeyError, ValueError, TypeError) as exc:
        await send_to_player(ws, {"type": "error", "message": str(exc)})
        return

    await _after_play(room)


async def handle_play_to_area(player_id: str, data: dict, ws: WebSocket):
    room = room_manager.get_player_room(player_id)
    if not room or not room.game_state:
        await send_to_player(ws, {"type": "error", "message": "当前不在游戏中"})
        return

    gs = room.game_state
    try:
        hand_index = int(data["hand_index"])
        gs.play_to_area(player_id, hand_index)
    except (KeyError, ValueError, TypeError) as exc:
        await send_to_player(ws, {"type": "error", "message": str(exc)})
        return

    await _after_play(room)


async def handle_disconnect(player_id: str):
    room = room_manager.get_player_room(player_id)
    if room is None:
        return

    if room.game_state is not None:
        room_manager.mark_player_disconnected(player_id)
    else:
        remaining_room = room_manager.leave_room(player_id)
        if remaining_room is not None:
            await broadcast_room_update(remaining_room)


async def handle_connection(player_id: str, ws: WebSocket):
    effective_id = player_id
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
                await handle_create_room(effective_id, data, ws)
            elif msg_type == "join_room":
                new_id = await handle_join_room(effective_id, data, ws)
                if new_id:
                    effective_id = new_id
            elif msg_type == "leave_room":
                await handle_disconnect(effective_id)
            elif msg_type == "player_ready":
                await handle_player_ready(effective_id)
            elif msg_type == "add_bot":
                await handle_add_bot(effective_id, ws)
            elif msg_type == "remove_bot":
                await handle_remove_bot(effective_id, ws)
            elif msg_type == "start_game":
                await handle_start_game(effective_id, ws)
            elif msg_type == "draw_card":
                await handle_draw_card(effective_id, ws)
            elif msg_type == "pick_market":
                await handle_pick_market(effective_id, data, ws)
            elif msg_type == "play_to_market":
                await handle_play_to_market(effective_id, data, ws)
            elif msg_type == "play_to_area":
                await handle_play_to_area(effective_id, data, ws)
            else:
                await send_to_player(ws, {"type": "error", "message": f"未知消息类型：{msg_type}"})

    except WebSocketDisconnect:
        logger.info("player disconnected: %s", effective_id)
        await handle_disconnect(effective_id)
