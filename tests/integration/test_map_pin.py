"""
T7 map-pin integration tests (spec docs/plans/t7-map-pin.md §4.14).

Runs against the live Docker stack, like the rest of this suite. Images are
generated with Pillow; the sample US map lives at sample_games/assets/us-map.png.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import pathlib
import subprocess
import uuid
from dataclasses import dataclass

import httpx
import pytest
from PIL import Image, ImageCms
from PIL.PngImagePlugin import PngInfo

from . import t4_helpers
from .engine.socket_client import TestSocketClient as SocketClient
from .t4_helpers import T4World, assert_error

t4 = t4_helpers.t4  # fixture

_REPO_ROOT = pathlib.Path(__file__).parent.parent.parent
US_MAP = _REPO_ROOT / "sample_games" / "assets" / "us-map.png"

# ---------------------------------------------------------------------------
# Image builders
# ---------------------------------------------------------------------------


def picture(size: tuple[int, int] = (80, 40), mode: str = "RGB") -> Image.Image:
    img = Image.new(mode, size)
    channels = len(img.getbands())
    for x in range(size[0]):
        for y in range(size[1]):
            v = (x * 7 + y * 13) % 256
            img.putpixel((x, y), (v, 255 - v, x % 256, 200)[:channels])
    return img


def encode(img: Image.Image, fmt: str, **kwargs) -> bytes:
    buf = io.BytesIO()
    img.save(buf, fmt, **kwargs)
    return buf.getvalue()


def png(size: tuple[int, int] = (80, 40)) -> bytes:
    return encode(picture(size), "PNG")


def gps_exif(orientation: int | None = None) -> Image.Exif:
    exif = Image.Exif()
    if orientation is not None:
        exif[0x0112] = orientation
    gps = exif.get_ifd(0x8825)
    gps[1] = "N"
    gps[2] = (43.0, 4.0, 30.0)
    return exif


def open_image(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    img.load()
    return img


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def upload(
    t4: T4World,
    data: bytes,
    *,
    token: str | None = None,
    course_id: int | None = None,
    host_course: int | None = None,
    filename: str = "img.png",
    content_type: str = "image/png",
) -> httpx.Response:
    """Admin upload by default; `host_course` uploads to that course's host route."""
    files = {"file": (filename, data, content_type)}
    if host_course is not None:
        return t4.request(
            "POST", f"/host/courses/{host_course}/images", token, files=files
        )
    form = {"course_id": str(course_id)} if course_id is not None else None
    return t4.request("POST", "/admin/images", token, files=files, data=form)


def upload_ok(t4: T4World, data: bytes, **kwargs) -> dict:
    r = upload(t4, data, **kwargs)
    assert r.status_code == 201, r.text
    return r.json()


def get_image(t4: T4World, image_id: str, token: str | None = None) -> httpx.Response:
    return t4.request("GET", f"/images/{image_id}", token)


def guest_token(t4: T4World) -> str:
    course = t4.course()
    game = t4.game(course)
    r = t4.create_room(game, course)
    assert r.status_code == 201, r.text
    return t4.guest_token(r.json()["room_code"])


# ---------------------------------------------------------------------------
# Test 1 — upload auth
# ---------------------------------------------------------------------------


def test_upload_auth(t4: T4World):
    course, other = t4.course(), t4.course()
    host = t4.user()
    t4.grant_course(host, course)
    data = png()

    admin_img = upload_ok(t4, data, course_id=course)
    assert set(admin_img) == {
        "id",
        "mime_type",
        "width",
        "height",
        "byte_size",
        "sha256",
    }
    assert uuid.UUID(admin_img["id"])

    host_img = upload_ok(t4, data, token=host.token, host_course=course)
    assert host_img["mime_type"] == "image/png"

    assert_error(
        upload(t4, data, token=host.token, host_course=other), 403, "FORBIDDEN"
    )
    assert_error(upload(t4, data, token=host.token), 403, "FORBIDDEN")  # admin route

    guest = guest_token(t4)
    assert upload(t4, data, token=guest, host_course=course).status_code == 403
    assert upload(t4, data, token=guest).status_code == 403

    r = httpx.post(
        f"{t4.base_url}/api/admin/images",
        files={"file": ("a.png", data, "image/png")},
        timeout=10.0,
    )
    assert r.status_code == 401


def test_admin_upload_unknown_course_404(t4: T4World):
    assert_error(upload(t4, png(), course_id=999_999_999), 404, "NOT_FOUND")


# ---------------------------------------------------------------------------
# Test 2 — upload validation
# ---------------------------------------------------------------------------


def _noise_png(min_bytes: int) -> bytes:
    """A PNG of random pixels at least `min_bytes` long (noise doesn't compress)."""
    import os

    side = int((min_bytes / 3) ** 0.5) + 20
    img = Image.frombytes("RGB", (side, side), os.urandom(side * side * 3))
    data = encode(img, "PNG")
    assert len(data) >= min_bytes
    return data


def test_upload_too_large_file_passes_body_limit_fails_prepare(t4: T4World):
    data = _noise_png(int(2.2 * 1024 * 1024))
    assert len(data) < int(2.5 * 1024 * 1024) - 1024  # leaves room for multipart
    assert_error(upload(t4, data), 413, "IMAGE_TOO_LARGE")


def test_upload_body_over_limit_rejected_before_parsing(t4: T4World):
    r = upload(t4, b"\x00" * (3 * 1024 * 1024))
    assert_error(r, 413, "REQUEST_TOO_LARGE")


