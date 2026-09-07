from sqlmodel.ext.asyncio.session import AsyncSession
from httpx import AsyncClient
from app.models.user import User
from app.services.auth.auth import get_password_hash


async def test_register_user(client: AsyncClient):
    response = await client.post(
        "/register", 
        json={
            "username": "donna",
            "email": "watermelon@gmail.com",
            "password": "donnahaditcoming"
        }
    )
    data = response.json()

    assert response.status_code == 200
    assert data["user"] == {
        "username": "donna",
        "email": "watermelon@gmail.com"
    }
    assert data["token"]["token_type"] == "bearer"


async def test_login(session: AsyncSession, client: AsyncClient):
    user_donna = User(username="donna", email="watermelon@gmail.com", hashed_password=get_password_hash("donnahaditcoming"))
    session.add(user_donna)
    await session.commit()

    response = await client.post(
        "/login", 
        json={
            "username": "donna",
            "password": "donnahaditcoming"
        }
    )
    data = response.json()

    assert response.status_code == 200
    assert data["user"] == {
        "username": "donna",
        "email": "watermelon@gmail.com"
    }
    assert data["token"]["token_type"] == "bearer"


async def test_incorrect_login_details(session: AsyncSession, client: AsyncClient):
    user_donna = User(username="donna", email="watermelon@gmail.com", hashed_password=get_password_hash("donnahaditcoming"))
    session.add(user_donna)
    await session.commit()

    response = await client.post(
            "/login", 
            json={
                "username": "donna",
                "password": "wrongpassword"
            }
    )
    assert response.status_code == 400
