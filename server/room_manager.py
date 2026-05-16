"""Room management."""

import asyncio
import random
import uuid
from dataclasses import dataclass, field
from typing import Optional

from fastapi import WebSocket

from .game.deck import TOTAL_CARDS
from .game.state import GameState


_CODE_CHARS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def _generate_room_code() -> str:
    return "".join(random.choices(_CODE_CHARS, k=6))


@dataclass
class PlayerInfo:
    name: str
    ws: Optional[WebSocket]
    is_ready: bool = False
    is_bot: bool = False


@dataclass
class Room:
    room_code: str
    host_id: str
    players: dict[str, PlayerInfo] = field(default_factory=dict)
    seats: list[Optional[str]] = field(default_factory=lambda: [None] * 7)
    game_state: Optional[GameState] = None
    max_players: int = 7
    min_players: int = 3
    remove_count: int = 5
    bot_task: Optional[asyncio.Task] = field(default=None, repr=False, compare=False)
    bot_task_player_id: Optional[str] = None
    bot_task_phase: Optional[str] = None
    is_post_game_lobby: bool = False
    pending_seat_swaps: dict[str, tuple[str, int]] = field(default_factory=dict)

    @property
    def is_started(self) -> bool:
        return self.game_state is not None

    def seated_player_ids(self) -> list[str]:
        seated = [pid for pid in self.seats if pid is not None and pid in self.players]
        extras = [pid for pid in self.players if pid not in seated]
        return seated + extras

    def first_empty_seat(self) -> Optional[int]:
        for index, pid in enumerate(self.seats):
            if pid is None:
                return index
        return None

    def seat_index(self, player_id: str) -> Optional[int]:
        try:
            return self.seats.index(player_id)
        except ValueError:
            return None

    def player_payload(self, player_id: str) -> dict:
        info = self.players[player_id]
        return {
            "id": player_id,
            "name": info.name,
            "is_host": player_id == self.host_id,
            "is_ready": info.is_ready,
            "is_bot": info.is_bot,
            "seat_index": self.seat_index(player_id),
        }

    def player_list(self) -> list[dict]:
        return [self.player_payload(pid) for pid in self.seated_player_ids()]

    def seat_list(self) -> list[Optional[dict]]:
        seats: list[Optional[dict]] = []
        for pid in self.seats:
            seats.append(self.player_payload(pid) if pid in self.players else None)
        return seats

    def required_start_cards(self) -> int:
        return len(self.players) * 4

    def available_start_cards(self) -> int:
        return TOTAL_CARDS - self.remove_count

    def has_enough_start_cards(self) -> bool:
        return self.required_start_cards() <= self.available_start_cards()


