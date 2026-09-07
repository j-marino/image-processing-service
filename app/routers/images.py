from typing import Annotated
from uuid import uuid4
from sqlmodel import select, delete
from fastapi import APIRouter, Depends, UploadFile, Response, HTTPException, Query, Request
from uuid import UUID
from app.services.slowapi.slowapi_limiter import limiter
from app.services.auth.auth import get_current_user
from app.dependencies import SessionDep, S3Dep, bucket_settings
from app.models.image import Image, TransformJob
from app.models.user import User
from app.schemas.images import ImageResponse, Transformations, ImageRead
from app.services.bucket.bucket_operations import delete_file, delete_files, get_bucket_image, upload_to_bucket, delete_from_bucket
from app.services.image.image_db import get_db_image
from app.services.rabbitmq.job_helper import get_job
from app.services.rabbitmq.rabbitmq import RabbitMQDep
from app.services.redis.redis import cache_image, endpoint_get_cached_image, delete_cached_image, delete_cached_images
from app.services.rabbitmq.send import publish_image_task
from app.config import ACCEPTED_FORMATS, MAX_BYTE_UPLOAD


router = APIRouter()


@router.post("/images", response_model=ImageResponse)
@limiter.limit("3/minute")
async def upload_image(request: Request, response: Response, session: SessionDep, s3: S3Dep, file: UploadFile, current_user: Annotated[User, Depends(get_current_user)]):
    content_split = file.content_type.split("/") # file.content_type for images is images/{file_extension}
    if content_split[1].lower() not in ACCEPTED_FORMATS or file.filename.rsplit(".", 1)[1].lower() not in ACCEPTED_FORMATS:
        raise HTTPException(status_code=415, detail=f"Unsupported file type: {content_split[1]}. Only supported formats are .png and .jpeg" )
    
    if file.size > MAX_BYTE_UPLOAD:
        raise HTTPException(status_code=413, detail=f"File {file.filename} of size {file.size} exceeds {MAX_BYTE_UPLOAD/1_000_000}MB per image storage limit")
    
    image_url = f"/{current_user.username}/{file.filename}"
    image = Image(name=file.filename, size=file.size, content_type=file.content_type, url=image_url, uploaded_by=current_user.id)
    existing_image = await session.exec(select(Image).where(Image.name == file.filename))
    existing_image = existing_image.first()

    if existing_image:
        raise HTTPException(status_code=409, detail=f"Image with name {file.filename} already exists ")

    file_data = await file.read()  # Await the result of the file read operation

    await upload_to_bucket(file_data, image_url, image.id, s3)

    # UUID v4 assigned automatically by default_factory in the Image model
    session.add(image)
    await session.commit()
    await session.refresh(image)

    await cache_image(image, file_data)

    return {
        "upload_status": True, 
        "details": image
        }

# pagination and limits through query params
# user get all (data of) images they have uploaded
@router.get("/images")
@limiter.limit("10/minute")
async def get_user_images(request: Request, response: Response, session: SessionDep, current_user: Annotated[User, Depends(get_current_user)], page: Annotated[int, Query(ge=1)] = 1, limit: Annotated[int, Query(ge=1, le=100)] = 10):
    offset = (page - 1) * limit
    images = await session.exec(select(Image).where(Image.uploaded_by == current_user.id).offset(offset).limit(limit))
    images = images.all()
    total = len(images)

    return {
        "items": images,
        "page": page,
        "limit": limit,
        "total": total,
        "pages": (total + limit - 1) // limit,
    }


@router.get("/images/{image_id}")
@limiter.limit("5/minute")
async def get_image(request: Request, session: SessionDep, s3: S3Dep, image_id: str, current_user: Annotated[User, Depends(get_current_user)]):
    cache_hit = await endpoint_get_cached_image(image_id, current_user.id)
    if cache_hit:
        return Response(content=cache_hit["image_data"], media_type=cache_hit["content_type"] or "image/jpeg")

    image = await get_db_image(session, image_id, current_user.id)
    file_data = await get_bucket_image(image, bucket_settings.bucket_name, s3)

    return Response(content=file_data, media_type=image.content_type or "image/jpeg")


