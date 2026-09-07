from aio_pika import DeliveryMode, Message
from aio_pika.abc import AbstractChannel
import json



async def publish_image_task(channel: AbstractChannel, task: dict) -> None:
    message_body = json.dumps(task).encode()  # dict -> bytes

    message = Message(
        message_body,
        delivery_mode=DeliveryMode.PERSISTENT,
        content_type="application/json",
    )

    await channel.default_exchange.publish(
        message,
        routing_key="image_queue",
    )