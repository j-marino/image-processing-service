from sqlmodel import SQLModel
from app.dependencies import engine
from app.models.user import User
from app.models.image import Image, TransformJob

import asyncio


async def create_db_and_tables():
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)  


# development usage: run this script to create the database and tables
if __name__ == "__main__":
    asyncio.run(create_db_and_tables())
    print("Database and tables creation script run successfully.")
