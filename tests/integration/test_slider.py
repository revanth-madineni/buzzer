"""
T7 slider integration tests (spec docs/plans/t7-slider.md §4.13).

Runs against the live Docker stack, like the rest of this suite. The live-game helpers
(`open_game`, `next_question`, `submit`, `results`, `finish`) and the bundle helpers are
shared with the map-pin tests.
"""

from __future__ import annotations

import pytest

from . import t4_helpers
from .t4_helpers import T4World
from .test_map_pin import (
    assert_validation_error,
    create_q,
    export_bundle,
    finish,
    hand_bundle,
    import_bundle,
    list_qs,
    next_question,
    open_game,
    results,
    submit,
    update_q,
)

t4 = t4_helpers.t4  # fixture

NUMERIC = {"min": 0, "max": 100, "step": 1, "unit": "hot dogs", "showValue": True}
SPECTRUM = {
    "min": 0,
    "max": 100,
    "step": 1,
    "showValue": False,
    "minLabel": "Ice cold",
    "maxLabel": "Lava",
}
TENTHS = {"min": 0, "max": 1, "step": 0.1}

REVEAL_KEYS = {
    "type",
    "gradingType",
    "min",
    "max",
    "step",
    "showValue",
    "unit",
    "minLabel",
    "maxLabel",
    "target",
    "fullRadius",
    "zeroRadius",
}


def slider_question(
    *,
    config: dict | None = None,
    target: float = 50,
    full: float = 0.05,
    zero: float = 0.3,
    grading_type: str = "ACCURACY",
    points: float = 10,
    prompt: str = "How many hot dogs?",
) -> dict:
    return {
        "type": "slider",
        "grading_type": grading_type,
        "prompt": prompt,
        "config": dict(config or NUMERIC),
        "answer_data": {"target": target, "fullRadius": full, "zeroRadius": zero},
        "points_value": points,
        "time_limit_seconds": 30,
    }


def slider_game(t4: T4World, questions: list[dict]) -> tuple[int, int, list[int]]:
    course = t4.course()
    game = t4.game(course)
    ids = []
    for body in questions:
        r = create_q(t4, game, body)
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])
    return course, game, ids


@pytest.fixture(params=["admin", "host"])
def editor(request, t4: T4World):
    """(game_id, token, host flag) for the admin or a course host."""
    course = t4.course()
    game = t4.game(course)
    if request.param == "admin":
        return game, None, False
    host = t4.user()
    t4.grant_course(host, course)
    return game, host.token, True


# ---------------------------------------------------------------------------
# 1 — create validation (admin and host routes)
# ---------------------------------------------------------------------------


def test_create_valid_numeric_and_spectrum(t4: T4World, editor):
    game, token, host = editor
    for body in (
        slider_question(),
        slider_question(config=SPECTRUM, target=35),
        slider_question(config=TENTHS, target=0.3, grading_type="COMPLETENESS"),
    ):
        r = create_q(t4, game, body, token, host=host)
        assert r.status_code == 201, r.text
        assert r.json()["config"] == body["config"]
        assert r.json()["answer_data"] == body["answer_data"]


@pytest.mark.parametrize(
    "body",
    [
        slider_question(target=50.5),  # off-grid
        slider_question(full=0.3, zero=0.3),  # fullRadius ≥ zeroRadius
        slider_question(config={"min": 10, "max": 10, "step": 1}, target=10),
        slider_question(config={"min": 0, "max": 10001, "step": 1}),
        {
            **slider_question(grading_type="COMPLETENESS"),
            "answer_data": {"fullRadius": 0.05, "zeroRadius": 0.3},
        },
    ],
    ids=["off-grid", "radii", "max-le-min", "too-many-steps", "completeness-no-target"],
)
def test_create_rejects(t4: T4World, editor, body: dict):
    game, token, host = editor
    assert_validation_error(create_q(t4, game, body, token, host=host))


# ---------------------------------------------------------------------------
# 2 — update symmetry
# ---------------------------------------------------------------------------


def test_update_off_grid_target_rejected_row_unchanged(t4: T4World, editor):
    game, token, host = editor
    q = create_q(t4, game, slider_question()).json()
    bad = {"target": 50.5, "fullRadius": 0.05, "zeroRadius": 0.3}
    assert_validation_error(
        update_q(t4, game, q["id"], {"answer_data": bad}, token, host=host)
    )
    assert list_qs(t4, game)[q["id"]]["answer_data"] == q["answer_data"]


