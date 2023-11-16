import yaml
import secrets
import pathlib
from pydantic import BaseModel, Field, ByteSize, HttpUrl

from .test_utils import in_test


class ServerSettings(BaseModel):
    host: str = Field("localhost", description="Address to listen on")
    port: int = Field(3001, description="Port the main app should listen on", ge=1, le=65535)
    worker_health_check_port: int = Field(3002, description="Port workers should listen on for healthcheck requests")
    reload: bool = Field(False, description="Reload the app on file changes")


class ThumbnailStorage(BaseModel):
    path: pathlib.Path = Field(pathlib.Path("cache"), description="Path to thumbnail cache directory")
    max_size: ByteSize = Field("50MB", description="Size of the thumbnail cache at which a cleanup should be triggered", validate_default=True)
    cleanup_multiplier: float = Field(0.5, description="Multiplier for max_size which determines how much space the thumbnail cache should take after cleanup", gt=0, le=1)
    redis_offset_allowed: int = Field(20, description="Max allowed amount of videos which usage wasn't recorded in redis before removal is triggered", ge=0)
    max_before_async_generation: int = Field(15, description="Max job position in queue before returning '400 Thumbnail not generated yet'", ge=2)


class RedisConfig(BaseModel):
    host: str = Field("localhost", description="Address of the redis server")
    port: int = Field(32774, description="Port of the redis server", ge=1, le=65535)


class ProxyInfoConfig(BaseModel):
    url: HttpUrl = Field(..., description="URL of the proxy (incl. username & password if needed)")
    country_code: str | None = Field(None, description="Country code of the proxy, used in error logging")


class Config(BaseModel):
    server: ServerSettings = Field(default_factory=ServerSettings)
    thumbnail_storage: ThumbnailStorage = Field(default_factory=ThumbnailStorage)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    default_max_height: int = Field(720, description="Max height of generated thumbnails")
    status_auth_password: str = Field(default_factory=lambda: secrets.token_urlsafe(64), description="Auth token for retrieving additional data from the status endpoint")
    try_floatie: bool = Field(True, description="Try using floatie to retrieve playback URLs")
    try_ytdlp: bool = Field(True, description="Try using yt-dlp to retrieve playback URLs")
    skip_local_ffmpeg: bool = Field(False, description="Only use proxies to download thumbnails with ffmpeg")
    proxy_urls: list[ProxyInfoConfig] | None = Field(None, description="Static list of proxies to use for downloading thumbnails", min_items=1)
    proxy_token: str | None = Field(None, description="Webshare.io API token for automatic proxy configuration")
    front_auth: str | None = Field(None, description="Auth token used to prioritize thumbnail generation jobs")
    debug: bool = Field(False, description="Print extra logging output")


_config: Config | None = None


def get_config() -> Config:
    global _config
    if _config is not None:
        return _config
    with open("config.yaml" if not in_test() else "tests/test_config.yaml") as f:
        _config = Config(**yaml.safe_load(f))
    return _config
