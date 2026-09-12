import os
import threading


import io
import random
import string
from locust import events
from locust.runners import MasterRunner

from PIL import Image as PILImage
from locust import HttpUser, task, between
from app.services.slowapi.slowapi_limiter import limiter


def random_string(n: int = 8) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def generate_image_bytes(fmt: str = "PNG", size: tuple[int, int] = (256, 256)) -> bytes:
    color = (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
    img = PILImage.new("RGB", size, color=color)
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


# --- R2 free-tier protection -------------------------------------------------
# Tracks only requests that consume real Class A/B quota (PutObject via
# upload/transform, GetObject via get-image/transform-read). Per Cloudflare's
# published pricing, DeleteObject is a free operation and doesn't count
# against either limit, so deletes/cleanup are deliberately excluded here.
# Register/login/token/list-images never touch the bucket at all.
BUCKET_TOUCHING_REQUEST_NAMES = {
    "/images [upload]",       # PutObject (Class A)
    "/images/[id] [get]",     # GetObject (Class B), skipped on cache hit
    "/images/[id]/transform", # worker does GetObject + PutObject per job
}
MAX_BUCKET_OPERATIONS = int(os.environ.get("MAX_BUCKET_OPERATIONS", "500"))
 
_bucket_op_count = 0
_bucket_op_lock = threading.Lock()
_environment_ref: dict = {}
 
 
@events.init.add_listener
def _capture_environment(environment, **kwargs):
    _environment_ref["env"] = environment
 
 
@events.request.add_listener
def _enforce_bucket_op_budget(name, exception, **kwargs):
    if name not in BUCKET_TOUCHING_REQUEST_NAMES:
        return
 
    global _bucket_op_count
    with _bucket_op_lock:
        _bucket_op_count += 1
        count = _bucket_op_count
 
    if count == MAX_BUCKET_OPERATIONS:
        env = _environment_ref.get("env")
        print(
            f"\n[R2 budget] Hit {MAX_BUCKET_OPERATIONS} bucket-touching requests "
            "-- stopping the test to protect your free-tier quota. "
            "Raise MAX_BUCKET_OPERATIONS if you meant to allow more."
        )
        if env is not None and env.runner is not None:
            env.runner.quit()



class ImageProcessingUser(HttpUser):
    """
    Simulates a logged-in user: registers once, then uploads, lists,
    fetches, transforms, polls transform status, and deletes images.
    """
    
    def on_start(self):
        self.token = None
        self.headers = {}
        self.image_ids: list[str] = []
        self.last_job_id: str | None = None
        self._register()

    def on_stop(self):
        if not self.token:
            return
        self.client.delete("/images", headers=self.headers, name="/images [cleanup]")

    def _register(self):
        username = f"loadtest_{random_string(10)}"
        payload = {
            "username": username,
            "email": f"{username}@example.com",
            "password": "LoadTest123!",
        }
        with self.client.post("/register", json=payload, name="/register", catch_response=True) as resp:
            if resp.status_code == 200:
                data = resp.json()
                self.token = data["token"]["access_token"]
                self.headers = {"Authorization": f"Bearer {self.token}"}
                resp.success()
            elif resp.status_code == 429:
                resp.success()  # limiter doing its job; this user just won't have auth this run
            else:
                resp.failure(f"register failed: {resp.status_code} {resp.text}")

    @task(4)
    def upload_image(self):
        if not self.token:
            return
        filename = f"{random_string(8)}.png"
        files = {"file": (filename, generate_image_bytes("PNG"), "image/png")}
        with self.client.post(
            "/images", files=files, headers=self.headers, name="/images [upload]", catch_response=True
        ) as resp:
            if resp.status_code == 200:
                self.image_ids.append(resp.json()["details"]["id"])
                resp.success()
            elif resp.status_code == 429:
                resp.success()
            else:
                resp.failure(f"upload failed: {resp.status_code} {resp.text}")

    @task(6)
    def list_images(self):
        if not self.token:
            return
        self.client.get(
            "/images",
            headers=self.headers,
            params={"page": 1, "limit": 10},
            name="/images [list]",
        )

    @task(4)
    def get_image(self):
        if not self.token or not self.image_ids:
            return
        image_id = random.choice(self.image_ids)
        self.client.get(f"/images/{image_id}", headers=self.headers, name="/images/[id] [get]")

    @task(3)
    def transform_image(self):
        if not self.token or not self.image_ids:
            return
        image_id = random.choice(self.image_ids)
        payload = {
            "resize": {"width": 128, "height": 128},
            "filters": {"grey_scale": True},
        }
        with self.client.post(
            f"/images/{image_id}/transform",
            json=payload,
            headers=self.headers,
            name="/images/[id]/transform",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                self.last_job_id = resp.json().get("job_id")
                resp.success()
            elif resp.status_code in (404, 429):
                resp.success()
            else:
                resp.failure(f"transform failed: {resp.status_code} {resp.text}")

    @task(3)
    def check_transform_status(self):
        if not self.token or not self.last_job_id:
            return
        self.client.get(
            f"/images/{self.last_job_id}/transform/status",
            headers=self.headers,
            name="/images/[job_id]/transform/status",
        )

    @task(1)
    def delete_image(self):
        if not self.token or not self.image_ids:
            return
        image_id = self.image_ids.pop()
        self.client.delete(f"/images/{image_id}", headers=self.headers, name="/images/[id] [delete]")


class AuthChurnUser(HttpUser):
    """
    Lighter-weight user that just hammers register/login/token to
    stress-test the auth path (and its separate rate limits)
    independently of the image pipeline.
    """

    wait_time = between(2, 5)

    @task(1)
    def register_and_login(self):
        username = f"authload_{random_string(10)}"
        password = "LoadTest123!"
        payload = {"username": username, "email": f"{username}@example.com", "password": password}

        with self.client.post("/register", json=payload, name="/register [auth-churn]", catch_response=True) as resp:
            if resp.status_code in (200, 400, 429):
                resp.success()
            else:
                resp.failure(f"register failed: {resp.status_code}")

        with self.client.post(
            "/login", json={"username": username, "password": password}, name="/login", catch_response=True
        ) as resp:
            if resp.status_code in (200, 400, 429):
                resp.success()
            else:
                resp.failure(f"login failed: {resp.status_code}")

        # /token uses OAuth2PasswordRequestForm, so it needs form data, not JSON
        with self.client.post(
            "/token",
            data={"username": username, "password": password},
            name="/token",
            catch_response=True,
        ) as resp:
            if resp.status_code in (200, 401, 429):
                resp.success()
            else:
                resp.failure(f"token failed: {resp.status_code}")