class RoomManager:
    """Singleton-style room manager."""

    def __init__(self):
        self.rooms: dict[str, Room] = {}
        self.player_room_map: dict[str, str] = {}

    def _unique_code(self) -> str:
        code = _generate_room_code()
        while code in self.rooms:
            code = _generate_room_code()
        return code

    def _next_bot_name(self, room: Room) -> str:
        taken = {info.name for info in room.players.values()}
        index = 1
        while True:
            name = f"人机{index}"
            if name not in taken:
                return name
            index += 1

    def _add_bot_players(self, room: Room, target_count: int):
        while len(room.players) < min(target_count, room.max_players):
            seat_index = room.first_empty_seat()
            if seat_index is None:
                return
            bot_id = f"bot-{uuid.uuid4().hex[:8]}"
            while bot_id in room.players:
                bot_id = f"bot-{uuid.uuid4().hex[:8]}"

            room.players[bot_id] = PlayerInfo(
                name=self._next_bot_name(room),
                ws=None,
                is_ready=True,
                is_bot=True,
            )
            room.seats[seat_index] = bot_id
            self.player_room_map[bot_id] = room.room_code

    def create_room(self, player_id: str, player_name: str, ws: WebSocket, remove_count: int = 5) -> Room:
        code = self._unique_code()
        room = Room(room_code=code, host_id=player_id, remove_count=remove_count)
        room.players[player_id] = PlayerInfo(name=player_name, ws=ws)
        room.seats[0] = player_id
        self.rooms[code] = room
        self.player_room_map[player_id] = code
        return room

    def add_bot(self, player_id: str) -> Room:
        room = self.get_player_room(player_id)
        if room is None:
            raise ValueError("你不在任何房间中")
        if room.host_id != player_id:
            raise ValueError("只有房主可以添加人机")
        if room.is_started:
            raise ValueError("游戏已经开始，无法添加人机")
        if len(room.players) >= room.max_players:
            raise ValueError("房间已满，无法继续添加人机")

        self._add_bot_players(room, len(room.players) + 1)
        return room

    def remove_bot(self, player_id: str) -> Room:
        room = self.get_player_room(player_id)
        if room is None:
            raise ValueError("你不在任何房间中")
        if room.host_id != player_id:
            raise ValueError("只有房主可以删除人机")
        if room.is_started:
            raise ValueError("游戏已经开始，无法删除人机")

        bot_ids = [pid for pid in room.seated_player_ids() if room.players[pid].is_bot]
        if not bot_ids:
            raise ValueError("当前房间没有可删除的人机")

        bot_id = bot_ids[-1]
        room.players.pop(bot_id, None)
        seat_index = room.seat_index(bot_id)
        if seat_index is not None:
            room.seats[seat_index] = None
        self.player_room_map.pop(bot_id, None)
        return room

    def update_remove_count(self, player_id: str, remove_count: int) -> Room:
        room = self.get_player_room(player_id)
        if room is None:
            raise ValueError("你不在任何房间中")
        if room.host_id != player_id:
            raise ValueError("只有房主可以调整扣减牌数")
        if room.is_started:
            raise ValueError("游戏已经开始，无法调整扣减牌数")

        room.remove_count = max(0, min(TOTAL_CARDS, remove_count))
        return room

    def join_room(
        self,
        room_code: str,
        player_id: str,
        player_name: str,
        ws: WebSocket,
    ) -> Room:
        room = self.rooms.get(room_code)
        if room is None:
            raise ValueError(f"房间 {room_code} 不存在")
        if room.is_started:
            raise ValueError("游戏已经开始，无法加入")
        if len(room.players) >= room.max_players:
            raise ValueError("房间已满")
        if any(p.name == player_name for p in room.players.values()):
            raise ValueError(f"昵称“{player_name}”已被使用，请换一个")

        seat_index = room.first_empty_seat()
        if seat_index is None:
            raise ValueError("房间已满")

        room.players[player_id] = PlayerInfo(name=player_name, ws=ws)
        room.seats[seat_index] = player_id
        self.player_room_map[player_id] = room_code
        return room

    def leave_room(self, player_id: str) -> Optional[Room]:
        room_code = self.player_room_map.pop(player_id, None)
        if room_code is None:
            return None

        room = self.rooms.get(room_code)
        if room is None:
            return None

        room.players.pop(player_id, None)
        seat_index = room.seat_index(player_id)
        if seat_index is not None:
            room.seats[seat_index] = None
        for target_id, (requester_id, _) in list(room.pending_seat_swaps.items()):
            if player_id in (target_id, requester_id):
                room.pending_seat_swaps.pop(target_id, None)

        if not any(not info.is_bot for info in room.players.values()):
            for pid in list(room.players.keys()):
                self.player_room_map.pop(pid, None)
            del self.rooms[room_code]
            return None

        if not room.players:
            del self.rooms[room_code]
            return None

        if room.host_id == player_id:
            room.host_id = next(
                pid for pid in room.seated_player_ids()
                if not room.players[pid].is_bot
            )

        return room

    def get_room(self, room_code: str) -> Optional[Room]:
        return self.rooms.get(room_code)

    def get_player_room(self, player_id: str) -> Optional[Room]:
        code = self.player_room_map.get(player_id)
        if code is None:
            return None
        return self.rooms.get(code)

    def start_game(self, player_id: str) -> Room:
        room = self.get_player_room(player_id)
        if room is None:
            raise ValueError("你不在任何房间中")
        if room.host_id != player_id:
            raise ValueError("只有房主可以开始游戏")
        if len(room.players) < room.min_players:
            raise ValueError(f"至少需要 {room.min_players} 人才能开始")

        if not room.has_enough_start_cards():
            raise ValueError(
                f"牌数不足：当前 {len(room.players)} 人至少需要 {room.required_start_cards()} 张，"
                f"扣减后只剩 {room.available_start_cards()} 张"
            )

        player_ids = room.seated_player_ids()
        not_ready = [
            room.players[pid].name
            for pid in player_ids
            if pid != room.host_id
            and not room.players[pid].is_bot
            and not room.players[pid].is_ready
        ]
        if not_ready:
            raise ValueError(f"以下玩家尚未准备：{'、'.join(not_ready)}")

        player_names = {pid: room.players[pid].name for pid in player_ids}
        player_meta = {
            pid: {"is_bot": room.players[pid].is_bot}
            for pid in player_ids
        }
        room.game_state = GameState(
            player_ids,
            player_names,
            remove_count=room.remove_count,
            player_meta=player_meta,
        )
        room.is_post_game_lobby = False
        room.pending_seat_swaps.clear()
        return room

    def rejoin_room(
        self,
        room_code: str,
        player_name: str,
        new_ws: WebSocket,
    ) -> str:
        room = self.rooms.get(room_code)
        if room is None:
            raise ValueError(f"房间 {room_code} 不存在")
        if not room.is_started:
            raise ValueError("游戏尚未开始")
        if room.game_state.phase == "ended":
            raise ValueError("游戏已结束，请回到大厅")

        for pid, info in room.players.items():
            if not info.is_bot and info.name == player_name:
                info.ws = new_ws
                self.player_room_map[pid] = room_code
                return pid

        raise ValueError(f"玩家“{player_name}”不在此游戏中")

    def mark_player_disconnected(self, player_id: str):
        code = self.player_room_map.pop(player_id, None)
        if code is None:
            return

        room = self.rooms.get(code)
        if room is None:
            return

        info = room.players.get(player_id)
        if info:
            info.ws = None

    def reset_room(self, room_code: str):
        room = self.rooms.get(room_code)
        if room is None:
            return

        room.game_state = None
        room.is_post_game_lobby = False
        room.pending_seat_swaps.clear()
        for pid, info in room.players.items():
            info.is_ready = False
            info.ws = None
            self.player_room_map.pop(pid, None)

    def rejoin_lobby(
        self,
        room_code: str,
        player_name: str,
        new_ws: WebSocket,
    ) -> str:
        room = self.rooms.get(room_code)
        if room is None:
            raise ValueError(f"房间 {room_code} 不存在")

        if room.game_state is not None and room.game_state.phase != "ended":
            raise ValueError("游戏仍在进行中")

        is_ended_game = room.game_state is not None and room.game_state.phase == "ended"
        for pid, info in room.players.items():
            if (
                not info.is_bot
                and info.name == player_name
                and (is_ended_game or room.is_post_game_lobby or info.ws is None)
            ):
                if room.game_state is not None:
                    room.game_state = None
                    room.is_post_game_lobby = True
                    room.pending_seat_swaps.clear()
                    for player in room.players.values():
                        if not player.is_bot:
                            player.is_ready = False
                info.ws = new_ws
                self.player_room_map[pid] = room_code
                return pid

        raise ValueError(f"玩家“{player_name}”不在此房间中")

    def request_seat_move(self, player_id: str, seat_index: int) -> tuple[Room, Optional[str]]:
        room = self.get_player_room(player_id)
        if room is None:
            raise ValueError("你不在任何房间中")
        if room.is_started:
            raise ValueError("游戏已经开始，无法调整座位")
        if player_id not in room.players:
            raise ValueError("你不在此房间中")
        if seat_index < 0 or seat_index >= room.max_players:
            raise ValueError("座位不存在")

        current_index = room.seat_index(player_id)
        if current_index is None:
            raise ValueError("你当前没有座位")
        if current_index == seat_index:
            return room, None

        target_id = room.seats[seat_index]
        if target_id is None:
            room.seats[current_index] = None
            room.seats[seat_index] = player_id
            self._clear_pending_for_players(room, player_id)
            return room, None

        target = room.players.get(target_id)
        if target is None:
            room.seats[seat_index] = player_id
            room.seats[current_index] = None
            self._clear_pending_for_players(room, player_id)
            return room, None

        if target.is_bot:
            room.seats[current_index], room.seats[seat_index] = room.seats[seat_index], room.seats[current_index]
            self._clear_pending_for_players(room, player_id, target_id)
            return room, None

        room.pending_seat_swaps[target_id] = (player_id, seat_index)
        return room, target_id

    def respond_seat_swap(self, player_id: str, accept: bool) -> tuple[Room, Optional[str]]:
        room = self.get_player_room(player_id)
        if room is None:
            raise ValueError("你不在任何房间中")

        request = room.pending_seat_swaps.pop(player_id, None)
        if request is None:
            raise ValueError("当前没有待确认的换座请求")

        requester_id, target_seat = request
        if not accept:
            return room, requester_id
        if room.is_started:
            raise ValueError("游戏已经开始，无法调整座位")
        if requester_id not in room.players or player_id not in room.players:
            raise ValueError("玩家已不在房间中")
        if room.seats[target_seat] != player_id:
            raise ValueError("座位已发生变化")

        requester_seat = room.seat_index(requester_id)
        if requester_seat is None:
            raise ValueError("申请人已不在座位中")

        room.seats[requester_seat], room.seats[target_seat] = room.seats[target_seat], room.seats[requester_seat]
        self._clear_pending_for_players(room, player_id, requester_id)
        return room, requester_id

    def _clear_pending_for_players(self, room: Room, *player_ids: str):
        players = set(player_ids)
        for target_id, (requester_id, _) in list(room.pending_seat_swaps.items()):
            if target_id in players or requester_id in players:
                room.pending_seat_swaps.pop(target_id, None)

    def owns_connection(self, player_id: str, ws: WebSocket) -> bool:
        room = self.get_player_room(player_id)
        if room is None:
            return False

        info = room.players.get(player_id)
        return info is not None and info.ws is ws

    def abort_room(self, room_code: str):
        room = self.rooms.pop(room_code, None)
        if room:
            for pid in list(room.players.keys()):
                self.player_room_map.pop(pid, None)


room_manager = RoomManager()