def test_host_upload_body_over_limit_rejected(t4: T4World):
    course = t4.course()
    r = upload(t4, b"\x00" * (3 * 1024 * 1024), host_course=course)
    assert_error(r, 413, "REQUEST_TOO_LARGE")


@pytest.mark.parametrize(
    ("data", "filename", "content_type", "status", "code"),
    [
        pytest.param(
            b'<svg xmlns="http://www.w3.org/2000/svg"><circle r="5"/></svg>',
            "map.svg",
            "image/svg+xml",
            422,
            "INVALID_IMAGE",
            id="svg",
        ),
        pytest.param(
            b"definitely not an image",
            "fake.png",
            "image/png",
            422,
            "INVALID_IMAGE",
            id="text-as-png",
        ),
        pytest.param(
            encode(picture(), "GIF"),
            "a.gif",
            "image/gif",
            415,
            "UNSUPPORTED_IMAGE_TYPE",
            id="gif",
        ),
        pytest.param(
            encode(
                picture(), "WEBP", save_all=True, append_images=[picture().rotate(180)]
            ),
            "a.webp",
            "image/webp",
            415,
            "UNSUPPORTED_IMAGE_TYPE",
            id="animated-webp",
        ),
        pytest.param(
            png((9000, 10)),
            "wide.png",
            "image/png",
            422,
            "INVALID_IMAGE",
            id="9000x10",
        ),
    ],
)
def test_upload_validation_codes(
    t4: T4World, data: bytes, filename: str, content_type: str, status: int, code: str
):
    assert_error(
        upload(t4, data, filename=filename, content_type=content_type), status, code
    )


def test_mime_comes_from_content_not_declared_type(t4: T4World):
    img = upload_ok(t4, png(), filename="lies.jpg", content_type="image/jpeg")
    assert img["mime_type"] == "image/png"
    r = get_image(t4, img["id"])
    assert r.headers["content-type"] == "image/png"


# ---------------------------------------------------------------------------
# Test 3 — metadata stripping
# ---------------------------------------------------------------------------


def test_jpeg_exif_stripped_and_rotated_upright(t4: T4World):
    src = encode(picture((400, 200)), "JPEG", quality=95, exif=gps_exif(orientation=6))
    assert open_image(src).getexif()  # the source really carries EXIF

    meta = upload_ok(t4, src, filename="photo.jpg", content_type="image/jpeg")
    assert (meta["width"], meta["height"]) == (200, 400)
    assert meta["mime_type"] == "image/jpeg"

    data = get_image(t4, meta["id"]).content
    img = open_image(data)
    assert not img.getexif()
    assert "exif" not in img.info
    assert img.size == (200, 400)
    assert meta["byte_size"] == len(data)
    assert meta["sha256"] == hashlib.sha256(data).hexdigest()


def test_png_text_chunk_removed(t4: T4World):
    info = PngInfo()
    info.add_text("Comment", "secret location")
    src = encode(picture(), "PNG", pnginfo=info)
    meta = upload_ok(t4, src)
    data = get_image(t4, meta["id"]).content
    assert open_image(data).text == {}
    assert b"secret location" not in data


def test_jpeg_icc_profile_kept(t4: T4World):
    icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    src = encode(picture(), "JPEG", icc_profile=icc, exif=gps_exif())
    meta = upload_ok(t4, src, filename="a.jpg", content_type="image/jpeg")
    img = open_image(get_image(t4, meta["id"]).content)
    assert img.info.get("icc_profile") == icc
    assert not img.getexif()


def test_jpeg_photoshop_app13_removed(t4: T4World):
    clean = encode(picture(), "JPEG")
    payload = b"Photoshop 3.0\x008BIM secret caption"
    segment = b"\xff\xed" + (len(payload) + 2).to_bytes(2, "big") + payload
    src = clean[:2] + segment + clean[2:]
    assert ("APP13", payload) in open_image(src).applist

    meta = upload_ok(t4, src, filename="a.jpg", content_type="image/jpeg")
    data = get_image(t4, meta["id"]).content
    assert [m for m, _ in open_image(data).applist] == ["APP0"]
    assert b"secret caption" not in data


def test_sample_us_map_uploads_under_limit(t4: T4World):
    meta = upload_ok(t4, US_MAP.read_bytes())
    assert meta["mime_type"] == "image/png"
    assert (meta["width"], meta["height"]) == (3600, 3600)
    assert meta["byte_size"] <= 2 * 1024 * 1024


# ---------------------------------------------------------------------------
# Test 4 — GET
# ---------------------------------------------------------------------------


def test_guest_can_read_image_with_cache_headers(t4: T4World):
    meta = upload_ok(t4, png())
    guest = guest_token(t4)
    r = get_image(t4, meta["id"], guest)
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.headers["cache-control"] == "private, max-age=31536000, immutable"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["content-disposition"] == "inline"
    assert len(r.content) == meta["byte_size"]


def test_get_unknown_or_malformed_404_and_no_list(t4: T4World):
    assert_error(get_image(t4, str(uuid.uuid4())), 404, "NOT_FOUND")
    assert_error(get_image(t4, "not-a-uuid"), 404, "NOT_FOUND")
    assert_error(get_image(t4, "1"), 404, "NOT_FOUND")
    assert t4.request("GET", "/images").status_code in (404, 405)
    assert t4.request("GET", "/images/").status_code in (404, 405)


def test_get_requires_auth(t4: T4World):
    meta = upload_ok(t4, png())
    r = httpx.get(f"{t4.base_url}/api/images/{meta['id']}", timeout=10.0)
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Question helpers
# ---------------------------------------------------------------------------


