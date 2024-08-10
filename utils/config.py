import yaml
import secrets
import pathlib
from pydantic import BaseModel, Field, ByteSize, HttpUrl
from socket import gethostname
from datetime import timedelta

from .test_utils import in_test
from . import misc


class ServerSettings(BaseModel):
    host: str = Field("localhost", description="Address to listen on")
    port: int = Field(3001, description="Port the main app should listen on", ge=1, le=65535)
    worker_health_check_port: int = Field(3002, description="Port workers should listen on for healthcheck requests")
    reload: bool = Field(False, description="Reload the app on file changes")


class ThumbnailStorage(BaseModel):
    path: pathlib.Path = Field(pathlib.Path("cache"), description="Path to thumbnail cache directory")
    max_size: ByteSize = Field(
        "50MB", validate_default=True,
        description="Size of the thumbnail cache at which a cleanup should be triggered"
    )
    cleanup_multiplier: float = Field(
        0.5, gt=0, le=1,
        description="Multiplier for max_size which determines how much space the thumbnail cache should take after cleanup",
    )
    redis_offset_allowed: int = Field(
        20, ge=0,
        description="Max allowed amount of videos which usage wasn't recorded in redis before removal is triggered",
    )
    max_before_async_generation: int = Field(
        15, ge=2,
        description="Max job position in queue before returning '204 Thumbnail not generated yet'",
    )
    timeout_before_async_generation: int = Field(
        15, gt=0,
        description="Max time to wait for thumbnail to be ready before returning 204",
    )
    max_queue_size: int = Field(10000, description="Max queue length before new requests are immediately dropped", ge=1)


class RedisConfig(BaseModel):
    host: str = Field("localhost", description="Address of the redis server")
    port: int = Field(32774, description="Port of the redis server", ge=1, le=65535)


class ProxyInfoConfig(BaseModel):
    url: HttpUrl = Field(..., description="URL of the proxy (incl. username & password if needed)")
    country_code: str | None = Field(None, description="Country code of the proxy, used in error logging")


class NSigHelperConfig(BaseModel):
    tcp: tuple[str, int] | None = Field(None, description="Address & port combo (for tcp comms)")
    unix: pathlib.Path | None = Field(None, description="Location of unix socket (for unix socket comms)")
    max_player_age: timedelta = Field(
        "1:00:00", ge=timedelta(0), validate_default=True,
        description="If nsig helper's player is older than this value, request an update",
    )


class YTAuth(BaseModel):
    visitor_data: str | None = Field(None, alias="visitorData", description="Value for the .context.client.visitorData field in player requests")
    po_token: str | None = Field(None, description="Value for the .serviceIntegrityDimensions.poToken field in player requests")
    nsig_helper: NSigHelperConfig = Field(..., default_factory=NSigHelperConfig, description="Connection config for invidious' NSig helper")


class Config(BaseModel):
    server: ServerSettings = Field(default_factory=ServerSettings)
    thumbnail_storage: ThumbnailStorage = Field(default_factory=ThumbnailStorage)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    yt_auth: YTAuth = Field(default_factory=YTAuth)
    default_max_height: int = Field(720, description="Max height of generated thumbnails")
    status_auth_password: str = Field(
        default_factory=lambda: secrets.token_urlsafe(64),
        description="Auth token for retrieving additional data from the status endpoint"
    )
    try_floatie: bool = Field(True, description="Try using floatie to retrieve playback URLs")
    try_ytdlp: bool = Field(True, description="Try using yt-dlp to retrieve playback URLs")
    skip_local_ffmpeg: bool = Field(False, description="Only use proxies to download thumbnails with ffmpeg")
    proxy_urls: list[ProxyInfoConfig] | None = Field(
        None, min_items=1,
        description="Static list of proxies to use for downloading thumbnails",
    )
    proxy_token: str | None = Field(None, description="Webshare.io API token for automatic proxy configuration")
    front_auth: str | None = Field(None, description="Auth token used to prioritize thumbnail generation jobs")
    unique_hostnames: bool = Field(False, description="Assume worker hostnames are unique - don't add random suffixes")
    debug: bool = Field(False, description="Print extra logging output")
    project_url: HttpUrl = Field(
        "https://github.com/ajayyy/DeArrowThumbnailCache", validate_default=True,
        description="Project homepage, '/' will redirect here",
    )

    @property
    def worker_name(self) -> str:
        if self.unique_hostnames:
            return gethostname()
        return f"{gethostname()}-{misc.random_hex(4)}"


_config: Config | None = None


def get_config() -> Config:
    global _config
    if _config is not None:
        return _config
    with open("config.yaml" if not in_test() else "tests/test_config.yaml") as f:
        _config = Config(**yaml.safe_load(f))
    return _config
