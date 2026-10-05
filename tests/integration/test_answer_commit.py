"""
Answers must be committed before the server announces them.

on_submit_answer used to emit answer_received / answer_status inside its `_db()`
block, which only commits on exit. A host that advanced the instant the last
answer_status arrived read MySQL without that SessionScore: question_results was
one answer short and that player's yourPoints/rank missed it. The window is small,
so this runs several rounds with an immediate advance each time.
"""

from __future__ import annotations

from . import t4_helpers
from .engine.socket_client import TestSocketClient as SocketClient
from .t4_helpers import T4World

t4 = t4_helpers.t4  # fixture

ROUNDS = 6
PLAYERS = 4


async def test_results_include_answers_announced_just_before(t4: T4World):
    course = t4.course()
    game = t4.game(course)
    for _ in range(ROUNDS):
        r = t4.request(
            "POST", f"/admin/games/{game}/questions", json=t4_helpers.MC_QUESTION
        )
        assert r.status_code == 201, r.text

    r = t4.create_room(game, course)
    assert r.status_code == 201, r.text
    room_code = r.json()["room_code"]
    host = SocketClient(t4.base_url, t4.admin_token, "host")
    players = [
        SocketClient(t4.base_url, t4.guest_token(room_code), f"p{i}")
        for i in range(PLAYERS)
    ]
    try:
        await host.connect()
        await host.emit("join_room", {"room_code": room_code, "role": "HOST"})
        await host.wait_for("sync_state")
        for p in players:
            await p.connect()
            await p.emit("join_room", {"room_code": room_code, "role": "PLAYER"})
            await host.wait_for("player_joined")

        for round_no in range(ROUNDS):
            await host.emit("host_advance", {})
            await host.wait_for("new_question")
            qid = None
            for p in players:
                qid = (await p.wait_for("new_question"))["questionId"]
            # Everyone answers at once; option 0 scores 1 point.
            for p in players:
                await p.emit(
                    "submit_answer",
                    {
                        "question_id": qid,
                        "answer_data": {"selectedIndex": 0},
                        "answer_time_ms": 100,
                    },
                )
            for _ in players:
                await host.wait_for("answer_status")
            # Advance the instant the last answer is announced, as a fast host would.
            await host.emit("host_advance", {})
            host_results = await host.wait_for("question_results")
            assert host_results["totalAnswered"] == PLAYERS, (
                f"round {round_no}: {host_results}"
            )
            for p in players:
                received = await p.wait_for("answer_received")
                mine = await p.wait_for("question_results")
                assert mine["yourPoints"] == received["pointsAwarded"] == 1, (
                    f"round {round_no} {p.label}: {mine} vs {received}"
                )
    finally:
        for c in (host, *players):
            await c.disconnect()
