import aioboto3

from typing import Annotated
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession
from fastapi import Depends
from types_aiobotocore_s3.client import S3Client
from contextlib import asynccontextmanager
import redis.asyncio as redis
from app.config import DatabaseSettings
from app.config import BucketSettings


database_settings = DatabaseSettings()
engine = create_async_engine(database_settings.db_url)


async def get_session():
    async with AsyncSession(engine, expire_on_commit=False,) as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


bucket_settings = BucketSettings()
aioboto3_session = aioboto3.Session()

# fastapi only depedency, not to be used with rabbitmq worker, which uses its own s3 client
async def get_s3_client():
    async with aioboto3_session.client(
        service_name='s3',
        # Provide your R2 endpoint: https://<ACCOUNT_ID>.r2.cloudflarestorage.com
        endpoint_url=bucket_settings.endpoint_url,
        # Provide your R2 Access Key ID and Secret Access Key
        aws_access_key_id=bucket_settings.aws_access_key_id,
        aws_secret_access_key=bucket_settings.aws_secret_access_key,
        region_name='auto',  # Required by boto3, not used by R2
    ) as s3:
        yield s3

S3Dep = Annotated[S3Client, Depends(get_s3_client)]


@asynccontextmanager
async def s3_client_context():
    async with aioboto3_session.client(
        service_name='s3',
        endpoint_url=bucket_settings.endpoint_url,
        aws_access_key_id=bucket_settings.aws_access_key_id,
        aws_secret_access_key=bucket_settings.aws_secret_access_key,
        region_name='auto',
    ) as s3:
        yield s3


@asynccontextmanager
async def redis_shared_client():
    r = redis.Redis(
        host='localhost', port=6379, decode_responses=False,  # Store bytes instead of strings
        max_connections=10,  
    )
    try:
        yield r
    finally:
        await r.close()
