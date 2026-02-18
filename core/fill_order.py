from __future__ import annotations

from enum import Enum


class FillOrder(Enum):
    STANDARD = "Standard"
    SPIRAL = "Spiral from center"
    DIAGONAL = "Diagonal"


def compute_fill_order(rows: int, cols: int, order: FillOrder) -> list[tuple[int, int]]:
    """Return a list of (row, col) positions for each frame index.

    The length of the returned list is always rows * cols.
    """
    if order == FillOrder.STANDARD:
        return _standard(rows, cols)
    elif order == FillOrder.SPIRAL:
        return _spiral_from_center(rows, cols)
    elif order == FillOrder.DIAGONAL:
        return _diagonal(rows, cols)
    raise ValueError(f"Unknown fill order: {order}")


def _standard(rows: int, cols: int) -> list[tuple[int, int]]:
    return [(r, c) for r in range(rows) for c in range(cols)]


def _spiral_from_center(rows: int, cols: int) -> list[tuple[int, int]]:
    total = rows * cols
    if total == 0:
        return []

    # Start at center
    r, c = rows // 2, cols // 2
    positions = [(r, c)]

    # Direction vectors: right, down, left, up
    dr = [0, 1, 0, -1]
    dc = [1, 0, -1, 0]
    direction = 0
    steps = 1

    while len(positions) < total:
        for _ in range(2):  # Each step count is used twice
            for _ in range(steps):
                r += dr[direction]
                c += dc[direction]
                if 0 <= r < rows and 0 <= c < cols:
                    positions.append((r, c))
                if len(positions) >= total:
                    break
            direction = (direction + 1) % 4
            if len(positions) >= total:
                break
        steps += 1

    return positions[:total]


def _diagonal(rows: int, cols: int) -> list[tuple[int, int]]:
    positions = []
    # Walk anti-diagonals where r + c = constant
    for diag_sum in range(rows + cols - 1):
        r_start = min(diag_sum, rows - 1)
        r_end = max(0, diag_sum - cols + 1)
        for r in range(r_start, r_end - 1, -1):
            c = diag_sum - r
            positions.append((r, c))
    return positions
