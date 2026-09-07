import asyncio
import functools
import json
import secrets
import logging

from aio_pika import connect_robust
from aio_pika.abc import AbstractIncomingMessage
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.image import TransformJob
from app.services.image.image_db import get_db_image
from app.services.bucket.bucket_operations import get_bucket_image, upload_to_bucket
from app.services.image.image_transformation import get_PIL_image, apply_transformations, pil_to_buffer
from app.schemas.images import Image, ImageRead, Transformations
from app.services.rabbitmq_config.job_helper import get_job
from app.config import MAX_BYTE_UPLOAD, BucketSettings, RabbitMQSettings
from app.dependencies import engine, s3_client_context
from app.services.redis.redis import cache_image, endpoint_get_cached_image 


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("image_worker")
rabbitmq_settings = RabbitMQSettings()
bucket_settings = BucketSettings()


async def process_image_task(session: AsyncSession, s3, task: dict) -> None:
    cache_hit = await endpoint_get_cached_image(task["given_image_id"], task["user_id"])
    if cache_hit:
        cache_hit["id"] = task["given_image_id"]
        image = ImageRead(**cache_hit)
        file_data = cache_hit["image_data"]
    else:
        image = await get_db_image(session, task["given_image_id"], task["user_id"])
        file_data = await get_bucket_image(image, bucket_settings.bucket_name, s3)
        await cache_image(image, file_data)

    try:
        pil_image = await get_PIL_image(file_data)
        transformed_image = await apply_transformations(
            pil_image, Transformations(**task["transformations"])
        )

        output_format = task["output_format"]
        buffer = await pil_to_buffer(transformed_image, output_format)
        new_size = buffer.getbuffer().nbytes

        # prevents a transformation increasing the file size and stops the user from
        # (maliciously) taking storage beyond the limits
        if new_size > MAX_BYTE_UPLOAD:
            raise ValueError(
                f"Transformed file exceeds {MAX_BYTE_UPLOAD / 1_000_000}MB per image storage limit"
            )

        new_image_id = task["transform_image_id"]
        image_name = task.get("image_name") or image.name.rsplit(".", 1)[0]
        # NOTE: an 8 random character string is added to the image name 
        # TODO: change it so that the user can have whatever name they want within character constraints
        # -> check if the name of the image has already been uploaded by the user
        new_name = f"{image_name}_{secrets.token_hex(4)}.{output_format}"
        new_url = f"/{task['username']}/{new_name}"

        buffer_bytes = buffer.getvalue()
        await upload_to_bucket(buffer_bytes, new_url, new_image_id, s3)

        new_image = Image(
            id=new_image_id,
            name=new_name,
            size=new_size,
            content_type=f"image/{output_format}",
            url=new_url,
            uploaded_by=task["user_id"],
        )
        
        session.add(new_image)
        await cache_image(new_image, buffer_bytes)

        job = await get_job(session, task["job_id"], task["user_id"])
        if job:
            job.status = "completed"
            job.transform_image_id = new_image.id
            session.add(job)

        await session.commit()
        await session.refresh(new_image)


        logger.info(
            "Completed transform for given_image_id=%s -> new image %s",
            task["given_image_id"], new_image.id,
        )

    except Exception as exc:
        await session.rollback()
        logger.exception("Transform failed for given_image_id=%s", task["given_image_id"])

        job = await get_job(session, task["job_id"], task["user_id"])
        if job:
            job.status = "failed"
            job.error_message = str(exc)
            session.add(job)
            await session.commit()
        raise


async def on_message(message: AbstractIncomingMessage, s3) -> None:
    async with message.process(requeue=False):
        try:
            task = json.loads(message.body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.exception("Received malformed message, dropping")
            return

        logger.info("Received image transformation task: image_id=%s", task.get("given_image_id"))

        async with AsyncSession(engine) as session:
            try:
                await process_image_task(session, s3, task)
            except Exception:
                logger.exception("Failed to process image_id=%s", task.get("given_image_id"))
                try:
                    await session.rollback()
                except Exception:
                    logger.exception("Also failed to record failure state for image_id=%s", task.get("given_image_id"))


async def main() -> None:
    # connection = await connect_robust(
    #     f"amqp://{rabbitmq_settings.rabbitmq_user}:{rabbitmq_settings.rabbitmq_pass}"
    #     f"@{rabbitmq_settings.rabbitmq_host}:{rabbitmq_settings.rabbitmq_port}/"
    # )
    connection = await connect_robust("amqp://guest:guest@localhost")
    async with connection, s3_client_context() as s3:
        channel = await connection.channel()
        await channel.set_qos(prefetch_count=1)

        queue = await channel.declare_queue("image_queue", durable=True)

        await queue.consume(functools.partial(on_message, s3=s3))

        logger.info(" [*] Waiting for messages. To exit press CTRL+C")
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())