def test_update_type_change_without_config_rejected(t4: T4World, editor):
    game, token, host = editor
    mc = create_q(t4, game, t4_helpers.MC_QUESTION).json()
    assert_validation_error(
        update_q(t4, game, mc["id"], {"type": "slider"}, token, host=host)
    )
    assert list_qs(t4, game)[mc["id"]]["type"] == "multiple_choice"


def test_update_valid(t4: T4World, editor):
    game, token, host = editor
    q = create_q(t4, game, slider_question()).json()
    body = {
        "config": SPECTRUM,
        "answer_data": {"target": 35, "fullRadius": 0.1, "zeroRadius": 0.4},
    }
    r = update_q(t4, game, q["id"], body, token, host=host)
    assert r.status_code == 200, r.text
    stored = list_qs(t4, game)[q["id"]]
    assert stored["config"] == SPECTRUM
    assert stored["answer_data"]["target"] == 35


# ---------------------------------------------------------------------------
# 3, 4 — scoring and COMPLETENESS
# ---------------------------------------------------------------------------


async def test_scoring_end_to_end(t4: T4World):
    course, game, _ = slider_game(
        t4,
        [
            slider_question(target=50),
            slider_question(target=0),
            slider_question(target=50, grading_type="COMPLETENESS"),
        ],
    )
    live = await open_game(t4, course, game, 4)
    try:
        qid = await next_question(live)
        values = [50, 55, 67.5, 80]
        got = [await submit(p, qid, {"value": v}) for p, v in zip(live.players, values)]
        assert all(kind == "answer_received" for kind, _ in got), got
        points = [payload["pointsAwarded"] for _, payload in got]
        assert points[0] == 10
        assert points[1] == 10  # d = 0.05, at the boundary
        assert points[2] == pytest.approx(4.8)  # snapped to 68
        assert points[3] == 0
        assert [payload["isCorrect"] for _, payload in got] == [
            True,
            True,
            False,
            False,
        ]
        await results(live)

        # Target 0: a value of 0 is a real answer, not an empty one.
        qid = await next_question(live)
        kind, payload = await submit(live.players[0], qid, {"value": 0})
        assert kind == "answer_received"
        assert (payload["pointsAwarded"], payload["isCorrect"]) == (10, True)
        await results(live)

        # COMPLETENESS: full points far from the target, and the reveal keeps the target.
        qid = await next_question(live)
        kind, payload = await submit(live.players[2], qid, {"value": 100})
        assert kind == "answer_received"
        assert (payload["pointsAwarded"], payload["isCorrect"]) == (10, True)
        host_results = await results(live)
        reveal = host_results["answerReveal"]
        assert reveal["gradingType"] == "COMPLETENESS"
        assert (reveal["target"], reveal["fullRadius"], reveal["zeroRadius"]) == (
            50,
            0.05,
            0.3,
        )

        over = await finish(live)
        # Player 2: 4.8 + 10, floats end to end. points_awarded is a single-precision
        # column, so the sum reads back as 14.800000190734863.
        assert any(score == pytest.approx(14.8) for score in over["scores"])
    finally:
        await live.close()


# ---------------------------------------------------------------------------
# 5 — socket validation
# ---------------------------------------------------------------------------

BAD_ANSWERS = [
    {"value": 101},
    {"value": "50"},
    {"value": None},
    {"value": True},
    {},
    {"value": 50, "extra": 1},
    {"value": float("nan")},  # json.dumps writes a literal NaN
]


async def test_socket_rejects_bad_answers(t4: T4World):
    course, game, _ = slider_game(t4, [slider_question()])
    live = await open_game(t4, course, game, 1)
    try:
        qid = await next_question(live)
        for bad in BAD_ANSWERS:
            kind, payload = await submit(live.players[0], qid, bad)
            assert kind == "error", (bad, payload)
            assert payload["message"] == (
                "slider answer must include a value within the slider's range"
            )
            assert "code" not in payload  # fatal, not a timing rejection
        assert (await results(live))["totalAnswered"] == 0
    finally:
        await live.close()


# ---------------------------------------------------------------------------
# 6 — canonical storage
# ---------------------------------------------------------------------------


async def test_answer_stored_as_canonical_value(t4: T4World):
    course, game, _ = slider_game(t4, [slider_question(config=TENTHS, target=0.3)])
    live = await open_game(t4, course, game, 1)
    try:
        qid = await next_question(live)
        kind, payload = await submit(
            live.players[0], qid, {"value": 0.30000000000000004}
        )
        assert kind == "answer_received"
        assert payload["pointsAwarded"] == 10
        await results(live)
        await finish(live)
        player_over = await live.players[0].wait_for("game_over")
        assert player_over["questionSummary"][0]["playerAnswer"] == {"value": 0.3}
    finally:
        await live.close()