def map_pin_question(
    image_id: str,
    *,
    grading_type: str = "ACCURACY",
    target: tuple[float, float] = (0.5, 0.5),
    full: float = 0.04,
    zero: float = 0.15,
    points: float = 10,
    prompt: str = "Where is Denver?",
    **config_extra,
) -> dict:
    return {
        "type": "map_pin",
        "grading_type": grading_type,
        "prompt": prompt,
        "config": {"imageId": image_id, **config_extra},
        "answer_data": {
            "targets": [{"x": target[0], "y": target[1]}],
            "fullRadius": full,
            "zeroRadius": zero,
        },
        "points_value": points,
        "time_limit_seconds": 30,
    }


def create_q(
    t4: T4World,
    game_id: int,
    body: dict,
    token: str | None = None,
    *,
    host: bool = False,
) -> httpx.Response:
    prefix = "/host" if host else "/admin"
    return t4.request("POST", f"{prefix}/games/{game_id}/questions", token, json=body)


def update_q(
    t4: T4World,
    game_id: int,
    question_id: int,
    body: dict,
    token: str | None = None,
    *,
    host: bool = False,
) -> httpx.Response:
    prefix = "/host" if host else "/admin"
    return t4.request(
        "PUT", f"{prefix}/games/{game_id}/questions/{question_id}", token, json=body
    )


def list_qs(t4: T4World, game_id: int) -> dict[int, dict]:
    r = t4.request("GET", f"/admin/games/{game_id}/questions")
    assert r.status_code == 200, r.text
    return {q["id"]: q for q in r.json()}


def assert_validation_error(r: httpx.Response) -> None:
    assert r.status_code == 422, r.text
    assert r.json().get("error") == "VALIDATION_ERROR", r.text


# ---------------------------------------------------------------------------
# Test 5 — create validation
# ---------------------------------------------------------------------------


def test_create_map_pin_stores_server_dimensions(t4: T4World):
    game = t4.game(t4.course())
    img = upload_ok(t4, png((800, 400)))
    r = create_q(t4, game, map_pin_question(img["id"], imageWidth=5, imageHeight=5))
    assert r.status_code == 201, r.text
    assert r.json()["config"] == {
        "imageId": img["id"],
        "imageWidth": 800,
        "imageHeight": 400,
    }
    assert r.json()["answer_data"]["targets"] == [{"x": 0.5, "y": 0.5}]


def test_create_map_pin_missing_image(t4: T4World):
    game = t4.game(t4.course())
    assert_error(
        create_q(t4, game, map_pin_question(str(uuid.uuid4()))), 422, "IMAGE_NOT_FOUND"
    )
    # Not UUID-shaped is allowed by the schema; it just doesn't exist.
    assert_error(create_q(t4, game, map_pin_question("map1")), 422, "IMAGE_NOT_FOUND")


def _mutations(image_id: str) -> dict[str, dict]:
    base = map_pin_question(image_id)

    def with_answer(**changes) -> dict:
        return {**base, "answer_data": {**base["answer_data"], **changes}}

    def with_config(**changes) -> dict:
        return {**base, "config": {**base["config"], **changes}}

    return {
        "zero-targets": with_answer(targets=[]),
        "two-targets": with_answer(
            targets=[{"x": 0.1, "y": 0.1}, {"x": 0.2, "y": 0.2}]
        ),
        "full-equals-zero": with_answer(fullRadius=0.1, zeroRadius=0.1),
        "full-above-zero": with_answer(fullRadius=0.2, zeroRadius=0.1),
        "full-below-floor": with_answer(fullRadius=0.019, zeroRadius=0.1),
        "zero-above-2": with_answer(zeroRadius=2.01),
        "x-bool": with_answer(targets=[{"x": True, "y": 0.5}]),
        "x-out-of-range": with_answer(targets=[{"x": 1.5, "y": 0.5}]),
        "x-string": with_answer(targets=[{"x": "0.5", "y": 0.5}]),
        "target-extra-key": with_answer(targets=[{"x": 0.5, "y": 0.5, "z": 0}]),
        "answer-extra-key": with_answer(hint="near the rockies"),
        "missing-radius": {**base, "answer_data": {"targets": [{"x": 0.5, "y": 0.5}]}},
        "imageWidth-string": with_config(imageWidth="abc"),
        "imageWidth-bool": with_config(imageWidth=True),
        "imageWidth-zero": with_config(imageWidth=0),
        "config-extra-key": with_config(caption="x"),
        "imageId-missing": {**base, "config": {}},
        "imageId-too-long": with_config(imageId="x" * 65),
        "completeness-no-target": {
            **base,
            "grading_type": "COMPLETENESS",
            "answer_data": {},
        },
    }


@pytest.mark.parametrize("case", sorted(_mutations("x")))
def test_create_map_pin_rejects(t4: T4World, case: str):
    game = t4.game(t4.course())
    img = upload_ok(t4, png())
    assert_validation_error(create_q(t4, game, _mutations(img["id"])[case]))
    assert list_qs(t4, game) == {}


def test_create_map_pin_completeness_with_target(t4: T4World):
    game = t4.game(t4.course())
    img = upload_ok(t4, png())
    r = create_q(t4, game, map_pin_question(img["id"], grading_type="COMPLETENESS"))
    assert r.status_code == 201, r.text


def test_create_map_pin_accepts_boundaries(t4: T4World):
    game = t4.game(t4.course())
    img = upload_ok(t4, png())
    for body in (
        map_pin_question(img["id"], target=(0, 1), full=0.02, zero=2),
        map_pin_question(img["id"], target=(1, 0), full=1, zero=1.5),
    ):
        r = create_q(t4, game, body)
        assert r.status_code == 201, r.text


