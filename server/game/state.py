"""核心游戏状态与规则引擎"""

import random
from typing import Optional
from .deck import Deck, CARD_CONFIG


class GameState:
    def __init__(self, player_ids: list[str], player_names: dict[str, str]):
        """
        初始化游戏状态。
        player_ids: 玩家ID列表（3-7人）
        player_names: {player_id: 昵称}
        """
        if not (3 <= len(player_ids) <= 7):
            raise ValueError(f"游戏人数须为3-7人，当前 {len(player_ids)} 人")

        self._player_ids: list[str] = list(player_ids)
        self._player_names: dict[str, str] = dict(player_names)

        # 牌堆初始化，移除5张
        self._deck = Deck(remove_count=5)

        # 玩家状态
        self._hands: dict[str, list[str]] = {}       # 手牌（仅自己可见）
        self._areas: dict[str, dict[str, int]] = {}  # 放置区 {card_type: count}
        self._coins: dict[str, int] = {}             # 资金

        for pid in self._player_ids:
            self._hands[pid] = self._deck.deal(3)
            self._areas[pid] = {ct: 0 for ct in CARD_CONFIG}
            self._coins[pid] = 10

        # 市场：[{"card": "🐶", "coins": 3}, ...]
        self._market: list[dict] = []

        # 大股东：{card_type: player_id or None}
        self._major_shareholders: dict[str, Optional[str]] = {
            ct: None for ct in CARD_CONFIG
        }

        # 反垄断标记：{player_id: set of card_type}
        self._anti_monopoly: dict[str, set[str]] = {
            pid: set() for pid in self._player_ids
        }

        # 回合状态
        self._current_index: int = random.randrange(len(self._player_ids))
        self._turn_phase: str = "draw"  # "draw" | "play"
        self._turn_context: dict = {}   # 本回合临时上下文

        # 游戏阶段
        self._phase: str = "playing"    # "playing" | "scoring" | "ended"
        self._last_card_drawn: bool = False
        self._last_card_player: Optional[str] = None  # 摸到最后一张牌的玩家
        self._scores: Optional[dict] = None

    # ─── 只读属性 ────────────────────────────────────────────────

    @property
    def current_player_id(self) -> str:
        return self._player_ids[self._current_index]

    @property
    def turn_phase(self) -> str:
        return self._turn_phase

    @property
    def phase(self) -> str:
        return self._phase

    # ─── 辅助方法 ────────────────────────────────────────────────

    def get_draw_cost(self, player_id: str) -> int:
        """计算该玩家摸牌需支付的资金（市场卡数 - 反垄断豁免数）"""
        exempt_types = self._anti_monopoly[player_id]
        cost = sum(
            1 for slot in self._market
            if slot["card"] not in exempt_types
        )
        return cost

    def can_draw(self, player_id: str) -> bool:
        """该玩家是否有足够资金摸牌"""
        return self._coins[player_id] >= self.get_draw_cost(player_id)

    def get_playable_actions(self, player_id: str) -> dict:
        """返回当前可执行的操作及约束"""
        if player_id != self.current_player_id or self._phase != "playing":
            return {"can_draw": False, "can_pick_market": [], "can_play_to_market": [], "can_play_to_area": []}

        if self._turn_phase == "draw":
            # 可摸牌的市场槽
            pickable = [
                i for i, slot in enumerate(self._market)
                if slot["card"] not in self._anti_monopoly[player_id]
            ]
            return {
                "can_draw": self.can_draw(player_id),
                "can_pick_market": pickable,
            }
        else:
            # play阶段：哪些手牌可打到市场
            picked_type = self._turn_context.get("picked_from_market")
            to_market = [
                i for i, card in enumerate(self._hands[player_id])
                if card != picked_type
            ]
            to_area = list(range(len(self._hands[player_id])))
            return {
                "can_play_to_market": to_market,
                "can_play_to_area": to_area,
            }

    def _check_turn(self, player_id: str, expected_phase: str):
        """校验是否轮到该玩家，以及当前是否在正确阶段"""
        if self._phase != "playing":
            raise ValueError("游戏未在进行中")
        if player_id != self.current_player_id:
            raise ValueError(f"现在不是玩家 {player_id} 的回合")
        if self._turn_phase != expected_phase:
            raise ValueError(f"当前阶段为 {self._turn_phase}，无法执行该操作")

    # ─── 阶段一：获取卡牌 ─────────────────────────────────────────

    def draw_card(self, player_id: str) -> str:
        """
        从牌堆摸牌。
        - 扣资金（市场卡数 - 反垄断豁免数）
        - 给市场中非豁免卡加1资金
        - 摸1张加入手牌
        - 检查是否为最后一张
        """
        self._check_turn(player_id, "draw")

        if self._deck.is_empty:
            raise ValueError("牌堆已空，无法摸牌")

        cost = self.get_draw_cost(player_id)
        if self._coins[player_id] < cost:
            raise ValueError(
                f"资金不足：需要 {cost}，当前有 {self._coins[player_id]}"
            )

        # 扣资金，给市场非豁免卡加1资金
        self._coins[player_id] -= cost
        exempt_types = self._anti_monopoly[player_id]
        for slot in self._market:
            if slot["card"] not in exempt_types:
                slot["coins"] += 1

        # 摸牌
        card = self._deck.draw()
        self._hands[player_id].append(card)

        # 检查是否摸到最后一张
        if self._deck.is_empty:
            self._last_card_drawn = True
            self._last_card_player = player_id

        self._turn_phase = "play"
        return card

    def pick_market(self, player_id: str, market_index: int) -> dict:
        """
        从市场取牌。
        返回 {"card": ..., "coins_gained": ...}
        """
        self._check_turn(player_id, "draw")

        if market_index < 0 or market_index >= len(self._market):
            raise ValueError(f"无效的市场索引 {market_index}")

        slot = self._market[market_index]
        card_type = slot["card"]

        if card_type in self._anti_monopoly[player_id]:
            raise ValueError(
                f"玩家持有 {card_type} 的反垄断标记，不能从市场取该公司卡牌"
            )

        # 取出卡牌，资金归玩家
        self._market.pop(market_index)
        self._hands[player_id].append(card_type)
        coins_gained = slot["coins"]
        self._coins[player_id] += coins_gained

        # 记录本轮取牌类型（用于规则D1校验）
        self._turn_context["picked_from_market"] = card_type

        self._turn_phase = "play"
        return {"card": card_type, "coins_gained": coins_gained}

    # ─── 阶段二：打出卡牌 ─────────────────────────────────────────

    def play_to_market(self, player_id: str, hand_index: int):
        """打出手牌到市场（0资金入场）"""
        self._check_turn(player_id, "play")

        hand = self._hands[player_id]
        if hand_index < 0 or hand_index >= len(hand):
            raise ValueError(f"无效的手牌索引 {hand_index}")

        card_type = hand[hand_index]

        # 规则D1：本轮从市场取了某类型卡，不能打回同类型
        picked_type = self._turn_context.get("picked_from_market")
        if picked_type and card_type == picked_type:
            raise ValueError(
                f"本轮已从市场取了 {card_type}，不能将相同公司的卡牌打回市场"
            )

        hand.pop(hand_index)
        self._market.append({"card": card_type, "coins": 0})

        self._end_turn()

    def play_to_area(self, player_id: str, hand_index: int):
        """将手牌放入自己的放置区"""
        self._check_turn(player_id, "play")

        hand = self._hands[player_id]
        if hand_index < 0 or hand_index >= len(hand):
            raise ValueError(f"无效的手牌索引 {hand_index}")

        card_type = hand[hand_index]
        hand.pop(hand_index)
        self._areas[player_id][card_type] += 1

        # 重新计算大股东和反垄断标记
        self._update_majority(card_type)

        self._end_turn()

    # ─── 大股东计算 ───────────────────────────────────────────────

    def _update_majority(self, card_type: str):
        """
        重新计算某公司的大股东。
        平局时大股东不变（先到先得，D6）。
        """
        counts = {
            pid: self._areas[pid][card_type]
            for pid in self._player_ids
        }
        max_count = max(counts.values())

        if max_count == 0:
            # 没人持有，无大股东
            self._major_shareholders[card_type] = None
            for pid in self._player_ids:
                self._anti_monopoly[pid].discard(card_type)
            return

        candidates = [pid for pid, c in counts.items() if c == max_count]

        current_major = self._major_shareholders[card_type]

        if len(candidates) == 1:
            # 唯一最多者成为大股东
            new_major = candidates[0]
        elif current_major in candidates:
            # 平局且现任大股东在平局中，保持不变
            new_major = current_major
        else:
            # 平局且现任大股东不在其中（理论上不会发生，防御性处理）
            new_major = current_major

        # 更新反垄断标记
        if new_major != current_major:
            # 移除原大股东的标记
            if current_major is not None:
                self._anti_monopoly[current_major].discard(card_type)
            # 赋予新大股东标记
            self._anti_monopoly[new_major].add(card_type)
            self._major_shareholders[card_type] = new_major
        elif new_major is not None and card_type not in self._anti_monopoly[new_major]:
            # 首次确立大股东
            self._anti_monopoly[new_major].add(card_type)
            self._major_shareholders[card_type] = new_major

    # ─── 结束回合 ─────────────────────────────────────────────────

    def _end_turn(self):
        """结束当前回合，切换到下一玩家或触发计分"""
        self._turn_context = {}

        if self._last_card_drawn and self._last_card_player == self.current_player_id:
            # 摸到最后一张牌的玩家完成打出阶段，触发计分
            self._phase = "scoring"
            self._scores = self.calculate_scores()
            self._phase = "ended"
            return

        # 切换到下一位玩家
        self._current_index = (self._current_index + 1) % len(self._player_ids)
        self._turn_phase = "draw"

    # ─── 计分 ─────────────────────────────────────────────────────

    def calculate_scores(self) -> dict:
        """
        计分规则：
        - 每家公司：统计手牌+放置区的总持有数
        - 唯一最多者为大股东（并列则无大股东，跳过）
        - 非大股东每张卡支付1资金，大股东每收1得3（D7）
        返回包含 final_coins、company_details、winner 的字典。
        """
        coins = {pid: self._coins[pid] for pid in self._player_ids}
        company_details = {}

        for card_type in CARD_CONFIG:
            # 统计每位玩家总持有数（手牌+放置区）
            totals = {}
            for pid in self._player_ids:
                hand_count = self._hands[pid].count(card_type)
                area_count = self._areas[pid][card_type]
                totals[pid] = hand_count + area_count

            max_count = max(totals.values())

            if max_count == 0:
                # 无人持有该公司卡牌
                company_details[card_type] = {
                    "major_shareholder": None,
                    "reason": "无人持有",
                    "penalties": {},
                }
                continue

            top_players = [pid for pid, c in totals.items() if c == max_count]

            if len(top_players) != 1:
                # 并列，无大股东，跳过结算
                company_details[card_type] = {
                    "major_shareholder": None,
                    "reason": "并列，无大股东",
                    "totals": totals,
                    "penalties": {},
                }
                continue

            major = top_players[0]
            penalties = {}

            for pid in self._player_ids:
                if pid == major:
                    continue
                count = totals[pid]
                if count > 0:
                    # 非大股东支付 count 资金，大股东得 count*3
                    coins[pid] -= count
                    coins[major] += count * 3
                    penalties[pid] = count

            company_details[card_type] = {
                "major_shareholder": major,
                "major_shareholder_name": self._player_names[major],
                "totals": totals,
                "penalties": penalties,  # {player_id: 支付张数}
            }

        # 找出获胜者（最多资金，并列时多人获胜）
        max_coins = max(coins.values())
        winners = [pid for pid, c in coins.items() if c == max_coins]

        return {
            "final_coins": coins,
            "company_details": company_details,
            "winner": winners[0] if len(winners) == 1 else winners,
            "winner_name": (
                self._player_names[winners[0]]
                if len(winners) == 1
                else [self._player_names[w] for w in winners]
            ),
        }

    # ─── 状态导出 ─────────────────────────────────────────────────

    def get_state_for_player(self, player_id: str) -> dict:
        """
        返回该玩家视角的游戏状态（信息隐藏）：
        - 自己手牌：完整内容
        - 其他人手牌：仅数量
        - 牌堆：仅剩余数
        - 其他公共信息：完整
        """
        players_view = []
        for pid in self._player_ids:
            if pid == player_id:
                hand_info = list(self._hands[pid])
            else:
                hand_info = len(self._hands[pid])  # 仅数量

            players_view.append({
                "id": pid,
                "name": self._player_names[pid],
                "hand": hand_info,
                "area": dict(self._areas[pid]),
                "coins": self._coins[pid],
                "anti_monopoly": list(self._anti_monopoly[pid]),
            })

        state = {
            "phase": self._phase,
            "current_player_id": self.current_player_id,
            "current_player_name": self._player_names[self.current_player_id],
            "turn_phase": self._turn_phase,
            "deck_remaining": self._deck.remaining,
            "market": list(self._market),
            "players": players_view,
            "major_shareholders": {
                ct: ms for ct, ms in self._major_shareholders.items()
            },
            "last_card_drawn": self._last_card_drawn,
        }

        if self._phase == "ended" and self._scores:
            state["scores"] = self._scores

        return state
