import asyncio
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from tests.conftest import get_test_token, TEST_BUCKET
from app.config import MAX_BYTE_UPLOAD
from app.models.user import User
from app.services.auth.auth import get_password_hash
from app.services.redis.redis import redis_shared_client
from app.services.rabbitmq.rabbitmq import get_rabbitmq_channel

from app.main import app
import app.routers.images as images_router


# get_test_token in conftest.py always creates a single hardcoded "donna"
# user, so it can't be called twice per test. This is a local variant for
# tests that need a *second*, distinct user.
async def get_second_test_token(session: AsyncSession, client: AsyncClient, username: str) -> dict:
    user = User(username=username, email=f"{username}@gmail.com", hashed_password=get_password_hash("testpassword123"))
    session.add(user)
    await session.commit()

    response = await client.post(
        "/token",
        data={"username": username, "password": "testpassword123"},
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def mock_rabbitmq():
    app.dependency_overrides[get_rabbitmq_channel] = lambda: MagicMock()
    original_publish = images_router.publish_image_task
    images_router.publish_image_task = AsyncMock()
    yield
    images_router.publish_image_task = original_publish
    app.dependency_overrides.pop(get_rabbitmq_channel, None)


# all endpoints in /images have the get_current_user dependency injection
async def test_unauthenticated_upload(client: AsyncClient):
    with open("tests/routers/test_image.jpg", "rb") as test_image:  # read as bytes
        response = await client.post(
            "/images",
            files={"file": ("test_image.jpg", test_image, "image/jpeg")}
        )

    assert response.status_code == 401


async def test_upload_image(session: AsyncSession, client: AsyncClient, s3_client):
    with open("tests/routers/test_image.jpg", "rb") as test_image:
        response = await client.post(
            "/images",
            headers=await get_test_token(session, client),
            files={"file": ("test_image.jpg", test_image, "image/jpeg")},
        )
    assert response.status_code == 200, response.text
    # verify it actually landed in the mocked bucket
    objects = await s3_client.list_objects_v2(Bucket=TEST_BUCKET)
    assert objects["KeyCount"] == 1


async def test_upload_image_rejects_bad_format(session: AsyncSession, client: AsyncClient):
    with open("tests/routers/test_image.jpg", "rb") as test_image:
        response = await client.post(
            "/images",
            headers=await get_test_token(session, client),
            files={"file": ("test_image.gif", test_image, "image/gif")},
        )
    assert response.status_code == 415


async def test_upload_image_rejects_oversized_file(session: AsyncSession, client: AsyncClient):
    # anything bigger than app.config.MAX_BYTE_UPLOAD should 413 before touching s3
    oversized = b"0" * (MAX_BYTE_UPLOAD + 1) 
    response = await client.post(
        "/images",
        headers=await get_test_token(session, client),
        files={"file": ("big_image.jpeg", oversized, "image/jpeg")},
    )
    assert response.status_code == 413


async def test_upload_image_rejects_duplicate_name(session: AsyncSession, client: AsyncClient, s3_client):
    headers = await get_test_token(session, client)
    with open("tests/routers/test_image.jpg", "rb") as test_image:
        first = await client.post(
            "/images",
            headers=headers,
            files={"file": ("dup_image.jpg", test_image, "image/jpeg")},
        )
    assert first.status_code == 200, first.text

    with open("tests/routers/test_image.jpg", "rb") as test_image:
        second = await client.post(
            "/images",
            headers=headers,
            files={"file": ("dup_image.jpg", test_image, "image/jpeg")},
        )
    assert second.status_code == 409


async def test_get_user_images_pagination(session: AsyncSession, client: AsyncClient):
    headers = await get_test_token(session, client)
    for i in range(3):
        with open("tests/routers/test_image.jpg", "rb") as test_image:
            resp = await client.post(
                "/images",
                headers=headers,
                files={"file": (f"page_image_{i}.jpg", test_image, "image/jpeg")},
            )
            assert resp.status_code == 200, resp.text

    response = await client.get("/images", headers=headers, params={"page": 1, "limit": 2})
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 2
    assert body["page"] == 1
    assert body["limit"] == 2
    assert body["total"] == 2  # note: total reflects len(page results), not full count
    assert body["pages"] == 1


async def test_get_user_images_unauthenticated(client: AsyncClient):
    response = await client.get("/images")
    assert response.status_code == 401


async def test_get_image_cache_hit(session: AsyncSession, client: AsyncClient, s3_client):
    headers = await get_test_token(session, client)
    with open("tests/routers/test_image.jpg", "rb") as test_image:
        upload = await client.post(
            "/images",
            headers=headers,
            files={"file": ("cache_hit.jpg", test_image, "image/jpeg")},
        )
    assert upload.status_code == 200, upload.text
    image_id = upload.json()["details"]["id"]

    # upload_image caches on write, so this should be served from redis, not s3
    response = await client.get(f"/images/{image_id}", headers=headers)
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert len(response.content) > 0


async def test_get_image_not_found(session: AsyncSession, client: AsyncClient):
    headers = await get_test_token(session, client)
    # must be a syntactically valid UUID or the UUID column type errors before
    # the "not found" check ever runs
    response = await client.get(f"/images/{uuid4()}", headers=headers)
    assert response.status_code == 404


async def test_get_image_wrong_owner(session: AsyncSession, client: AsyncClient):
    owner_headers = await get_test_token(session, client)
    with open("tests/routers/test_image.jpg", "rb") as test_image:
        upload = await client.post(
            "/images",
            headers=owner_headers,
            files={"file": ("owned_image.jpg", test_image, "image/jpeg")},
        )
    assert upload.status_code == 200, upload.text
    image_id = upload.json()["details"]["id"]

    # a second, distinct user should not be able to fetch someone else's image
    other_headers = await get_second_test_token(session, client, "other_user")
    response = await client.get(f"/images/{image_id}", headers=other_headers)
    assert response.status_code == 403


async def test_transform_image_creates_pending_job(session: AsyncSession, client: AsyncClient, s3_client):
    headers = await get_test_token(session, client)
    with open("tests/routers/test_image.jpg", "rb") as test_image:
        upload = await client.post(
            "/images",
            headers=headers,
            files={"file": ("transform_me.jpg", test_image, "image/jpeg")},
        )
    assert upload.status_code == 200, upload.text
    image_id = upload.json()["details"]["id"]

    response = await client.post(
        f"/images/{image_id}/transform",
        headers=headers,
        json={"resize": {"width": 100, "height": 100}},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "pending"
    assert "job_id" in body


async def test_transform_image_not_found(session: AsyncSession, client: AsyncClient):
    headers = await get_test_token(session, client)
    response = await client.post(
        f"/images/{uuid4()}/transform",
        headers=headers,
        json={"resize": {"width": 50, "height": 50}},
    )
    assert response.status_code == 404


async def test_get_image_status_pending(session: AsyncSession, client: AsyncClient, s3_client):
    headers = await get_test_token(session, client)
    with open("tests/routers/test_image.jpg", "rb") as test_image:
        upload = await client.post(
            "/images",
            headers=headers,
            files={"file": ("status_check.jpg", test_image, "image/jpeg")},
        )
    assert upload.status_code == 200, upload.text
    
    image_id = upload.json()["details"]["id"]

    transform = await client.post(
        f"/images/{image_id}/transform",
        headers=headers,
        json={"resize": {"width": 100, "height": 100}},
    )
    job_id = transform.json()["job_id"]

    # no worker is consuming the rabbitmq task in tests, so this should still read "pending"
    response = await client.get(f"/images/{job_id}/transform/status", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending"


async def test_get_image_status_job_not_found(session: AsyncSession, client: AsyncClient):
    headers = await get_test_token(session, client)
    response = await client.get(f"/images/i-dont-exist/transform/status", headers=headers)
    assert response.status_code == 404


async def test_delete_image(session: AsyncSession, client: AsyncClient, s3_client):
    headers = await get_test_token(session, client)
    with open("tests/routers/test_image.jpg", "rb") as test_image:
        upload = await client.post(
            "/images",
            headers=headers,
            files={"file": ("delete_me.jpg", test_image, "image/jpeg")},
        )
    assert upload.status_code == 200, upload.text
    image_id = upload.json()["details"]["id"]

    response = await client.delete(f"/images/{image_id}", headers=headers)
    assert response.status_code == 200
    assert response.json()["ok"] is True

    # confirm the bucket object is actually gone
    objects = await s3_client.list_objects_v2(Bucket=TEST_BUCKET)
    assert objects["KeyCount"] == 0

    # and that it's really gone from the db, not just the bucket
    follow_up = await client.get(f"/images/{image_id}", headers=headers)
    assert follow_up.status_code == 404


async def test_delete_all_images(session: AsyncSession, client: AsyncClient, s3_client):
    headers = await get_test_token(session, client)
    for i in range(2):
        with open("tests/routers/test_image.jpg", "rb") as test_image:
            resp = await client.post(
                "/images",
                headers=headers,
                files={"file": (f"bulk_delete_{i}.jpg", test_image, "image/jpeg")},
            )
            assert resp.status_code == 200, resp.text

    response = await client.delete("/images", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["deletions"] == 2

    objects = await s3_client.list_objects_v2(Bucket=TEST_BUCKET)
    assert objects["KeyCount"] == 0


async def test_delete_all_images_when_none_exist(session: AsyncSession, client: AsyncClient):
    headers = await get_second_test_token(session, client, "empty_user")
    response = await client.delete("/images", headers=headers)
    assert response.status_code == 200
    assert response.json()["deletions"] == 0


# redis caching
# There's no lightweight test-redis swap in here, so these just hit the same
# redis instance the app uses (cache_image sets a 20 min TTL) and clean up
# the key afterwards instead of waiting for it to expire.
# TODO: CHANGE to fakeredis for testing
async def test_upload_caches_image_in_redis(session: AsyncSession, client: AsyncClient, s3_client):
    headers = await get_test_token(session, client)
    with open("tests/routers/test_image.jpg", "rb") as test_image:
        upload = await client.post(
            "/images",
            headers=headers,
            files={"file": ("redis_cached.jpg", test_image, "image/jpeg")},
        )
    assert upload.status_code == 200, upload.text
    image_id = upload.json()["details"]["id"]

    async with redis_shared_client() as r:
        try:
            # cache_image stores this as a hash, not a plain string, so just
            # check the key exists rather than assuming the value shape
            assert await r.exists(image_id)
        finally:
            # don't leave test keys sitting around for the full 20 min TTL
            await r.delete(image_id)


async def test_delete_image_evicts_redis_cache(session: AsyncSession, client: AsyncClient, s3_client):
    headers = await get_test_token(session, client)
    with open("tests/routers/test_image.jpg", "rb") as test_image:
        upload = await client.post(
            "/images",
            headers=headers,
            files={"file": ("redis_evict.jpg", test_image, "image/jpeg")},
        )
    assert upload.status_code == 200, upload.text
    image_id = upload.json()["details"]["id"]

    async with redis_shared_client() as r:
        assert await r.exists(image_id)

    delete_resp = await client.delete(f"/images/{image_id}", headers=headers)
    assert delete_resp.status_code == 200

    async with redis_shared_client() as r:
        try:
            assert not await r.exists(image_id)
        finally:
            await r.delete(image_id)