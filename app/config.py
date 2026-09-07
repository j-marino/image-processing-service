from pydantic_settings import BaseSettings, SettingsConfigDict

ACCEPTED_FORMATS = ["png","jpeg","jpg"]
MAX_BYTE_UPLOAD = 40_000_000 # 40MB
REDIS_EXPIRE_TIME = 60 * 20  # 20 minutes

class TokenSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    secret_key: str
    algorithm: str
    access_token_expire_minutes: int 


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    db_url: str


class BucketSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    endpoint_url: str
    aws_access_key_id: str
    aws_secret_access_key: str
    bucket_name: str
    

class RabbitMQSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    rabbitmq_user: str
    rabbitmq_pass: str
    rabbitmq_host: str
    rabbitmq_port: int