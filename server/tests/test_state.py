"""核心游戏状态单元测试"""

import pytest
from server.game.state import GameState
from server.game.deck import CARD_CONFIG


# ─── 测试辅助 ─────────────────────────────────────────────────────

def make_game(n: int = 3):
    """创建 n 人游戏，返回 (state, player_ids)"""
    ids = [f"p{i}" for i in range(n)]
    names = {pid: f"玩家{i}" for i, pid in enumerate(ids)}
    return GameState(ids, names), ids


def current(state: GameState):
    """返回当前玩家ID"""
    return state.current_player_id


def force_hand(state: GameState, player_id: str, cards: list[str]):
    """强制设置玩家手牌（测试专用）"""
    state._hands[player_id] = list(cards)


def force_market(state: GameState, slots: list[dict]):
    """强制设置市场（测试专用）"""
    state._market = [dict(s) for s in slots]


def force_area(state: GameState, player_id: str, card_type: str, count: int):
    """强制设置放置区数量"""
    state._areas[player_id][card_type] = count


def force_anti_monopoly(state: GameState, player_id: str, card_type: str):
    """强制赋予反垄断标记"""
    state._anti_monopoly[player_id].add(card_type)
    state._major_shareholders[card_type] = player_id


def force_coins(state: GameState, player_id: str, amount: int):
    """强制设置玩家资金"""
    state._coins[player_id] = amount


def skip_draw_phase(state: GameState):
    """直接跳到 play 阶段（给当前玩家手牌加一张）"""
    pid = current(state)
    # 确保手牌里有牌可打
    if not state._hands[pid]:
        state._hands[pid] = ["🐘"]
    state._turn_phase = "play"


# ─── 初始化测试 ───────────────────────────────────────────────────

def test_init_player_count_invalid():
    """人数不足3人或超过7人时抛异常"""
    with pytest.raises(ValueError):
        GameState(["p1", "p2"], {"p1": "A", "p2": "B"})
    with pytest.raises(ValueError):
        ids = [f"p{i}" for i in range(8)]
        GameState(ids, {pid: pid for pid in ids})


def test_init_hand_and_coins():
    """初始化：每人3张手牌、10资金"""
    state, ids = make_game(3)
    for pid in ids:
        view = state.get_state_for_player(pid)
        me = next(p for p in view["players"] if p["id"] == pid)
        assert len(me["hand"]) == 3
        assert me["coins"] == 10


def test_init_market_empty():
    """初始市场为空"""
    state, _ = make_game(3)
    view = state.get_state_for_player("p0")
    assert view["market"] == []


def test_init_deck_remaining():
    """初始化后牌堆剩余 = 40 - 3*n"""
    state, _ = make_game(3)
    view = state.get_state_for_player("p0")
    assert view["deck_remaining"] == 40 - 3 * 3


# ─── 摸牌测试 ─────────────────────────────────────────────────────

def test_draw_card_basic():
    """摸牌：资金正确扣除，手牌+1"""
    state, ids = make_game(3)
    pid = current(state)
    # 市场空，费用=0
    force_coins(state, pid, 10)
    before_coins = state._coins[pid]
    before_hand = len(state._hands[pid])

    state.draw_card(pid)

    assert state._coins[pid] == before_coins  # 市场空，无费用
    assert len(state._hands[pid]) == before_hand + 1
    assert state.turn_phase == "play"


def test_draw_card_cost_market():
    """摸牌：市场有牌时正确扣费，市场卡资金增加"""
    state, ids = make_game(3)
    pid = current(state)
    force_coins(state, pid, 10)
    force_market(state, [
        {"card": "🐶", "coins": 0},
        {"card": "🦢", "coins": 1},
    ])

    state.draw_card(pid)

    # 费用=2（2张市场卡），扣2资金
    assert state._coins[pid] == 8
    # 市场每张卡 +1 资金
    assert state._market[0]["coins"] == 1
    assert state._market[1]["coins"] == 2


def test_draw_card_anti_monopoly_exemption():
    """摸牌：反垄断标记豁免对应公司的费用"""
    state, ids = make_game(3)
    pid = current(state)
    force_coins(state, pid, 10)
    force_market(state, [
        {"card": "🐶", "coins": 0},  # 玩家持有反垄断标记，豁免
        {"card": "🦢", "coins": 0},  # 正常收费
    ])
    force_anti_monopoly(state, pid, "🐶")

    state.draw_card(pid)

    # 只扣1资金（🦢），🐶豁免
    assert state._coins[pid] == 9
    # 🐶 的市场资金不变，🦢 +1
    assert state._market[0]["coins"] == 0
    assert state._market[1]["coins"] == 1


