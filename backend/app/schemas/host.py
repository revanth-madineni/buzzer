from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .admin import AdminSessionItem, GameResponse

# ---------------------------------------------------------------------------
# Games (course comes from the URL; hosts cannot move or restrict games)
# ---------------------------------------------------------------------------


class HostGameCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(..., min_length=1, max_length=255)
    description: str = Field("", max_length=5000)
    max_players: int = Field(150, ge=1, le=500)


class HostGameUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=5000)
    max_players: int | None = Field(None, ge=1, le=500)


class HostGameListItem(GameResponse):
    question_count: int


# ---------------------------------------------------------------------------
# Roster
# ---------------------------------------------------------------------------

RosterUploadMode = Literal["add_update", "replace"]


# ---------------------------------------------------------------------------
# Sessions — same shape as the admin sessions list
# ---------------------------------------------------------------------------

SessionListItem = AdminSessionItem