def test_host_create_map_pin(t4: T4World):
    course = t4.course()
    game = t4.game(course)
    host = t4.user()
    t4.grant_course(host, course)
    img = upload_ok(t4, png((300, 600)), token=host.token, host_course=course)
    r = create_q(t4, game, map_pin_question(img["id"]), host.token, host=True)
    assert r.status_code == 201, r.text
    assert r.json()["config"]["imageHeight"] == 600


# ---------------------------------------------------------------------------
# Test 6 — update symmetry (admin and host routes)
# ---------------------------------------------------------------------------


@pytest.fixture(params=["admin", "host"])
def editor(request, t4: T4World):
    """(t4, game_id, token, host flag) for the admin or a course host."""
    course = t4.course()
    game = t4.game(course)
    if request.param == "admin":
        return game, None, False
    host = t4.user()
    t4.grant_course(host, course)
    return game, host.token, True


def test_update_invalid_answer_data_rejected_row_unchanged(t4: T4World, editor):
    game, token, host = editor
    img = upload_ok(t4, png())
    q = create_q(t4, game, map_pin_question(img["id"])).json()

    r = update_q(t4, game, q["id"], {"answer_data": {"targets": []}}, token, host=host)
    assert_validation_error(r)
    assert list_qs(t4, game)[q["id"]]["answer_data"] == q["answer_data"]


def test_update_type_change_without_config_rejected(t4: T4World, editor):
    game, token, host = editor
    mc = create_q(t4, game, t4_helpers.MC_QUESTION).json()

    r = update_q(t4, game, mc["id"], {"type": "map_pin"}, token, host=host)
    assert_validation_error(r)
    assert list_qs(t4, game)[mc["id"]]["type"] == "multiple_choice"


def test_update_valid_map_pin(t4: T4World, editor):
    game, token, host = editor
    img = upload_ok(t4, png((800, 400)))
    other = upload_ok(t4, png((100, 300)))
    q = create_q(t4, game, map_pin_question(img["id"])).json()

    r = update_q(
        t4,
        game,
        q["id"],
        {
            "prompt": "Where is <b>Boise</b>?<script>x</script>",
            "config": {"imageId": other["id"], "imageWidth": 1},
            "answer_data": {
                "targets": [{"x": 0.2, "y": 0.3}],
                "fullRadius": 0.05,
                "zeroRadius": 0.2,
            },
        },
        token,
        host=host,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["config"] == {
        "imageId": other["id"],
        "imageWidth": 100,
        "imageHeight": 300,
    }
    assert body["answer_data"]["targets"] == [{"x": 0.2, "y": 0.3}]
    assert "<script>" not in body["prompt"]
    assert "<b>Boise</b>" in body["prompt"]


def test_update_prompt_only_keeps_map_pin(t4: T4World, editor):
    game, token, host = editor
    img = upload_ok(t4, png((800, 400)))
    q = create_q(t4, game, map_pin_question(img["id"])).json()
    r = update_q(t4, game, q["id"], {"prompt": "Where is Austin?"}, token, host=host)
    assert r.status_code == 200, r.text
    assert r.json()["config"] == q["config"]
    assert r.json()["answer_data"] == q["answer_data"]


def test_update_missing_image_rejected(t4: T4World, editor):
    game, token, host = editor
    img = upload_ok(t4, png())
    q = create_q(t4, game, map_pin_question(img["id"])).json()
    r = update_q(
        t4, game, q["id"], {"config": {"imageId": str(uuid.uuid4())}}, token, host=host
    )
    assert_error(r, 422, "IMAGE_NOT_FOUND")
    assert list_qs(t4, game)[q["id"]]["config"] == q["config"]


def test_update_other_types_still_validated(t4: T4World, editor):
    """The merged-validation fix applies to every type, not just map_pin."""
    game, token, host = editor
    mc = create_q(t4, game, t4_helpers.MC_QUESTION).json()
    r = update_q(
        t4, game, mc["id"], {"answer_data": {"answer_points": [1]}}, token, host=host
    )
    assert_validation_error(r)
    r = update_q(t4, game, mc["id"], {"prompt": "Renamed"}, token, host=host)
    assert r.status_code == 200, r.text
    assert r.json()["answer_data"] == mc["answer_data"]


# ---------------------------------------------------------------------------
# Live game helpers (sockets)
# ---------------------------------------------------------------------------


@dataclass
class LiveGame:
    host: SocketClient
    players: list[SocketClient]
    room_code: str
    session_id: str

    async def close(self) -> None:
        for c in (self.host, *self.players):
            await c.disconnect()


async def open_game(t4: T4World, course: int, game: int, n_players: int) -> LiveGame:
    """Room + guests, everyone joined, host first. Nothing started yet."""
    r = t4.create_room(game, course)
    assert r.status_code == 201, r.text
    room_code, session_id = r.json()["room_code"], r.json()["session_id"]
    tokens = [t4.guest_token(room_code) for _ in range(n_players)]
    host = SocketClient(t4.base_url, t4.admin_token, "host")
    players = [SocketClient(t4.base_url, tok, f"p{i}") for i, tok in enumerate(tokens)]
    live = LiveGame(host, players, room_code, session_id)
    try:
        await host.connect()
        await host.emit("join_room", {"room_code": room_code, "role": "HOST"})
        await host.wait_for("sync_state")
        for p in players:
            await p.connect()
            await p.emit("join_room", {"room_code": room_code, "role": "PLAYER"})
            await host.wait_for("player_joined")
    except BaseException:
        await live.close()
        raise
    return live


async def next_question(live: LiveGame) -> int:
    """host_advance into the next question; returns its ID (as every player sees it)."""
    await live.host.emit("host_advance", {})
    qid = (await live.host.wait_for("new_question"))["questionId"]
    for p in live.players:
        assert (await p.wait_for("new_question"))["questionId"] == qid
    return qid


async def submit(player: SocketClient, qid: int, answer: object) -> tuple[str, dict]:
    """("answer_received" | "error", payload)."""
    await player.emit(
        "submit_answer",
        {"question_id": qid, "answer_data": answer, "answer_time_ms": 500},
    )
    ok = asyncio.ensure_future(player.wait_for("answer_received"))
    err = asyncio.ensure_future(player.wait_for("error"))
    done, pending = await asyncio.wait(
        {ok, err}, timeout=10.0, return_when=asyncio.FIRST_COMPLETED
    )
    for task in pending:
        task.cancel()
    assert done, f"[{player.label}] no answer_received or error"
    task = done.pop()
    return ("answer_received" if task is ok else "error"), task.result()


async def results(live: LiveGame) -> dict:
    """host_advance QUESTION → RESULTS; returns the host's question_results."""
    await live.host.emit("host_advance", {})
    host_results = await live.host.wait_for("question_results")
    for p in live.players:
        await p.wait_for("question_results")
    return host_results


async def finish(live: LiveGame) -> dict:
    """host_advance from the last RESULTS; returns the host's game_over."""
    await live.host.emit("host_advance", {})
    return await live.host.wait_for("game_over")


def map_game(t4: T4World, questions: list[dict]) -> tuple[int, int, list[int]]:
    course = t4.course()
    game = t4.game(course)
    ids = []
    for body in questions:
        r = create_q(t4, game, body)
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])
    return course, game, ids


