from fastapi import HTTPException
from sqlmodel import select
from uuid import UUID
from app.models.image import Image
from app.dependencies import SessionDep


async def get_db_image(session: SessionDep, image_id: int, user_id: int) -> Image:
    try:
        image_id = UUID(image_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Image not found")
    
    result = await session.exec(select(Image).where(Image.id == image_id))
    image = result.first()
    if not image:
        raise HTTPException(status_code=404, detail="Image does not exist")

    if image.uploaded_by != user_id:
        raise HTTPException(status_code=403, detail="You do not have permission to access this image")

    return image

