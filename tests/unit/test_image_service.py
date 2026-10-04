"""
Unit tests for app.services.image_service.prepare_image (T7 spec §4.3).

Pure Pillow, no database or Docker stack.

Run with:
    cd tests/unit && PYTHONPATH=../../backend pytest test_image_service.py -v
"""

from __future__ import annotations

import io

import pytest
from app.common.exceptions import BuzzerError
from app.services.image_service import MAX_IMAGE_BYTES, _webp_chunks, prepare_image
from PIL import Image, ImageCms
from PIL.PngImagePlugin import PngInfo

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _picture(mode: str = "RGB", size: tuple[int, int] = (40, 20)) -> Image.Image:
    """A non-uniform image, so lossy encoders have something to do."""
    img = Image.new(mode, size)
    channels = len(img.getbands())
    for x in range(size[0]):
        for y in range(size[1]):
            v = (x * 7 + y * 13) % 256
            img.putpixel((x, y), (v, 255 - v, x % 256, 200)[:channels])
    return img


def _encode(img: Image.Image, fmt: str, **kwargs) -> bytes:
    buf = io.BytesIO()
    img.save(buf, fmt, **kwargs)
    return buf.getvalue()


def _gps_exif(orientation: int | None = None) -> Image.Exif:
    exif = Image.Exif()
    exif[0x010E] = "secret description"
    if orientation is not None:
        exif[0x0112] = orientation
    gps = exif.get_ifd(0x8825)
    gps[1] = "N"
    gps[2] = (43.0, 4.0, 30.0)
    return exif


def _srgb_icc() -> bytes:
    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def _png_text() -> PngInfo:
    info = PngInfo()
    info.add_text("Comment", "secret")
    return info


def _insert_jpeg_segment(jpeg: bytes, marker: int, payload: bytes) -> bytes:
    """Insert an APPn/COM segment right after SOI."""
    assert jpeg[:2] == b"\xff\xd8"
    segment = bytes([0xFF, marker]) + (len(payload) + 2).to_bytes(2, "big") + payload
    return jpeg[:2] + segment + jpeg[2:]


def _add_webp_chunk(webp: bytes, fourcc: bytes, payload: bytes) -> bytes:
    """Append a chunk and fix up the RIFF size."""
    if len(payload) % 2:
        payload += b"\x00"
    body = webp[12:] + fourcc + len(payload).to_bytes(4, "little") + payload
    return b"RIFF" + (len(body) + 4).to_bytes(4, "little") + b"WEBP" + body