# ---------------------------------------------------------------------------
# Test 7 — scoring (non-square image, aspect 2)
# ---------------------------------------------------------------------------

FULL, ZERO = 0.04, 0.15
D_MID = (FULL + ZERO) / 2


async def test_scoring_end_to_end(t4: T4World):
    img = upload_ok(t4, png((800, 400)))
    course, game, _ = map_game(
        t4,
        [
            map_pin_question(img["id"], points=10),
            map_pin_question(img["id"], points=10, grading_type="COMPLETENESS"),
            map_pin_question(img["id"], points=7),
        ],
    )
    live = await open_game(t4, course, game, 4)
    try:
        # Q1: on target / horizontal mid / vertical mid (aspect-corrected) / beyond
        qid = await next_question(live)
        taps = [
            {"x": 0.5, "y": 0.5},
            {"x": 0.5 + D_MID, "y": 0.5},
            {"x": 0.5, "y": 0.5 + D_MID * 2},  # dy = d_mid × aspect = 0.19
            {"x": 0.5 + ZERO + 0.05, "y": 0.5},
        ]
        got = [await submit(p, qid, tap) for p, tap in zip(live.players, taps)]
        assert all(kind == "answer_received" for kind, _ in got), got
        points = [payload["pointsAwarded"] for _, payload in got]
        correct = [payload["isCorrect"] for _, payload in got]
        assert points[0] == 10
        assert points[1] == pytest.approx(5, abs=0.01)
        assert points[2] == pytest.approx(5, abs=0.01)
        assert points[3] == 0
        assert correct == [True, False, False, False]
        await results(live)

        # Q2 COMPLETENESS: full points even beyond zeroRadius
        qid = await next_question(live)
        kind, payload = await submit(live.players[0], qid, {"x": 0.0, "y": 0.0})
        assert kind == "answer_received"
        assert (payload["pointsAwarded"], payload["isCorrect"]) == (10, True)
        await results(live)

        # Q3 points 7 at 50% → 3.5
        qid = await next_question(live)
        kind, payload = await submit(live.players[0], qid, {"x": 0.5 + D_MID, "y": 0.5})
        assert kind == "answer_received"
        assert payload["pointsAwarded"] == 3.5
        assert payload["totalScore"] == 23.5
        await results(live)

        over = await finish(live)
        assert 23.5 in over["scores"]
        p0_over = await live.players[0].wait_for("game_over")
        assert p0_over["yourFinalScore"] == 23.5
    finally:
        await live.close()


# ---------------------------------------------------------------------------
# Test 8 — socket validation
# ---------------------------------------------------------------------------

BAD_ANSWERS = [
    {"x": "0.5", "y": 0.5},
    {"x": None, "y": 0.5},
    {"x": float("nan"), "y": 0.5},  # json.dumps writes a literal NaN
    {"x": 0.5},
    {"x": 0.5, "y": 0.5, "z": 1},
]


async def test_socket_rejects_bad_map_pin_answers(t4: T4World):
    img = upload_ok(t4, png())
    course, game, _ = map_game(t4, [map_pin_question(img["id"])])
    live = await open_game(t4, course, game, 1)
    try:
        qid = await next_question(live)
        player = live.players[0]
        for bad in BAD_ANSWERS:
            kind, payload = await submit(player, qid, bad)
            assert kind == "error", (bad, payload)
            assert payload["message"] == (
                "map_pin answer must include x and y between 0 and 1"
            )
            assert "code" not in payload  # fatal, not a timing rejection
        assert (await results(live))["totalAnswered"] == 0
    finally:
        await live.close()


