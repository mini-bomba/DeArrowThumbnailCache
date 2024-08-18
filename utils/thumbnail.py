import asyncio
import logging
import math
import os
import pathlib
import re
import sys
import time as time_module
from dataclasses import dataclass
from typing import cast

import requests
from retry import retry

from constants.thumbnail import image_format, metadata_format, minimum_file_size

from .cleanup import add_storage_used, check_if_cleanup_needed, update_last_used
from .config import get_config
from .ffmpeg import FFmpegError, run_ffmpeg
from .proxy import get_proxy_url
from .redis_handler import get_async_redis_conn, redis_conn
from .video import PlaybackUrl, get_playback_url, valid_video_id

VIDEO_REQUEST_TIMEOUT = 5
config = get_config()
logger = logging.getLogger("utils.thumbnail")


class ThumbnailGenerationError(Exception):
    pass


@dataclass
class Thumbnail:
    image: bytes
    time: float
    title: str | None = None


# Redis queue does not properly support async, and doesn't need it anyway since it is
# only running one job at a time
def generate_thumbnail(video_id: str, time: float, title: str | None, is_livestream: bool = False, update_redis: bool = True):
    try:
        now = time_module.time()
        if not valid_video_id(video_id):
            raise ValueError(f"Invalid video ID: {video_id}")
        if not isinstance(time, float):
            raise ValueError(f"Invalid time: {time}")

        if update_redis:
            try:
                asyncio.get_event_loop().run_until_complete(update_last_used(video_id))
            except Exception:
                logger.exception("Failed to update last used")

        generate_and_store_thumbnail(video_id, time, is_livestream)

        _, output_file, metadata_file, _ = get_file_paths(video_id, time, is_livestream)
        if title is not None:
            metadata_file.write_text(title)

        title_file_size = len(title.encode("utf-8")) if title else 0
        image_file_size = os.path.getsize(output_file)
        storage_used = title_file_size + image_file_size

        if image_file_size < minimum_file_size:
            os.remove(output_file)
            if update_redis:
                try:
                    asyncio.get_event_loop().run_until_complete(add_storage_used(title_file_size))
                except Exception:
                    logger.exception("Failed to update storage used")

            raise ThumbnailGenerationError(f"Image file for {video_id} at {time} is too small, probably a premiere: {image_file_size} bytes")

        if update_redis:
            try:
                asyncio.get_event_loop().run_until_complete(add_storage_used(storage_used))
            except Exception:
                logger.exception("Failed to update storage used")
        publish_job_status(video_id, time, "true")
        check_if_cleanup_needed()

        logger.info(f"Generated thumbnail for {video_id} at {time} in {time_module.time() - now} seconds")

    except Exception:
        logger.exception(f"Failed to generate thumbnail for {video_id} at {time}")
        publish_job_status(video_id, time, "false")
        raise


@retry(ThumbnailGenerationError, tries=2, delay=1)
def generate_and_store_thumbnail(video_id: str, time: float, is_livestream: bool):
    logger.debug(f"playback url start: {time_module.time()}")

    proxy = get_proxy_url()
    proxy_url = proxy.url if proxy is not None else None
    playback_url = get_playback_url(video_id, proxy_url)

    logger.debug(f"playback url done {time_module.time()}")

    try:
        try:
            proxy_to_use = proxy_url if config.skip_local_ffmpeg else None
            logger.debug(
                f"Generating image for {video_id}, {time_module.time()}"
                f"{'' if proxy_to_use is None or proxy is None else f' through proxy {proxy.country_code}'}"
            )

            generate_with_ffmpeg(video_id, time, playback_url, is_livestream, proxy_to_use)
            logger.debug(f"generated: {time_module.time()}")
        except FFmpegError:
            if proxy_url is not None and proxy is not None:
                # try again through proxy
                logger.debug(f"Trying to generate again through the proxy {proxy.country_code}: {time_module.time()}")
                generate_with_ffmpeg(video_id, time, playback_url, is_livestream, proxy_url)
            else:
                raise
    except FFmpegError as e:
        raise ThumbnailGenerationError(
            f"Failed to generate thumbnail for {video_id} at {time} "
            f"with proxy {proxy.country_code if proxy is not None else ''}"
        ) from e


