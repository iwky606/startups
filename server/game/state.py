"""Core game state and rules engine."""

import json
import random
from typing import Optional

from .deck import CARD_CONFIG, Deck


class GameState:
    def __init__(
        self,
        player_ids: list[str],
        player_names: dict[str, str],
        remove_count: int = 5,
        player_meta: Optional[dict[str, dict]] = None,
    ):
        if not (3 <= len(player_ids) <= 7):
            raise ValueError(f"游戏人数须为 3-7 人，当前 {len(player_ids)} 人")

        self._player_ids: list[str] = list(player_ids)
        self._player_names: dict[str, str] = dict(player_names)
        self._player_meta: dict[str, dict] = {
            pid: dict((player_meta or {}).get(pid, {}))
            for pid in self._player_ids
        }

        self._deck = Deck(remove_count=remove_count)

        self._hands: dict[str, list[str]] = {}
        self._areas: dict[str, dict[str, int]] = {}
        self._coins: dict[str, int] = {}

        for pid in self._player_ids:
            self._hands[pid] = self._deck.deal(3)
            self._areas[pid] = {ct: 0 for ct in CARD_CONFIG}
            self._coins[pid] = 10

        self._market: list[dict] = []
        self._major_shareholders: dict[str, Optional[str]] = {
            ct: None for ct in CARD_CONFIG
        }
        self._anti_monopoly: dict[str, set[str]] = {
            pid: set() for pid in self._player_ids
        }

        self._current_index: int = random.randrange(len(self._player_ids))
        self._turn_phase: str = "draw"
        self._turn_context: dict = {}

        self._phase: str = "playing"
        self._last_card_drawn: bool = False
        self._last_card_player: Optional[str] = None
        self._scores: Optional[dict] = None

        self._action_log: list[dict] = []
        self._turn_number: int = 0

    @property
    def current_player_id(self) -> str:
        return self._player_ids[self._current_index]

    @property
    def turn_phase(self) -> str:
        return self._turn_phase

    @property
    def phase(self) -> str:
        return self._phase

    def get_draw_cost(self, player_id: str) -> int:
        exempt_types = self._anti_monopoly[player_id]
        return sum(1 for slot in self._market if slot["card"] not in exempt_types)

    def can_draw(self, player_id: str) -> bool:
        return self._coins[player_id] >= self.get_draw_cost(player_id)

    def get_playable_actions(self, player_id: str) -> dict:
        if player_id != self.current_player_id or self._phase != "playing":
            return {
                "can_draw": False,
                "can_pick_market": [],
                "can_play_to_market": [],
                "can_play_to_area": [],
            }

        if self._turn_phase == "draw":
            pickable = [
                i for i, slot in enumerate(self._market)
                if slot["card"] not in self._anti_monopoly[player_id]
            ]
            return {
                "can_draw": self.can_draw(player_id),
                "can_pick_market": pickable,
            }

        picked_type = self._turn_context.get("picked_from_market")
        to_market = [
            i for i, card in enumerate(self._hands[player_id])
            if card != picked_type
        ]
        return {
            "can_play_to_market": to_market,
            "can_play_to_area": list(range(len(self._hands[player_id]))),
        }

    def _log_action(self, player_id: str, action: str, detail: str):
        self._action_log.append({
            "turn": self._turn_number,
            "player_id": player_id,
            "player_name": self._player_names[player_id],
            "action": action,
            "detail": detail,
        })

    def _check_turn(self, player_id: str, expected_phase: str):
        if self._phase != "playing":
            raise ValueError("游戏未在进行中")
        if player_id != self.current_player_id:
            raise ValueError(f"现在不是玩家 {player_id} 的回合")
        if self._turn_phase != expected_phase:
            raise ValueError(f"当前阶段为 {self._turn_phase}，无法执行该操作")

    def draw_card(self, player_id: str) -> str:
        self._check_turn(player_id, "draw")

        if self._deck.is_empty:
            raise ValueError("牌堆已空，无法摸牌")

        cost = self.get_draw_cost(player_id)
        if self._coins[player_id] < cost:
            raise ValueError(f"资金不足：需要 {cost}，当前有 {self._coins[player_id]}")

        self._coins[player_id] -= cost
        exempt_types = self._anti_monopoly[player_id]
        for slot in self._market:
            if slot["card"] not in exempt_types:
                slot["coins"] += 1

        card = self._deck.draw()
        self._hands[player_id].append(card)

        if self._deck.is_empty:
            self._last_card_drawn = True
            self._last_card_player = player_id

        self._log_action(player_id, "draw_card", f"摸牌 {card}，消耗 {cost} 💰")
        self._turn_phase = "play"
        return card

    def pick_market(self, player_id: str, market_index: int) -> dict:
        self._check_turn(player_id, "draw")

        if market_index < 0 or market_index >= len(self._market):
            raise ValueError(f"无效的市场索引 {market_index}")

        slot = self._market[market_index]
        card_type = slot["card"]

        if card_type in self._anti_monopoly[player_id]:
            raise ValueError(
                f"玩家持有 {card_type} 的反垄断标记，不能从市场取该公司卡牌"
            )

        self._market.pop(market_index)
        self._hands[player_id].append(card_type)
        coins_gained = slot["coins"]
        self._coins[player_id] += coins_gained
        self._turn_context["picked_from_market"] = card_type
        self._log_action(player_id, "pick_market", f"从市场取 {card_type}，获得 {coins_gained} 💰")
        self._turn_phase = "play"
        return {"card": card_type, "coins_gained": coins_gained}

    def play_to_market(self, player_id: str, hand_index: int):
        self._check_turn(player_id, "play")

        hand = self._hands[player_id]
        if hand_index < 0 or hand_index >= len(hand):
            raise ValueError(f"无效的手牌索引 {hand_index}")

        card_type = hand[hand_index]
        picked_type = self._turn_context.get("picked_from_market")
        if picked_type and card_type == picked_type:
            raise ValueError(f"本轮已从市场取了 {card_type}，不能将相同公司卡牌打回市场")

        hand.pop(hand_index)
        self._market.append({"card": card_type, "coins": 0})
        self._log_action(player_id, "play_to_market", f"将 {card_type} 打出到市场")
        self._end_turn()

    def play_to_area(self, player_id: str, hand_index: int):
        self._check_turn(player_id, "play")

        hand = self._hands[player_id]
        if hand_index < 0 or hand_index >= len(hand):
            raise ValueError(f"无效的手牌索引 {hand_index}")

        card_type = hand[hand_index]
        hand.pop(hand_index)
        self._areas[player_id][card_type] += 1
        self._update_majority(card_type)
        self._log_action(player_id, "play_to_area", f"将 {card_type} 放入放置区")
        self._end_turn()

    def _update_majority(self, card_type: str):
        counts = {
            pid: self._areas[pid][card_type]
            for pid in self._player_ids
        }
        max_count = max(counts.values())

        if max_count == 0:
            self._major_shareholders[card_type] = None
            for pid in self._player_ids:
                self._anti_monopoly[pid].discard(card_type)
            return

        candidates = [pid for pid, count in counts.items() if count == max_count]
        current_major = self._major_shareholders[card_type]

        if len(candidates) == 1:
            new_major = candidates[0]
        elif current_major in candidates:
            new_major = current_major
        else:
            new_major = current_major

        if new_major != current_major:
            if current_major is not None:
                self._anti_monopoly[current_major].discard(card_type)
            if new_major is not None:
                self._anti_monopoly[new_major].add(card_type)
            self._major_shareholders[card_type] = new_major
        elif new_major is not None and card_type not in self._anti_monopoly[new_major]:
            self._anti_monopoly[new_major].add(card_type)
            self._major_shareholders[card_type] = new_major

    def _end_turn(self):
        self._turn_context = {}
        self._turn_number += 1

        if self._last_card_drawn and self._last_card_player == self.current_player_id:
            self._phase = "scoring"
            self._scores = self.calculate_scores()
            self._phase = "ended"
            return

        self._current_index = (self._current_index + 1) % len(self._player_ids)
        self._turn_phase = "draw"

    def calculate_scores(self) -> dict:
        coins = {pid: self._coins[pid] for pid in self._player_ids}
        company_details = {}

        for card_type in CARD_CONFIG:
            totals = {}
            for pid in self._player_ids:
                hand_count = self._hands[pid].count(card_type)
                area_count = self._areas[pid][card_type]
                totals[pid] = hand_count + area_count

            max_count = max(totals.values())

            if max_count == 0:
                company_details[card_type] = {
                    "major_shareholder": None,
                    "reason": "无人持有",
                    "penalties": {},
                }
                continue

            top_players = [pid for pid, count in totals.items() if count == max_count]
            if len(top_players) != 1:
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
                    coins[pid] -= count
                    coins[major] += count * 3
                    penalties[pid] = count

            company_details[card_type] = {
                "major_shareholder": major,
                "major_shareholder_name": self._player_names[major],
                "totals": totals,
                "penalties": penalties,
            }

        max_coins = max(coins.values())
        winners = [pid for pid, amount in coins.items() if amount == max_coins]
        end_result_dict = {
            "final_coins": coins,
            "company_details": company_details,
            "winner": winners[0] if len(winners) == 1 else winners,
            "winner_name": (
                self._player_names[winners[0]]
                if len(winners) == 1
                else [self._player_names[w] for w in winners]
            ),
        }

        print("##end##\nend_result_dict: ", json.dumps(end_result_dict))
        return end_result_dict

    def get_state_for_player(self, player_id: str) -> dict:
        players_view = []
        for pid in self._player_ids:
            if pid == player_id:
                hand_info = list(self._hands[pid])
            else:
                hand_info = len(self._hands[pid])
            players_view.append({
                "id": pid,
                "name": self._player_names[pid],
                "hand": hand_info,
                "area": dict(self._areas[pid]),
                "coins": self._coins[pid],
                "anti_monopoly": list(self._anti_monopoly[pid]),
                "is_bot": bool(self._player_meta.get(pid, {}).get("is_bot")),
            })

        state = {
            "phase": self._phase,
            "current_player_id": self.current_player_id,
            "current_player_name": self._player_names[self.current_player_id],
            "turn_phase": self._turn_phase,
            "deck_remaining": self._deck.remaining,
            "market": list(self._market),
            "players": players_view,
            "major_shareholders": dict(self._major_shareholders),
            "last_card_drawn": self._last_card_drawn,
            "action_log": self._action_log[-60:],
        }

        if self._phase == "ended" and self._scores:
            state["scores"] = self._scores

        return state
