from __future__ import annotations

import math
import random
from dataclasses import dataclass
from enum import Enum


class SubdivisionStyle(Enum):
    BALANCED = "Balanced"
    RANDOM = "Random"
    CENTER_WEIGHTED = "Center weighted"


@dataclass
class QuadCell:
    x: float  # normalized 0–1
    y: float
    w: float
    h: float
    depth: int


def generate_quadtree(
    max_depth: int,
    style: SubdivisionStyle,
    seed: int = 42,
) -> list[QuadCell]:
    """Recursively subdivide the unit square into quadrant cells.

    Returns leaf cells sorted in reading order (top-to-bottom, left-to-right).
    """
    rng = random.Random(seed)
    leaves: list[QuadCell] = []

    def _subdivide(x: float, y: float, w: float, h: float, depth: int):
        if depth >= max_depth:
            leaves.append(QuadCell(x, y, w, h, depth))
            return

        should_split = _should_subdivide(x, y, w, h, depth, max_depth, style, rng)

        if not should_split:
            leaves.append(QuadCell(x, y, w, h, depth))
            return

        hw = w / 2
        hh = h / 2
        _subdivide(x, y, hw, hh, depth + 1)          # top-left
        _subdivide(x + hw, y, hw, hh, depth + 1)      # top-right
        _subdivide(x, y + hh, hw, hh, depth + 1)      # bottom-left
        _subdivide(x + hw, y + hh, hw, hh, depth + 1)  # bottom-right

    # Root is always split (depth 0 → guarantees at least 4 cells)
    hw = 0.5
    hh = 0.5
    _subdivide(0, 0, hw, hh, 1)
    _subdivide(hw, 0, hw, hh, 1)
    _subdivide(0, hh, hw, hh, 1)
    _subdivide(hw, hh, hw, hh, 1)

    # Sort in reading order: top-to-bottom then left-to-right with tolerance
    # Group rows by y-center with tolerance based on the smallest cell height
    min_h = min(c.h for c in leaves) if leaves else 0.01
    tolerance = min_h / 2

    leaves.sort(key=lambda c: (round(c.y / tolerance) * tolerance, c.x))

    return leaves


def _should_subdivide(
    x: float,
    y: float,
    w: float,
    h: float,
    depth: int,
    max_depth: int,
    style: SubdivisionStyle,
    rng: random.Random,
) -> bool:
    if depth >= max_depth:
        return False

    if style == SubdivisionStyle.BALANCED:
        return True

    if style == SubdivisionStyle.RANDOM:
        return rng.random() < 0.70

    if style == SubdivisionStyle.CENTER_WEIGHTED:
        # Center of this cell
        cx = x + w / 2
        cy = y + h / 2
        # Distance from canvas center (0.5, 0.5), max is ~0.707
        dist = math.sqrt((cx - 0.5) ** 2 + (cy - 0.5) ** 2)
        max_dist = math.sqrt(0.5)
        t = dist / max_dist  # 0 at center, 1 at corner
        # 95% at center → 15% at corners
        prob = 0.95 - 0.80 * t
        return rng.random() < prob

    return False


def cells_to_pixel_rects(
    cells: list[QuadCell],
    canvas_width: int,
    canvas_height: int,
    padding: int = 0,
) -> list[tuple[int, int, int, int]]:
    """Convert normalized QuadCells to pixel (x, y, w, h) tuples.

    Applies padding as inset so each cell shrinks by padding//2 per edge,
    creating uniform visual gaps.
    """
    inset = padding // 2
    rects: list[tuple[int, int, int, int]] = []

    for cell in cells:
        px = round(cell.x * canvas_width)
        py = round(cell.y * canvas_height)
        pw = round(cell.w * canvas_width)
        ph = round(cell.h * canvas_height)

        # Apply padding inset
        px += inset
        py += inset
        pw -= padding  # shrink by inset on each side
        ph -= padding

        # Clamp to ensure minimum 1px
        pw = max(1, pw)
        ph = max(1, ph)

        rects.append((px, py, pw, ph))

    return rects