# ---------------------------------------------------------------------------
# 7 — distribution, reveal and host stats
# ---------------------------------------------------------------------------


async def test_distribution_reveal_and_stats(t4: T4World):
    course, game, _ = slider_game(
        t4, [slider_question(), slider_question(config=TENTHS, target=0.5)]
    )
    live = await open_game(t4, course, game, 4)
    try:
        qid = await next_question(live)
        # N = 100 → 20 bins over 101 positions: bin 9 = 46..50, so 47, 50 → "9";
        # 68 → "13"; 100 → "19".
        for p, v in zip(live.players, [50, 47, 68, 100]):
            assert (await submit(p, qid, {"value": v}))[0] == "answer_received"
        host_results = await results(live)
        assert host_results["answerDistribution"] == {"9": 2, "13": 1, "19": 1}
        reveal = host_results["answerReveal"]
        assert set(reveal) == REVEAL_KEYS
        assert reveal["type"] == "slider"
        assert reveal["unit"] == "hot dogs"
        assert reveal["minLabel"] is None and reveal["maxLabel"] is None

        # N = 10 → one bin per position.
        qid = await next_question(live)
        assert (await submit(live.players[0], qid, {"value": 0.7}))[
            0
        ] == "answer_received"
        assert (await results(live))["answerDistribution"] == {"7": 1}

        summary = (await finish(live))["questionSummary"]
        assert summary[0]["answerDistribution"] == {"9": 2, "13": 1, "19": 1}
        # 50 and 47 within 5%; credit 1 + 1 + 0.48 + 0 over 4.
        assert summary[0]["withinFullPct"] == 50.0
        assert summary[0]["averageCredit"] == 0.62
        assert summary[0]["answerReveal"]["target"] == 50
    finally:
        await live.close()


# ---------------------------------------------------------------------------
# 8 — import / export
# ---------------------------------------------------------------------------


def test_export_import_round_trip(t4: T4World):
    _course, game, _ = slider_game(
        t4,
        [
            slider_question(),
            slider_question(config=SPECTRUM, target=35, grading_type="COMPLETENESS"),
        ],
    )
    bundle = export_bundle(t4, game)
    r = import_bundle(t4, bundle)
    assert r.status_code == 201, r.text
    original = sorted(list_qs(t4, game).values(), key=lambda q: q["order_index"])
    copied = sorted(
        list_qs(t4, r.json()["game_id"]).values(), key=lambda q: q["order_index"]
    )
    assert [(q["config"], q["answer_data"]) for q in copied] == [
        (q["config"], q["answer_data"]) for q in original
    ]


def test_import_off_grid_target_rejected(t4: T4World):
    bundle = hand_bundle([], [slider_question(target=50.5)])
    r = import_bundle(t4, bundle)
    assert r.status_code == 422, r.text


# ---------------------------------------------------------------------------
# 9 — report and CSV
# ---------------------------------------------------------------------------


async def test_report_and_csv(t4: T4World):
    course, game, _ = slider_game(
        t4,
        [
            slider_question(target=58),
            slider_question(config=SPECTRUM, target=35),
        ],
    )
    live = await open_game(t4, course, game, 2)
    try:
        qid = await next_question(live)
        for p, v in zip(live.players, [58, 70]):
            assert (await submit(p, qid, {"value": v}))[0] == "answer_received"
        await results(live)
        qid = await next_question(live)
        assert (await submit(live.players[0], qid, {"value": 35}))[
            0
        ] == "answer_received"
        await results(live)
        await finish(live)
    finally:
        await live.close()

    r = t4.request("GET", f"/admin/sessions/{live.session_id}/report")
    assert r.status_code == 200, r.text
    report = r.text
    assert 'class="badge badge-slider"' in report
    assert "Target: 58 hot dogs · full credit within ±5 hot dogs" in report
    assert "Target: 35% of the way from Ice cold to Lava" in report
    assert "50% within target" in report  # 58 within, 70 at d = 0.12

    r = t4.request(
        "GET", f"/admin/sessions/{live.session_id}/export", params={"format": "raw"}
    )
    assert r.status_code == 200, r.text
    rows = [line.split(",") for line in r.text.strip().splitlines()]
    q1_points = sorted(float(row[1]) for row in rows[1:])
    assert q1_points == [7.2, 10.0]  # 70: 10 × (1 − 0.07 / 0.25)
