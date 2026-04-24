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