# ---------------------------------------------------------------------------
# Test 9 — answer privacy and reveal
# ---------------------------------------------------------------------------


async def test_new_question_hides_answer_and_reveal_is_full(t4: T4World):
    img = upload_ok(t4, png((800, 400)))
    course, game, _ = map_game(
        t4,
        [
            map_pin_question(img["id"], target=(0.25, 0.75)),
            map_pin_question(img["id"], target=(0.6, 0.4), grading_type="COMPLETENESS"),
            {
                **t4_helpers.MC_QUESTION,
                "grading_type": "COMPLETENESS",
                "answer_data": {},
            },
        ],
    )
    live = await open_game(t4, course, game, 1)
    try:
        for target, grading in (
            ((0.25, 0.75), "ACCURACY"),
            ((0.6, 0.4), "COMPLETENESS"),
        ):
            await live.host.emit("host_advance", {})
            host_q = await live.host.wait_for("new_question")
            player_q = await live.players[0].wait_for("new_question")
            for payload in (host_q, player_q):
                text = json.dumps(payload)
                for secret in ("targets", "fullRadius", "zeroRadius", "answer_data"):
                    assert secret not in text, payload
                assert payload["config"] == {
                    "imageId": img["id"],
                    "imageWidth": 800,
                    "imageHeight": 400,
                }

            reveal = (await results(live))["answerReveal"]
            assert reveal == {
                "type": "map_pin",
                "gradingType": grading,
                "imageId": img["id"],
                "imageWidth": 800,
                "imageHeight": 400,
                "target": {"x": target[0], "y": target[1]},
                "fullRadius": FULL,
                "zeroRadius": ZERO,
            }

        # Regression guard: COMPLETENESS multiple_choice still reveals "completeness".
        await next_question(live)
        assert (await results(live))["answerReveal"] == {"type": "completeness"}
    finally:
        await live.close()


# ---------------------------------------------------------------------------
# Test 10 — distribution
# ---------------------------------------------------------------------------


async def test_distribution_buckets(t4: T4World):
    img = upload_ok(t4, png())
    course, game, _ = map_game(t4, [map_pin_question(img["id"])])
    live = await open_game(t4, course, game, 3)
    try:
        qid = await next_question(live)
        # Two taps in the same 2% cell (11,20), one elsewhere (49,49).
        taps = [
            {"x": 0.221, "y": 0.401},
            {"x": 0.239, "y": 0.419},
            {"x": 1.0, "y": 1.0},
        ]
        for p, tap in zip(live.players, taps):
            assert (await submit(p, qid, tap))[0] == "answer_received"
        host_results = await results(live)
        assert host_results["answerDistribution"] == {"11,20": 2, "49,49": 1}

        over = await finish(live)
        summary = over["questionSummary"][0]
        assert summary["answerDistribution"] == {"11,20": 2, "49,49": 1}
    finally:
        await live.close()


# ---------------------------------------------------------------------------
# Test 12 — preloading
# ---------------------------------------------------------------------------


async def test_preload_image_ids(t4: T4World):
    a = upload_ok(t4, png())
    b = upload_ok(t4, png((40, 80)))
    course, game, _ = map_game(
        t4,
        [
            map_pin_question(b["id"]),
            t4_helpers.MC_QUESTION,
            map_pin_question(a["id"]),
            map_pin_question(b["id"]),
        ],
    )
    live = await open_game(t4, course, game, 2)
    try:
        sync = await live.players[0].wait_for("sync_state")
        assert sync["imageIds"] == [b["id"], a["id"]]

        await live.host.emit("host_advance", {})
        for client in (live.host, *live.players):
            images = await client.wait_for("game_images")
            assert images == {"imageIds": [b["id"], a["id"]]}
            await client.wait_for("new_question")
            assert client.log.index("game_images") < client.log.index("new_question")
    finally:
        await live.close()


async def test_preload_image_ids_empty_without_map_pin(t4: T4World):
    course, game, _ = map_game(t4, [t4_helpers.MC_QUESTION])
    live = await open_game(t4, course, game, 1)
    try:
        assert (await live.players[0].wait_for("sync_state"))["imageIds"] == []
        await live.host.emit("host_advance", {})
        assert (await live.players[0].wait_for("game_images")) == {"imageIds": []}
    finally:
        await live.close()


async def test_preload_image_ids_on_rejoin_in_progress(t4: T4World):
    img = upload_ok(t4, png())
    course, game, _ = map_game(t4, [map_pin_question(img["id"])])
    live = await open_game(t4, course, game, 1)
    try:
        await next_question(live)
        late = SocketClient(t4.base_url, live.players[0].token, "rejoin")
        await late.connect()
        try:
            await late.emit("rejoin_room", {"room_code": live.room_code})
            assert (await late.wait_for("sync_state"))["imageIds"] == [img["id"]]
        finally:
            await late.disconnect()
    finally:
        await live.close()


# ---------------------------------------------------------------------------
# Test 13 — late answers are non-fatal (error codes)
# ---------------------------------------------------------------------------


