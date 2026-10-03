"""
T4 results tests (spec §4.14): the host sessions list, CSV export and HTML
report. Sessions belong to the course they were played in.
"""

from __future__ import annotations

import csv
import io

from . import t4_helpers
from .t4_helpers import T4World, add_question, assert_error, play_game

t4 = t4_helpers.t4  # fixture


def host_of(t4: T4World, course_id: int):
    host = t4.user()
    t4.grant_course(host, course_id)
    return host


def sessions(t4: T4World, course_id: int, token: str, query: str = "") -> list[dict]:
    r = t4.request("GET", f"/host/courses/{course_id}/sessions{query}", token)
    assert r.status_code == 200, r.text
    return r.json()


async def test_host_downloads_results_of_completed_session(t4: T4World):
    course = t4.course()
    host, co_host = host_of(t4, course), host_of(t4, course)
    game = t4.game(course)
    add_question(t4, game)
    played = await play_game(t4, game, course, host.token, choices=[0, 1])

    listed = {s["session_id"]: s for s in sessions(t4, course, co_host.token)}
    item = listed[played.session_id]
    assert item["status"] == "COMPLETED"
    assert item["player_count"] == 2
    assert item["game_id"] == game and item["course_id"] == course
    assert item["host_display_name"] == host.username
    assert item["completed_at"] is not None

    # Any HOST of the session's course can download, not only the session host.
    r = t4.request("GET", f"/host/sessions/{played.session_id}/export", co_host.token)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    assert r.headers["content-disposition"].startswith("attachment; filename=")
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0] == ["Player", "Q1", "Total"]
    totals = {row[0]: float(row[-1]) for row in rows[1:]}
    assert totals == {played.player_names[0]: 1.0, played.player_names[1]: 0.0}

    r = t4.request("GET", f"/host/sessions/{played.session_id}/report", co_host.token)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/html")
    assert r.headers["content-disposition"].startswith("attachment; filename=")
    assert "<html" in r.text.lower()


def test_results_require_completed_session(t4: T4World):
    course = t4.course()
    host = host_of(t4, course)
    game = t4.game(course)
    r = t4.create_room(game, course, host.token)
    session_id = r.json()["session_id"]

    for kind in ("export", "report"):
        r = t4.request("GET", f"/host/sessions/{session_id}/{kind}", host.token)
        assert_error(r, 409, "SESSION_NOT_COMPLETED")
    assert_error(
        t4.request("GET", "/host/sessions/no-such-session/export", host.token),
        404,
        "NOT_FOUND",
    )


async def test_results_are_private_to_the_sessions_course(t4: T4World):
    course_a, course_b = t4.course(), t4.course()
    host_a, host_b = host_of(t4, course_a), host_of(t4, course_b)
    game = t4.game(course_a)
    add_question(t4, game)
    played = await play_game(t4, game, course_a, host_a.token, choices=[0])

    for kind in ("export", "report"):
        r = t4.request(
            "GET", f"/host/sessions/{played.session_id}/{kind}", host_b.token
        )
        assert_error(r, 403, "FORBIDDEN")
    assert_error(
        t4.request("GET", f"/host/courses/{course_a}/sessions", host_b.token),
        403,
        "FORBIDDEN",
    )

    # Moving the game does not move its old sessions' results.
    r = t4.request(
        "POST",
        f"/admin/games/{game}/move",
        json={"course_id": course_b, "confirm": True},
    )
    assert r.status_code == 200, r.text
    assert played.session_id not in {
        s["session_id"] for s in sessions(t4, course_b, host_b.token)
    }
    assert_error(
        t4.request("GET", f"/host/sessions/{played.session_id}/export", host_b.token),
        403,
        "FORBIDDEN",
    )
    r = t4.request("GET", f"/host/sessions/{played.session_id}/export", host_a.token)
    assert r.status_code == 200, r.text


async def test_restricted_game_results_need_a_grant(t4: T4World):
    course = t4.course()
    host, granted = host_of(t4, course), host_of(t4, course)
    game = t4.game(course, restricted=True)
    t4.grant_game(granted, game)
    add_question(t4, game)
    played = await play_game(t4, game, course, t4.admin_token, choices=[0])

    assert played.session_id not in {
        s["session_id"] for s in sessions(t4, course, host.token)
    }
    for kind in ("export", "report"):
        r = t4.request("GET", f"/host/sessions/{played.session_id}/{kind}", host.token)
        assert_error(r, 403, "GAME_RESTRICTED")

    assert played.session_id in {
        s["session_id"] for s in sessions(t4, course, granted.token)
    }
    r = t4.request("GET", f"/host/sessions/{played.session_id}/export", granted.token)
    assert r.status_code == 200, r.text


async def test_sessions_status_filter(t4: T4World):
    course = t4.course()
    host = host_of(t4, course)
    game = t4.game(course)
    add_question(t4, game)
    completed = await play_game(t4, game, course, host.token, choices=[0])
    lobby = t4.create_room(game, course, host.token).json()["session_id"]

    only_completed = sessions(t4, course, host.token, "?status=COMPLETED")
    assert {s["session_id"] for s in only_completed} == {completed.session_id}
    everything = sessions(t4, course, host.token)
    assert {s["session_id"] for s in everything} == {lobby, completed.session_id}
    # Newest first. created_at has 1 s resolution, so equal timestamps may tie.
    created = [s["created_at"] for s in everything]
    assert created == sorted(created, reverse=True)
    assert_error(
        t4.request("GET", f"/host/courses/{course}/sessions?status=bogus", host.token),
        422,
        "VALIDATION_ERROR",
    )
