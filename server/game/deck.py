"""牌堆管理模块"""

import random
from typing import List

# 6种公司卡牌及数量，共45张
CARD_CONFIG: dict[str, int] = {
    "🦒": 5,   # 长颈鹿公司，最稀有
    "🐶": 6,   # 小狗公司
    "🦢": 7,   # 天鹅公司
    "🐙": 8,   # 章鱼公司
    "🦛": 9,   # 河马公司
    "🐘": 10,  # 大象公司，最多
}

TOTAL_CARDS = sum(CARD_CONFIG.values())  # 45


class Deck:
    def __init__(self, remove_count: int = 5):
        """
        初始化牌堆：生成45张牌，洗牌，随机移除 remove_count 张。
        移除的牌记录在 _removed 中，对玩家不可见。
        """
        # 生成完整牌堆
        all_cards: List[str] = []
        for card_type, count in CARD_CONFIG.items():
            all_cards.extend([card_type] * count)

        random.shuffle(all_cards)

        # 随机移除 remove_count 张（全局隐藏）
        self._removed: List[str] = all_cards[:remove_count]
        self._cards: List[str] = all_cards[remove_count:]

    def deal(self, n: int) -> List[str]:
        """从顶部发 n 张牌，返回列表。牌堆不足时抛异常。"""
        if n > len(self._cards):
            raise ValueError(f"牌堆剩余 {len(self._cards)} 张，无法发 {n} 张牌")
        dealt = self._cards[:n]
        self._cards = self._cards[n:]
        return dealt

    def draw(self) -> str:
        """摸1张牌。牌堆为空时抛异常。"""
        if self.is_empty:
            raise ValueError("牌堆已空，无法摸牌")
        card = self._cards[0]
        self._cards = self._cards[1:]
        return card

    @property
    def remaining(self) -> int:
        """剩余张数"""
        return len(self._cards)

    @property
    def is_empty(self) -> bool:
        return len(self._cards) == 0
