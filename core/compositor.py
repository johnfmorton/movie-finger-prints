from PIL import Image


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


def compose_grid(
    frame_paths: list[str],
    rows: int,
    cols: int,
    output_width: int,
    output_height: int,
    output_path: str,
) -> None:
    """Compose extracted frames into a grid image and save as PNG."""
    canvas = Image.new("RGB", (output_width, output_height), (0, 0, 0))

    cell_w = output_width / cols
    cell_h = output_height / rows

    # Use integer cell sizes, rounding to nearest pixel
    cell_w_int = max(1, round(cell_w))
    cell_h_int = max(1, round(cell_h))

    for idx, frame_path in enumerate(frame_paths):
        if idx >= rows * cols:
            break

        row = idx // cols
        col = idx % cols

        # Calculate paste position - distribute rounding error evenly
        x = round(col * cell_w)
        y = round(row * cell_h)

        img = Image.open(frame_path)
        img = _center_crop_resize(img, cell_w_int, cell_h_int)
        canvas.paste(img, (x, y))

    canvas.save(output_path, "PNG")
