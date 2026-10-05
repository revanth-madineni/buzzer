"""Image read endpoint (T7 spec §4.4). Mounted at /api/images.

Any authenticated user, GUEST included, can read an image by ID. There is no course
check and no list endpoint: IDs are random UUIDs, and the image is shown to every
player of the question anyway. Images are immutable, so responses cache forever.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from ..common.dependencies import get_current_user
from ..common.exceptions import NotFoundError
from ..database import get_db
from ..models.user import User
from ..services import image_service

router = APIRouter(prefix="/images", tags=["images"])


@router.get("/{image_id}")
async def get_image(
    image_id: str,
    _: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    image = await image_service.get_image_with_data(db, image_id)
    if image is None:
        raise NotFoundError("Image not found")
    return Response(
        content=image.data,
        media_type=image.mime_type,
        headers={
            "Cache-Control": "private, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": "inline",
        },
    )
