"""
game_over payload tests.

maxPossibleScore used to be int()-truncated, so a game whose point values sum to
a non-integer reported a ceiling below the scores players could actually reach.
"""

from __future__ import annotations

from . import t4_helpers
from .engine.socket_client import TestSocketClient as SocketClient
from .t4_helpers import T4World

t4 = t4_helpers.t4  # fixture


def _mc(points: float) -> dict:
    return {
        **t4_helpers.MC_QUESTION,
        "answer_data": {"answer_points": [points, 0]},
        "points_value": points,
    }


async def test_max_possible_score_keeps_fractional_points(t4: T4World):
    course = t4.course()
    game = t4.game(course)
    for points in (7.5, 1.25):
        r = t4.request("POST", f"/admin/games/{game}/questions", json=_mc(points))
        assert r.status_code == 201, r.text

    r = t4.create_room(game, course)
    assert r.status_code == 201, r.text
    room_code = r.json()["room_code"]
    host = SocketClient(t4.base_url, t4.admin_token, "host")
    player = SocketClient(t4.base_url, t4.guest_token(room_code), "p0")
    try:
        await host.connect()
        await host.emit("join_room", {"room_code": room_code, "role": "HOST"})
        await host.wait_for("sync_state")
        await player.connect()
        await player.emit("join_room", {"room_code": room_code, "role": "PLAYER"})
        await host.wait_for("player_joined")

        for _ in range(2):
            await host.emit("host_advance", {})
            qid = (await player.wait_for("new_question"))["questionId"]
            await player.emit(
                "submit_answer",
                {
                    "question_id": qid,
                    "answer_data": {"selectedIndex": 0},
                    "answer_time_ms": 500,
                },
            )
            await player.wait_for("answer_received")
            await host.emit("host_advance", {})
            await host.wait_for("question_results")

        await host.emit("host_advance", {})
        over = await host.wait_for("game_over")
        assert over["maxPossibleScore"] == 8.75
        assert over["scores"] == [8.75]
        assert max(over["scores"]) <= over["maxPossibleScore"]
    finally:
        await host.disconnect()
        await player.disconnect()
