"""Image storage for map-pin questions (T7, spec docs/plans/t7-map-pin.md §4.3).

Images are immutable. Every upload is rotated upright from its EXIF orientation and
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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from ..common.exceptions import BuzzerError
from ..models.image import Image
from ..models.user import User

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
    db: AsyncSession, prepared: PreparedImage, user: User | None, course_id: int | None
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
    )
    db.add(image)
    await db.flush()
    logger.info(
        "image_stored",
        image_id=image.id,
        mime=image.mime_type,
        byte_size=image.byte_size,
        course_id=course_id,
    )
    return image


async def store_image(
    db: AsyncSession, raw: bytes, user: User, course_id: int | None
) -> Image:
    """Upload path: always re-encoded."""
    return await store_prepared(
        db, prepare_image(raw, force_reencode=True), user, course_id
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
