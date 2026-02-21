"""Highlight frame utilities: timestamp parsing, weighted sampling, cell assignment."""

from __future__ import annotations

import re
from enum import Enum


class EmphasisStyle(Enum):
    BIGGER = "Bigger"
    RAMP_UP = "Ramp Up"
    RAMP_DOWN = "Ramp Down"
    RAMP_UP_DOWN = "Ramp Up & Down"


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


def assign_highlights_to_cells_temporal(
    highlight_times: list[float],
    video_duration: float,
    total_frames: int,
) -> list[int]:
    """Map highlight timestamps to cell indices by temporal position.

    Each timestamp maps to ``round(ts / duration * (total_frames - 1))``.
    Collisions are resolved by bumping to the next free cell.
    Returns sorted cell indices (one per highlight, in timestamp order).
    """
    if not highlight_times or total_frames <= 0 or video_duration <= 0:
        return []

    sorted_times = sorted(highlight_times)
    used: set[int] = set()
    indices: list[int] = []

    for ts in sorted_times:
        ideal = round(ts / video_duration * (total_frames - 1))
        ideal = max(0, min(ideal, total_frames - 1))
        idx = ideal
        # Bump forward on collision, then wrap backward if needed
        while idx in used and idx < total_frames:
            idx += 1
        if idx >= total_frames:
            idx = ideal - 1
            while idx in used and idx >= 0:
                idx -= 1
        idx = max(0, min(idx, total_frames - 1))
        used.add(idx)
        indices.append(idx)

    return sorted(indices)


def compute_frame_weights(
    total_frames: int,
    highlight_cell_indices: list[int],
    highlight_emphasis: list[EmphasisStyle],
    ramp_length: int = 3,
    size_boost: float = 3.0,
) -> list[float]:
    """Compute per-frame size weights based on highlight emphasis styles.

    Normal frames get weight 1.0.  Highlight frames get ``size_boost``.
    Ramp frames are linearly interpolated from 1.0 to ``size_boost`` over
    ``ramp_length`` cells.  Overlapping ramps resolve via ``max()``.

    ``highlight_cell_indices`` and ``highlight_emphasis`` must be parallel
    lists (same length, matched by position after sorting by index).
    """
    weights = [1.0] * total_frames

    if not highlight_cell_indices or not highlight_emphasis:
        return weights

    # Pair indices with emphasis, sorted by index
    pairs = sorted(zip(highlight_cell_indices, highlight_emphasis), key=lambda p: p[0])

    for cell_idx, style in pairs:
        if 0 <= cell_idx < total_frames:
            weights[cell_idx] = max(weights[cell_idx], size_boost)

        # Apply ramps
        if style in (EmphasisStyle.RAMP_UP, EmphasisStyle.RAMP_UP_DOWN):
            for step in range(1, ramp_length + 1):
                ri = cell_idx - step
                if 0 <= ri < total_frames:
                    t = 1.0 + (size_boost - 1.0) * (ramp_length - step) / ramp_length
                    weights[ri] = max(weights[ri], t)

        if style in (EmphasisStyle.RAMP_DOWN, EmphasisStyle.RAMP_UP_DOWN):
            for step in range(1, ramp_length + 1):
                ri = cell_idx + step
                if 0 <= ri < total_frames:
                    t = 1.0 + (size_boost - 1.0) * (ramp_length - step) / ramp_length
                    weights[ri] = max(weights[ri], t)

    return weights


def compute_weighted_cell_rects(
    weights: list[float],
    rows: int,
    cols: int,
    canvas_w: int,
    canvas_h: int,
    padding: int = 0,
) -> list[tuple[int, int, int, int]]:
    """Row-based justified layout where each frame's area is proportional to its weight.

    Frames are chunked into ``rows`` rows of ``cols`` frames each.
    Row height is proportional to the row's total weight.
    Frame width within a row is proportional to its individual weight.
    Padding is applied as inset (same pattern as ``cells_to_pixel_rects``).
    Returns ``(x, y, w, h)`` pixel tuples compatible with ``_compose_quadtree``.
    """
    total_frames = len(weights)
    inset = padding // 2

    # Chunk weights into rows
    row_weights: list[list[float]] = []
    for r in range(rows):
        start = r * cols
        end = min(start + cols, total_frames)
        row_weights.append(weights[start:end])

    # Row heights proportional to sum of weights in each row
    row_sums = [sum(rw) for rw in row_weights]
    total_weight = sum(row_sums)
    if total_weight <= 0:
        total_weight = 1.0

    rects: list[tuple[int, int, int, int]] = []
    y_cursor = 0

    for r, rw in enumerate(row_weights):
        row_sum = row_sums[r]
        # Integer row height (last row takes remainder)
        if r == rows - 1:
            row_h = canvas_h - y_cursor
        else:
            row_h = round(row_sum / total_weight * canvas_h)

        x_cursor = 0
        for i, w in enumerate(rw):
            # Integer frame width (last frame in row takes remainder)
            if i == len(rw) - 1:
                frame_w = canvas_w - x_cursor
            else:
                frame_w = round(w / row_sum * canvas_w) if row_sum > 0 else 0

            # Apply padding inset
            px = x_cursor + inset
            py = y_cursor + inset
            pw = max(1, frame_w - padding)
            ph = max(1, row_h - padding)

            rects.append((px, py, pw, ph))
            x_cursor += frame_w

        y_cursor += row_h

    return rects
