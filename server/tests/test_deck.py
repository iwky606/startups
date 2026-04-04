"""牌堆单元测试"""

import pytest
from server.game.deck import Deck, CARD_CONFIG, TOTAL_CARDS


def test_initial_count():
    """初始化后牌数 = 40（45 - 5）"""
    deck = Deck(remove_count=5)
    assert deck.remaining == 40


def test_custom_remove_count():
    """自定义移除数量"""
    deck = Deck(remove_count=0)
    assert deck.remaining == TOTAL_CARDS  # 45

    deck2 = Deck(remove_count=10)
    assert deck2.remaining == TOTAL_CARDS - 10


def test_deal_reduces_count():
    """发牌后牌数正确减少"""
    deck = Deck(remove_count=5)
    deck.deal(3)
    assert deck.remaining == 37

    deck.deal(7)
    assert deck.remaining == 30


def test_deal_returns_correct_cards():
    """deal 返回正确数量的牌"""
    deck = Deck(remove_count=5)
    cards = deck.deal(3)
    assert len(cards) == 3
    # 每张牌都是合法类型
    for card in cards:
        assert card in CARD_CONFIG


def test_deal_insufficient_raises():
    """牌堆不足时 deal 抛异常"""
    deck = Deck(remove_count=5)
    deck.deal(40)
    with pytest.raises(ValueError, match="无法发"):
        deck.deal(1)


def test_draw_reduces_count():
    """摸1张，牌数减1"""
    deck = Deck(remove_count=5)
    before = deck.remaining
    card = deck.draw()
    assert deck.remaining == before - 1
    assert card in CARD_CONFIG


def test_draw_empty_raises():
    """牌堆空时 draw 抛异常"""
    deck = Deck(remove_count=5)
    deck.deal(40)
    assert deck.is_empty
    with pytest.raises(ValueError, match="牌堆已空"):
        deck.draw()


def test_is_empty():
    """is_empty 属性正确"""
    deck = Deck(remove_count=5)
    assert not deck.is_empty
    deck.deal(40)
    assert deck.is_empty


def test_removed_cards_not_in_deck():
    """移除的牌确实从牌堆中消失（总数守恒）"""
    deck = Deck(remove_count=5)
    # 取出所有剩余牌
    remaining_cards = deck.deal(deck.remaining)
    removed = deck._removed

    all_cards = remaining_cards + removed
    # 合计应为45张
    assert len(all_cards) == TOTAL_CARDS
    # 每种牌数量正确
    for card_type, count in CARD_CONFIG.items():
        assert all_cards.count(card_type) == count