def test_draw_card_insufficient_coins():
    """摸牌：资金不足时抛异常"""
    state, ids = make_game(3)
    pid = current(state)
    force_coins(state, pid, 1)
    force_market(state, [
        {"card": "🐶", "coins": 0},
        {"card": "🦢", "coins": 0},
        {"card": "🐙", "coins": 0},
    ])

    with pytest.raises(ValueError, match="资金不足"):
        state.draw_card(pid)


def test_draw_card_wrong_player():
    """非当前玩家摸牌抛异常"""
    state, ids = make_game(3)
    other = next(pid for pid in ids if pid != current(state))
    with pytest.raises(ValueError):
        state.draw_card(other)


# ─── 市场取牌测试 ─────────────────────────────────────────────────

def test_pick_market_basic():
    """从市场取牌：卡牌和资金正确转移"""
    state, ids = make_game(3)
    pid = current(state)
    force_market(state, [{"card": "🐶", "coins": 3}])
    before_coins = state._coins[pid]
    before_hand = len(state._hands[pid])

    result = state.pick_market(pid, 0)

    assert result["card"] == "🐶"
    assert result["coins_gained"] == 3
    assert state._coins[pid] == before_coins + 3
    assert len(state._hands[pid]) == before_hand + 1
    assert state._hands[pid][-1] == "🐶"
    assert len(state._market) == 0
    assert state.turn_phase == "play"


def test_pick_market_anti_monopoly_blocked():
    """市场取牌：反垄断标记阻止取牌"""
    state, ids = make_game(3)
    pid = current(state)
    force_anti_monopoly(state, pid, "🐶")
    force_market(state, [{"card": "🐶", "coins": 0}])

    with pytest.raises(ValueError, match="反垄断标记"):
        state.pick_market(pid, 0)


def test_pick_market_invalid_index():
    """无效市场索引抛异常"""
    state, ids = make_game(3)
    pid = current(state)
    force_market(state, [{"card": "🐶", "coins": 0}])

    with pytest.raises(ValueError):
        state.pick_market(pid, 5)


def test_pick_market_records_context():
    """取牌后 turn_context 记录取牌类型"""
    state, ids = make_game(3)
    pid = current(state)
    force_market(state, [{"card": "🦢", "coins": 0}])
    state.pick_market(pid, 0)
    assert state._turn_context.get("picked_from_market") == "🦢"


# ─── 打出到市场测试 ────────────────────────────────────────────────

def test_play_to_market_basic():
    """打出手牌到市场"""
    state, ids = make_game(3)
    pid = current(state)
    force_hand(state, pid, ["🐶", "🦢", "🐙"])
    skip_draw_phase(state)

    state.play_to_market(pid, 0)

    assert {"card": "🐶", "coins": 0} in state._market


def test_play_to_market_same_type_blocked():
    """本轮从市场取了🐶，不能打回🐶"""
    state, ids = make_game(3)
    pid = current(state)
    force_market(state, [{"card": "🐶", "coins": 0}])
    state.pick_market(pid, 0)  # 取了🐶
    # 现在手牌里有🐶，尝试打回去
    hand = state._hands[pid]
    dog_index = hand.index("🐶")

    with pytest.raises(ValueError, match="打回市场"):
        state.play_to_market(pid, dog_index)


def test_play_to_market_different_type_allowed():
    """本轮取了🐶，可以打出其他类型"""
    state, ids = make_game(3)
    pid = current(state)
    force_market(state, [{"card": "🐶", "coins": 0}])
    state.pick_market(pid, 0)  # 取了🐶
    # 强制手牌中有🦢
    force_hand(state, pid, ["🦢"])
    state._turn_phase = "play"

    state.play_to_market(pid, 0)
    assert any(s["card"] == "🦢" for s in state._market)


# ─── 放入放置区测试 ────────────────────────────────────────────────

def test_play_to_area_basic():
    """放入放置区：放置区数量增加"""
    state, ids = make_game(3)
    pid = current(state)
    force_hand(state, pid, ["🦒", "🐶"])
    skip_draw_phase(state)

    state.play_to_area(pid, 0)

    assert state._areas[pid]["🦒"] == 1


def test_play_to_area_triggers_majority():
    """放入放置区后大股东和反垄断正确更新"""
    state, ids = make_game(3)
    p0, p1, p2 = ids
    # p0 有2张🦒，p1 有1张🦒
    force_area(state, p0, "🦒", 2)
    force_area(state, p1, "🦒", 1)
    # 手动跑一次 majority 更新以初始化 p0 为大股东
    state._update_majority("🦒")
    assert state._major_shareholders["🦒"] == p0
    assert "🦒" in state._anti_monopoly[p0]

    # p1 再放1张🦒 → p1 持有2张，平局，大股东不变
    force_area(state, p1, "🦒", 2)
    state._update_majority("🦒")
    assert state._major_shareholders["🦒"] == p0  # 平局不更替

    # p1 再放1张🦒 → p1 持有3张，超越 p0，大股东易主
    force_area(state, p1, "🦒", 3)
    state._update_majority("🦒")
    assert state._major_shareholders["🦒"] == p1
    assert "🦒" in state._anti_monopoly[p1]
    assert "🦒" not in state._anti_monopoly[p0]