def _open(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    img.load()
    return img


def _error(raw: bytes) -> tuple[int, str]:
    with pytest.raises(BuzzerError) as exc:
        prepare_image(raw)
    return exc.value.status_code, exc.value.code


def _clean_jpeg() -> bytes:
    return _encode(_picture(), "JPEG", quality=90)


# ---------------------------------------------------------------------------
# Idempotence invariant (§4.3 step 8): prepare_image's own output is clean
# ---------------------------------------------------------------------------

_SOURCES = {
    "jpeg": lambda: _encode(_picture(), "JPEG", quality=95, exif=_gps_exif()),
    "png": lambda: _encode(_picture("RGBA"), "PNG", pnginfo=_png_text()),
    "webp_lossy": lambda: _encode(_picture(), "WEBP", quality=80, exif=_gps_exif()),
    "webp_lossless": lambda: _encode(_picture("RGBA"), "WEBP", lossless=True),
}


@pytest.mark.parametrize("kind", sorted(_SOURCES))
def test_output_round_trips_unchanged(kind: str) -> None:
    first = prepare_image(_SOURCES[kind](), force_reencode=True)
    again = prepare_image(first.data, force_reencode=False)
    assert again == first


def test_webp_keeps_lossless_or_lossy() -> None:
    lossless = prepare_image(_SOURCES["webp_lossless"]())
    lossy = prepare_image(_SOURCES["webp_lossy"]())
    assert b"VP8L" in _webp_chunks(lossless.data)
    assert b"VP8L" not in _webp_chunks(lossy.data)
    assert b"VP8 " in _webp_chunks(lossy.data)


# ---------------------------------------------------------------------------
# has_metadata allowlist (§4.3 step 7), observed through force_reencode=False:
# clean input is returned byte-for-byte, anything else is re-encoded.
# ---------------------------------------------------------------------------

_CLEAN = {
    "jpeg-jfif-only": lambda: _clean_jpeg(),
    "jpeg-icc": lambda: _encode(_picture(), "JPEG", icc_profile=_srgb_icc()),
    "jpeg-cmyk-adobe": lambda: _encode(_picture("CMYK"), "JPEG"),
    "png-plain": lambda: _encode(_picture(), "PNG"),
    "png-icc-dpi": lambda: _encode(
        _picture(), "PNG", icc_profile=_srgb_icc(), dpi=(72, 72)
    ),
    "webp-lossy": lambda: _encode(_picture(), "WEBP", quality=90),
    "webp-alpha": lambda: _encode(_picture("RGBA"), "WEBP", quality=90),
    "webp-iccp": lambda: _encode(_picture(), "WEBP", icc_profile=_srgb_icc()),
}


@pytest.mark.parametrize("kind", sorted(_CLEAN))
def test_clean_inputs_are_kept_byte_for_byte(kind: str) -> None:
    raw = _CLEAN[kind]()
    assert prepare_image(raw, force_reencode=False).data == raw


_DIRTY = {
    "jpeg-exif-app1": lambda: _encode(_picture(), "JPEG", exif=_gps_exif()),
    "jpeg-xmp-app1": lambda: _insert_jpeg_segment(
        _clean_jpeg(), 0xE1, b"http://ns.adobe.com/xap/1.0/\x00<x/>"
    ),
    "jpeg-photoshop-app13": lambda: _insert_jpeg_segment(
        _clean_jpeg(), 0xED, b"Photoshop 3.0\x008BIM"
    ),
    "jpeg-comment": lambda: _encode(_picture(), "JPEG", comment=b"secret"),
    "jpeg-trailing-data": lambda: _clean_jpeg() + b"trailer",
    "png-text": lambda: _encode(_picture(), "PNG", pnginfo=_png_text()),
    "png-exif": lambda: _encode(_picture(), "PNG", exif=_gps_exif()),
    "png-trailing-data": lambda: _encode(_picture(), "PNG") + b"trailer",
    "webp-exif-chunk": lambda: _encode(_picture(), "WEBP", exif=_gps_exif()),
    "webp-xmp-chunk": lambda: _encode(_picture(), "WEBP", xmp=b"<x:xmpmeta/>"),
    "webp-unknown-chunk": lambda: _add_webp_chunk(
        _encode(_picture(), "WEBP"), b"ZZZZ", b"secret"
    ),
}


@pytest.mark.parametrize("kind", sorted(_DIRTY))
def test_metadata_inputs_are_reencoded_clean(kind: str) -> None:
    raw = _DIRTY[kind]()
    out = prepare_image(raw, force_reencode=False)
    assert out.data != raw
    assert prepare_image(out.data, force_reencode=False).data == out.data
    img = _open(out.data)
    assert not img.getexif()
    for key in ("exif", "xmp", "comment", "Comment", "photoshop"):
        assert key not in img.info
    assert b"secret" not in out.data
    assert b"trailer" not in out.data


def test_jpeg_output_has_only_jfif_and_icc_segments() -> None:
    src = _encode(_picture(), "JPEG", exif=_gps_exif(), icc_profile=_srgb_icc())
    img = _open(prepare_image(src).data)
    assert [m for m, _ in img.applist] == ["APP0", "APP2"]
    assert img.info["icc_profile"] == _srgb_icc()


def test_png_text_chunk_removed() -> None:
    src = _encode(_picture(), "PNG", pnginfo=_png_text())
    assert _open(src).text == {"Comment": "secret"}
    assert _open(prepare_image(src).data).text == {}


def test_png_transparency_and_mode_kept() -> None:
    pal = _picture().convert("P")
    src = _encode(pal, "PNG", transparency=0, pnginfo=_png_text())
    out = _open(prepare_image(src).data)
    assert out.mode == "P"
    assert out.info["transparency"] == 0


# ---------------------------------------------------------------------------
# Rotation, MPO
# ---------------------------------------------------------------------------


def test_exif_orientation_is_applied_and_dimensions_swap() -> None:
    src = _encode(_picture(size=(400, 200)), "JPEG", exif=_gps_exif(orientation=6))
    out = prepare_image(src)
    assert (out.width, out.height) == (200, 400)
    img = _open(out.data)
    assert img.size == (200, 400)
    assert not img.getexif()


def test_mpo_is_stored_as_single_frame_jpeg() -> None:
    first, second = _picture(), _picture().rotate(180)
    src = _encode(first, "MPO", save_all=True, append_images=[second])
    assert Image.open(io.BytesIO(src)).format == "MPO"

    out = prepare_image(src, force_reencode=False)  # MPO always re-encodes
    assert out.mime == "image/jpeg"
    img = _open(out.data)
    assert img.format == "JPEG"
    assert getattr(img, "n_frames", 1) == 1
    assert [m for m, _ in img.applist] == ["APP0"]
    assert b"MPF" not in out.data


# ---------------------------------------------------------------------------
# Rejections (§4.3 steps 1–6, test 2's table)
# ---------------------------------------------------------------------------


def test_too_large_input() -> None:
    raw = _encode(_picture(), "PNG")
    assert _error(raw + b"\x00" * (MAX_IMAGE_BYTES - len(raw) + 1)) == (
        413,
        "IMAGE_TOO_LARGE",
    )


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param(b"<svg xmlns='http://www.w3.org/2000/svg'/>", id="svg"),
        pytest.param(b"just some text pretending to be a png", id="text"),
        pytest.param(b"", id="empty"),
        pytest.param(_clean_jpeg()[:200], id="truncated-jpeg"),
    ],
)
def test_invalid_images(raw: bytes) -> None:
    assert _error(raw) == (422, "INVALID_IMAGE")


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param(_encode(_picture(), "GIF"), id="gif"),
        pytest.param(_encode(_picture(), "BMP"), id="bmp"),
        pytest.param(_encode(_picture(), "TIFF"), id="tiff"),
        pytest.param(
            _encode(
                _picture(),
                "WEBP",
                save_all=True,
                append_images=[_picture().rotate(180)],
            ),
            id="animated-webp",
        ),
        pytest.param(
            _encode(
                _picture(), "PNG", save_all=True, append_images=[_picture().rotate(180)]
            ),
            id="animated-png",
        ),
    ],
)
def test_unsupported_images(raw: bytes) -> None:
    assert _error(raw) == (415, "UNSUPPORTED_IMAGE_TYPE")


@pytest.mark.parametrize("size", [(9000, 10), (10, 9000), (7000, 7000)])
def test_oversized_dimensions_rejected_before_decode(size: tuple[int, int]) -> None:
    raw = _encode(Image.new("L", size), "PNG")
    assert _error(raw) == (422, "INVALID_IMAGE")


def test_mime_comes_from_content() -> None:
    assert prepare_image(_encode(_picture(), "PNG")).mime == "image/png"
    assert prepare_image(_clean_jpeg()).mime == "image/jpeg"
    assert prepare_image(_encode(_picture(), "WEBP")).mime == "image/webp"
