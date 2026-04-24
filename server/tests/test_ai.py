from server.game.ai import choose_draw_action, choose_play_action
from server.game.state import GameState


def test_bot_prefers_market_when_cannot_afford_draw():
    state = GameState(
        ["bot", "p1", "p2"],
        {"bot": "Bot", "p1": "P1", "p2": "P2"},
        player_meta={"bot": {"is_bot": True}},
    )
    state._current_index = 0
    state._turn_phase = "draw"
    state._coins["bot"] = 0
    state._market = [
        {"card": "🐶", "coins": 1},
        {"card": "🦒", "coins": 3},
    ]

    action = choose_draw_action(state, "bot")

    assert action == {"action": "pick_market", "card_index": 1}


def test_bot_prefers_area_when_it_can_take_majority():
    state = GameState(
        ["bot", "p1", "p2"],
        {"bot": "Bot", "p1": "P1", "p2": "P2"},
        player_meta={"bot": {"is_bot": True}},
    )
    state._current_index = 0
    state._turn_phase = "play"
    state._hands["bot"] = ["🐶"]
    state._areas["p1"]["🐶"] = 1
    state._areas["bot"]["🐶"] = 1
    state._update_majority("🐶")

    action = choose_play_action(state, "bot")

    assert action == {"action": "play_to_area", "hand_index": 0}


def test_bot_actions_keep_turn_progressing():
    state = GameState(
        ["bot", "p1", "p2"],
        {"bot": "Bot", "p1": "P1", "p2": "P2"},
        player_meta={"bot": {"is_bot": True}},
    )
    state._current_index = 0
    state._turn_phase = "draw"
    state._market = [{"card": "🐶", "coins": 2}]

    draw_action = choose_draw_action(state, "bot")
    if draw_action["action"] == "draw_card":
        state.draw_card("bot")
    else:
        state.pick_market("bot", draw_action["card_index"])

    assert state.turn_phase == "play"

    play_action = choose_play_action(state, "bot")
    if play_action["action"] == "play_to_market":
        state.play_to_market("bot", play_action["hand_index"])
    else:
        state.play_to_area("bot", play_action["hand_index"])

    assert state.turn_phase == "draw"
    assert state.current_player_id == "p1"
