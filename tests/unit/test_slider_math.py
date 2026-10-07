"""
Unit tests for the slider helpers (T7 slider spec §4.3, §4.13): `app.services.slider_math`,
the slider pieces of `app.services.game_service`, and the `QuestionCreate` validator.

Pure functions, no database or Docker stack. `frontend/*/src/lib/slider.ts` mirrors these
formulas, so a change here must be made there too.

Run with:
    cd tests/unit && PYTHONPATH=../../backend pytest test_slider_math.py -v
"""

from __future__ import annotations

import math
from itertools import pairwise
from types import SimpleNamespace

import pytest
from app.schemas.admin import QuestionCreate
from app.services.game_service import (
    calculate_score,
    slider_answer_index,
    slider_dist_key,
    slider_reveal,
    slider_stats,
)
from app.services.slider_math import (
    slider_bin,
    slider_bins,
    slider_geometry,
    slider_index,
    slider_pct,
    slider_target_line,
    slider_value,
)
from pydantic import ValidationError

NUMERIC = {"min": 0, "max": 100, "step": 1, "unit": "hot dogs", "showValue": True}
SPECTRUM = {
    "min": 0,
    "max": 100,
    "step": 1,
    "showValue": False,
    "minLabel": "Ice cold",
    "maxLabel": "Lava",
}
TENTHS = {"min": 0, "max": 0.3, "step": 0.1}


def _answer(target: float = 50, full: float = 0.05, zero: float = 0.3) -> dict:
    return {"target": target, "fullRadius": full, "zeroRadius": zero}


def _question(
    *,
    grading_type: str = "ACCURACY",
    config: dict | None = None,
    points: float = 10,
    **answer_kwargs,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        type="slider",
        grading_type=grading_type,
        config=config or NUMERIC,
        answer_data=_answer(**answer_kwargs),
        points_value=points,
    )


# ---------------------------------------------------------------------------
# 1. geometry
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("config", "n_steps"),
    [
        ({"min": 0, "max": 100, "step": 1}, 100),
        ({"min": 0, "max": 1, "step": 0.1}, 10),
        ({"min": 0, "max": 0.3, "step": 0.1}, 3),  # 0.3 / 0.1 = 2.9999999999999996
        ({"min": -5, "max": 5, "step": 0.5}, 20),
    ],
)
def test_geometry_valid(config: dict, n_steps: int) -> None:
    geometry = slider_geometry(config)
    assert geometry is not None
    assert geometry[3] == n_steps


@pytest.mark.parametrize(
    "config",
    [
        {"min": 0, "max": 10, "step": 3},  # not a whole number of steps
        {"min": 0, "max": 1e6, "step": 1},  # > 10000 steps
        {"min": 0, "max": 100},  # no step
        {"min": 10, "max": 0, "step": 1},  # max < min
        {"min": 0, "max": 100, "step": 0},
        {"min": True, "max": 100, "step": 1},
        {"min": 0, "max": 2e9, "step": 1e6},  # over 1e9
        {"min": 0.0000001, "max": 1, "step": 0.1},  # 7 decimals
        "not a dict",
    ],
)
def test_geometry_invalid(config: object) -> None:
    assert slider_geometry(config) is None


# ---------------------------------------------------------------------------
# 2. index / snapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "k"),
    [
        (57.4, 57),
        (57.6, 58),
        (56.5, 57),  # ties up: Python's round(56.5) would give 56
        (57.5, 58),
        (0, 0),  # a value of 0 is a real answer
        (100, 100),
        (-0.0000001, 0),  # within EPS of min
    ],
)
def test_index_snaps_ties_up(value: float, k: int) -> None:
    assert slider_index(NUMERIC, value) == k


def test_index_float_noise_at_max_is_in_range() -> None:
    assert slider_index(TENTHS, 0.30000000000000004) == 3


@pytest.mark.parametrize("value", [-1, 101, math.nan, math.inf, "5", True, None])
def test_index_rejects(value: object) -> None:
    assert slider_index(NUMERIC, value) is None


@pytest.mark.parametrize(
    "answer",
    [
        {"value": 101},
        {"value": "50"},
        {"value": None},
        {},
        {"value": 50, "extra": 1},
        [],
    ],
)
def test_answer_index_requires_exact_shape(answer: object) -> None:
    assert slider_answer_index(NUMERIC, answer) is None


# ---------------------------------------------------------------------------
# 3. canonical values, percent, target line
# ---------------------------------------------------------------------------


