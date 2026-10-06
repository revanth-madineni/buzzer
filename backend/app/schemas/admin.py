from __future__ import annotations

import math
from datetime import datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)

# ---------------------------------------------------------------------------
# Courses
# ---------------------------------------------------------------------------


class CourseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(..., min_length=1, max_length=255)
    semester: str = Field(..., min_length=1, max_length=50)
    allow_guests: bool = True


class CourseUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(None, min_length=1, max_length=255)
    semester: str | None = Field(None, min_length=1, max_length=50)
    allow_guests: bool | None = None


class CourseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    semester: str
    allow_guests: bool
    created_at: datetime


# ---------------------------------------------------------------------------
# Roster
# ---------------------------------------------------------------------------


class RosterEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    course_id: int
    netid: str
    full_name: str
    email: str
    is_active: bool
    imported_at: datetime


class RosterUploadResult(BaseModel):
    imported: int
    updated: int
    deactivated: int
    errors: list[str]


class RosterEntryPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_active: bool | None = None
    netid: str | None = Field(None, min_length=1, max_length=100)
    full_name: str | None = Field(None, min_length=1, max_length=255)
    email: EmailStr | None = None


class RosterRowIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    netid: str = Field(..., min_length=1, max_length=100)
    full_name: str = Field(..., min_length=1, max_length=255)
    email: str = Field(..., min_length=1, max_length=255)


class RosterImportPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rows: list[RosterRowIn] = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# Games
# ---------------------------------------------------------------------------


class GameFields(BaseModel):
    """A game's own fields. Also validates an import bundle's `game` block,
    which must not carry a course_id (spec §4.7)."""

    model_config = ConfigDict(extra="forbid")
    title: str = Field(..., min_length=1, max_length=255)
    description: str = Field("", max_length=5000)
    max_players: int = Field(150, ge=1, le=500)


class GameCreate(GameFields):
    course_id: int | None = None


class GameUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=5000)
    max_players: int | None = Field(None, ge=1, le=500)
    # Not course_id: moving a game goes through POST /admin/games/{id}/move.
    restricted: bool | None = None


class GameResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    description: str
    max_players: int
    course_id: int | None
    restricted: bool
    created_at: datetime


class GameMoveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    course_id: int
    confirm: bool = False


# ---------------------------------------------------------------------------
# Questions
# ---------------------------------------------------------------------------

QUESTION_TYPE_PATTERN = (
    "^(multiple_choice|true_false|fill_in_the_blank|multi_select|map_pin)$"
)

# map_pin limits (T7 spec §4.5). Radii are in image-width units.
MAP_PIN_MIN_FULL_RADIUS = 0.02
MAP_PIN_MAX_ZERO_RADIUS = 2
MAP_PIN_MAX_IMAGE_ID = 64


