"""
T4 management tests (spec §4.14): questions and rosters through the shared
services (question_service, roster_service). Admin paths must behave exactly as
before the extraction; host paths are added with the host router.
"""

from __future__ import annotations

import json

from . import t4_helpers
from .t4_helpers import T4World, assert_error

t4 = t4_helpers.t4  # fixture

MC_QUESTION = {
    "type": "multiple_choice",
    "grading_type": "ACCURACY",
    "config": {"options": ["A", "B"]},
    "answer_data": {"answer_points": [1, 0]},
    "points_value": 1,
}


def question_ids(t4: T4World, prefix: str, game_id: int, token: str | None = None):
    r = t4.request("GET", f"{prefix}/games/{game_id}/questions", token)
    assert r.status_code == 200, r.text
    return [q["id"] for q in r.json()]


# ---------------------------------------------------------------------------
# Questions
# ---------------------------------------------------------------------------


def test_admin_question_round_trip_and_sanitizing(t4: T4World):
    game = t4.game()
    base = f"/admin/games/{game}/questions"

    r = t4.request(
        "POST",
        base,
        json={**MC_QUESTION, "prompt": "<script>alert(1)</script><b>Bold</b> one"},
    )
    assert r.status_code == 201, r.text
    q1 = r.json()
    assert "<script" not in q1["prompt"]
    assert "<b>Bold</b> one" in q1["prompt"]
    assert q1["order_index"] == 0

    r = t4.request("POST", base, json={**MC_QUESTION, "prompt": "two"})
    assert r.status_code == 201, r.text
    q2 = r.json()
    assert q2["order_index"] == 1

    # Partial update: only sent, non-null fields change; prompt is sanitized.
    r = t4.request(
        "PUT",
        f"{base}/{q1['id']}",
        json={"prompt": '<img src=x onerror="alert(1)">safe', "points_value": 5},
    )
    assert r.status_code == 200, r.text
    updated = r.json()
    assert updated["prompt"] == "safe"
    assert updated["points_value"] == 5
    assert updated["config"] == MC_QUESTION["config"]

    r = t4.request("POST", f"{base}/reorder", json={"order": [q2["id"], q1["id"]]})
    assert r.status_code == 204, r.text
    assert question_ids(t4, "/admin", game) == [q2["id"], q1["id"]]

    # Invalid reorder keeps today's generic 409 CONFLICT (INVALID_ORDER is [Extra]).
    r = t4.request("POST", f"{base}/reorder", json={"order": [q2["id"]]})
    assert_error(r, 409, "CONFLICT")
    assert question_ids(t4, "/admin", game) == [q2["id"], q1["id"]]

    r = t4.request("DELETE", f"{base}/{q1['id']}")
    assert r.status_code == 204, r.text
    assert question_ids(t4, "/admin", game) == [q2["id"]]


def test_admin_question_in_another_game_is_not_found(t4: T4World):
    game_a, game_b = t4.game(), t4.game()
    r = t4.request(
        "POST", f"/admin/games/{game_a}/questions", json={**MC_QUESTION, "prompt": "q"}
    )
    assert r.status_code == 201, r.text
    qid = r.json()["id"]

    r = t4.request(
        "PUT", f"/admin/games/{game_b}/questions/{qid}", json={"prompt": "x"}
    )
    assert_error(r, 404, "NOT_FOUND")
    r = t4.request("DELETE", f"/admin/games/{game_b}/questions/{qid}")
    assert_error(r, 404, "NOT_FOUND")


# ---------------------------------------------------------------------------
# Roster (admin upload is mode=replace)
# ---------------------------------------------------------------------------


def gradebook_csv(netids: list[str], extra_rows: str = "") -> bytes:
    lines = ["Student,ID,SIS User ID,SIS Login ID,Section"]
    lines.append("Points Possible,,,,")
    for i, netid in enumerate(netids):
        lines.append(f'"Last{i}, First{i}",{i},{i},{netid}@wisc.edu,S1')
    return ("\n".join(lines) + "\n" + extra_rows).encode()


def upload(t4: T4World, course_id: int, content: bytes):
    return t4.request(
        "POST",
        f"/admin/courses/{course_id}/roster",
        files={"file": ("roster.csv", content, "text/csv")},
    )


def roster_state(t4: T4World, course_id: int) -> dict[str, bool]:
    r = t4.request("GET", f"/admin/courses/{course_id}/roster")
    assert r.status_code == 200, r.text
    return {e["netid"]: e["is_active"] for e in r.json()}