@router.post("/images/{image_id}/transform")
@limiter.limit("3/minute")
async def transform_image(
    request: Request,
    response: Response,
    image_id: str,
    transformations: Transformations,
    session: SessionDep,
    s3: S3Dep,
    current_user: Annotated[User, Depends(get_current_user)],
    channel: RabbitMQDep,
):
    # cache-then-db lookup; also enforces the image belongs to current_user
    cache_hit = await endpoint_get_cached_image(image_id, current_user.id)
    if cache_hit:
        cache_hit["id"] = image_id
        image = ImageRead(**cache_hit)
    else:
        image = await get_db_image(session, image_id, current_user.id)
        # image = ImageRead.model_validate(db_image)
        image_data = await get_bucket_image(image, bucket_settings.bucket_name, s3)
        await cache_image(image, image_data)

    
    
    output_format = transformations.image_format
    if output_format:
        output_format = output_format.target_format
    if not output_format:
        output_format = image.content_type.rsplit("/", 1)[1].lower()
        if not output_format:
            output_format = "jpeg"

    transformed_image_id = uuid4()
    transform_job = TransformJob(
        given_image_id=image.id,
        transform_image_id=transformed_image_id,
        status="pending",
        user_id=current_user.id
    )

    await publish_image_task(channel, {
        "job_id": str(transform_job.job_id),
        "given_image_id": str(image.id),
        "transform_image_id": str(transformed_image_id),
        "user_id": image.uploaded_by,
        "username": current_user.username,
        "transformations": transformations.model_dump(),
        "image_name": transformations.image_name,   # optional override
        "output_format": output_format,
    })

    session.add(transform_job)
    await session.commit()
    await session.refresh(transform_job) 

    return {
        "job_id": transform_job.job_id,
        "status": transform_job.status,
    }


@router.get("/images/{job_id}/transform/status")
@limiter.limit("5/minute")
async def get_image_status(request: Request, response: Response, job_id: str, session: SessionDep, current_user: Annotated[User, Depends(get_current_user)]):
    job = await get_job(session, job_id, current_user.id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job with job id {job.job_id} not found.")

    if job.status == "failed" or job.status == "pending":
        return {
            "status": job.status,
            "image_id": job.transform_image_id,
            "error_message": job.error_message
        }


    image_id = str(job.transform_image_id)

    cache_hit = await endpoint_get_cached_image(image_id, current_user.id)
    if cache_hit:
        cache_hit["id"] = image_id
        image = ImageRead(**cache_hit)

    else:
        image = await get_db_image(session, image_id, current_user.id)

    return {
        "status": job.status, 
        "image_id": image_id, 
        "url": image.url, 
        "metadata": {
            "name": image.name,
            "size": image.size, 
            "content_type": image.content_type,
            "uploaded_by": image.uploaded_by
            }
        }

@router.delete("/images")
@limiter.limit("5/minute")
async def delete_all_images(request: Request, response: Response, session: SessionDep, s3: S3Dep, current_user: Annotated[User, Depends(get_current_user)]):
    image_paths = await session.exec(select(Image.url).where(Image.uploaded_by == current_user.id))
    image_paths = image_paths.all()

    if image_paths:
        await delete_from_bucket(delete_files(image_paths, bucket_settings.bucket_name, s3))
        await session.exec(delete(Image).where(Image.uploaded_by == current_user.id))
        await session.commit()
        await delete_cached_images(image_paths)

    return {
        "ok": True, 
        "deletions": len(image_paths)
    }


@router.delete("/images/{image_id}")
@limiter.limit("5/minute")
async def delete_image(request: Request, response: Response, session: SessionDep, s3: S3Dep, image_id: str, current_user: Annotated[User, Depends(get_current_user)]):
    image = await get_db_image(session, image_id, current_user.id)
    await delete_from_bucket(delete_file(image.url, bucket_settings.bucket_name, s3))
    await session.delete(image)
    await session.commit()
    await delete_cached_image(image_id)

    return {
        "ok": True
        }

