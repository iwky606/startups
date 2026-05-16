from server.room_manager import RoomManager


def test_create_room_auto_fills_bots_to_min_players():
    manager = RoomManager()

    room = manager.create_room("host", "Host", ws=object(), remove_count=5)

    assert len(room.players) == 1
    assert list(room.players) == ["host"]


def test_host_can_add_and_remove_bots():
    manager = RoomManager()
    room = manager.create_room("host", "Host", ws=object(), remove_count=5)

    manager.add_bot("host")
    manager.add_bot("host")
    assert len(room.players) == 3
    assert sum(1 for info in room.players.values() if info.is_bot) == 2

    manager.remove_bot("host")
    assert len(room.players) == 2
    assert sum(1 for info in room.players.values() if info.is_bot) == 1


def test_remove_bot_requires_existing_bot():
    manager = RoomManager()
    manager.create_room("host", "Host", ws=object(), remove_count=5)

    try:
        manager.remove_bot("host")
    except ValueError as exc:
        assert "人机" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_start_game_passes_bot_metadata_into_state():
    manager = RoomManager()
    room = manager.create_room("host", "Host", ws=object(), remove_count=5)
    manager.add_bot("host")
    manager.add_bot("host")

    room = manager.start_game("host")
    bot_id = next(pid for pid, info in room.players.items() if info.is_bot)
    bot_state = next(player for player in room.game_state.get_state_for_player("host")["players"] if player["id"] == bot_id)

    assert bot_state["is_bot"] is True


def test_ended_game_lobby_rejoin_replaces_existing_connection():
    manager = RoomManager()
    host_old_ws = object()
    host_new_ws = object()
    guest_old_ws = object()
    guest_new_ws = object()
    room = manager.create_room("host", "Host", ws=host_old_ws, remove_count=5)
    manager.join_room(room.room_code, "guest", "Guest", guest_old_ws)
    manager.add_bot("host")
    room.players["guest"].is_ready = True
    manager.start_game("host")
    room.game_state._phase = "ended"

    player_id = manager.rejoin_lobby(room.room_code, "Host", host_new_ws)
    guest_id = manager.rejoin_lobby(room.room_code, "Guest", guest_new_ws)

    assert player_id == "host"
    assert guest_id == "guest"
    assert room.game_state is None
    assert room.is_post_game_lobby is True
    assert room.players["host"].ws is host_new_ws
    assert room.players["guest"].ws is guest_new_ws
    assert manager.owns_connection("host", host_old_ws) is False
    assert manager.owns_connection("host", host_new_ws) is True
    assert manager.owns_connection("guest", guest_old_ws) is False
    assert manager.owns_connection("guest", guest_new_ws) is True


def test_seats_preserve_gaps_and_start_game_uses_seat_order():
    manager = RoomManager()
    room = manager.create_room("host", "Host", ws=object(), remove_count=5)
    manager.join_room(room.room_code, "p2", "P2", object())
    manager.join_room(room.room_code, "p3", "P3", object())
    manager.request_seat_move("p3", 5)
    room.players["p2"].is_ready = True
    room.players["p3"].is_ready = True

    manager.start_game("host")

    assert room.seats[:6] == ["host", "p2", None, None, None, "p3"]
    assert room.game_state._player_ids == ["host", "p2", "p3"]
    assert room.game_state.current_player_id == "host"


def test_start_game_rejects_remove_count_that_leaves_too_few_cards():
    manager = RoomManager()
    room = manager.create_room("host", "Host", ws=object(), remove_count=5)
    manager.join_room(room.room_code, "p2", "P2", object())
    manager.join_room(room.room_code, "p3", "P3", object())
    room.players["p2"].is_ready = True
    room.players["p3"].is_ready = True
    manager.update_remove_count("host", 34)

    try:
        manager.start_game("host")
    except ValueError as exc:
        assert "牌数不足" in str(exc)
    else:
        raise AssertionError("expected ValueError")

    manager.update_remove_count("host", 33)
    manager.start_game("host")
    assert room.game_state.current_player_id == "host"


def test_host_and_seat_order_survive_post_game_lobby_rejoin():
    manager = RoomManager()
    room = manager.create_room("host", "Host", ws=object(), remove_count=5)
    manager.join_room(room.room_code, "guest", "Guest", object())
    manager.add_bot("host")
    manager.request_seat_move("guest", 4)
    original_seats = list(room.seats)
    room.players["guest"].is_ready = True
    manager.start_game("host")
    room.game_state._phase = "ended"

    manager.rejoin_lobby(room.room_code, "Guest", object())
    manager.rejoin_lobby(room.room_code, "Host", object())

    assert room.host_id == "host"
    assert room.seats == original_seats
    assert room.player_list()[0]["id"] == "host"
    assert room.player_list()[1]["id"] == next(pid for pid in original_seats if pid and pid.startswith("bot-"))
    assert room.player_list()[2]["id"] == "guest"


def test_human_seat_swap_requires_acceptance():
    manager = RoomManager()
    room = manager.create_room("host", "Host", ws=object(), remove_count=5)
    manager.join_room(room.room_code, "guest", "Guest", object())

    room, target_id = manager.request_seat_move("host", 1)

    assert target_id == "guest"
    assert room.seats[:2] == ["host", "guest"]

    room, requester_id = manager.respond_seat_swap("guest", True)

    assert requester_id == "host"
    assert room.seats[:2] == ["guest", "host"]