def test_majority_tie_no_change():
    """大股东平局时不更替（D6）"""
    state, ids = make_game(3)
    p0, p1, p2 = ids

    # p0 先持有1张🐶，成为大股东
    force_area(state, p0, "🐶", 1)
    state._update_majority("🐶")
    assert state._major_shareholders["🐶"] == p0

    # p1 追平 → 不更替
    force_area(state, p1, "🐶", 1)
    state._update_majority("🐶")
    assert state._major_shareholders["🐶"] == p0


# ─── 计分测试 ─────────────────────────────────────────────────────

def test_calculate_scores_unique_major():
    """唯一大股东：收3倍资金，其他人扣1"""
    state, ids = make_game(3)
    p0, p1, p2 = ids

    # 清空手牌，避免干扰
    for pid in ids:
        state._hands[pid] = []

    # p0 放置区有2张🦒，p1 和 p2 各1张
    force_area(state, p0, "🦒", 2)
    force_area(state, p1, "🦒", 1)
    force_area(state, p2, "🦒", 1)

    # 设置初始资金
    force_coins(state, p0, 10)
    force_coins(state, p1, 10)
    force_coins(state, p2, 10)

    scores = state.calculate_scores()

    detail = scores["company_details"]["🦒"]
    assert detail["major_shareholder"] == p0
    # p1 支付1，p2 支付1 → p0 收 2*3=6
    assert scores["final_coins"][p0] == 10 + 2 * 3
    assert scores["final_coins"][p1] == 10 - 1
    assert scores["final_coins"][p2] == 10 - 1


def test_calculate_scores_tied_no_major():
    """并列最多，无大股东，跳过结算"""
    state, ids = make_game(3)
    p0, p1, p2 = ids
    for pid in ids:
        state._hands[pid] = []

    force_area(state, p0, "🦒", 2)
    force_area(state, p1, "🦒", 2)
    force_coins(state, p0, 10)
    force_coins(state, p1, 10)
    force_coins(state, p2, 10)

    scores = state.calculate_scores()

    detail = scores["company_details"]["🦒"]
    assert detail["major_shareholder"] is None
    # 资金不变
    assert scores["final_coins"][p0] == 10
    assert scores["final_coins"][p1] == 10


def test_calculate_scores_hand_counts():
    """计分时手牌也计入持有数（D4）"""
    state, ids = make_game(3)
    p0, p1, p2 = ids

    for pid in ids:
        state._hands[pid] = []

    # p0 放置区1张🐶，p1 手牌1张🐶 → 并列，无大股东
    force_area(state, p0, "🐶", 1)
    state._hands[p1] = ["🐶"]

    scores = state.calculate_scores()
    detail = scores["company_details"]["🐶"]
    assert detail["major_shareholder"] is None


# ─── 状态导出测试 ─────────────────────────────────────────────────

def test_get_state_for_player_hand_visibility():
    """自己手牌完整可见，其他人只有数量"""
    state, ids = make_game(3)
    p0, p1, p2 = ids
    force_hand(state, p0, ["🦒", "🐶"])
    force_hand(state, p1, ["🦢", "🐙", "🦛"])

    view = state.get_state_for_player(p0)

    players = {p["id"]: p for p in view["players"]}
    assert players[p0]["hand"] == ["🦒", "🐶"]   # 完整内容
    assert players[p1]["hand"] == 3               # 仅数量
    assert players[p2]["hand"] == len(state._hands[p2])  # 仅数量


def test_get_state_for_player_deck_hidden():
    """牌堆内容不可见，只有剩余数"""
    state, ids = make_game(3)
    view = state.get_state_for_player("p0")
    assert isinstance(view["deck_remaining"], int)
    assert "deck" not in view  # 不暴露牌堆内容


def test_get_state_public_info_complete():
    """市场、放置区、资金、反垄断标记全部公开"""
    state, ids = make_game(3)
    pid = current(state)
    force_market(state, [{"card": "🐶", "coins": 2}])

    view = state.get_state_for_player("p0")
    assert len(view["market"]) == 1
    assert view["market"][0]["coins"] == 2
    for p in view["players"]:
        assert "area" in p
        assert "coins" in p
        assert "anti_monopoly" in p
