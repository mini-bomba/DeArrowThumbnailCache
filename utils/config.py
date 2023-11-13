import yaml
from pydantic import BaseModel, Field

from utils.test_utils import in_test


class ServerSettings(BaseModel):
    host: str
    port: int
    worker_health_check_port: int
    reload: bool


class ThumbnailStorage(BaseModel):
    path: str
    max_size: int
    cleanup_multiplier: float
    redis_offset_allowed: int
    max_before_async_generation: int
    max_queue_size: int


class RedisConfig(BaseModel):
    host: str
    port: int


class ProxyInfoConfig(BaseModel):
    url: str
    country_code: str | None = None


class YTAuth(BaseModel):
    visitor_data: str | None = Field(None, alias="visitorData")


class Config(BaseModel):
    server: ServerSettings
    thumbnail_storage: ThumbnailStorage
    redis: RedisConfig
    default_max_height: int
    status_auth_password: str
    yt_auth: YTAuth
    try_floatie: bool
    try_ytdlp: bool
    skip_local_ffmpeg: bool
    proxy_urls: list[ProxyInfoConfig] = Field(default_factory=list)
    proxy_token: str | None = None
    front_auth: str | None = None
    debug: bool


with open("config.yaml" if not in_test() else "tests/test_config.yaml") as f:
    config = Config.model_validate(yaml.safe_load(f), strict=True)
