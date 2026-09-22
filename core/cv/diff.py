from __future__ import annotations

from typing import Optional, Union
import cv2
import numpy as np


def compute_dhash(image_input: Union[np.ndarray, bytes], hash_size: int = 8) -> str:
    """Compute difference hash (dHash) for fast frame comparison."""
    if isinstance(image_input, bytes):
        nparr = np.frombuffer(image_input, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_GRAYSCALE)
    elif len(image_input.shape) == 3:
        img = cv2.cvtColor(image_input, cv2.COLOR_BGR2GRAY)
    else:
        img = image_input

    if img is None:
        return "0" * (hash_size * hash_size)

    # Resize to (width + 1, height)
    resized = cv2.resize(img, (hash_size + 1, hash_size), interpolation=cv2.INTER_AREA)

    # Compare adjacent pixels
    diff = resized[:, 1:] > resized[:, :-1]
    # Convert bool array to hex string
    bit_string = "".join(["1" if b else "0" for b in diff.flatten()])
    return f"{int(bit_string, 2):0{hash_size * hash_size // 4}x}"


def calc_hamming_distance(hash1: str, hash2: str) -> int:
    """Calculate the Hamming distance between two hex hash strings."""
    if len(hash1) != len(hash2):
        return 999
    try:
        val1 = int(hash1, 16)
        val2 = int(hash2, 16)
        return bin(val1 ^ val2).count("1")
    except ValueError:
        return 999


def is_frame_static(
    frame1: Union[np.ndarray, bytes],
    frame2: Union[np.ndarray, bytes],
    max_distance: int = 3,
) -> bool:
    """Return True if two frames have a Hamming distance within max_distance threshold (essentially static)."""
    h1 = compute_dhash(frame1)
    h2 = compute_dhash(frame2)
    dist = calc_hamming_distance(h1, h2)
    return dist <= max_distance


class FrameDiffDetector:
    """Tracks frame changes across consecutive pipeline ticks to prevent idle CPU spinning."""

    def __init__(self, max_distance: int = 3):
        self.max_distance = max_distance
        self.last_hash: Optional[str] = None
        self.static_count: int = 0

    def update(self, frame: Union[np.ndarray, bytes]) -> bool:
        """Update tracker with new frame. Returns True if frame has changed, False if static."""
        current_hash = compute_dhash(frame)
        if self.last_hash is None:
            self.last_hash = current_hash
            self.static_count = 0
            return True

        dist = calc_hamming_distance(self.last_hash, current_hash)
        if dist <= self.max_distance:
            self.static_count += 1
            return False

        self.last_hash = current_hash
        self.static_count = 0
        return True