async def test_late_answer_error_codes(t4: T4World):
    img = upload_ok(t4, png())
    course, game, _ = map_game(
        t4,
        [
            {**map_pin_question(img["id"]), "time_limit_seconds": 2},
            map_pin_question(img["id"]),
        ],
    )
    live = await open_game(t4, course, game, 1)
    player = live.players[0]
    tap = {"x": 0.5, "y": 0.5}
    try:
        q1 = await next_question(live)
        await player.wait_for("question_locked", timeout=10)
        kind, payload = await submit(player, q1, tap)
        assert (kind, payload.get("code")) == ("error", "QUESTION_LOCKED"), payload
        assert payload["message"] == "Question is locked"

        assert (await results(live))["totalAnswered"] == 0
        kind, payload = await submit(player, q1, tap)
        assert (kind, payload.get("code")) == ("error", "NO_ACTIVE_QUESTION"), payload

        q2 = await next_question(live)
        kind, payload = await submit(player, q1, tap)  # stale question_id
        assert (kind, payload.get("code")) == ("error", "QUESTION_MISMATCH"), payload
        assert payload["message"] == "Question ID does not match the active question"
        assert (await results(live))["totalAnswered"] == 0

        # The socket is still usable afterwards: nothing above was fatal server-side.
        assert q2 != q1
    finally:
        await live.close()


# ---------------------------------------------------------------------------
# Test 14 — host summary stats
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("grading", ["ACCURACY", "COMPLETENESS"])
async def test_host_summary_stats(t4: T4World, grading: str):
    img = upload_ok(t4, png((800, 400)))
    course, game, _ = map_game(
        t4,
        [
            map_pin_question(img["id"], grading_type=grading),
            map_pin_question(img["id"], grading_type=grading),  # nobody answers
        ],
    )
    live = await open_game(t4, course, game, 3)
    try:
        qid = await next_question(live)
        taps = [
            {"x": 0.5, "y": 0.5},  # d = 0, within
            {"x": 0.5 + D_MID, "y": 0.5},  # credit 0.5
            {"x": 0.5 + ZERO + 0.1, "y": 0.5},  # beyond zero
        ]
        for p, tap in zip(live.players, taps):
            assert (await submit(p, qid, tap))[0] == "answer_received"
        await results(live)
        await next_question(live)
        await results(live)

        summary = (await finish(live))["questionSummary"]
        assert summary[0]["withinFullPct"] == 33.3
        assert summary[0]["averageCredit"] == 0.5
        assert summary[0]["answerReveal"]["type"] == "map_pin"
        assert summary[1]["withinFullPct"] is None
        assert summary[1]["averageCredit"] is None
    finally:
        await live.close()


# ---------------------------------------------------------------------------
# Import / export helpers
# ---------------------------------------------------------------------------


def export_bundle(t4: T4World, game_id: int) -> dict:
    r = t4.request("GET", f"/admin/games/{game_id}/export")
    assert r.status_code == 200, r.text
    return r.json()


def import_bundle(
    t4: T4World, bundle: dict | bytes, course_id: int | None = None
) -> httpx.Response:
    body = bundle if isinstance(bundle, bytes) else json.dumps(bundle).encode()
    form = {"course_id": str(course_id)} if course_id is not None else None
    r = t4.request(
        "POST",
        "/admin/games/import",
        files={"file": ("game.json", body, "application/json")},
        data=form,
    )
    if r.status_code == 201:
        t4.track_game(r.json()["game_id"])
    return r


