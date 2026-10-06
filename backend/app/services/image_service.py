"""Image storage and management (T7 spec docs/plans/t7-map-pin.md §4.3; T8 spec
docs/plans/t8-images.md §4.6–§4.7a).

Image bytes are immutable; only `alt_text` and `course_id` change in place. Every upload is rotated upright from its EXIF orientation and
re-encoded so no metadata (GPS EXIF, XMP, IPTC, comments, text chunks) reaches players;
the ICC colour profile is kept. Import re-encodes only images that still carry
metadata, so Buzzer's own (already clean) exports round-trip byte-for-byte.

`Image` is always the ORM model in this module; Pillow's is `PILImage`.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from io import BytesIO

import structlog
from PIL import Image as PILImage
from PIL import ImageOps
from sqlalchemy import String, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from ..common.exceptions import (
    BuzzerError,
    ConflictError,
    ForbiddenError,
    ImageInUseError,
    NotFoundError,
)
from ..models.game import Game, Question
from ..models.image import Image
from ..models.user import User
from . import access_service as access
from . import game_service

logger = structlog.get_logger()

MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_SIDE = 8000
MAX_PIXELS = 40_000_000

# Decoded Pillow format → stored mime. MPO is a multi-image (phone) JPEG: kept as JPEG.
_FORMAT_MIME = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "MPO": "image/jpeg",
    "WEBP": "image/webp",
}
_MIME_SAVE_FORMAT = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}

# What is *not* metadata, per format (§4.3 step 7). Everything else is.
_JPEG_ALLOWED_APP = (("APP0", b"JFIF"), ("APP2", b"ICC_PROFILE"), ("APP14", b"Adobe"))
_JPEG_ALLOWED_INFO = frozenset(
    {
        "jfif",
        "jfif_version",
        "jfif_unit",
        "jfif_density",
        "dpi",
        "progressive",
        "progression",
        "adobe",
        "adobe_transform",
        "icc_profile",
    }
)
_PNG_ALLOWED_INFO = frozenset(
    {"icc_profile", "dpi", "gamma", "transparency", "srgb", "chromaticity", "aspect"}
)
_WEBP_ALLOWED_CHUNKS = frozenset({b"VP8 ", b"VP8L", b"VP8X", b"ALPH", b"ICCP"})

_PNG_IEND = b"\x00\x00\x00\x00IEND\xaeB`\x82"
_JPEG_EOI = b"\xff\xd9"


@dataclass(frozen=True)
class PreparedImage:
    data: bytes
    mime: str
    width: int
    height: int
    sha256: str


def _too_large() -> BuzzerError:
    return BuzzerError("IMAGE_TOO_LARGE", "Image must be at most 2 MB", 413)


def _invalid(message: str = "File is not a valid image") -> BuzzerError:
    return BuzzerError("INVALID_IMAGE", message, 422)


def _unsupported(message: str = "Image must be PNG, JPEG or WebP") -> BuzzerError:
    return BuzzerError("UNSUPPORTED_IMAGE_TYPE", message, 415)


def _webp_chunks(raw: bytes) -> list[bytes] | None:
    """FourCCs of the chunks after the 12-byte RIFF/WEBP header, in order.

    Returns None when the RIFF structure doesn't account for every byte of `raw`
    (truncated, or trailing data after the RIFF): the caller treats that as metadata.
    """
    if len(raw) < 12 or raw[:4] != b"RIFF" or raw[8:12] != b"WEBP":
        return None
    if int.from_bytes(raw[4:8], "little") + 8 != len(raw):
        return None
    chunks: list[bytes] = []
    pos = 12
    while pos + 8 <= len(raw):
        size = int.from_bytes(raw[pos + 4 : pos + 8], "little")
        chunks.append(raw[pos : pos + 4])
        pos += 8 + size + (size & 1)
    return chunks if pos == len(raw) else None


def _has_metadata(img: PILImage.Image, raw: bytes) -> bool:
    fmt = img.format
    if fmt == "MPO":
        return True  # the MPF segment and secondary images
    if fmt == "JPEG":
        for marker, segment in getattr(img, "applist", []):
            if not any(
                marker == m and segment.startswith(prefix)
                for m, prefix in _JPEG_ALLOWED_APP
            ):
                return True
        return any(k not in _JPEG_ALLOWED_INFO for k in img.info) or not raw.endswith(
            _JPEG_EOI
        )
    if fmt == "PNG":
        return (
            bool(getattr(img, "text", None))
            or any(k not in _PNG_ALLOWED_INFO for k in img.info)
            or not raw.endswith(_PNG_IEND)
        )
    if fmt == "WEBP":
        # Pillow's `info` carries container fields for every WebP, so check chunks.
        chunks = _webp_chunks(raw)
        return chunks is None or any(c not in _WEBP_ALLOWED_CHUNKS for c in chunks)
    return True


def _reencode(img: PILImage.Image, mime: str, raw: bytes) -> bytes:
    icc = img.info.get("icc_profile")
    out = ImageOps.exif_transpose(img)
    # Keep only what the encoders should carry over; everything else is metadata.
    out.info = {k: v for k, v in out.info.items() if k == "transparency"}

    fmt = _MIME_SAVE_FORMAT[mime]
    kwargs: dict = {}
    if icc:
        kwargs["icc_profile"] = icc
    if fmt == "JPEG":
        kwargs["quality"] = 90
    elif fmt == "PNG":
        kwargs["optimize"] = True
    else:
        chunks = _webp_chunks(raw) or []
        if b"VP8L" in chunks:
            kwargs["lossless"] = True
        else:
            kwargs["quality"] = 90

    buf = BytesIO()
    try:
        out.save(buf, fmt, **kwargs)
    except Exception as exc:  # e.g. a mode the encoder can't write
        logger.warning(
            "image_reencode_failed", mime=mime, mode=out.mode, error=str(exc)
        )
        raise _invalid("Image could not be processed") from exc
    return buf.getvalue()


def prepare_image(raw: bytes, *, force_reencode: bool = True) -> PreparedImage:
    """Validate an image and strip its metadata. Steps follow spec §4.3 in order."""
    if len(raw) > MAX_IMAGE_BYTES:
        raise _too_large()

    try:
        img = PILImage.open(BytesIO(raw))
    except Exception as exc:
        raise _invalid() from exc

    mime = _FORMAT_MIME.get(img.format or "")
    if mime is None:
        raise _unsupported()

    if img.format != "MPO" and (
        getattr(img, "is_animated", False) or getattr(img, "n_frames", 1) > 1
    ):
        raise _unsupported("Animated images are not supported")

    # Decompression-bomb guard: header size, before anything is decoded.
    width, height = img.size
    if not (1 <= width <= MAX_SIDE and 1 <= height <= MAX_SIDE):
        raise _invalid(f"Image sides must be between 1 and {MAX_SIDE} pixels")
    if width * height > MAX_PIXELS:
        raise _invalid("Image has too many pixels")

    try:
        img.load()
    except Exception as exc:
        raise _invalid() from exc

    if force_reencode or _has_metadata(img, raw):
        data = _reencode(img, mime, raw)
        with PILImage.open(BytesIO(data)) as out:
            width, height = out.size
    else:
        data = raw

    if len(data) > MAX_IMAGE_BYTES:
        raise _too_large()

    return PreparedImage(
        data=data,
        mime=mime,
        width=width,
        height=height,
        sha256=hashlib.sha256(data).hexdigest(),
    )


async def store_prepared(
    db: AsyncSession,
    prepared: PreparedImage,
    user: User | None,
    course_id: int | None,
    alt_text: str = "",
) -> Image:
    """Insert with a new UUID and flush. The caller owns the transaction."""
    image = Image(
        id=str(uuid.uuid4()),
        mime_type=prepared.mime,
        width=prepared.width,
        height=prepared.height,
        byte_size=len(prepared.data),
        sha256=prepared.sha256,
        data=prepared.data,
        uploaded_by_user_id=user.id if user else None,
        course_id=course_id,
        alt_text=alt_text,
    )
    db.add(image)
    await db.flush()
    # created_at is a server default: load it now, since responses read it after
    # the session can no longer lazy-load (async).
    await db.refresh(image, ["created_at"])
    logger.info(
        "image_stored",
        image_id=image.id,
        mime=image.mime_type,
        byte_size=image.byte_size,
        course_id=course_id,
    )
    return image


async def store_image(
    db: AsyncSession, raw: bytes, user: User, course_id: int | None, alt_text: str = ""
) -> Image:
    """Upload path: always re-encoded."""
    return await store_prepared(
        db, prepare_image(raw, force_reencode=True), user, course_id, alt_text
    )


def _canonical_id(image_id: str) -> str | None:
    try:
        parsed = uuid.UUID(image_id)
    except (ValueError, TypeError, AttributeError):
        return None
    return image_id if str(parsed) == image_id else None


async def get_image(db: AsyncSession, image_id: str) -> Image | None:
    """Metadata only (`data` stays deferred). None for a malformed ID, without querying."""
    if _canonical_id(image_id) is None:
        return None
    return await db.get(Image, image_id)


async def get_image_with_data(db: AsyncSession, image_id: str) -> Image | None:
    if _canonical_id(image_id) is None:
        return None
    result = await db.execute(
        select(Image).where(Image.id == image_id).options(undefer(Image.data))
    )
    return result.scalar_one_or_none()


async def get_images_meta(db: AsyncSession, ids: set[str]) -> dict[str, Image]:
    """One `SELECT … WHERE id IN`, without `data`."""
    if not ids:
        return {}
    result = await db.execute(select(Image).where(Image.id.in_(ids)))
    return {image.id: image for image in result.scalars().all()}


# ---------------------------------------------------------------------------
# T8: alt text, usage, delete, replace, and images following their game.
# Lock order everywhere (spec §4.0): game rows → image rows → question rows.
# ---------------------------------------------------------------------------

ALT_TEXT_MAX = 250
ASPECT_TOLERANCE = 0.01


def clean_alt_text(value: str | None) -> str:
    """Upload/replace form field: stripped, at most 250 chars, else 422."""
    text = (value or "").strip()
    if len(text) > ALT_TEXT_MAX:
        raise BuzzerError(
            "VALIDATION_ERROR",
            f"alt_text must be at most {ALT_TEXT_MAX} characters",
            422,
        )
    return text


async def lock_images(
    db: AsyncSession, ids: set[str], *, read: bool
) -> dict[str, Image]:
    """`SELECT … WHERE id IN (…) ORDER BY id FOR SHARE|FOR UPDATE`, metadata only."""
    if not ids:
        return {}
    result = await db.execute(
        select(Image)
        .where(Image.id.in_(ids))
        .order_by(Image.id)
        .with_for_update(read=read)
        .execution_options(populate_existing=True)
    )
    return {image.id: image for image in result.scalars().all()}


async def image_usage(
    db: AsyncSession, image_ids: set[str], *, lock: bool
) -> dict[str, list[dict]]:
    """Every use of each image, as `ImageUsage`-shaped dicts (spec §4.6).

    The `LIKE '%imageid%'` pre-filter can't miss a reference: all three keys contain
    `imageid` case-insensitively. With `lock=True` it is a locking read on **question
    rows only** (`FOR SHARE OF questions`); without `OF`, MySQL would also lock the
    joined game rows, taking a game lock after an image lock.
    """
    usage: dict[str, list[dict]] = {i: [] for i in image_ids}
    if not image_ids:
        return usage
    stmt = (
        select(
            Question.id,
            Question.game_id,
            Question.type,
            Question.config,
            Game.title,
            Game.course_id,
        )
        .join(Game, Game.id == Question.game_id)
        .where(func.lower(cast(Question.config, String)).like("%imageid%"))
    )
    if lock:
        stmt = stmt.with_for_update(read=True, of=Question)
    rows = (await db.execute(stmt)).all()

    found: list[tuple[str, dict]] = []
    for qid, game_id, type_, config, title, course_id in rows:
        seen_roles: set[tuple[str, str]] = set()
        for image_id, role in game_service.question_image_ids(type_, config):
            if image_id not in image_ids or (image_id, role) in seen_roles:
                continue
            seen_roles.add((image_id, role))
            found.append(
                (
                    image_id,
                    {
                        "game_id": game_id,
                        "game_title": title,
                        "course_id": course_id,
                        "question_id": qid,
                        "question_number": 0,
                        "role": role,
                    },
                )
            )
    if not found:
        return usage

    # Position in the game (order_index has gaps after deletes).
    game_ids = {u["game_id"] for _, u in found}
    positions: dict[int, int] = {}
    counters: dict[int, int] = {}
    ordered = await db.execute(
        select(Question.id, Question.game_id)
        .where(Question.game_id.in_(game_ids))
        .order_by(Question.game_id, Question.order_index, Question.id)
    )
    for qid, game_id in ordered.all():
        counters[game_id] = counters.get(game_id, 0) + 1
        positions[qid] = counters[game_id]
    for image_id, u in found:
        u["question_number"] = positions.get(u["question_id"], 0)
        usage[image_id].append(u)
    return usage


async def visible_usage(
    db: AsyncSession, user: User, uses: list[dict]
) -> tuple[list[dict], int]:
    """Split uses into those in games the caller can use, and a count of the rest."""
    if user.role == "ADMIN" or not uses:
        return uses, 0
    allowed: dict[int, bool] = {}
    for game_id in {u["game_id"] for u in uses}:
        game = await db.get(Game, game_id)
        allowed[game_id] = bool(game) and await access.can_use_game(db, user, game)
    visible = [u for u in uses if allowed[u["game_id"]]]
    hidden = len({u["question_id"] for u in uses if not allowed[u["game_id"]]})
    return visible, hidden


async def list_images(
    db: AsyncSession,
    user: User,
    *,
    course_id: int | None = None,
    unassigned: bool = False,
) -> list[dict]:
    """Images newest first, each with `usage` and `hidden_usage_count`."""
    stmt = select(Image).order_by(Image.created_at.desc(), Image.id)
    if unassigned:
        stmt = stmt.where(Image.course_id.is_(None))
    elif course_id is not None:
        stmt = stmt.where(Image.course_id == course_id)
    images = list((await db.execute(stmt)).scalars().all())
    usage = await image_usage(db, {i.id for i in images}, lock=False)
    items = []
    for image in images:
        visible, hidden = await visible_usage(db, user, usage[image.id])
        items.append(
            {
                "id": image.id,
                "mime_type": image.mime_type,
                "width": image.width,
                "height": image.height,
                "byte_size": image.byte_size,
                "sha256": image.sha256,
                "alt_text": image.alt_text,
                "course_id": image.course_id,
                "created_at": image.created_at,
                "usage": visible,
                "hidden_usage_count": hidden,
            }
        )
    return items


async def set_alt_text(db: AsyncSession, image: Image, alt_text: str) -> Image:
    image.alt_text = alt_text
    await db.flush()
    return image


async def delete_image(db: AsyncSession, image: Image, user: User) -> None:
    """Delete an unused image (spec §4.6). No game lock: an image in use can't be
    deleted, and an unused one isn't in any live game. Flush only."""
    locked = (await lock_images(db, {image.id}, read=False)).get(image.id)
    if locked is None:
        raise NotFoundError(f"Image {image.id} not found")
    uses = (await image_usage(db, {image.id}, lock=True))[image.id]
    if uses:
        visible, hidden = await visible_usage(db, user, uses)
        raise ImageInUseError(visible, hidden)
    await db.delete(locked)
    await db.flush()
    logger.info("image_deleted", image_id=image.id, user_id=user.id)


