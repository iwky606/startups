"""Server-side bot policy."""

from .state import GameState


def _best_other_area_count(gs: GameState, player_id: str, card_type: str) -> int:
    return max(
        gs._areas[other_id][card_type]
        for other_id in gs._player_ids
        if other_id != player_id
    )


def _score_market_pick(gs: GameState, player_id: str, market_index: int) -> int:
    slot = gs._market[market_index]
    card_type = slot["card"]
    coins = slot["coins"]
    my_area = gs._areas[player_id][card_type]
    my_hand = gs._hands[player_id].count(card_type)
    other_best = _best_other_area_count(gs, player_id, card_type)
    current_major = gs._major_shareholders[card_type]

    score = coins * 4 + my_area * 5 + my_hand * 3
    if current_major is None and my_area + my_hand >= 1:
        score += 4
    elif current_major != player_id and my_area + 1 > other_best:
        score += 6
    elif current_major == player_id:
        score -= 4
    return score


def choose_draw_action(gs: GameState, player_id: str) -> dict:
    actions = gs.get_playable_actions(player_id)
    pickable = list(actions.get("can_pick_market", []))
    can_draw = bool(actions.get("can_draw"))

    if pickable:
        best_index = max(pickable, key=lambda idx: _score_market_pick(gs, player_id, idx))
        best_score = _score_market_pick(gs, player_id, best_index)
    else:
        best_index = None
        best_score = -10**9

    draw_cost = gs.get_draw_cost(player_id)
    draw_score = 5 - draw_cost
    if gs._deck.remaining <= 5:
        draw_score -= 2

    if best_index is not None and (not can_draw or best_score >= draw_score + 2):
        return {"action": "pick_market", "card_index": best_index}
    if can_draw:
        return {"action": "draw_card"}
    if best_index is not None:
        return {"action": "pick_market", "card_index": best_index}
    raise ValueError("bot 在 draw 阶段没有可执行动作")


def _score_play_to_area(gs: GameState, player_id: str, hand_index: int) -> int:
    card_type = gs._hands[player_id][hand_index]
    my_after = gs._areas[player_id][card_type] + 1
    other_best = _best_other_area_count(gs, player_id, card_type)
    current_major = gs._major_shareholders[card_type]
    same_in_hand = gs._hands[player_id].count(card_type)

    score = my_after * 2 + same_in_hand
    if current_major == player_id:
        score += 8
    elif my_after > other_best:
        score += 10
    elif my_after == other_best and current_major != player_id:
        score += 4
    return score


def _score_play_to_market(gs: GameState, player_id: str, hand_index: int) -> int:
    card_type = gs._hands[player_id][hand_index]
    if card_type == gs._turn_context.get("picked_from_market"):
        return -10**9

    current_major = gs._major_shareholders[card_type]
    same_in_market = sum(1 for slot in gs._market if slot["card"] == card_type)
    same_in_hand = gs._hands[player_id].count(card_type)

    score = same_in_market * 2
    if current_major == player_id:
        score += 8
    elif gs._areas[player_id][card_type] == 0 and same_in_hand == 1:
        score += 3
    return score


def choose_play_action(gs: GameState, player_id: str) -> dict:
    actions = gs.get_playable_actions(player_id)
    can_area = set(actions.get("can_play_to_area", []))
    can_market = set(actions.get("can_play_to_market", []))

    best_action = None
    best_score = -10**9

    for hand_index in can_area:
        score = _score_play_to_area(gs, player_id, hand_index)
        if score > best_score:
            best_score = score
            best_action = {"action": "play_to_area", "hand_index": hand_index}

    for hand_index in can_market:
        score = _score_play_to_market(gs, player_id, hand_index)
        if score > best_score:
            best_score = score
            best_action = {"action": "play_to_market", "hand_index": hand_index}

    if best_action is not None:
        return best_action
    if gs._hands[player_id]:
        return {"action": "play_to_area", "hand_index": 0}
    raise ValueError("bot 在 play 阶段没有可执行动作")
