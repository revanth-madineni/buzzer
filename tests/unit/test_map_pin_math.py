"""
Unit tests for the map-pin helpers in app.services.game_service (T7 spec §4.6).

Pure functions, no database or Docker stack.

Run with:
    cd tests/unit && PYTHONPATH=../../backend pytest test_map_pin_math.py -v
"""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest
from app.services.game_service import (
    calculate_score,
    game_image_ids,
    map_pin_bucket,
    map_pin_click,
    map_pin_distance,
    map_pin_fraction,
    map_pin_reveal,
    map_pin_stats,
)

FULL, ZERO = 0.04, 0.15
D_MID = (FULL + ZERO) / 2


def _question(
    *,
    grading_type: str = "ACCURACY",
    width: int = 800,
    height: int = 400,
    target: tuple[float, float] = (0.5, 0.5),
    points: float = 10,
    **answer_overrides,
) -> SimpleNamespace:
    answer_data = {
        "targets": [{"x": target[0], "y": target[1]}],
        "fullRadius": FULL,
        "zeroRadius": ZERO,
        **answer_overrides,
    }
    return SimpleNamespace(
        id=1,
        type="map_pin",
        grading_type=grading_type,
        config={"imageId": "img", "imageWidth": width, "imageHeight": height},
        answer_data=answer_data,
        points_value=points,
    )


# ---------------------------------------------------------------------------
# distance / fraction / bucket
# ---------------------------------------------------------------------------


def test_distance_is_aspect_corrected_to_width_units() -> None:
    # 2:1 image: a vertical offset of 0.2 height-fractions is 0.1 width units.
    assert map_pin_distance(2.0, (0.5, 0.5), (0.5, 0.7)) == pytest.approx(0.1)
    assert map_pin_distance(2.0, (0.5, 0.5), (0.6, 0.5)) == pytest.approx(0.1)
    assert map_pin_distance(0.5, (0.5, 0.5), (0.5, 0.55)) == pytest.approx(0.1)
    assert map_pin_distance(1.0, (0, 0), (0.3, 0.4)) == pytest.approx(0.5)


@pytest.mark.parametrize(
    ("d", "expected"),
    [
        (0.0, 1.0),
        (FULL, 1.0),
        (D_MID, 0.5),
        (ZERO, 0.0),
        (ZERO + 1, 0.0),
        (FULL + (ZERO - FULL) / 4, 0.75),
    ],
)
def test_fraction_linear_falloff(d: float, expected: float) -> None:
    assert map_pin_fraction(d, FULL, ZERO) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("x", "y", "key"),
    [
        (0.0, 0.0, "0,0"),
        (1.0, 1.0, "49,49"),
        (1.0, 0.0, "49,0"),
        (0.999, 0.5, "49,25"),
        (0.02, 0.0399, "1,1"),
        (0.0199, 0.02, "0,1"),
    ],
)
def test_bucket(x: float, y: float, key: str) -> None:
    assert map_pin_bucket(x, y) == key


# ---------------------------------------------------------------------------
# answer validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "answer",
    [
        {"x": "0.5", "y": 0.5},
        {"x": None, "y": 0.5},
        {"x": math.nan, "y": 0.5},
        {"x": math.inf, "y": 0.5},
        {"x": True, "y": 0.5},
        {"x": 0.5},
        {"x": 0.5, "y": 0.5, "z": 1},
        {"x": 1.01, "y": 0.5},
        {"x": -0.01, "y": 0.5},
        {},
        [0.5, 0.5],
        None,
    ],
)
def test_invalid_clicks(answer: object) -> None:
    assert map_pin_click(answer) is None


@pytest.mark.parametrize("answer", [{"x": 0, "y": 1}, {"x": 0.25, "y": 0.75}])
def test_valid_clicks(answer: dict) -> None:
    assert map_pin_click(answer) == (answer["x"], answer["y"])


# ---------------------------------------------------------------------------
# calculate_score
# ---------------------------------------------------------------------------


