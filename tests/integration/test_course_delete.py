"""
Course delete (spec docs/plans/course-delete.md §4.4): an admin can delete an
empty course; its roster and access rows go with it. A course with any game,
session (by the course it was played in) or image is refused with 409
COURSE_NOT_EMPTY, and nothing is deleted.
"""

from __future__ import annotations

import httpx

from . import t4_helpers
from .t4_helpers import T4World, add_question, assert_error, play_game, png, upload

t4 = t4_helpers.t4  # fixture


def delete_course(t4: T4World, course_id: int, token: str | None = None):
    return t4.request("DELETE", f"/admin/courses/{course_id}", token)


def assert_not_empty(r: httpx.Response, games: int, sessions: int, images: int):
    assert_error(r, 409, "COURSE_NOT_EMPTY")
    body = r.json()
    assert (body["games"], body["sessions"], body["images"]) == (
        games,
        sessions,
        images,
    ), body


def course_exists(t4: T4World, course_id: int) -> bool:
    return t4.request("GET", f"/admin/courses/{course_id}").status_code == 200


def test_delete_empty_course(t4: T4World):
    course = t4.course()
    r = delete_course(t4, course)
    assert r.status_code == 204, r.text
    assert t4.request("GET", f"/admin/courses/{course}").status_code == 404
    listed = t4.request("GET", "/admin/courses").json()
    assert course not in {c["id"] for c in listed}


def test_delete_cascades_roster_and_access(t4: T4World):
    course = t4.course()
    r = t4.request(
        "POST",
        f"/admin/courses/{course}/roster/import",
        json={
            "rows": [
                {
                    "netid": f"cd{t4.tag}{i}",
                    "full_name": f"Student {i}",
                    "email": f"cd{t4.tag}{i}@example.com",
                }
                for i in range(2)
            ]
        },
    )
    assert r.status_code == 200, r.text
    host = t4.user()
    t4.grant_course(host, course)
    mine = t4.request("GET", "/game/my-courses", host.token).json()
    assert course in {c["id"] for c in mine}

    r = delete_course(t4, course)
    assert r.status_code == 204, r.text
    mine = t4.request("GET", "/game/my-courses", host.token).json()
    assert course not in {c["id"] for c in mine}
    assert t4.request("GET", f"/admin/courses/{course}/roster").status_code == 404


def test_course_with_game_is_refused(t4: T4World):
    course = t4.course()
    t4.game(course)
    assert_not_empty(delete_course(t4, course), games=1, sessions=0, images=0)
    assert course_exists(t4, course)


async def test_course_with_session_of_moved_game_is_refused(t4: T4World):
    course_a, course_b = t4.course(), t4.course()
    game = t4.game(course_a)
    add_question(t4, game)
    await play_game(t4, game, course_a, t4.admin_token, choices=[0])
    r = t4.request(
        "POST",
        f"/admin/games/{game}/move",
        json={"course_id": course_b, "confirm": True},
    )
    assert r.status_code == 200, r.text

    assert_not_empty(delete_course(t4, course_a), games=0, sessions=1, images=0)
    assert course_exists(t4, course_a)


def test_course_with_image_is_refused(t4: T4World):
    course = t4.course()
    r = upload(t4, png(), course_id=course)
    assert r.status_code == 201, r.text
    assert_not_empty(delete_course(t4, course), games=0, sessions=0, images=1)
    assert course_exists(t4, course)


async def test_course_deletable_after_its_game_is_deleted(t4: T4World):
    course = t4.course()
    game = t4.game(course)
    add_question(t4, game)
    await play_game(t4, game, course, t4.admin_token, choices=[0])
    assert_not_empty(delete_course(t4, course), games=1, sessions=1, images=0)

    r = t4.request("DELETE", f"/admin/games/{game}")
    assert r.status_code == 204, r.text
    r = delete_course(t4, course)
    assert r.status_code == 204, r.text


def test_course_host_cannot_delete(t4: T4World):
    course = t4.course()
    host = t4.user()
    t4.grant_course(host, course)
    r = delete_course(t4, course, host.token)
    assert r.status_code == 403, r.text
    assert course_exists(t4, course)


def test_delete_missing_course(t4: T4World):
    assert delete_course(t4, 999999999).status_code == 404


def test_delete_requires_auth(t4: T4World):
    course = t4.course()
    r = httpx.delete(f"{t4.base_url}/api/admin/courses/{course}", timeout=10.0)
    assert r.status_code == 401, r.text
    assert course_exists(t4, course)
