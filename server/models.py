"""WebSocket 消息数据结构"""

from typing import TypedDict, Optional


# ─── 客户端 → 服务端 ────────────────────────────────────────────────

class CreateRoomMsg(TypedDict):
    type: str          # "create_room"
    player_name: str


class JoinRoomMsg(TypedDict):
    type: str          # "join_room"
    room_code: str
    player_name: str


class LeaveRoomMsg(TypedDict):
    type: str          # "leave_room"


class PlayerReadyMsg(TypedDict):
    type: str          # "player_ready"


class StartGameMsg(TypedDict):
    type: str          # "start_game"


# ─── 服务端 → 客户端 ────────────────────────────────────────────────

class PlayerInfo(TypedDict):
    id: str
    name: str
    is_host: bool
    is_ready: bool


class RoomCreatedMsg(TypedDict):
    type: str          # "room_created"
    room_code: str
    player_id: str


class RoomUpdateMsg(TypedDict):
    type: str          # "room_update"
    room_code: str
    players: list[PlayerInfo]


class ErrorMsg(TypedDict):
    type: str          # "error"
    message: str


class GameStartMsg(TypedDict):
    type: str          # "game_start"
    game_state: dict   # 各玩家私有视角，由 state.get_state_for_player 生成
