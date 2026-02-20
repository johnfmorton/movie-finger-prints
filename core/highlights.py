"""Highlight frame utilities: timestamp parsing, weighted sampling, cell assignment."""

from __future__ import annotations

import re


def parse_timestamp(text: str) -> float:
    """Parse HH:MM:SS, MM:SS, or raw seconds into float seconds.

    Raises ValueError on unrecognised format.
    """
    text = text.strip()

    # Try raw number first (seconds, possibly with decimals)
    try:
        value = float(text)
        if value < 0:
            raise ValueError(f"Negative timestamp: {text}")
        return value
    except ValueError:
        pass

    # Try HH:MM:SS or MM:SS
    match = re.match(r"^(\d+):(\d{1,2}):(\d{1,2}(?:\.\d+)?)$", text)
    if match:
        h, m, s = int(match.group(1)), int(match.group(2)), float(match.group(3))
        return h * 3600 + m * 60 + s

    match = re.match(r"^(\d+):(\d{1,2}(?:\.\d+)?)$", text)
    if match:
        m, s = int(match.group(1)), float(match.group(2))
        return m * 60 + s

    raise ValueError(f"Unrecognised timestamp format: {text!r}")


def compute_weighted_timestamps(
    video_duration: float,
    num_frames: int,
    highlight_times: list[float],
    boost_factor: float = 2.0,
) -> list[float]:
    """Zone-based weighted sampling that places more frames near highlights.

    1. Define zones around each highlight (radius = min of half-gap-to-neighbor,
       10% of duration). Merge overlapping zones.
    2. Zone segments get boost_factor times their proportional share of frames.
    3. Within each segment, frames are evenly spaced.
    4. Return sorted timestamps.
    """
    if num_frames <= 0:
        return []
    if not highlight_times or boost_factor <= 0:
        # Fall back to even spacing
        interval = video_duration / num_frames
        return [interval * i + interval / 2 for i in range(num_frames)]

    # Build zones around highlights
    sorted_hl = sorted(highlight_times)
    max_radius = 0.10 * video_duration
    zones: list[tuple[float, float]] = []

    for i, ht in enumerate(sorted_hl):
        radius = max_radius
        if i > 0:
            radius = min(radius, (ht - sorted_hl[i - 1]) / 2)
        if i < len(sorted_hl) - 1:
            radius = min(radius, (sorted_hl[i + 1] - ht) / 2)
        start = max(0, ht - radius)
        end = min(video_duration, ht + radius)
        zones.append((start, end))

    # Merge overlapping zones
    merged: list[tuple[float, float]] = []
    for start, end in zones:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))

    # Build segments: alternating non-zone and zone
    segments: list[tuple[float, float, bool]] = []  # (start, end, is_zone)
    cursor = 0.0
    for zs, ze in merged:
        if cursor < zs:
            segments.append((cursor, zs, False))
        segments.append((zs, ze, True))
        cursor = ze
    if cursor < video_duration:
        segments.append((cursor, video_duration, False))

    # Compute total weighted duration
    zone_dur = sum(e - s for s, e, is_z in segments if is_z)
    non_zone_dur = sum(e - s for s, e, is_z in segments if not is_z)
    total_weighted = zone_dur * boost_factor + non_zone_dur

    if total_weighted <= 0:
        interval = video_duration / num_frames
        return [interval * i + interval / 2 for i in range(num_frames)]

    # Allocate frames to segments proportionally
    timestamps: list[float] = []
    frames_left = num_frames

    alloc: list[int] = []
    for s, e, is_z in segments:
        dur = e - s
        weight = dur * boost_factor if is_z else dur
        n = round(weight / total_weighted * num_frames)
        alloc.append(n)

    # Fix rounding: adjust the largest segment
    diff = num_frames - sum(alloc)
    if diff != 0 and alloc:
        max_idx = max(range(len(alloc)), key=lambda i: alloc[i])
        alloc[max_idx] += diff

    for (s, e, _), n in zip(segments, alloc):
        if n <= 0:
            continue
        interval = (e - s) / n
        for i in range(n):
            t = s + interval * i + interval / 2
            t = min(t, video_duration - 0.01)
            t = max(t, 0.0)
            timestamps.append(t)

    timestamps.sort()
    return timestamps


def assign_highlights_to_cells(
    cells: list,
    num_highlights: int,
) -> list[int]:
    """Pick the N largest cells by area (w*h), return their indices in reading order.

    Clamps if num_highlights > len(cells).
    """
    if num_highlights <= 0 or not cells:
        return []
    num_highlights = min(num_highlights, len(cells))

    # Rank by area descending, pick top N
    indexed = [(i, c.w * c.h) for i, c in enumerate(cells)]
    indexed.sort(key=lambda x: x[1], reverse=True)
    chosen = sorted(i for i, _ in indexed[:num_highlights])
    return chosen
