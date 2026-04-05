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


class DrawCardMsg(TypedDict):
    type: str          # "draw_card"


class PickMarketMsg(TypedDict):
    type: str          # "pick_market"
    card_index: int


class PlayToMarketMsg(TypedDict):
    type: str          # "play_to_market"
    hand_index: int


class PlayToAreaMsg(TypedDict):
    type: str          # "play_to_area"
    hand_index: int


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
    player_id: str
    game_state: dict


class GameStateMsg(TypedDict):
    type: str          # "game_state"
    state: dict


class YourTurnMsg(TypedDict):
    type: str          # "your_turn"
    phase: str         # "draw" | "play"
    # draw 阶段
    draw_cost: Optional[int]
    can_draw: Optional[bool]
    blocked_market: Optional[list[int]]
    # play 阶段
    blocked_play_to_market: Optional[list[int]]


class ActionResultMsg(TypedDict):
    type: str          # "action_result"
    action: str
    success: bool
    message: str


class GameEndMsg(TypedDict):
    type: str          # "game_end"
    scores: dict       # {player_id: final_coins}
    company_details: dict
    winner: object     # str 或 list[str]（并列时）
    winner_name: object
    revealed_hands: dict   # {player_id: [cards]}
    player_names: dict     # {player_id: name}


class GameAbortedMsg(TypedDict):
    type: str          # "game_aborted"
    reason: str
