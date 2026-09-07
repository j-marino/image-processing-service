import pytest_asyncio
import aioboto3
import boto3
from aiobotocore.session import AioSession
from aiomoto import mock_aws
from httpx import AsyncClient, ASGITransport
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from app.main import app
from app.dependencies import get_session, aioboto3_session, get_s3_client, bucket_settings
from app.models.user import User
from app.schemas.token import Token
from app.services.auth.auth import get_password_hash
from app.services.slowapi.slowapi_limiter import limiter


limiter.enabled = False
TEST_BUCKET = bucket_settings.bucket_name


@pytest_asyncio.fixture(name="session")
async def session_fixture():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    async with AsyncSession(engine) as session:
        yield session


@pytest_asyncio.fixture(name="client")
async def client_fixture(session: AsyncSession):
    def get_session_override():
        return session

    app.dependency_overrides[get_session] = get_session_override

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()


async def override_get_s3_client():
    async with aioboto3_session.client(
        service_name="s3",
        region_name="us-east-1",  # no endpoint_url, no real creds needed
    ) as s3:
        yield s3


@pytest_asyncio.fixture(autouse=True)
async def _mock_s3():
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=TEST_BUCKET)
        app.dependency_overrides[get_s3_client] = override_get_s3_client
        yield
        app.dependency_overrides.pop(get_s3_client, None)


@pytest_asyncio.fixture(name="s3_client")
async def s3_fixture(_mock_s3):
    # just gives the test a client to make assertions with;
    # the actual mocking/override now happens in _mock_s3 above
    session = aioboto3.Session()
    async with session.client("s3", region_name="us-east-1") as s3:
        yield s3


async def get_test_token(session: AsyncSession, client: AsyncClient) -> Token:
    user_donna = User(username="donna", email="watermelon@gmail.com", hashed_password=get_password_hash("donnahaditcoming"))
    session.add(user_donna)
    await session.commit()

    response = await client.post(
                    "/token",
                    data={
                        "username": "donna",
                        "password": "donnahaditcoming"
                    }
                )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
