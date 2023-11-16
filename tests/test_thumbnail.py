import pathlib
from multiprocessing import Process
import shutil
import time
from unittest.mock import patch

from fastapi import Response
import pytest
from rq.worker import Worker
from app import get_thumbnail
from utils.cleanup import cleanup, last_used_element_key, last_used_key
from utils.redis_handler import get_async_redis_conn, reset_async_redis_conn, redis_conn
from utils.thumbnail import generate_thumbnail, get_file_paths

TEST_CACHE = pathlib.Path("test-cache")
# Clear test cache folder
if TEST_CACHE.exists():
    shutil.rmtree("test-cache")

@pytest.fixture(scope="function", autouse=True)
def setup():
    reset_async_redis_conn()

@pytest.mark.asyncio
async def test_thumbnail_zero():
    test_video_id = "jNQXAC9IVRw"
    test_time = 0.0
    await load_and_verify_thumbnail(test_video_id, test_time)
    await load_and_verify_request(test_video_id, test_time)

@pytest.mark.asyncio
async def test_thumbnail_non_zero():
    test_video_id = "jNQXAC9IVRw"
    test_time = 5.3
    await load_and_verify_thumbnail(test_video_id, test_time)
    await load_and_verify_request(test_video_id, test_time)

@pytest.mark.asyncio
async def test_thumbnail_with_title():
    test_video_id = "jNQXAC9IVRw"
    test_time = 17.0
    test_title = "Me at the zoo"
    await load_and_verify_thumbnail(test_video_id, test_time, test_title)
    await load_and_verify_request(test_video_id, test_time, test_title)

@pytest.mark.asyncio
async def test_thumbnail_with_title_generate_now():
    worker = Worker("high", connection=redis_conn)
    thread = Process(target=worker.work, args=(worker,))
    thread.start()

    test_video_id = "bdq-IYxhByw"
    test_time = 15.0
    test_title = "Not me at the zoo"
    await load_and_verify_request(test_video_id, test_time, test_title, True, True)

    # Try again without sending the title
    await load_and_verify_request(test_video_id, test_time, test_title)

    thread.kill()

def fake_folder_size(path: pathlib.Path, _ = False) -> tuple[int, int]:
    if path == TEST_CACHE:
        return (100001, 1)
    else:
        return (100, 0)

@pytest.mark.asyncio
async def test_cleanup():
    with patch("utils.cleanup.get_folder_size", wraps=fake_folder_size):
        new_video_id = "bdq-IYxhByw"
        old_video_id = "jNQXAC9IVRw"

        # Make this video the newest
        await (await get_async_redis_conn()).zadd(name=last_used_key(), mapping={
            last_used_element_key(new_video_id): int(time.time())
        })

        assert (TEST_CACHE/new_video_id).exists()
        assert (TEST_CACHE/old_video_id).exists()

        cleanup()

        assert (TEST_CACHE/new_video_id).exists()
        assert not (TEST_CACHE/old_video_id).exists()

async def load_and_verify_request(video_id: str, time: float, title: str | None = None, send_title: bool = False, generate_now: bool = False) -> None:
    test_response = Response()
    test_result = await get_thumbnail(test_response, None, video_id, time, generate_now, title if send_title else None) # type: ignore
    assert test_result.status_code == 200
    assert test_result.body != b""
    assert test_result.headers["X-Timestamp"] == str(time)

    if title is not None and not send_title:
        assert test_result.headers["X-Title"] == title


async def load_and_verify_thumbnail(video_id: str, time: float, title: str | None = None) -> None:
    generate_thumbnail(video_id, time, title, False, False)

    # verify file exists
    _, output_file, metadata_file = get_file_paths(video_id, time, False)
    assert output_file.is_file()
    image = output_file.read_bytes()
    assert len(image) > 0

    if title is not None:
        assert metadata_file.is_file()
        assert metadata_file.read_text() == title