def test_value_is_exact_on_decimal_grid() -> None:
    assert slider_value(TENTHS, 3) == 0.3
    assert repr(slider_value(TENTHS, 3)) == "0.3"


def test_value_is_int_on_whole_grid() -> None:
    v = slider_value(NUMERIC, 58)
    assert v == 58
    assert isinstance(v, int)


def test_pct() -> None:
    assert slider_pct(100, 35) == 35
    assert slider_pct(10, 5) == 50
    assert slider_pct(8, 1) == 13  # 12.5 rounds up


def test_target_line_numeric() -> None:
    reveal = slider_reveal("ACCURACY", NUMERIC, _answer(target=58))
    assert slider_target_line(reveal) == (
        "Target: 58 hot dogs · full credit within ±5 hot dogs"
    )


def test_target_line_width_never_rounds_to_zero() -> None:
    reveal = slider_reveal(
        "ACCURACY", {"min": 0, "max": 7, "step": 1}, _answer(target=3)
    )
    assert slider_target_line(reveal) == "Target: 3 · full credit within ±0.35"


def test_target_line_spectrum() -> None:
    reveal = slider_reveal("ACCURACY", SPECTRUM, _answer(target=35))
    assert slider_target_line(reveal) == "Target: 35% of the way from Ice cold to Lava"


def test_target_line_thousands_and_decimals() -> None:
    config = {"min": 1000, "max": 2000, "step": 0.5}
    reveal = slider_reveal("ACCURACY", config, _answer(target=1500.5))
    assert slider_target_line(reveal) == ("Target: 1,500.5 · full credit within ±50")


# ---------------------------------------------------------------------------
# 4. bins
# ---------------------------------------------------------------------------


def test_bins_one_per_position_when_small() -> None:
    assert slider_bins(10) == 11
    assert [slider_bin(10, k) for k in range(11)] == [str(k) for k in range(11)]


def test_bins_twenty_when_large_and_cover_without_gaps() -> None:
    assert slider_bins(100) == 20
    assert slider_bin(100, 0) == "0"
    assert slider_bin(100, 100) == "19"
    keys = [int(slider_bin(100, k)) for k in range(101)]
    assert keys == sorted(keys)
    assert set(keys) == set(range(20))
    assert all(b - a in (0, 1) for a, b in pairwise(keys))


def test_dist_key_uses_snapped_index() -> None:
    assert slider_dist_key(NUMERIC, {"value": 100}) == "19"
    assert slider_dist_key(NUMERIC, {"value": 101}) is None


# ---------------------------------------------------------------------------
# scoring, reveal, stats
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "points", "correct"),
    [
        (50, 10, True),
        (55, 10, True),  # d = 0.05, the boundary
        (67.5, 4.8, False),  # snaps to 68, d = 0.18 → 10 × (1 − 0.13 / 0.25)
        (80, 0, False),
    ],
)
def test_score(value: float, points: float, correct: bool) -> None:
    result = calculate_score(_question(), {"value": value})
    assert result.points_awarded == pytest.approx(points)
    assert result.is_correct is correct


def test_score_value_zero_is_not_empty() -> None:
    result = calculate_score(_question(target=0), {"value": 0})
    assert result.points_awarded == 10
    assert result.is_correct


def test_completeness_full_points_any_value() -> None:
    result = calculate_score(_question(grading_type="COMPLETENESS"), {"value": 100})
    assert result.points_awarded == 10
    assert result.is_correct


def test_bad_question_and_answer_score_zero() -> None:
    bad = _question()
    bad.answer_data = {"target": 50.5, "fullRadius": 0.05, "zeroRadius": 0.3}
    assert calculate_score(bad, {"value": 50}).points_awarded == pytest.approx(10)
    bad.config = {"min": 0, "max": 10, "step": 3}
    assert calculate_score(bad, {"value": 5}).points_awarded == 0
    assert calculate_score(_question(), {"value": "50"}).points_awarded == 0