def test_admin_roster_replace_deactivates_missing_entries(t4: T4World):
    course = t4.course()
    n = [f"t4n{t4.tag}{i}" for i in range(3)]

    r = upload(t4, course, gradebook_csv(n))
    assert r.status_code == 200, r.text
    assert r.json() == {"imported": 3, "updated": 0, "deactivated": 0, "errors": []}

    r = upload(t4, course, gradebook_csv(n[:2]))
    assert r.status_code == 200, r.text
    assert r.json()["deactivated"] == 1
    assert roster_state(t4, course) == {n[0]: True, n[1]: True, n[2]: False}

    # Re-listing a deactivated entry reactivates it.
    r = upload(t4, course, gradebook_csv(n))
    assert r.status_code == 200, r.text
    assert roster_state(t4, course) == {n[0]: True, n[1]: True, n[2]: True}


def test_admin_roster_upload_with_no_valid_rows_changes_nothing(t4: T4World):
    """The `if seen_netids` guard (spec §4.5): no valid rows must not wipe the roster."""
    course = t4.course()
    n = [f"t4n{t4.tag}{i}" for i in range(2)]
    assert upload(t4, course, gradebook_csv(n)).status_code == 200
    before = roster_state(t4, course)

    only_bad_rows = gradebook_csv([], extra_rows='"Nobody, Here",9,9,,S1\n')
    only_points_possible = gradebook_csv([])
    for content in (only_bad_rows, only_points_possible):
        r = upload(t4, course, content)
        assert r.status_code == 200, r.text
        body = r.json()
        assert (body["imported"], body["updated"], body["deactivated"]) == (0, 0, 0)
        assert roster_state(t4, course) == before
    assert body["errors"] == []  # Points Possible alone is skipped, not an error
    assert upload(t4, course, only_bad_rows).json()["errors"]


def test_admin_roster_without_required_columns_changes_nothing(t4: T4World):
    course = t4.course()
    n = [f"t4n{t4.tag}{i}" for i in range(2)]
    assert upload(t4, course, gradebook_csv(n)).status_code == 200
    before = roster_state(t4, course)

    r = upload(t4, course, b"Name,Email\nSomeone,someone@wisc.edu\n")
    assert r.status_code == 200, r.text
    assert r.json()["errors"][0].startswith("Missing required columns")
    assert roster_state(t4, course) == before


# ---------------------------------------------------------------------------
# Admin: courses (allow_guests) and game import (course_id form field)
# ---------------------------------------------------------------------------


def test_admin_course_allow_guests(t4: T4World):
    course = t4.course()
    r = t4.request("GET", f"/admin/courses/{course}")
    assert r.status_code == 200, r.text
    assert r.json()["allow_guests"] is True

    r = t4.request("PUT", f"/admin/courses/{course}", json={"allow_guests": False})
    assert r.status_code == 200, r.text
    assert t4.request("GET", f"/admin/courses/{course}").json()["allow_guests"] is False

    r = t4.request(
        "POST",
        "/admin/courses",
        json={"name": f"T4 Course {t4.tag}ng", "semester": "T4", "allow_guests": False},
    )
    assert r.status_code == 201, r.text
    assert r.json()["allow_guests"] is False


def bundle(game: dict) -> bytes:
    return json.dumps(
        {
            "format": "buzzer/game",
            "version": 1,
            "game": game,
            "questions": [
                {**MC_QUESTION, "prompt": "<script>x</script>imported"},
            ],
        }
    ).encode()


def import_game(t4: T4World, content: bytes, course_id: int | None = None):
    data = {} if course_id is None else {"course_id": str(course_id)}
    return t4.request(
        "POST",
        "/admin/games/import",
        files={"file": ("game.json", content, "application/json")},
        data=data,
    )


def test_admin_import_attaches_course_from_form_field(t4: T4World):
    course = t4.course()
    r = import_game(t4, bundle({"title": f"T4 Import {t4.tag}"}), course)
    assert r.status_code == 201, r.text
    game = r.json()["game_id"]
    t4.track_game(game)
    assert t4.get_game(game)["course_id"] == course
    prompts = [
        q["prompt"] for q in t4.request("GET", f"/admin/games/{game}/questions").json()
    ]
    assert prompts == ["ximported"]

    r = import_game(t4, bundle({"title": f"T4 Import {t4.tag}b"}))
    assert r.status_code == 201, r.text
    t4.track_game(r.json()["game_id"])
    assert t4.get_game(r.json()["game_id"])["course_id"] is None


