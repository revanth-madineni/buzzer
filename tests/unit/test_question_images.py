"""T8 image references, validation rules and error shapes (docs/plans/t8-images.md
§4.0, §4.2, §4.3). Pure functions only; the DB paths are integration-tested."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from app.common.exceptions import (
    BuzzerError,
    ImageInUseError,
    register_exception_handlers,
)
from app.schemas.admin import QuestionCreate
from app.services.game_service import (
    game_image_ids,
    question_image_ids,
    repoint_config,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError

# ── question_image_ids ───────────────────────────────────────────────────────


def test_question_image_ids_every_role_in_fixed_order() -> None:
    config = {
        "imageId": "map",
        "imageWidth": 10,
        "imageHeight": 10,
        "promptImageId": "prompt",
    }
    assert question_image_ids("map_pin", config) == [
        ("map", "map"),
        ("prompt", "prompt"),
    ]
    config = {
        "options": ["", "b", ""],
        "optionImageIds": ["x", None, "x"],
        "promptImageId": "p",
    }
    assert question_image_ids("multiple_choice", config) == [
        ("p", "prompt"),
        ("x", "option"),
        ("x", "option"),
    ]


def test_question_image_ids_ignores_malformed_values() -> None:
    assert question_image_ids("map_pin", None) == []
    assert question_image_ids("map_pin", {"imageId": 7}) == []
    assert question_image_ids("multiple_choice", {"imageId": "only-map-pin"}) == []
    assert question_image_ids("multi_select", {"optionImageIds": "nope"}) == []
    assert question_image_ids(
        "multi_select", {"promptImageId": "", "optionImageIds": [None, 3, "", "ok"]}
    ) == [("ok", "option")]


def test_game_image_ids_audience() -> None:
    questions = [
        SimpleNamespace(type="true_false", config={"promptImageId": "p1"}),
        SimpleNamespace(
            type="multiple_choice",
            config={"options": ["", ""], "optionImageIds": ["o1", "p1"]},
        ),
        SimpleNamespace(type="map_pin", config={"imageId": "m1"}),
    ]
    assert game_image_ids(questions, "host") == ["p1", "o1", "m1"]
    # A prompt-only image is left out for phones, but kept when it's also an option.
    assert game_image_ids(questions, "player") == ["o1", "p1", "m1"]
    assert game_image_ids(questions[:1], "player") == []


def test_repoint_config_every_role_and_entry_new_objects() -> None:
    config = {
        "options": ["", "", "t"],
        "optionImageIds": ["old", "old", None],
        "promptImageId": "old",
    }
    out = repoint_config("multiple_choice", config, "old", "new")
    assert out["optionImageIds"] == ["new", "new", None]
    assert out["promptImageId"] == "new"
    assert out is not config and out["optionImageIds"] is not config["optionImageIds"]
    assert config["promptImageId"] == "old"  # input untouched
    mp = repoint_config("map_pin", {"imageId": "old", "imageWidth": 3}, "old", "n")
    assert mp == {"imageId": "n", "imageWidth": 3}


# ── QuestionCreate rules (§4.2) ──────────────────────────────────────────────


def _mc(config: dict, type_: str = "multiple_choice") -> QuestionCreate:
    return QuestionCreate(
        type=type_, grading_type="COMPLETENESS", prompt="Q", config=config
    )


@pytest.mark.parametrize(
    "type_,config",
    [
        ("multiple_choice", {"options": ["a", "b"]}),
        ("multi_select", {"options": ["a", "b"]}),
        ("true_false", {}),
        ("fill_in_the_blank", {}),
    ],
)
def test_prompt_image_allowed_on_every_type(type_: str, config: dict) -> None:
    q = _mc({**config, "promptImageId": "img"}, type_)
    assert q.config["promptImageId"] == "img"


def test_prompt_image_allowed_on_map_pin() -> None:
    q = QuestionCreate(
        type="map_pin",
        grading_type="ACCURACY",
        prompt="Where?",
        config={"imageId": "m", "promptImageId": "p"},
        answer_data={
            "targets": [{"x": 0.5, "y": 0.5}],
            "fullRadius": 0.05,
            "zeroRadius": 0.2,
        },
    )
    assert q.config["promptImageId"] == "p"


@pytest.mark.parametrize("value", [None, "", 5, "x" * 65])
def test_prompt_image_must_be_a_ref(value: object) -> None:
    with pytest.raises(ValidationError, match="promptImageId"):
        _mc({"options": ["a", "b"], "promptImageId": value})


@pytest.mark.parametrize("type_", ["multiple_choice", "multi_select"])
def test_option_images_mixed_and_repeated(type_: str) -> None:
    q = _mc({"options": ["", "b", ""], "optionImageIds": ["x", None, "x"]}, type_)
    assert q.config["optionImageIds"] == ["x", None, "x"]


@pytest.mark.parametrize(
    "config,message",
    [
        ({"options": ["a", "b"], "optionImageIds": ["x"]}, "same length"),
        ({"options": ["a", "b"], "optionImageIds": ["x", None]}, "not both"),
        ({"options": ["", " "], "optionImageIds": ["x", None]}, "not neither"),
        ({"options": ["", "b"], "optionImageIds": [5, None]}, "optionImageIds\\[0\\]"),
        ({"options": ["", 3], "optionImageIds": ["x", None]}, "must be a string"),
    ],
)
def test_option_image_rules(config: dict, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        _mc(config)


def test_option_images_only_on_choice_types() -> None:
    with pytest.raises(ValidationError, match="only allowed"):
        _mc({"optionImageIds": []}, "true_false")


def test_all_null_option_images_treated_as_absent() -> None:
    # Blank text options stay allowed, exactly as without the key.
    q = _mc({"options": ["", "b"], "optionImageIds": [None, None]})
    assert q.config["options"] == ["", "b"]
    assert _mc({"options": ["", "b"]}).config["options"] == ["", "b"]


# ── Error shapes (§4.0) ──────────────────────────────────────────────────────


def _client(exc: Exception) -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    async def boom() -> None:
        raise exc

    return TestClient(app, raise_server_exceptions=False)


def test_extra_fields_merged_without_overriding() -> None:
    exc = BuzzerError("X", "msg", 418, extra={"error": "nope", "more": 1})
    res = _client(exc).get("/boom")
    assert res.status_code == 418
    assert res.json() == {"error": "X", "message": "msg", "more": 1}


def test_image_in_use_body() -> None:
    usage = [{"question_id": 1, "role": "prompt"}, {"question_id": 1, "role": "option"}]
    res = _client(ImageInUseError(usage, 2)).get("/boom")
    assert res.status_code == 409
    body = res.json()
    assert body["error"] == "IMAGE_IN_USE"
    assert body["message"] == "Image is used by 3 question(s)"
    assert body["usage"] == usage and body["hidden_usage_count"] == 2


def test_mysql_deadlock_becomes_409_conflict() -> None:
    deadlock = OperationalError("SELECT 1", {}, Exception(1213, "Deadlock found"))
    res = _client(deadlock).get("/boom")
    assert res.status_code == 409
    assert res.json()["error"] == "CONFLICT"


def test_other_db_errors_stay_500() -> None:
    other = OperationalError("SELECT 1", {}, Exception(2006, "gone away"))
    res = _client(other).get("/boom")
    assert res.status_code == 500
    assert res.json()["error"] == "INTERNAL_ERROR"