def test_score_on_target_and_horizontal_vertical_symmetry() -> None:
    q = _question()  # 800x400, aspect 2
    on = calculate_score(q, {"x": 0.5, "y": 0.5})
    assert (on.points_awarded, on.is_correct) == (10, True)

    horizontal = calculate_score(q, {"x": 0.5 + D_MID, "y": 0.5})
    vertical = calculate_score(q, {"x": 0.5, "y": 0.5 + D_MID * 2})
    assert horizontal.points_awarded == pytest.approx(5, abs=0.01)
    assert vertical.points_awarded == pytest.approx(5, abs=0.01)
    assert not horizontal.is_correct and not vertical.is_correct


def test_score_beyond_zero_radius() -> None:
    result = calculate_score(_question(), {"x": 0.5 + ZERO + 0.01, "y": 0.5})
    assert (result.points_awarded, result.is_correct) == (0, False)


def test_score_rounds_to_two_decimals_and_stays_float() -> None:
    result = calculate_score(_question(points=7), {"x": 0.5 + D_MID, "y": 0.5})
    assert result.points_awarded == 3.5
    third = calculate_score(
        _question(points=1), {"x": 0.5 + FULL + (ZERO - FULL) / 3, "y": 0.5}
    )
    assert third.points_awarded == 0.67


def test_completeness_full_points_for_any_tap() -> None:
    q = _question(grading_type="COMPLETENESS")
    result = calculate_score(q, {"x": 0.0, "y": 0.0})
    assert (result.points_awarded, result.is_correct) == (10, True)


@pytest.mark.parametrize(
    "question",
    [
        _question(width=0),
        _question(targets=[]),
        _question(fullRadius=None),
        SimpleNamespace(
            id=1,
            type="map_pin",
            grading_type="ACCURACY",
            config={"imageId": "img"},
            answer_data={"targets": [{"x": 0.5, "y": 0.5}]},
            points_value=10,
        ),
    ],
)
def test_bad_question_scores_zero(question) -> None:
    result = calculate_score(question, {"x": 0.5, "y": 0.5})
    assert (result.points_awarded, result.is_correct) == (0, False)


def test_bad_answer_scores_zero() -> None:
    result = calculate_score(_question(), {"x": "0.5", "y": 0.5})
    assert (result.points_awarded, result.is_correct) == (0, False)


# ---------------------------------------------------------------------------
# reveal, stats, image ids
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("grading_type", ["ACCURACY", "COMPLETENESS"])
def test_reveal_same_shape_for_both_grading_types(grading_type: str) -> None:
    q = _question(grading_type=grading_type, target=(0.2, 0.3))
    assert map_pin_reveal(q.grading_type, q.config, q.answer_data) == {
        "type": "map_pin",
        "gradingType": grading_type,
        "imageId": "img",
        "imageWidth": 800,
        "imageHeight": 400,
        "target": {"x": 0.2, "y": 0.3},
        "fullRadius": FULL,
        "zeroRadius": ZERO,
    }


def test_stats_within_and_average_credit() -> None:
    q = _question()
    answers = [
        {"x": 0.5, "y": 0.5},  # within, credit 1
        {"x": 0.5 + D_MID, "y": 0.5},  # credit 0.5
        {"x": 0.9, "y": 0.5},  # beyond, credit 0
        {"x": "bad", "y": 0.5},  # not counted
        None,  # not counted
    ]
    assert map_pin_stats(q.config, q.answer_data, answers) == {
        "withinFullPct": 33.3,
        "averageCredit": 0.5,
    }


def test_stats_null_when_no_valid_answers() -> None:
    q = _question()
    assert map_pin_stats(q.config, q.answer_data, []) == {
        "withinFullPct": None,
        "averageCredit": None,
    }


def test_game_image_ids_distinct_in_question_order() -> None:
    def q(qtype: str, image_id: str | None = None) -> SimpleNamespace:
        config = {"imageId": image_id} if image_id else {"options": ["a", "b"]}
        return SimpleNamespace(type=qtype, config=config)

    questions = [
        q("map_pin", "b"),
        q("multiple_choice"),
        q("map_pin", "a"),
        q("map_pin", "b"),
    ]
    assert game_image_ids(questions) == ["b", "a"]
    assert game_image_ids([q("multiple_choice")]) == []
