import os

from fastapi import FastAPI
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler

from app.services.rabbitmq_config.rabbitmq import lifespan
from app.services.slowapi.slowapi_limiter import limiter
from app.routers import users, token, images


app = FastAPI(lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

if os.getenv("DISABLE_RATE_LIMIT") == "1":
    limiter.enabled = False

app.include_router(users.router)
app.include_router(token.router)
app.include_router(images.router)

@app.get("/health")
async def health_check():
    return {"status": "healthy"}


