import uuid
import io
from fastapi import HTTPException
from app.dependencies import S3Dep, bucket_settings
from app.models.image import Image


# upload file obj
async def upload_file(file_obj, bucket_file_obj: str, bucket_name: str, image_id: uuid.UUID, s3: S3Dep) -> bool:
    image_id = f'{image_id}'
    await s3.upload_fileobj(
        io.BytesIO(file_obj), bucket_name, bucket_file_obj,
        ExtraArgs={'Metadata': {'id': image_id}}
    )
    return True


# download a file
async def get_file_data(path: str, bucket_name: str, s3: S3Dep) -> bytes:
    response = await s3.get_object(Bucket=bucket_name, Key=path)
    return await response['Body'].read()


async def get_bucket_image(image: Image, bucket_name, s3: S3Dep) -> bytes:
    try:
        file_data = await get_file_data(image.url, bucket_name, s3)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Image retrieval error: {e}")

    return file_data


# delete 1 file
async def delete_file(file_path: str, bucket_name:str, s3: S3Dep) -> bool:
    await s3.delete_object(Bucket=bucket_name, Key=file_path)
    return True


# delete all files uploaded from user
async def delete_files(file_paths: list[str], bucket_name: str, s3: S3Dep) -> bool:
    objects_to_delete = [{'Key': path} for path in file_paths]

    await s3.delete_objects(
        Bucket=bucket_name,
        Delete={'Objects': objects_to_delete, 'Quiet': False},
    )
    return True


async def upload_to_bucket(file_obj, url: str, image_id, s3: S3Dep = None) -> None:
    try:
        upload_success = await upload_file(file_obj, url, bucket_settings.bucket_name, image_id, s3)
        if not upload_success:
            raise HTTPException(status_code=400, detail=f"Upload of image to bucket failed for url {url}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Image upload error: {e}")
 

async def delete_from_bucket(delete_coro) -> None:
    try:
        response = await delete_coro
        if not response:
            raise HTTPException(status_code=500, detail="Image deletion failed")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{"Image Deletion error"}: {e}")