@pytest.mark.parametrize("grading_type", ["ACCURACY", "COMPLETENESS"])
def test_reveal_has_every_key(grading_type: str) -> None:
    reveal = slider_reveal(grading_type, TENTHS, _answer(target=0.30000000000000004))
    assert set(reveal) == {
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
    assert reveal["gradingType"] == grading_type
    assert reveal["showValue"] is True
    assert reveal["unit"] is None and reveal["minLabel"] is None
    assert repr(reveal["target"]) == "0.3"


def test_stats() -> None:
    answers = [{"value": 50}, {"value": 55}, {"value": 68}, {"value": 80}, {"bad": 1}]
    stats = slider_stats(NUMERIC, _answer(), answers)
    assert stats["withinFullPct"] == 50.0
    assert stats["averageCredit"] == pytest.approx((1 + 1 + 0.48 + 0) / 4, abs=1e-3)


def test_stats_null_without_valid_answers() -> None:
    assert slider_stats(NUMERIC, _answer(), [{}, None]) == {
        "withinFullPct": None,
        "averageCredit": None,
    }


# ---------------------------------------------------------------------------
# 5. validator (QuestionCreate)
# ---------------------------------------------------------------------------


def _create(config: dict, answer_data: dict, grading_type: str = "ACCURACY") -> None:
    QuestionCreate(
        type="slider",
        grading_type=grading_type,
        prompt="How many?",
        config=config,
        answer_data=answer_data,
        points_value=10,
    )


@pytest.mark.parametrize(
    ("config", "answer_data"),
    [
        (NUMERIC, _answer(target=58)),
        (SPECTRUM, _answer(target=35)),
        (TENTHS, _answer(target=0.30000000000000004)),
        ({"min": 0, "max": 100, "step": 1}, _answer(full=0.01, zero=1)),
        ({**NUMERIC, "promptImageId": "img1"}, _answer()),
        ({"min": -1e9, "max": 1e9, "step": 1e6}, _answer(target=0)),
    ],
)
def test_validator_accepts(config: dict, answer_data: dict) -> None:
    _create(config, answer_data)
    _create(config, answer_data, grading_type="COMPLETENESS")


@pytest.mark.parametrize(
    ("config", "answer_data", "message"),
    [
        ({**NUMERIC, "colour": "red"}, _answer(), "unknown keys"),
        ({"max": 100, "step": 1}, _answer(), "config.min"),
        ({"min": 0, "max": 100, "step": True}, _answer(), "config.step"),
        ({"min": 2e9, "max": 3e9, "step": 1e6}, _answer(target=2e9), "1e9"),
        ({"min": 0, "max": 0, "step": 1}, _answer(target=0), "greater than min"),
        ({"min": 0, "max": 100, "step": -1}, _answer(), "step must be greater"),
        ({"min": 0.1234567, "max": 1, "step": 0.1}, _answer(), "6 decimals"),
        ({"min": 0, "max": 10001, "step": 1}, _answer(), "whole number of steps"),
        ({"min": 0, "max": 10, "step": 3}, _answer(target=3), "whole number of steps"),
        ({**NUMERIC, "showValue": "yes"}, _answer(), "showValue"),
        ({**NUMERIC, "unit": "  "}, _answer(), "unit"),
        ({**NUMERIC, "unit": "x" * 21}, _answer(), "unit"),
        ({**NUMERIC, "minLabel": "Cold"}, _answer(), "together"),
        ({**NUMERIC, "minLabel": "", "maxLabel": "Hot"}, _answer(), "minLabel"),
        ({**NUMERIC, "minLabel": "a", "maxLabel": "b" * 41}, _answer(), "maxLabel"),
        (
            {"min": 0, "max": 100, "step": 1, "showValue": False},
            _answer(),
            "needs minLabel",
        ),
        (NUMERIC, {**_answer(), "extra": 1}, "unknown keys"),
        (NUMERIC, {"fullRadius": 0.05, "zeroRadius": 0.3}, "target must be a number"),
        (NUMERIC, _answer(target=50.5), "on a step"),
        (NUMERIC, _answer(target=101), "on a step"),
        (NUMERIC, _answer(full=0.009), "fullRadius"),
        (NUMERIC, _answer(full=1, zero=1), "fullRadius"),
        (NUMERIC, _answer(full=0.3, zero=0.3), "zeroRadius"),
        (NUMERIC, _answer(zero=1.01), "zeroRadius"),
    ],
)
def test_validator_rejects(config: dict, answer_data: dict, message: str) -> None:
    for grading_type in ("ACCURACY", "COMPLETENESS"):
        with pytest.raises(ValidationError, match=message):
            _create(config, answer_data, grading_type)


def test_validator_rejects_option_images() -> None:
    with pytest.raises(ValidationError, match="optionImageIds|unknown keys"):
        _create({**NUMERIC, "optionImageIds": [None]}, _answer())