async def _questions_by_id(
    db: AsyncSession, question_ids: set[int]
) -> dict[int, Question]:
    if not question_ids:
        return {}
    result = await db.execute(
        select(Question)
        .where(Question.id.in_(question_ids))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return {q.id: q for q in result.scalars().all()}


async def replace_image(
    db: AsyncSession,
    redis,
    old: Image,
    raw: bytes,
    alt_text: str | None,
    user: User,
) -> Image:
    """Upload a new image and re-point every question that used `old` (spec §4.7).
    Flush only; the router commits."""
    prepared = prepare_image(raw, force_reencode=True)  # before any lock

    before = (await image_usage(db, {old.id}, lock=False))[old.id]
    locked_games = sorted({u["game_id"] for u in before})
    for game_id in locked_games:
        await game_service.lock_game(db, game_id)
        await game_service.assert_not_live(db, redis, game_id)

    locked = (await lock_images(db, {old.id}, read=False)).get(old.id)
    if locked is None:
        raise NotFoundError(f"Image {old.id} not found")
    uses = (await image_usage(db, {old.id}, lock=True))[old.id]
    if any(u["game_id"] not in locked_games for u in uses):
        raise ConflictError("Image usage changed; try again")

    if user.role != "ADMIN":
        _, hidden = await visible_usage(db, user, uses)
        if hidden:
            raise ForbiddenError("This image is also used in games you can't access")

    if any(u["role"] == "map" for u in uses):
        old_aspect = locked.width / locked.height
        new_aspect = prepared.width / prepared.height
        if abs(new_aspect - old_aspect) / old_aspect > ASPECT_TOLERANCE:
            raise BuzzerError(
                "IMAGE_ASPECT_MISMATCH",
                "The new image's shape differs from the old one, which would move "
                "map-pin targets",
                422,
            )

    new = await store_prepared(
        db,
        prepared,
        user,
        locked.course_id,
        locked.alt_text if alt_text is None else alt_text,
    )
    questions = await _questions_by_id(db, {u["question_id"] for u in uses})
    for q in questions.values():
        config = game_service.repoint_config(q.type, q.config or {}, old.id, new.id)
        if q.type == "map_pin" and config.get("imageId") == new.id:
            config["imageWidth"] = new.width
            config["imageHeight"] = new.height
        q.config = config
    await db.flush()
    logger.info(
        "image_replaced",
        old_image_id=old.id,
        new_image_id=new.id,
        questions=len(questions),
        user_id=user.id,
    )
    return new


@dataclass(frozen=True)
class ImageRehome:
    moved: int
    copied: int


async def rehome_game_images(
    db: AsyncSession,
    game: Game,
    new_course_id: int,
    user: User,
    *,
    apply: bool,
) -> ImageRehome:
    """Images follow a game to its course (spec §4.7a): an image only this game uses
    is re-tagged; one shared with other games is copied and this game re-pointed.

    `apply=False` only counts (unlocked). `apply=True` expects the caller to hold the
    game-row lock; it then locks images `FOR UPDATE` and scans question rows `FOR
    SHARE` (game → image → question rows). Flush only.
    """
    stmt = select(Question).where(Question.game_id == game.id)
    if apply:
        stmt = stmt.with_for_update(read=True).execution_options(populate_existing=True)
    questions = list((await db.execute(stmt)).scalars().all())
    ids = set(game_service.game_image_ids(questions, "host"))
    if not ids:
        return ImageRehome(0, 0)

    if apply:
        images = await lock_images(db, ids, read=False)
    else:
        images = await get_images_meta(db, ids)
    usage = await image_usage(db, set(images), lock=apply)

    to_move: list[Image] = []
    to_copy: list[Image] = []
    for image_id in sorted(images):
        image = images[image_id]
        if image.course_id == new_course_id:
            continue
        shared = any(u["game_id"] != game.id for u in usage[image_id])
        (to_copy if shared else to_move).append(image)

    if apply:
        for image in to_move:
            image.course_id = new_course_id
        for image in to_copy:
            original = await get_image_with_data(db, image.id)
            copy = Image(
                id=str(uuid.uuid4()),
                mime_type=original.mime_type,
                width=original.width,
                height=original.height,
                byte_size=original.byte_size,
                sha256=original.sha256,
                data=original.data,
                uploaded_by_user_id=user.id,
                course_id=new_course_id,
                alt_text=original.alt_text,
            )
            db.add(copy)
            for q in questions:
                config = game_service.repoint_config(
                    q.type, q.config or {}, image.id, copy.id
                )
                if config != (q.config or {}):
                    q.config = config
        await db.flush()
        logger.info(
            "game_images_rehomed",
            game_id=game.id,
            course_id=new_course_id,
            moved=len(to_move),
            copied=len(to_copy),
        )
    return ImageRehome(len(to_move), len(to_copy))
