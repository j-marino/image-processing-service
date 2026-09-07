import logging

from app.dependencies import redis_shared_client
from app.models.image import Image
from app.config import REDIS_EXPIRE_TIME

# in the redis the Image(image_id, uploaded_by etc.) and bucket image (bytes) will be stored as a hash with the image_id as the key

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)


async def cache_image(image: Image, image_data: bytes):
    try:
        async with redis_shared_client() as r:
            image_id = str(image.id)
            image_data = image_data if image_data else b""  # Use empty bytes if image_data is None
            await r.hset(image_id, mapping={
                'name': image.name,
                'size': image.size,
                'content_type': image.content_type, 
                'url': image.url,
                'uploaded_by': image.uploaded_by, # is User.id 
                'image_data': image_data,
                })

            await r.expire(image_id, REDIS_EXPIRE_TIME)  # Set expiration time for the cache 
            logger.info(f"Cached image {image_id} in Redis")

    except Exception as e:
        logger.error(f"Error caching image {image.id} in Redis: {e}")

async def get_cached_image(image_id: str, user_id: int) -> dict | None:
    async with redis_shared_client() as r:
        data = await r.hgetall(image_id)

        if not data:
            return None

        result = {}

        for key, value in data.items():
            key = key.decode("utf-8")

            if key != "image_data":
                value = value.decode("utf-8")

            result[key] = value

        if int(result["uploaded_by"]) != user_id:
            print(f"{result["uploaded_by"]}, user: {user_id}")
            return None

        return result

async def delete_cached_image(image_id: str):
    async with redis_shared_client() as r:
        await r.delete(image_id)
        logger.info(f"deleted {image_id} from redis")


async def delete_cached_images(image_ids: list):
    async with redis_shared_client() as r:
        await r.delete(*image_ids)
        logger.info(f"deleted {image_ids} from redis")


async def endpoint_get_cached_image(image_id: str, user_id: int) -> dict | None:
    try:
        cached_image = await get_cached_image(image_id, user_id)
        if cached_image:
            logger.info(f"Retrieved image {image_id} from cache")
            return cached_image
        logger.info(f"image {image_id} cache miss")
        
    except Exception as e:
        logger.error(f"Error retrieving cached image: {e}")
        return None