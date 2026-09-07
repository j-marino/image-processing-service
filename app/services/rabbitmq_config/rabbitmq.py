from contextlib import asynccontextmanager
from typing import Annotated

from aio_pika import connect_robust
from aio_pika.abc import AbstractChannel
from fastapi import Depends, FastAPI, Request
from app.config import RabbitMQSettings


rabbitmq_settings = RabbitMQSettings()


@asynccontextmanager
async def lifespan(app: FastAPI):
#     connection = await connect_robust(
#     f"amqp://{rabbitmq_settings.rabbitmq_user}:{rabbitmq_settings.rabbitmq_pass}"
#     f"@{rabbitmq_settings.rabbitmq_host}:{rabbitmq_settings.rabbitmq_port}/"
# )
    connection = await connect_robust("amqp://guest:guest@localhost")
    channel = await connection.channel()
    await channel.declare_queue("image_queue", durable=True)

    app.state.rabbitmq_connection = connection
    app.state.rabbitmq_channel = channel

    yield

    await connection.close()


def get_rabbitmq_channel(request: Request) -> AbstractChannel:
    return request.app.state.rabbitmq_channel


RabbitMQDep = Annotated[AbstractChannel, Depends(get_rabbitmq_channel)]
