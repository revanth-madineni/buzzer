"""
Helpers and the `t4` fixture for the T4 (course-host) integration tests.

Every name is unique per test (`tag = uuid4().hex[:8]`), as in conftest's
`game_setup`. Teardown, each call tolerant of 404:
  1. DELETE /game/sessions/{id} for every room created — clears its Redis keys,
     so LOBBY rooms don't count toward MAX_ROOMS for 90 minutes;
  2. DELETE /admin/games/{id} for every game created;
  3. DELETE /admin/users/{id} for every user created (their access rows cascade).
Courses and roster rows are left as inert records (no course-delete endpoint).
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field

import httpx
import pytest

from .engine.socket_client import TestSocketClient

_PASSWORD = "t4-password-123"
_TIMEOUT = 10.0


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@dataclass
class T4User:
    id: str
    username: str
    token: str


@dataclass
class T4World:
    base_url: str
    admin_token: str
    tag: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    _n: int = 0
    _games: list[int] = field(default_factory=list)
    _users: list[str] = field(default_factory=list)
    _sessions: list[str] = field(default_factory=list)

    # --- raw HTTP --------------------------------------------------------

    def request(
        self, method: str, path: str, token: str | None = None, **kwargs
    ) -> httpx.Response:
        return httpx.request(
            method,
            f"{self.base_url}/api{path}",
            headers=auth(token or self.admin_token),
            timeout=_TIMEOUT,
            **kwargs,
        )

    def _unique(self, prefix: str) -> str:
        self._n += 1
        return f"{prefix}_{self.tag}{self._n}"

    # --- setup as admin --------------------------------------------------

    def course(self) -> int:
        self._n += 1
        r = self.request(
            "POST",
            "/admin/courses",
            json={"name": f"T4 Course {self.tag}{self._n}", "semester": "T4"},
        )
        assert r.status_code == 201, r.text
        return r.json()["id"]

    def game(self, course_id: int | None = None, restricted: bool = False) -> int:
        """An admin-created game in `course_id` (courseless if None)."""
        self._n += 1
        r = self.request(
            "POST",
            "/admin/games",
            json={"title": f"T4 Game {self.tag}{self._n}", "course_id": course_id},
        )
        assert r.status_code == 201, r.text
        game_id = r.json()["id"]
        self.track_game(game_id)
        if restricted:
            self.set_restricted(game_id, True)
        return game_id

    def track_game(self, game_id: int) -> None:
        self._games.append(game_id)

    def get_game(self, game_id: int) -> dict:
        r = self.request("GET", f"/admin/games/{game_id}")
        assert r.status_code == 200, r.text
        return r.json()

    def set_restricted(self, game_id: int, restricted: bool) -> None:
        r = self.request(
            "PUT", f"/admin/games/{game_id}", json={"restricted": restricted}
        )
        assert r.status_code == 200, r.text
        assert r.json()["restricted"] is restricted

    def admin_session(self, session_id: str) -> dict | None:
        r = self.request("GET", "/admin/sessions")
        assert r.status_code == 200, r.text
        return next((s for s in r.json() if s["session_id"] == session_id), None)

    def user(self, prefix: str = "t4_host") -> T4User:
        username = self._unique(prefix)
        r = self.request(
            "POST",
            "/admin/users",
            json={
                "username": username,
                "display_name": username,
                "password": _PASSWORD,
            },
        )
        assert r.status_code == 201, r.text
        user_id = r.json()["id"]
        self._users.append(user_id)
        r = httpx.post(
            f"{self.base_url}/api/auth/login",
            json={"username": username, "password": _PASSWORD},
            timeout=_TIMEOUT,
        )
        assert r.status_code == 200, r.text
        return T4User(user_id, username, r.json()["access_token"])

    def grant_course(self, user: T4User, course_id: int, role: str = "HOST") -> None:
        r = self.request(
            "POST",
            f"/admin/users/{user.id}/course-access",
            json={"course_id": course_id, "role": role},
        )
        assert r.status_code == 204, r.text

    def grant_game(self, user: T4User, game_id: int) -> None:
        r = self.request(
            "POST", f"/admin/users/{user.id}/game-access", json={"game_id": game_id}
        )
        assert r.status_code == 204, r.text

    def guest_token(self, room_code: str) -> str:
        uid = uuid.uuid4().hex[:8]
        r = httpx.post(
            f"{self.base_url}/api/auth/guest",
            json={
                "display_name": f"T4Guest{uid}",
                "email": f"t4guest.{uid}@example.com",
                "room_code": room_code,
            },
            timeout=_TIMEOUT,
        )
        assert r.status_code == 200, r.text
        return r.json()["access_token"]

    # --- rooms -----------------------------------------------------------

    def create_room(
        self, game_id: int, course_id: int, token: str | None = None
    ) -> httpx.Response:
        r = self.request(
            "POST",
            "/game/rooms",
            token,
            json={"game_id": game_id, "course_id": course_id},
        )
        if r.status_code == 201:
            self._sessions.append(r.json()["session_id"])
        return r

    def delete_session(self, session_id: str) -> None:
        self.request("DELETE", f"/game/sessions/{session_id}")

    def my_game_ids(self, token: str) -> set[int]:
        r = self.request("GET", "/game/my-games", token)
        assert r.status_code == 200, r.text
        return {g["id"] for g in r.json()}

    # --- teardown --------------------------------------------------------

    def cleanup(self) -> None:
        for session_id in self._sessions:
            self.delete_session(session_id)
        for game_id in self._games:
            self.request("DELETE", f"/admin/games/{game_id}")
        for user_id in self._users:
            self.request("DELETE", f"/admin/users/{user_id}")


@pytest.fixture()
def t4(docker_stack, base_url: str, admin_token: str):
    world = T4World(base_url, admin_token)
    yield world
    world.cleanup()


def assert_error(r: httpx.Response, status: int, code: str) -> None:
    assert r.status_code == status, (
        f"expected {status} {code}, got {r.status_code}: {r.text}"
    )
    assert r.json().get("error") == code, r.text


async def join_as(
    base_url: str, token: str, room_code: str, role: str, label: str
) -> tuple[TestSocketClient, str, dict]:
    """
    Connect and emit join_room. Returns (client, outcome, payload) where outcome
    is "sync_state" or "error". The caller disconnects the client.
    """
    client = TestSocketClient(base_url, token, label=label)
    await client.connect()
    await client.emit("join_room", {"room_code": room_code, "role": role})
    ok = asyncio.ensure_future(client.wait_for("sync_state"))
    err = asyncio.ensure_future(client.wait_for("error"))
    done, pending = await asyncio.wait(
        {ok, err}, timeout=10.0, return_when=asyncio.FIRST_COMPLETED
    )
    for task in pending:
        task.cancel()
    assert done, f"[{label}] neither sync_state nor error within 10s"
    task = done.pop()
    return client, ("sync_state" if task is ok else "error"), task.result()
