import subprocess
import shutil
import socket
import time
import pathlib

TimeoutExpired = subprocess.TimeoutExpired
ffmpeg_path = shutil.which("ffmpeg")
if ffmpeg_path is None:
    raise RuntimeError("ffmpeg binary couldn't be found on the PATH")


class FFmpegError(Exception):
    exit_code: int

    def __init__(self, exit_code: int):
        super().__init__(f"FFmpeg exited with exit code {exit_code}")
        self.exit_code = exit_code


def run_ffmpeg(*args: str, timeout: float | None = None):
    """
    Runs FFmpeg. Any output is /dev/null'd.

    Raises subprocess.TimeoutExpired on timeout. (reexported here for convenience)
    Raises FFmpegError if FFmpeg exits with a non-zero code.
    """
    log = pathlib.Path(f"logs/{socket.gethostname()}/ffmpeg-{round(time.time()*1000)}.log")
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w") as f:
        proc = subprocess.run(
            [ffmpeg_path, *args],
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=f,
            stderr=f,
            timeout=timeout,
        )

    if proc.returncode != 0:
        raise FFmpegError(proc.returncode)
    else:
        log.unlink()