def is_valid_number(value: object) -> bool:
    """JSON number, int or float but not bool, and finite (spec §4.0)."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def is_image_ref(value: object) -> bool:
    """A stored image reference: a non-empty string of at most 64 chars (T7/T8)."""
    return isinstance(value, str) and 0 < len(value) <= MAP_PIN_MAX_IMAGE_ID


def _validate_image_ref(value: object, key: str) -> None:
    if not is_image_ref(value):
        raise ValueError(f"{key} must be a non-empty string of at most 64 characters")


def _validate_question_images(type_: str, config: dict) -> None:
    """T8 §4.2: promptImageId on every type; optionImageIds on MC and multi-select."""
    if "promptImageId" in config:
        _validate_image_ref(config["promptImageId"], "config.promptImageId")
    if "optionImageIds" not in config:
        return
    if type_ not in ("multiple_choice", "multi_select"):
        raise ValueError(
            "optionImageIds is only allowed on multiple_choice and multi_select"
        )
    ids = config["optionImageIds"]
    options = config.get("options")
    if (
        not isinstance(ids, list)
        or not isinstance(options, list)
        or len(ids) != len(options)
    ):
        raise ValueError("optionImageIds must be a list the same length as options")
    for i, image_id in enumerate(ids):
        if image_id is not None:
            _validate_image_ref(image_id, f"config.optionImageIds[{i}]")
    if all(image_id is None for image_id in ids):
        return  # treated exactly like an absent key
    for i, (text, image_id) in enumerate(zip(options, ids, strict=True)):
        if not isinstance(text, str):
            raise ValueError(f"Option {i + 1} must be a string")  # noqa: TRY004 (pydantic needs ValueError)
        if image_id is not None and text != "":
            raise ValueError(
                f"Option {i + 1} must have either text or an image, not both"
            )
        if image_id is None and not text.strip():
            raise ValueError(
                f"Option {i + 1} must have either text or an image, not neither"
            )


def _validate_map_pin(config: dict, answer_data: dict) -> None:
    """Same rules for both grading types: both show the same reveal (spec §4.5)."""
    extra = set(config) - {"imageId", "imageWidth", "imageHeight", "promptImageId"}
    if extra:
        raise ValueError(f"map_pin config has unknown keys: {sorted(extra)}")
    image_id = config.get("imageId")
    if (
        not isinstance(image_id, str)
        or not image_id
        or len(image_id) > MAP_PIN_MAX_IMAGE_ID
    ):
        raise ValueError(
            "map_pin config.imageId must be a non-empty string of at most 64 characters"
        )
    for key in ("imageWidth", "imageHeight"):
        if key in config:
            v = config[key]
            if not isinstance(v, int) or isinstance(v, bool) or v <= 0:
                raise ValueError(f"map_pin config.{key} must be a positive integer")

    extra = set(answer_data) - {"targets", "fullRadius", "zeroRadius"}
    if extra:
        raise ValueError(f"map_pin answer_data has unknown keys: {sorted(extra)}")
    targets = answer_data.get("targets")
    if not isinstance(targets, list) or len(targets) != 1:
        raise ValueError(
            "map_pin answer_data.targets must be a list of exactly 1 point"
        )
    target = targets[0]
    if not isinstance(target, dict) or set(target) != {"x", "y"}:
        raise ValueError("map_pin target must be an object with exactly keys x and y")
    if not all(is_valid_number(target[k]) and 0 <= target[k] <= 1 for k in ("x", "y")):
        raise ValueError("map_pin target x and y must be numbers between 0 and 1")
    full = answer_data.get("fullRadius")
    zero = answer_data.get("zeroRadius")
    if not is_valid_number(full) or full < MAP_PIN_MIN_FULL_RADIUS:
        raise ValueError(
            f"map_pin fullRadius must be a number of at least {MAP_PIN_MIN_FULL_RADIUS}"
        )
    if not is_valid_number(zero) or not full < zero <= MAP_PIN_MAX_ZERO_RADIUS:
        raise ValueError(
            "map_pin zeroRadius must be a number greater than fullRadius and at most "
            f"{MAP_PIN_MAX_ZERO_RADIUS}"
        )


class QuestionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str = Field(..., pattern=QUESTION_TYPE_PATTERN)
    grading_type: str = Field(..., pattern="^(ACCURACY|COMPLETENESS)$")
    prompt: str = Field(..., min_length=1, max_length=2000)
    config: dict = Field(default_factory=dict)
    answer_data: dict = Field(default_factory=dict)
    time_limit_seconds: int = Field(30, ge=2, le=300)
    points_value: float = Field(1.0, ge=0, le=100000)
    order_index: int | None = Field(None, ge=0)

    @model_validator(mode="after")
    def validate_structure(self) -> QuestionCreate:
        if self.type == "multiple_choice":
            opts = self.config.get("options")
            if not isinstance(opts, list) or len(opts) < 2:
                raise ValueError(
                    "multiple_choice config must have 'options' list with at least 2 items"
                )
            if self.grading_type == "ACCURACY":
                pts = self.answer_data.get("answer_points")
                if not isinstance(pts, list) or len(pts) != len(opts):
                    raise ValueError(
                        "ACCURACY multiple_choice answer_data must have 'answer_points' list matching options length"
                    )
                if any(not isinstance(p, (int, float)) or p < 0 for p in pts):
                    raise ValueError(
                        "answer_points values must be non-negative numbers"
                    )
        if self.type == "true_false" and self.grading_type == "ACCURACY":
            pts = self.answer_data.get("answer_points")
            if not isinstance(pts, dict) or set(pts.keys()) != {"true", "false"}:
                raise ValueError(
                    "ACCURACY true_false answer_data must have 'answer_points' with 'true' and 'false' keys"
                )
        if self.type == "fill_in_the_blank" and self.grading_type == "ACCURACY":
            answers = self.answer_data.get("acceptedAnswers")
            if not isinstance(answers, list) or len(answers) == 0:
                raise ValueError(
                    "ACCURACY fill_in_the_blank answer_data must have 'acceptedAnswers' list with at least one item"
                )
            if any(not isinstance(a, str) or not a.strip() for a in answers):
                raise ValueError("acceptedAnswers entries must be non-empty strings")
            pts = self.answer_data.get("answerPoints")
            if not isinstance(pts, list) or len(pts) != len(answers):
                raise ValueError(
                    "ACCURACY fill_in_the_blank answer_data must have 'answerPoints' list matching acceptedAnswers length"
                )
            if any(not isinstance(p, (int, float)) or p < 0 for p in pts):
                raise ValueError("answerPoints values must be non-negative numbers")
            edit_dist = self.answer_data.get("editDistance", 0)
            if not isinstance(edit_dist, int) or edit_dist < 0:
                raise ValueError("editDistance must be a non-negative integer")
        if self.type == "multi_select":
            opts = self.config.get("options")
            if not isinstance(opts, list) or len(opts) < 2:
                raise ValueError(
                    "multi_select config must have 'options' list with at least 2 items"
                )
            if self.grading_type == "ACCURACY":
                pts = self.answer_data.get("answer_points")
                if not isinstance(pts, list) or len(pts) != len(opts):
                    raise ValueError(
                        "ACCURACY multi_select answer_data must have 'answer_points' list matching options length"
                    )
                if any(not isinstance(p, (int, float)) for p in pts):
                    raise ValueError("answer_points values must be numbers")
        if self.type == "map_pin":
            _validate_map_pin(self.config, self.answer_data)
        _validate_question_images(self.type, self.config)
        return self


class QuestionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str | None = Field(None, pattern=QUESTION_TYPE_PATTERN)
    grading_type: str | None = Field(None, pattern="^(ACCURACY|COMPLETENESS)$")
    prompt: str | None = Field(None, min_length=1, max_length=2000)
    config: dict | None = None
    answer_data: dict | None = None
    time_limit_seconds: int | None = Field(None, ge=2, le=300)
    points_value: float | None = Field(None, ge=0, le=100000)
    order_index: int | None = Field(None, ge=0)


class QuestionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    game_id: int
    type: str
    grading_type: str
    prompt: str
    config: dict
    answer_data: dict
    time_limit_seconds: int
    points_value: float
    order_index: int
    created_at: datetime
    # T8: {image_id: alt_text} for the question's existing images. Not an ORM
    # attribute; built by question_service.question_responses.
    image_alt: dict[str, str] = Field(default_factory=dict)


class QuestionReorder(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order: list[int] = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# Images (T7). Never includes the bytes; those come from GET /api/images/{id}.
# ---------------------------------------------------------------------------


ALT_TEXT_MAX = 250


class ImageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    mime_type: str
    width: int
    height: int
    byte_size: int
    sha256: str
    alt_text: str
    course_id: int | None
    created_at: datetime


class ImageUsage(BaseModel):
    """One use of an image: one entry per question **and** role (T8 §4.2)."""

    game_id: int
    game_title: str
    course_id: int | None
    question_id: int
    question_number: int  # 1-based position in the game, not order_index + 1
    role: Literal["map", "prompt", "option"]


class ImageListItem(ImageResponse):
    usage: list[ImageUsage]
    hidden_usage_count: int  # uses in games the caller can't use; always 0 for admins


class ImageAltUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    alt_text: str = Field(..., max_length=ALT_TEXT_MAX)

    @field_validator("alt_text")
    @classmethod
    def strip_alt(cls, v: str) -> str:
        return v.strip()


# ---------------------------------------------------------------------------
# Users (local accounts)
# ---------------------------------------------------------------------------


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(..., min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_-]+$")
    display_name: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=8, max_length=72)
    email: EmailStr | None = None

    @field_validator("username")
    @classmethod
    def lower_username(cls, v: str) -> str:
        return v.lower()


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str | None = Field(
        None, min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_-]+$"
    )
    display_name: str | None = Field(None, min_length=1, max_length=255)
    email: EmailStr | None = None
    password: str | None = Field(None, min_length=8, max_length=72)
    role: str | None = Field(None, pattern="^(USER|ADMIN)$")

    @field_validator("username")
    @classmethod
    def lower_username(cls, v: str | None) -> str | None:
        return v.lower() if v is not None else None


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    username: str | None
    netid: str | None
    display_name: str | None
    email: str | None
    role: str
    created_at: datetime
    last_login: datetime | None


# ---------------------------------------------------------------------------
# Access management
# ---------------------------------------------------------------------------


class CourseAccessGrant(BaseModel):
    model_config = ConfigDict(extra="forbid")
    course_id: int
    role: str = Field(..., pattern="^(HOST|PLAYER)$")


class GameAccessGrant(BaseModel):
    model_config = ConfigDict(extra="forbid")
    game_id: int


class UserWithAccessResponse(UserResponse):
    course_access: list[dict]
    game_access: list[int]


class CourseAccessEntry(BaseModel):
    user_id: str
    username: str | None
    netid: str | None
    display_name: str | None
    role: Literal["HOST", "PLAYER"]


class GameAccessEntry(BaseModel):
    user_id: str
    username: str | None
    netid: str | None
    display_name: str | None
    has_course_host: bool


class GameMoveResult(BaseModel):
    applied: bool
    game: GameResponse
    dropped_grants: list[GameAccessEntry]
    # T8 §4.7a: images re-tagged to the new course / copied because they're shared.
    images_moved: int = 0
    images_copied: int = 0


# ---------------------------------------------------------------------------
# Sessions (admin view)
# ---------------------------------------------------------------------------


class AdminSessionItem(BaseModel):
    model_config = ConfigDict(from_attributes=False)
    session_id: str
    room_code: str
    status: str
    game_id: int
    game_title: str
    course_id: int
    course_name: str
    course_semester: str
    host_display_name: str | None
    created_at: datetime
    completed_at: datetime | None
    player_count: int
