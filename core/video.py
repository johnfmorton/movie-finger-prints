import json
import os
import subprocess
import tempfile
from dataclasses import dataclass

from core.filters import is_black_frame


@dataclass
class VideoInfo:
    duration: float
    width: int
    height: int
    frame_count: int
    aspect_ratio: tuple[int, int]


def _gcd(a: int, b: int) -> int:
    while b:
        a, b = b, a % b
    return a


def probe_video(path: str) -> VideoInfo:
    """Use ffprobe to get video metadata."""
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)

    video_stream = None
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            video_stream = stream
            break

    if video_stream is None:
        raise ValueError("No video stream found in file")

    width = int(video_stream["width"])
    height = int(video_stream["height"])
    duration = float(data["format"]["duration"])

    # Try to get frame count from stream metadata
    frame_count = 0
    if "nb_frames" in video_stream:
        try:
            frame_count = int(video_stream["nb_frames"])
        except (ValueError, TypeError):
            pass

    if frame_count == 0:
        # Estimate from duration and frame rate
        r_frame_rate = video_stream.get("r_frame_rate", "24/1")
        num, den = r_frame_rate.split("/")
        fps = float(num) / float(den)
        frame_count = int(duration * fps)

    # Calculate simplified aspect ratio
    divisor = _gcd(width, height)
    aspect_ratio = (width // divisor, height // divisor)

    return VideoInfo(
        duration=duration,
        width=width,
        height=height,
        frame_count=frame_count,
        aspect_ratio=aspect_ratio,
    )


def extract_frames(
    path: str,
    count: int,
    skip_black: bool = False,
    progress_callback=None,
) -> list[str]:
    """Extract evenly-spaced frames from a video file.

    Returns a list of file paths to extracted JPEG frames.
    """
    info = probe_video(path)
    tmp_dir = tempfile.mkdtemp(prefix="movie_fp_")

    # Extract extra frames if we need to filter black ones
    extract_count = int(count * 1.2) if skip_black else count
    extract_count = min(extract_count, info.frame_count)

    interval = info.duration / extract_count
    extracted_paths = []

    for i in range(extract_count):
        timestamp = interval * i + interval / 2  # sample mid-interval
        # Clamp to stay within video duration
        timestamp = min(timestamp, info.duration - 0.01)
        out_path = os.path.join(tmp_dir, f"frame_{i:06d}.jpg")

        cmd = [
            "ffmpeg",
            "-v", "quiet",
            "-ss", str(timestamp),
            "-i", path,
            "-frames:v", "1",
            "-q:v", "2",
            out_path,
        ]
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode == 0 and os.path.isfile(out_path):
            extracted_paths.append(out_path)

        if progress_callback:
            progress_callback(i + 1, extract_count + 1)  # +1 for compositing step

    if skip_black:
        filtered = [p for p in extracted_paths if not is_black_frame(p)]
        # If filtering removed too many, fall back to all extracted frames
        if len(filtered) < count:
            filtered = extracted_paths
        return _evenly_sample(filtered, count)

    return extracted_paths[:count]


def _evenly_sample(items: list, count: int) -> list:
    """Pick `count` evenly-spaced items from a list to preserve full coverage."""
    n = len(items)
    if n <= count:
        return items
    # Evenly spaced indices across the full list
    return [items[round(i * (n - 1) / (count - 1))] for i in range(count)]
