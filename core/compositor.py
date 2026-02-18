from __future__ import annotations

from typing import Optional

from PIL import Image, ImageDraw, ImageFont


def _center_crop_resize(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """Crop the image to match the target aspect ratio, then resize."""
    src_w, src_h = img.size
    target_ratio = target_w / target_h
    src_ratio = src_w / src_h

    if src_ratio > target_ratio:
        # Source is wider - crop sides
        new_w = int(src_h * target_ratio)
        offset = (src_w - new_w) // 2
        img = img.crop((offset, 0, offset + new_w, src_h))
    elif src_ratio < target_ratio:
        # Source is taller - crop top/bottom
        new_h = int(src_w / target_ratio)
        offset = (src_h - new_h) // 2
        img = img.crop((0, offset, src_w, offset + new_h))

    return img.resize((target_w, target_h), Image.LANCZOS)


def _load_font(size: int):
    """Try to load a system font, fall back to Pillow default."""
    for name in ("Helvetica", "Arial", "DejaVuSans"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def compose_grid(
    frame_paths: list[str],
    rows: int,
    cols: int,
    output_width: int,
    output_height: int,
    output_path: str,
    output_format: str = "PNG",
    jpeg_quality: int = 90,
    padding: int = 0,
    background_color: tuple[int, int, int] = (0, 0, 0),
    cell_labels: str = "none",
    fill_positions: list[tuple[int, int]] | None = None,
    frame_timestamps: list[str] | None = None,
    cell_rects: list[tuple[int, int, int, int]] | None = None,
) -> None:
    """Compose extracted frames into a grid image and save."""
    canvas = Image.new("RGB", (output_width, output_height), background_color)

    if cell_rects is not None:
        _compose_quadtree(canvas, frame_paths, cell_rects, cell_labels, frame_timestamps)
    else:
        _compose_uniform(
            canvas, frame_paths, rows, cols, output_width, output_height,
            padding, cell_labels, fill_positions, frame_timestamps,
        )

    # Save with format-specific options
    fmt_upper = output_format.upper()
    if fmt_upper == "JPEG":
        canvas.save(output_path, "JPEG", quality=jpeg_quality, subsampling=0)
    elif fmt_upper == "WEBP":
        canvas.save(output_path, "WEBP", quality=jpeg_quality)
    elif fmt_upper == "TIFF":
        canvas.save(output_path, "TIFF", compression="tiff_lzw")
    else:
        canvas.save(output_path, "PNG")


def _compose_uniform(
    canvas: Image.Image,
    frame_paths: list[str],
    rows: int,
    cols: int,
    output_width: int,
    output_height: int,
    padding: int,
    cell_labels: str,
    fill_positions: list[tuple[int, int]] | None,
    frame_timestamps: list[str] | None,
) -> None:
    # Calculate cell dimensions accounting for padding gaps
    h_gaps = cols - 1
    v_gaps = rows - 1
    total_h_padding = padding * h_gaps
    total_v_padding = padding * v_gaps

    # Clamp: ensure cells get at least 1px each
    usable_w = max(cols, output_width - total_h_padding)
    usable_h = max(rows, output_height - total_v_padding)

    cell_w = usable_w / cols
    cell_h = usable_h / rows

    cell_w_int = max(1, round(cell_w))
    cell_h_int = max(1, round(cell_h))

    # Prepare label drawing
    draw = None
    font = None
    font_size = 0
    if cell_labels != "none" and cell_h_int >= 20:
        draw = ImageDraw.Draw(canvas)
        font_size = max(10, min(cell_h_int // 4, cell_w_int // 4, 24))
        font = _load_font(font_size)

    for idx, frame_path in enumerate(frame_paths):
        if idx >= rows * cols:
            break

        if fill_positions and idx < len(fill_positions):
            row, col = fill_positions[idx]
        else:
            row = idx // cols
            col = idx % cols

        # Position includes padding gaps
        x = round(col * (cell_w + padding))
        y = round(row * (cell_h + padding))

        img = Image.open(frame_path)
        img = _center_crop_resize(img, cell_w_int, cell_h_int)
        canvas.paste(img, (x, y))

        # Draw cell label
        if draw and font:
            if cell_labels == "frame_number":
                label_text = str(idx + 1)
            elif cell_labels == "timestamp" and frame_timestamps and idx < len(frame_timestamps):
                label_text = frame_timestamps[idx]
            else:
                label_text = None

            if label_text:
                lx = x + 4
                ly = y + cell_h_int - font_size - 4
                # Shadow for readability
                draw.text((lx + 1, ly + 1), label_text, fill=(0, 0, 0), font=font)
                draw.text((lx, ly), label_text, fill=(255, 255, 255), font=font)


def _compose_quadtree(
    canvas: Image.Image,
    frame_paths: list[str],
    cell_rects: list[tuple[int, int, int, int]],
    cell_labels: str,
    frame_timestamps: list[str] | None,
) -> None:
    draw = ImageDraw.Draw(canvas) if cell_labels != "none" else None

    for idx, (frame_path, (cx, cy, cw, ch)) in enumerate(zip(frame_paths, cell_rects)):
        img = Image.open(frame_path)
        img = _center_crop_resize(img, cw, ch)
        canvas.paste(img, (cx, cy))

        # Draw cell label — skip when cell is too small
        if draw and ch >= 20 and cw >= 30:
            if cell_labels == "frame_number":
                label_text = str(idx + 1)
            elif cell_labels == "timestamp" and frame_timestamps and idx < len(frame_timestamps):
                label_text = frame_timestamps[idx]
            else:
                label_text = None

            if label_text:
                font_size = max(10, min(ch // 4, cw // 4, 24))
                font = _load_font(font_size)
                lx = cx + 4
                ly = cy + ch - font_size - 4
                draw.text((lx + 1, ly + 1), label_text, fill=(0, 0, 0), font=font)
                draw.text((lx, ly), label_text, fill=(255, 255, 255), font=font)
