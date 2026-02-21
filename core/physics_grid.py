"""Physics-based grid layout using pymunk for collision resolution."""

from __future__ import annotations

import math
from dataclasses import dataclass

import pymunk


@dataclass
class PhysicsFrameResult:
    x: int       # top-left pixel x
    y: int       # top-left pixel y
    w: int       # unrotated frame width
    h: int       # unrotated frame height
    angle: float  # rotation in degrees (0.0 when disabled)


def compute_physics_layout(
    rows: int,
    cols: int,
    canvas_w: int,
    canvas_h: int,
    frame_weights: list[float],
    allow_rotation: bool = False,
    padding: int = 0,
    max_iterations: int = 2000,
    settle_threshold: float = 0.5,
) -> list[PhysicsFrameResult]:
    """Lay out frames using physics simulation.

    Highlighted frames (weight > 1.0) grow and push neighbours aside via
    pymunk collision resolution.  Returns per-frame position, size, and
    rotation data ready for the compositor.
    """
    total = rows * cols
    weights = frame_weights[:total]
    while len(weights) < total:
        weights.append(1.0)

    # Fast path: no highlights -> standard grid
    if max(weights) <= 1.0:
        return _standard_grid(rows, cols, canvas_w, canvas_h, padding)

    # Base cell size
    base_w = canvas_w / cols
    base_h = canvas_h / rows

    # Build pymunk space
    space = pymunk.Space()
    space.gravity = (0, 0)
    space.damping = 0.3

    # Static boundary walls (thick so nothing escapes)
    wall_thickness = 200
    walls = [
        # bottom
        ((canvas_w / 2, canvas_h + wall_thickness / 2), (canvas_w + wall_thickness * 2, wall_thickness)),
        # top
        ((canvas_w / 2, -wall_thickness / 2), (canvas_w + wall_thickness * 2, wall_thickness)),
        # left
        ((-wall_thickness / 2, canvas_h / 2), (wall_thickness, canvas_h + wall_thickness * 2)),
        # right
        ((canvas_w + wall_thickness / 2, canvas_h / 2), (wall_thickness, canvas_h + wall_thickness * 2)),
    ]
    for (wx, wy), (ww, wh) in walls:
        body = pymunk.Body(body_type=pymunk.Body.STATIC)
        body.position = (wx, wy)
        shape = pymunk.Poly.create_box(body, (ww, wh))
        shape.elasticity = 0.0
        shape.friction = 0.8
        space.add(body, shape)

    bodies: list[pymunk.Body] = []
    origins: list[tuple[float, float]] = []

    for idx in range(total):
        r = idx // cols
        c = idx % cols
        w = weights[idx]

        # Center of standard grid cell
        cx = (c + 0.5) * base_w
        cy = (r + 0.5) * base_h

        # Scale by sqrt(weight) per axis so area ~ weight
        scale = math.sqrt(w)
        fw = base_w * scale
        fh = base_h * scale

        mass = fw * fh  # proportional to area
        if allow_rotation:
            moment = pymunk.moment_for_box(mass, (fw, fh))
        else:
            moment = float('inf')

        body = pymunk.Body(mass, moment)
        body.position = (cx, cy)
        shape = pymunk.Poly.create_box(body, (fw, fh))
        shape.elasticity = 0.0
        shape.friction = 0.8
        space.add(body, shape)

        bodies.append(body)
        origins.append((cx, cy))

    # Centering springs: pull each body toward its original position
    static_anchor = pymunk.Body(body_type=pymunk.Body.STATIC)
    space.add(static_anchor)

    for idx, body in enumerate(bodies):
        ox, oy = origins[idx]
        static_anchor.position = (ox, oy)
        spring = pymunk.DampedSpring(
            body, static_anchor,
            anchor_a=(0, 0), anchor_b=(0, 0),
            rest_length=0,
            stiffness=50,
            damping=100,
        )
        space.add(spring)

    # Simulate until settled
    dt = 1.0 / 60.0
    for _ in range(max_iterations):
        space.step(dt)
        total_ke = sum(b.kinetic_energy for b in bodies)
        if total_ke < settle_threshold:
            break

    # Extract results
    results: list[PhysicsFrameResult] = []
    for idx, body in enumerate(bodies):
        w = weights[idx]
        scale = math.sqrt(w)
        fw = int(round(base_w * scale))
        fh = int(round(base_h * scale))

        # Body position is center; convert to top-left
        cx, cy = body.position
        angle_deg = math.degrees(body.angle) if allow_rotation else 0.0

        x = int(round(cx - fw / 2))
        y = int(round(cy - fh / 2))

        # Clamp to canvas
        x = max(0, min(x, canvas_w - fw))
        y = max(0, min(y, canvas_h - fh))
        fw = min(fw, canvas_w)
        fh = min(fh, canvas_h)

        results.append(PhysicsFrameResult(x=x, y=y, w=fw, h=fh, angle=angle_deg))

    return results


def _standard_grid(
    rows: int, cols: int, canvas_w: int, canvas_h: int, padding: int,
) -> list[PhysicsFrameResult]:
    """Fast path: uniform grid with no simulation."""
    h_gaps = cols - 1
    v_gaps = rows - 1
    total_h_padding = padding * h_gaps
    total_v_padding = padding * v_gaps

    usable_w = max(cols, canvas_w - total_h_padding)
    usable_h = max(rows, canvas_h - total_v_padding)

    cell_w = usable_w / cols
    cell_h = usable_h / rows

    results: list[PhysicsFrameResult] = []
    for idx in range(rows * cols):
        r = idx // cols
        c = idx % cols
        x = round(c * (cell_w + padding))
        y = round(r * (cell_h + padding))
        results.append(PhysicsFrameResult(
            x=x, y=y,
            w=max(1, round(cell_w)),
            h=max(1, round(cell_h)),
            angle=0.0,
        ))
    return results
