"""房间管理模块"""

import random
import string
from dataclasses import dataclass, field
from typing import Optional
from fastapi import WebSocket

from .game.state import GameState


# 去掉易混淆字符
_CODE_CHARS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def _generate_room_code() -> str:
    return "".join(random.choices(_CODE_CHARS, k=6))


@dataclass
class PlayerInfo:
    name: str
    ws: WebSocket
    is_ready: bool = False


@dataclass
class Room:
    room_code: str
    host_id: str
    players: dict[str, PlayerInfo] = field(default_factory=dict)
    game_state: Optional[GameState] = None
    max_players: int = 7
    min_players: int = 3
    remove_count: int = 5  # 开局移除张数（房主创建时设定）

    @property
    def is_started(self) -> bool:
        return self.game_state is not None

    def player_list(self) -> list[dict]:
        """返回 room_update 用的玩家列表"""
        return [
            {
                "id": pid,
                "name": info.name,
                "is_host": pid == self.host_id,
                "is_ready": info.is_ready,
            }
            for pid, info in self.players.items()
        ]


class RoomManager:
    """单例房间管理器"""

    def __init__(self):
        self.rooms: dict[str, Room] = {}
        self.player_room_map: dict[str, str] = {}  # player_id → room_code

    def _unique_code(self) -> str:
        code = _generate_room_code()
        while code in self.rooms:
            code = _generate_room_code()
        return code

    def create_room(self, player_id: str, player_name: str, ws: WebSocket, remove_count: int = 5) -> Room:
        """创建房间，创建者自动加入并成为房主"""
        code = self._unique_code()
        room = Room(room_code=code, host_id=player_id, remove_count=remove_count)
        room.players[player_id] = PlayerInfo(name=player_name, ws=ws)
        self.rooms[code] = room
        self.player_room_map[player_id] = code
        return room

    def join_room(
        self,
        room_code: str,
        player_id: str,
        player_name: str,
        ws: WebSocket,
    ) -> Room:
        """加入已有房间"""
        room = self.rooms.get(room_code)
        if room is None:
            raise ValueError(f"房间 {room_code} 不存在")
        if room.is_started:
            raise ValueError("游戏已经开始，无法加入")
        if len(room.players) >= room.max_players:
            raise ValueError("房间已满")
        if any(p.name == player_name for p in room.players.values()):
            raise ValueError(f"昵称「{player_name}」已被使用，请换一个")

        room.players[player_id] = PlayerInfo(name=player_name, ws=ws)
        self.player_room_map[player_id] = room_code
        return room

    def leave_room(self, player_id: str) -> Optional[Room]:
        """
        玩家离开房间。
        - 如果是房主，转移给下一位玩家
        - 如果房间空了，删除房间
        - 返回受影响的房间（可能已被删除，此时返回 None）
        """
        room_code = self.player_room_map.pop(player_id, None)
        if room_code is None:
            return None

        room = self.rooms.get(room_code)
        if room is None:
            return None

        room.players.pop(player_id, None)

        if not room.players:
            # 房间已空，删除
            del self.rooms[room_code]
            return None

        # 如果离开的是房主，转移房主
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
        """
        校验并启动游戏：
        - 必须是房主
        - 人数 >= 3
        - 所有非房主玩家已准备
        """
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
            if pid != room.host_id and not info.is_ready
        ]
        if not_ready:
            raise ValueError(f"以下玩家尚未准备：{'、'.join(not_ready)}")

        player_ids = list(room.players.keys())
        player_names = {pid: info.name for pid, info in room.players.items()}
        room.game_state = GameState(player_ids, player_names, remove_count=room.remove_count)
        return room


    def rejoin_room(
        self,
        room_code: str,
        player_name: str,
        new_ws: WebSocket,
    ) -> str:
        """
        游戏进行中重连。找到同名玩家，更新其 WebSocket 引用，返回原 player_id。
        用于页面跳转（room→game）导致的短暂断线后重连。
        """
        room = self.rooms.get(room_code)
        if room is None:
            raise ValueError(f"房间 {room_code} 不存在")
        if not room.is_started:
            raise ValueError("游戏尚未开始")
        for pid, info in room.players.items():
            if info.name == player_name:
                info.ws = new_ws
                self.player_room_map[pid] = room_code   # 重建映射
                return pid
        raise ValueError(f"玩家「{player_name}」不在此游戏中")

    def mark_player_disconnected(self, player_id: str):
        """
        游戏进行中断线：将玩家 WS 置为 None，保留房间等待重连。
        不删除 room.players 中的记录，不 abort 房间。
        """
        code = self.player_room_map.pop(player_id, None)
        if code is None:
            return
        room = self.rooms.get(code)
        if room is None:
            return
        info = room.players.get(player_id)
        if info:
            info.ws = None

    def abort_room(self, room_code: str):
        """强制删除房间，清理所有玩家的映射（断线/游戏中止使用）"""
        room = self.rooms.pop(room_code, None)
        if room:
            for pid in list(room.players.keys()):
                self.player_room_map.pop(pid, None)


# 全局单例
room_manager = RoomManager()
