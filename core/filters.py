import numpy as np
from PIL import Image


def is_black_frame(image_path: str, threshold: float = 10.0) -> bool:
    """Check if an image is a near-black frame.

    Loads the image, converts to a numpy array, and checks whether
    the mean pixel intensity is below the threshold.
    """
    img = Image.open(image_path).convert("RGB")
    pixels = np.array(img)
    return float(pixels.mean()) < threshold