def test_admin_import_rejects_unknown_course_and_bundle_course_id(t4: T4World):
    def titles() -> set[str]:
        return {g["title"] for g in t4.request("GET", "/admin/games").json()}

    title = f"T4 Import {t4.tag}x"
    assert_error(
        import_game(t4, bundle({"title": title}), 2_000_000_000), 404, "NOT_FOUND"
    )
    r = import_game(t4, bundle({"title": title, "course_id": t4.course()}))
    assert r.status_code == 422, r.text
    assert title not in titles()


# ---------------------------------------------------------------------------
# Host: games and questions
# ---------------------------------------------------------------------------


def host_of(t4: T4World, course_id: int):
    host = t4.user()
    t4.grant_course(host, course_id)
    return host


def test_host_creates_game_in_path_course(t4: T4World):
    course = t4.course()
    host = host_of(t4, course)

    r = t4.request(
        "POST",
        f"/host/courses/{course}/games",
        host.token,
        json={"title": f"T4 Host Game {t4.tag}", "description": "d"},
    )
    assert r.status_code == 201, r.text
    game = r.json()
    t4.track_game(game["id"])
    assert game["course_id"] == course
    assert game["restricted"] is False
    assert t4.get_game(game["id"])["course_id"] == course

    # Hosts cannot choose the course or restrict through the body.
    r = t4.request(
        "POST",
        f"/host/courses/{course}/games",
        host.token,
        json={"title": "x", "course_id": course},
    )
    assert_error(r, 422, "VALIDATION_ERROR")
    r = t4.request(
        "PUT", f"/host/games/{game['id']}", host.token, json={"restricted": True}
    )
    assert_error(r, 422, "VALIDATION_ERROR")
    assert t4.get_game(game["id"])["restricted"] is False

    # The game is usable by its creator right away.
    assert game["id"] in t4.my_game_ids(host.token)
    assert t4.create_room(game["id"], course, host.token).status_code == 201


def test_host_question_crud_reorder_and_count(t4: T4World):
    course = t4.course()
    host = host_of(t4, course)
    game = t4.game(course)
    base = f"/host/games/{game}/questions"

    r = t4.request(
        "POST",
        base,
        host.token,
        json={**MC_QUESTION, "prompt": "<script>alert(1)</script><i>one</i>"},
    )
    assert r.status_code == 201, r.text
    q1 = r.json()
    assert q1["prompt"] == "alert(1)<i>one</i>"
    assert q1["answer_data"] == MC_QUESTION["answer_data"]  # hosts edit scoring

    r = t4.request("POST", base, host.token, json={**MC_QUESTION, "prompt": "two"})
    assert r.status_code == 201, r.text
    q2 = r.json()

    r = t4.request(
        "PUT",
        f"{base}/{q1['id']}",
        host.token,
        json={
            "prompt": "<script>x</script>edited",
            "answer_data": {"answer_points": [0, 1]},
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["prompt"] == "xedited"
    assert r.json()["answer_data"] == {"answer_points": [0, 1]}

    r = t4.request(
        "POST", f"{base}/reorder", host.token, json={"order": [q2["id"], q1["id"]]}
    )
    assert r.status_code == 204, r.text
    assert question_ids(t4, "/host", game, host.token) == [q2["id"], q1["id"]]

    r = t4.request("GET", f"/host/courses/{course}/games", host.token)
    assert {g["id"]: g["question_count"] for g in r.json()} == {game: 2}

    r = t4.request("DELETE", f"{base}/{q1['id']}", host.token)
    assert r.status_code == 204, r.text
    assert question_ids(t4, "/host", game, host.token) == [q2["id"]]


def test_host_question_from_another_game_is_not_found(t4: T4World):
    course = t4.course()
    host = host_of(t4, course)
    game_a, game_b = t4.game(course), t4.game(course)
    r = t4.request(
        "POST",
        f"/host/games/{game_a}/questions",
        host.token,
        json={**MC_QUESTION, "prompt": "q"},
    )
    qid = r.json()["id"]

    for method, body in (("PUT", {"prompt": "x"}), ("DELETE", None)):
        r = t4.request(
            method, f"/host/games/{game_b}/questions/{qid}", host.token, json=body
        )
        assert_error(r, 404, "NOT_FOUND")
    assert question_ids(t4, "/host", game_a, host.token) == [qid]
