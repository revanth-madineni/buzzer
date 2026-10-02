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


# ---------------------------------------------------------------------------
# Restricted games
# ---------------------------------------------------------------------------


def test_restricted_game_needs_a_grant(t4: T4World):
    course_a = t4.course()
    game = t4.game(course_a, restricted=True)
    host = t4.user()
    t4.grant_course(host, course_a)

    assert game not in t4.my_game_ids(host.token)
    assert_error(t4.create_room(game, course_a, host.token), 403, "GAME_RESTRICTED")

    t4.grant_game(host, game)
    assert game in t4.my_game_ids(host.token)
    assert t4.create_room(game, course_a, host.token).status_code == 201

    # Un-restricting opens it to every HOST of the course.
    co_host = t4.user()
    t4.grant_course(co_host, course_a)
    assert game not in t4.my_game_ids(co_host.token)
    t4.set_restricted(game, False)
    assert game in t4.my_game_ids(co_host.token)


def test_grant_without_course_host_is_forbidden_not_restricted(t4: T4World):
    course_a = t4.course()
    game = t4.game(course_a, restricted=True)
    grant_only = t4.user()
    t4.grant_game(grant_only, game)

    assert game not in t4.my_game_ids(grant_only.token)
    assert_error(t4.create_room(game, course_a, grant_only.token), 403, "FORBIDDEN")


def test_admin_runs_restricted_game_without_grant(t4: T4World):
    course_a = t4.course()
    game = t4.game(course_a, restricted=True)
    assert t4.create_room(game, course_a).status_code == 201


# ---------------------------------------------------------------------------
# Admin: create in a course, assign / move, access lists
# ---------------------------------------------------------------------------


def test_admin_create_game_in_course(t4: T4World):
    course_a = t4.course()
    game = t4.game(course_a)
    assert t4.get_game(game)["course_id"] == course_a
    assert t4.get_game(game)["restricted"] is False

    r = t4.request(
        "POST", "/admin/games", json={"title": "x", "course_id": 2_000_000_000}
    )
    assert_error(r, 404, "NOT_FOUND")


def test_move_reports_then_drops_grants_that_stop_working(t4: T4World):
    course_a, course_b = t4.course(), t4.course()
    game = t4.game(course_a, restricted=True)
    keeps = t4.user()  # HOST on both courses
    t4.grant_course(keeps, course_a)
    t4.grant_course(keeps, course_b)
    loses = t4.user()  # HOST on A only
    t4.grant_course(loses, course_a)
    for user in (keeps, loses):
        t4.grant_game(user, game)

    old = t4.create_room(game, course_a)
    assert old.status_code == 201, old.text
    old_session = old.json()["session_id"]

    def holders() -> dict[str, bool]:
        r = t4.request("GET", f"/admin/games/{game}/access")
        assert r.status_code == 200, r.text
        return {e["user_id"]: e["has_course_host"] for e in r.json()}

    assert holders() == {keeps.id: True, loses.id: True}

    r = t4.request("POST", f"/admin/games/{game}/move", json={"course_id": course_b})
    assert r.status_code == 200, r.text
    preview = r.json()
    assert preview["applied"] is False
    assert [e["user_id"] for e in preview["dropped_grants"]] == [loses.id]
    assert preview["game"]["course_id"] == course_a
    assert t4.get_game(game)["course_id"] == course_a
    assert holders() == {keeps.id: True, loses.id: True}

    r = t4.request(
        "POST",
        f"/admin/games/{game}/move",
        json={"course_id": course_b, "confirm": True},
    )
    assert r.status_code == 200, r.text
    moved = r.json()
    assert moved["applied"] is True
    assert [e["user_id"] for e in moved["dropped_grants"]] == [loses.id]
    assert moved["game"]["course_id"] == course_b
    assert moved["game"]["restricted"] is True  # a move never changes restricted

    assert t4.get_game(game)["course_id"] == course_b
    assert holders() == {keeps.id: True}
    assert t4.admin_session(old_session)["course_id"] == course_a
    assert game in t4.my_game_ids(keeps.token)
    assert game not in t4.my_game_ids(loses.token)


def test_move_assigns_courseless_game_and_validates_target(t4: T4World):
    course_a = t4.course()
    game = t4.game()

    r = t4.request("POST", f"/admin/games/{game}/move", json={"course_id": None})
    assert_error(r, 422, "VALIDATION_ERROR")
    r = t4.request(
        "POST", f"/admin/games/{game}/move", json={"course_id": 2_000_000_000}
    )
    assert_error(r, 404, "NOT_FOUND")
    r = t4.request("POST", "/admin/games/2000000000/move", json={"course_id": course_a})
    assert_error(r, 404, "NOT_FOUND")
    assert t4.get_game(game)["course_id"] is None

    r = t4.request(
        "POST",
        f"/admin/games/{game}/move",
        json={"course_id": course_a, "confirm": True},
    )
    assert r.status_code == 200, r.text
    assert r.json()["dropped_grants"] == []
    assert t4.get_game(game)["course_id"] == course_a


def test_access_lists(t4: T4World):
    course_a = t4.course()
    game = t4.game(course_a)
    host, player, outsider = t4.user(), t4.user("t4_player"), t4.user()
    t4.grant_course(host, course_a, "HOST")
    t4.grant_course(player, course_a, "PLAYER")
    t4.grant_game(host, game)
    t4.grant_game(outsider, game)

    r = t4.request("GET", f"/admin/courses/{course_a}/access")
    assert r.status_code == 200, r.text
    entries = {e["user_id"]: e for e in r.json()}
    assert {uid: e["role"] for uid, e in entries.items()} == {
        host.id: "HOST",
        player.id: "PLAYER",
    }
    assert entries[host.id]["username"] == host.username

    r = t4.request("GET", f"/admin/games/{game}/access")
    assert r.status_code == 200, r.text
    assert {e["user_id"]: e["has_course_host"] for e in r.json()} == {
        host.id: True,
        outsider.id: False,
    }

    assert_error(
        t4.request("GET", "/admin/courses/2000000000/access"), 404, "NOT_FOUND"
    )
    assert_error(t4.request("GET", "/admin/games/2000000000/access"), 404, "NOT_FOUND")
    assert_error(
        t4.request("GET", f"/admin/games/{game}/access", host.token), 403, "FORBIDDEN"
    )
