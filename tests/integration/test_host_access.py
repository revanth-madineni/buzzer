"""
T4 access tests (spec §4.14): who may create rooms for which games, what
my-games shows, attach-on-first-room, and which players may join a room.
"""

from __future__ import annotations

import asyncio

import pytest

from . import t4_helpers
from .t4_helpers import T4World, assert_error, join_as

t4 = t4_helpers.t4  # fixture

NOT_ENROLLED = "You are not enrolled in the course roster for this game"


# ---------------------------------------------------------------------------
# Course-specific rooms
# ---------------------------------------------------------------------------


def test_host_runs_own_course_game_and_sees_it(t4: T4World):
    course_a, course_b = t4.course(), t4.course()
    game_a, game_b = t4.game(course_a), t4.game(course_b)
    courseless = t4.game()
    host = t4.user()
    t4.grant_course(host, course_a)

    r = t4.create_room(game_a, course_a, host.token)
    assert r.status_code == 201, r.text

    mine = t4.my_game_ids(host.token)
    assert game_a in mine
    assert game_b not in mine
    assert courseless not in mine


def test_room_for_game_from_another_course_is_course_mismatch(t4: T4World):
    course_a, course_b = t4.course(), t4.course()
    game_a = t4.game(course_a)
    host = t4.user()
    t4.grant_course(host, course_a)
    t4.grant_course(host, course_b)

    assert_error(t4.create_room(game_a, course_b, host.token), 422, "COURSE_MISMATCH")
    # Admins get the same rule once the game has a course.
    assert_error(t4.create_room(game_a, course_b), 422, "COURSE_MISMATCH")


def test_room_requires_course_host(t4: T4World):
    course_a = t4.course()
    game_a = t4.game(course_a)
    outsider = t4.user()
    grant_only = t4.user()
    t4.grant_game(grant_only, game_a)
    player = t4.user("t4_player")
    t4.grant_course(player, course_a, "PLAYER")

    for user in (outsider, grant_only, player):
        assert_error(t4.create_room(game_a, course_a, user.token), 403, "FORBIDDEN")
        assert game_a not in t4.my_game_ids(user.token)


def test_guest_cannot_create_rooms_or_list_games(t4: T4World):
    course_a = t4.course()
    game_a = t4.game(course_a)
    room = t4.create_room(game_a, course_a)
    assert room.status_code == 201, room.text
    guest = t4.guest_token(room.json()["room_code"])

    assert_error(t4.create_room(game_a, course_a, guest), 403, "FORBIDDEN")
    assert_error(t4.request("GET", "/game/my-games", guest), 403, "FORBIDDEN")


def test_nonexistent_course_or_game_is_not_found(t4: T4World):
    course_a = t4.course()
    game_a = t4.game(course_a)
    host = t4.user()
    t4.grant_course(host, course_a)

    assert_error(t4.create_room(game_a, 2_000_000_000, host.token), 404, "NOT_FOUND")
    assert_error(t4.create_room(2_000_000_000, course_a, host.token), 404, "NOT_FOUND")


# ---------------------------------------------------------------------------
# Attach on first room
# ---------------------------------------------------------------------------


def test_courseless_game_is_attached_by_first_admin_room(t4: T4World):
    course_a, course_b = t4.course(), t4.course()
    game = t4.game()
    assert t4.get_game(game)["course_id"] is None

    r = t4.create_room(game, course_a)
    assert r.status_code == 201, r.text
    assert t4.get_game(game)["course_id"] == course_a

    assert_error(t4.create_room(game, course_b), 422, "COURSE_MISMATCH")
    assert t4.get_game(game)["course_id"] == course_a


def test_nonexistent_course_leaves_game_courseless(t4: T4World):
    game = t4.game()
    assert_error(t4.create_room(game, 2_000_000_000), 404, "NOT_FOUND")
    assert t4.get_game(game)["course_id"] is None


def test_non_admin_cannot_see_or_run_courseless_game(t4: T4World):
    course_a = t4.course()
    game = t4.game()
    host = t4.user()
    t4.grant_course(host, course_a)
    t4.grant_game(host, game)  # a grant does not make a courseless game usable

    assert game not in t4.my_game_ids(host.token)
    assert_error(t4.create_room(game, course_a, host.token), 404, "NOT_FOUND")
    assert t4.get_game(game)["course_id"] is None


# ---------------------------------------------------------------------------
# Player access (unchanged code, newly guaranteed meaning — §4.4)
# ---------------------------------------------------------------------------


async def test_only_players_of_the_rooms_course_can_join(t4: T4World, base_url: str):
    course_a, course_b = t4.course(), t4.course()
    game_a = t4.game(course_a)
    room = t4.create_room(game_a, course_a)
    assert room.status_code == 201, room.text
    code = room.json()["room_code"]

    stranger = t4.user("t4_player")
    other_course_player = t4.user("t4_player")
    t4.grant_course(other_course_player, course_b, "PLAYER")
    enrolled = t4.user("t4_player")
    t4.grant_course(enrolled, course_a, "PLAYER")

    clients = []
    try:
        host, outcome, _ = await join_as(base_url, t4.admin_token, code, "HOST", "host")
        clients.append(host)
        assert outcome == "sync_state"

        for user in (stranger, other_course_player):
            client, outcome, payload = await join_as(
                base_url, user.token, code, "PLAYER", user.username
            )
            clients.append(client)
            assert outcome == "error", payload
            assert payload["message"] == NOT_ENROLLED

        client, outcome, payload = await join_as(
            base_url, enrolled.token, code, "PLAYER", enrolled.username
        )
        clients.append(client)
        assert outcome == "sync_state", payload

        joined = await host.wait_for("player_joined")
        assert joined["userId"] == enrolled.id
        assert joined["playerCount"] == 1
        with pytest.raises(asyncio.TimeoutError):
            await host.wait_for("player_joined", timeout=1.0)
    finally:
        for client in clients:
            await client.disconnect()