def generate_with_ffmpeg(video_id: str, time: float, playback_url: PlaybackUrl,
                         is_livestream: bool, proxy_url: str | None = None) -> None:
    output_folder, output_file, _, video_file = get_file_paths(video_id, time, is_livestream)
    output_folder.mkdir(parents=True, exist_ok=True)

    # Round down time to nearest frame be consistent with browsers
    rounded_time = int(time * playback_url.fps) / playback_url.fps

    # Rounding error with 60 fps videos cause the wrong frame to render
    if playback_url.fps == 60:
        rounded_time = max(0, rounded_time - 1/100)

    if is_livestream:
        video_request_start = time_module.time()

        def trace_function(*_):
            if time_module.time() - video_request_start > VIDEO_REQUEST_TIMEOUT:
                raise Exception("Video Request Timed Out")

        sys.settrace(trace_function)
        try:
            proxies = {
                "http": proxy_url,
                "https": proxy_url
            } if proxy_url is not None else None

            video = requests.get(playback_url.url,
                                 timeout=5,
                                 proxies=proxies)
            video_file.write_bytes(video.content)
            logger.debug(f"Downloaded livestream video to {video_file} with size of {len(video.content)}")
        except Exception:
            video_file.unlink(missing_ok=True)
            raise
        finally:
            sys.settrace(None)

    http_proxy = []
    if proxy_url is not None and not is_livestream:
        http_proxy = ["-http_proxy", proxy_url]
    try:
        run_ffmpeg(
            "-y",
            *http_proxy,
            "-ss", str(rounded_time), "-i", video_file if is_livestream else playback_url.url,
            "-vframes", "1", "-lossless", "0", "-pix_fmt", "bgra", output_file,
            "-timelimit", "20",
            timeout=20,
        )
    except FFmpegError:
        output_file.unlink(missing_ok=True)
        raise
    finally:
        if is_livestream:
            video_file.unlink(missing_ok=True)


async def get_latest_thumbnail_from_files(video_id: str, is_livestream: bool) -> Thumbnail:
    if not valid_video_id(video_id):
        raise ValueError(f"Invalid video ID: {video_id}")

    output_folder = get_folder_path(video_id)

    files = os.listdir(output_folder)
    files.sort(key=lambda x: os.path.getmtime(output_folder / x), reverse=True)

    best_time = await get_best_time(video_id)

    selected_file: str | None = f"{best_time.decode()}{image_format}" if best_time is not None else None

    # Fallback to latest image
    if selected_file is None or selected_file not in files:
        selected_file = None

        for file in files:
            # First try latest metadata file
            # Most recent with a title is probably best
            if file.endswith(metadata_format):
                selected_file = file
                break

        if selected_file is None:
            # Fallback to latest image
            for file in files:
                if file.endswith(image_format):
                    selected_file = file
                    break

    if selected_file is not None:
        # Remove file extension
        time = float(re.sub(r"(?:-live)?\.\S{3,4}$", "", selected_file))
        return await get_thumbnail_from_files(video_id, time, is_livestream)

    raise FileNotFoundError(f"Failed to find thumbnail for {video_id}")


async def get_thumbnail_from_files(video_id: str, time: float, is_livestream: bool, title: str | None = None) -> Thumbnail:
    if not valid_video_id(video_id):
        raise ValueError(f"Invalid video ID: {video_id}")
    if not isinstance(time, float):
        raise ValueError(f"Invalid time: {time}")

    with os.scandir(get_folder_path(video_id)) as it:
        truncated_time = math.floor((time * 1000)) / 1000
        truncated_time_string = str(truncated_time)
        if "." in truncated_time_string:
            for entry in it:
                if entry.is_file() and entry.name.endswith(image_format) \
                        and entry.name.startswith(truncated_time_string):
                    try:
                        time = float(entry.name.replace(image_format, ""))
                    except ValueError:
                        continue
                    break

    _, output_file, metadata_file, _ = get_file_paths(video_id, time, is_livestream)

    image_data = output_file.read_bytes()
    if image_data == b"":
        raise FileNotFoundError(f"Image file for {video_id} at {time} zero bytes")

    if title is not None:
        metadata_file.write_text(title)

    try:
        await update_last_used(video_id)
    except Exception:
        logger.exception("Failed to update last used")

    if title is None and metadata_file.exists():
        return Thumbnail(image_data, time, metadata_file.read_text())
    else:
        return Thumbnail(image_data, time)


def get_file_paths(video_id: str, time: float, is_livestream: bool) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path, pathlib.Path]:
    if not valid_video_id(video_id):
        raise ValueError(f"Invalid video ID: {video_id}")
    if not isinstance(time, float):
        raise ValueError(f"Invalid time: {time}")

    output_folder = get_folder_path(video_id)
    output_filename = output_folder/f"{time}{'-live' if is_livestream else ''}{image_format}"
    metadata_filename = output_folder/f"{time}{metadata_format}"
    video_filename = output_folder/f"{time}.mp4"

    return output_folder, output_filename, metadata_filename, video_filename


def get_folder_path(video_id: str) -> pathlib.Path:
    if not valid_video_id(video_id):
        raise ValueError(f"Invalid video ID: {video_id}")

    return config.thumbnail_storage.path/video_id


def get_job_id(video_id: str, time: float) -> str:
    return f"{video_id}-{time}"


def get_best_time_key(video_id: str) -> str:
    return f"best-{video_id}"


@retry(tries=5, delay=0.1, backoff=3)
def publish_job_status(video_id: str, time: float, status: str) -> None:
    redis_conn.publish(get_job_id(video_id, time), status)


async def set_best_time(video_id: str, time: float) -> None:
    await (await get_async_redis_conn()).set(get_best_time_key(video_id), time)


async def get_best_time(video_id: str) -> bytes | None:
    return cast(bytes | None, await (await get_async_redis_conn()).get(get_best_time_key(video_id)))
