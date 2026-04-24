"""Room management."""

import asyncio
import random
import uuid
from dataclasses import dataclass, field
from typing import Optional

from fastapi import WebSocket

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
    game_state: Optional[GameState] = None
    max_players: int = 7
    min_players: int = 3
    remove_count: int = 5
    bot_task: Optional[asyncio.Task] = field(default=None, repr=False, compare=False)
    bot_task_player_id: Optional[str] = None
    bot_task_phase: Optional[str] = None

    @property
    def is_started(self) -> bool:
        return self.game_state is not None

    def player_list(self) -> list[dict]:
        return [
            {
                "id": pid,
                "name": info.name,
                "is_host": pid == self.host_id,
                "is_ready": info.is_ready,
                "is_bot": info.is_bot,
            }
            for pid, info in self.players.items()
        ]


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
            bot_id = f"bot-{uuid.uuid4().hex[:8]}"
            while bot_id in room.players:
                bot_id = f"bot-{uuid.uuid4().hex[:8]}"

            room.players[bot_id] = PlayerInfo(
                name=self._next_bot_name(room),
                ws=None,
                is_ready=True,
                is_bot=True,
            )
            self.player_room_map[bot_id] = room.room_code

    def create_room(self, player_id: str, player_name: str, ws: WebSocket, remove_count: int = 5) -> Room:
        code = self._unique_code()
        room = Room(room_code=code, host_id=player_id, remove_count=remove_count)
        room.players[player_id] = PlayerInfo(name=player_name, ws=ws)
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

        bot_ids = [pid for pid, info in room.players.items() if info.is_bot]
        if not bot_ids:
            raise ValueError("当前房间没有可删除的人机")

        bot_id = bot_ids[-1]
        room.players.pop(bot_id, None)
        self.player_room_map.pop(bot_id, None)
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

        room.players[player_id] = PlayerInfo(name=player_name, ws=ws)
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

        if not room.players:
            del self.rooms[room_code]
            return None

        if room.host_id == player_id:
            room.host_id = next(iter(room.players))

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

        not_ready = [
            info.name
            for pid, info in room.players.items()
            if pid != room.host_id and not info.is_bot and not info.is_ready
        ]
        if not_ready:
            raise ValueError(f"以下玩家尚未准备：{'、'.join(not_ready)}")

        player_ids = list(room.players.keys())
        player_names = {pid: info.name for pid, info in room.players.items()}
        player_meta = {
            pid: {"is_bot": info.is_bot}
            for pid, info in room.players.items()
        }
        room.game_state = GameState(
            player_ids,
            player_names,
            remove_count=room.remove_count,
            player_meta=player_meta,
        )
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

        for pid, info in room.players.items():
            if not info.is_bot and info.name == player_name and info.ws is None:
                if room.game_state is not None:
                    room.game_state = None
                    for player in room.players.values():
                        if not player.is_bot:
                            player.is_ready = False
                info.ws = new_ws
                self.player_room_map[pid] = room_code
                return pid

        raise ValueError(f"玩家“{player_name}”不在此房间中")

    def abort_room(self, room_code: str):
        room = self.rooms.pop(room_code, None)
        if room:
            for pid in list(room.players.keys()):
                self.player_room_map.pop(pid, None)


room_manager = RoomManager()