def image_row_count() -> int:
    """No list endpoint exists (by design), so count rows in the compose MySQL."""
    shell = 'mysql -N -uapp_user -p"$MYSQL_PASSWORD" buzzer -e "SELECT COUNT(*) FROM images"'
    out = subprocess.run(
        ["docker", "compose", "exec", "-T", "mysql", "sh", "-c", shell],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return int(out.stdout.strip())


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def hand_bundle(images: list[dict], questions: list[dict], version: int = 2) -> dict:
    bundle = {
        "format": "buzzer/game",
        "version": version,
        "game": {"title": f"Hand bundle {uuid.uuid4().hex[:6]}"},
        "questions": questions,
    }
    if images is not None:
        bundle["images"] = images
    return bundle


def game_titles(t4: T4World) -> set[str]:
    r = t4.request("GET", "/admin/games")
    assert r.status_code == 200, r.text
    return {g["title"] for g in r.json()}


# ---------------------------------------------------------------------------
# Test 11 — import/export round trip
# ---------------------------------------------------------------------------


def test_export_import_round_trip(t4: T4World):
    img = upload_ok(
        t4,
        encode(picture((300, 150)), "JPEG", exif=gps_exif()),
        filename="a.jpg",
        content_type="image/jpeg",
    )
    _, game, _ = map_game(
        t4,
        [
            map_pin_question(img["id"], target=(0.1, 0.2)),
            t4_helpers.MC_QUESTION,
            map_pin_question(img["id"], target=(0.7, 0.8), grading_type="COMPLETENESS"),
        ],
    )
    bundle = export_bundle(t4, game)
    assert bundle["version"] == 2
    assert [i["id"] for i in bundle["images"]] == [img["id"]]
    assert bundle["images"][0]["mime_type"] == "image/jpeg"
    original = get_image(t4, img["id"]).content
    assert base64.b64decode(bundle["images"][0]["data"]) == original

    before = image_row_count()
    r = import_bundle(t4, bundle)
    assert r.status_code == 201, r.text
    assert image_row_count() == before + 1  # one image, shared by both questions

    questions = sorted(
        list_qs(t4, r.json()["game_id"]).values(), key=lambda q: q["order_index"]
    )
    pins = [q for q in questions if q["type"] == "map_pin"]
    assert len(pins) == 2
    new_id = pins[0]["config"]["imageId"]
    assert new_id != img["id"]
    assert uuid.UUID(new_id)
    assert all(
        q["config"] == {"imageId": new_id, "imageWidth": 300, "imageHeight": 150}
        for q in pins
    )
    assert [q["answer_data"]["targets"] for q in pins] == [
        [{"x": 0.1, "y": 0.2}],
        [{"x": 0.7, "y": 0.8}],
    ]
    # Buzzer exports are already clean, so the bytes are kept exactly.
    assert get_image(t4, new_id).content == original


def test_import_missing_image_reference_creates_nothing(t4: T4World):
    q = map_pin_question("not-in-bundle")
    bundle = hand_bundle(
        [{"id": "map1", "mime_type": "image/png", "data": b64(png())}], [q]
    )
    before_images, before_titles = image_row_count(), game_titles(t4)
    r = import_bundle(t4, bundle)
    assert r.status_code == 422, r.text
    assert (
        r.json()["detail"] == "Question 1 references image not-in-bundle not in bundle"
    )
    assert image_row_count() == before_images
    assert bundle["game"]["title"] not in game_titles(t4) - before_titles


def test_import_server_image_reference_rejected(t4: T4World):
    """References to images already on the server are not allowed."""
    img = upload_ok(t4, png())
    r = import_bundle(t4, hand_bundle([], [map_pin_question(img["id"])]))
    assert r.status_code == 422, r.text
    assert "not in bundle" in r.json()["detail"]


def test_import_v1_without_map_pin(t4: T4World):
    bundle = hand_bundle(None, [t4_helpers.MC_QUESTION], version=1)
    r = import_bundle(t4, bundle)
    assert r.status_code == 201, r.text


def test_import_v1_with_images_rejected(t4: T4World):
    bundle = hand_bundle([], [t4_helpers.MC_QUESTION], version=1)
    r = import_bundle(t4, bundle)
    assert r.status_code == 422, r.text


def test_import_hand_made_exif_is_stripped(t4: T4World):
    src = encode(picture((400, 200)), "JPEG", quality=95, exif=gps_exif(orientation=6))
    bundle = hand_bundle(
        [{"id": "photo", "mime_type": "image/jpeg", "data": b64(src)}],
        [map_pin_question("photo")],
    )
    r = import_bundle(t4, bundle)
    assert r.status_code == 201, r.text
    (q,) = list_qs(t4, r.json()["game_id"]).values()
    assert (q["config"]["imageWidth"], q["config"]["imageHeight"]) == (200, 400)
    stored = open_image(get_image(t4, q["config"]["imageId"]).content)
    assert not stored.getexif()
    assert "exif" not in stored.info


@pytest.mark.parametrize(
    ("images", "detail_part"),
    [
        (
            {"id": "m", "mime_type": "image/png", "data": "!!!not base64!!!"},
            "not base64",
        ),
        (
            {"id": "m", "mime_type": "image/png", "data": b64(b"plain text")},
            "Image m invalid",
        ),
        (
            {
                "id": "m",
                "mime_type": "image/gif",
                "data": b64(encode(picture(), "GIF")),
            },
            "Image m invalid",
        ),
        ({"id": "", "mime_type": "image/png", "data": b64(png())}, "non-empty string"),
        ({"id": "m", "data": b64(png())}, "mime_type"),
    ],
)
def test_import_bad_referenced_image(t4: T4World, images: dict, detail_part: str):
    bundle = hand_bundle([images], [map_pin_question("m")])
    r = import_bundle(t4, bundle)
    assert r.status_code == 422, r.text
    assert detail_part in r.json()["detail"]


def test_import_image_list_limits(t4: T4World):
    entry = {"mime_type": "image/png", "data": b64(png())}
    too_many = [{"id": f"i{n}", **entry} for n in range(51)]
    r = import_bundle(t4, hand_bundle(too_many, [t4_helpers.MC_QUESTION]))
    assert r.status_code == 422, r.text
    dupes = [{"id": "x", **entry}, {"id": "x", **entry}]
    r = import_bundle(t4, hand_bundle(dupes, [t4_helpers.MC_QUESTION]))
    assert r.status_code == 422, r.text
    assert "appears twice" in r.json()["detail"]


def test_import_over_25mb_rejected(t4: T4World):
    r = import_bundle(t4, b" " * (25 * 1024 * 1024 + 1))
    assert r.status_code == 422, r.text
    assert "25 MB" in r.json()["detail"]


def test_export_without_map_pin_has_empty_images(t4: T4World):
    _, game, _ = map_game(t4, [t4_helpers.MC_QUESTION])
    bundle = export_bundle(t4, game)
    assert bundle["version"] == 2
    assert bundle["images"] == []


# ---------------------------------------------------------------------------
# Test 15 — import edge cases
# ---------------------------------------------------------------------------


def test_import_hand_made_id_is_remapped_to_uuid(t4: T4World):
    data = png((120, 60))
    bundle = hand_bundle(
        [{"id": "map1", "mime_type": "image/png", "data": b64(data)}],
        [map_pin_question("map1")],
    )
    r = import_bundle(t4, bundle)
    assert r.status_code == 201, r.text
    (q,) = list_qs(t4, r.json()["game_id"]).values()
    assert uuid.UUID(q["config"]["imageId"])
    assert q["config"]["imageWidth"] == 120
    assert get_image(t4, q["config"]["imageId"]).content == data  # clean PNG kept as-is


def test_import_unreferenced_bad_image_ignored(t4: T4World):
    bundle = hand_bundle(
        [
            {"id": "used", "mime_type": "image/png", "data": b64(png())},
            {"id": "stray", "mime_type": "image/png", "data": "%%% not base64 %%%"},
        ],
        [map_pin_question("used")],
    )
    before = image_row_count()
    r = import_bundle(t4, bundle)
    assert r.status_code == 201, r.text
    assert image_row_count() == before + 1  # only the referenced image is stored
