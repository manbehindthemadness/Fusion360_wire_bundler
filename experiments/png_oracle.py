"""
Decode deterministic MCP viewport PNGs and measure rendered differences.

This intentionally uses only the Python standard library so development QA adds no
runtime or installation dependency to the Fusion add-in.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

PNG_SIGNATURE: bytes = b"\x89PNG\r\n\x1a\n"


@dataclass(frozen=True)
class DecodedPng:
    """
    Store one decoded 8-bit PNG as normalized RGBA bytes.

    Args:
        width: Image width in pixels.
        height: Image height in pixels.
        rgba: Row-major red, green, blue, and alpha bytes.
    """

    width: int
    height: int
    rgba: bytes


@dataclass(frozen=True)
class ImageDifference:
    """
    Summarize a pixel comparison between equal-size screenshots.

    Args:
        changed_pixel_fraction: Fraction of pixels with any channel change above the
            supplied per-channel tolerance.
        mean_channel_delta: Mean absolute RGBA channel difference in the 0–255 range.
        maximum_channel_delta: Largest absolute channel difference.
    """

    changed_pixel_fraction: float
    mean_channel_delta: float
    maximum_channel_delta: int


def decode_png(payload: bytes) -> DecodedPng:
    """
    Decode an ordinary non-interlaced 8-bit PNG into RGBA bytes.

    Args:
        payload: Complete PNG file bytes.

    Returns:
        Decoded dimensions and normalized pixels.

    Raises:
        ValueError: If the image is malformed or uses an unsupported PNG mode.
    """
    if not payload.startswith(PNG_SIGNATURE):
        raise ValueError("Screenshot is not a PNG file.")
    offset = len(PNG_SIGNATURE)
    width: int | None = None
    height: int | None = None
    color_type: int | None = None
    bit_depth: int | None = None
    interlace: int | None = None
    compressed = bytearray()
    while offset < len(payload):
        if offset + 12 > len(payload):
            raise ValueError("PNG ended inside a chunk header.")
        chunk_length = struct.unpack(">I", payload[offset : offset + 4])[0]
        chunk_type = payload[offset + 4 : offset + 8]
        data_start = offset + 8
        data_end = data_start + chunk_length
        crc_end = data_end + 4
        if crc_end > len(payload):
            raise ValueError("PNG ended inside a chunk payload.")
        chunk_data = payload[data_start:data_end]
        expected_crc = struct.unpack(">I", payload[data_end:crc_end])[0]
        actual_crc = zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise ValueError(f"PNG {chunk_type!r} chunk failed its CRC check.")
        if chunk_type == b"IHDR":
            if chunk_length != 13:
                raise ValueError("PNG IHDR has an invalid length.")
            width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", chunk_data
            )
            if width <= 0 or height <= 0:
                raise ValueError("PNG dimensions must be positive.")
            if compression != 0 or filtering != 0:
                raise ValueError("PNG uses an unsupported compression or filter method.")
        elif chunk_type == b"IDAT":
            compressed.extend(chunk_data)
        elif chunk_type == b"IEND":
            break
        offset = crc_end

    if (
        width is None
        or height is None
        or color_type is None
        or bit_depth is None
        or interlace is None
    ):
        raise ValueError("PNG omitted its IHDR chunk.")
    if bit_depth != 8 or interlace != 0:
        raise ValueError("Screenshot PNG must be non-interlaced with 8-bit channels.")
    channel_counts = {0: 1, 2: 3, 4: 2, 6: 4}
    channels = channel_counts.get(color_type)
    if channels is None:
        raise ValueError(f"Screenshot PNG color type {color_type} is unsupported.")
    try:
        filtered_rows = zlib.decompress(bytes(compressed))
    except zlib.error as error:
        raise ValueError("Screenshot PNG has invalid compressed pixels.") from error
    row_size = width * channels
    expected_size = height * (row_size + 1)
    if len(filtered_rows) != expected_size:
        raise ValueError(
            f"Screenshot PNG decoded to {len(filtered_rows)} bytes; expected {expected_size}."
        )

    previous = bytearray(row_size)
    raw_pixels = bytearray()
    source_offset = 0
    for _row_index in range(height):
        filter_type = filtered_rows[source_offset]
        source_offset += 1
        filtered = filtered_rows[source_offset : source_offset + row_size]
        source_offset += row_size
        row = _unfilter_row(filtered, previous, channels, filter_type)
        raw_pixels.extend(row)
        previous = row
    rgba = _to_rgba(bytes(raw_pixels), color_type)
    return DecodedPng(width, height, rgba)


def compare_pngs(
    first_payload: bytes,
    second_payload: bytes,
    channel_tolerance: int = 3,
) -> ImageDifference:
    """
    Compare two same-size screenshots with a small channel-level tolerance.

    Args:
        first_payload: First complete PNG.
        second_payload: Second complete PNG.
        channel_tolerance: A pixel counts as changed when any RGBA channel differs by
            more than this value.

    Returns:
        Aggregate rendered-image difference.

    Raises:
        ValueError: If tolerance is invalid or image dimensions differ.
    """
    if channel_tolerance < 0 or channel_tolerance > 255:
        raise ValueError("PNG channel tolerance must be between 0 and 255.")
    first = decode_png(first_payload)
    second = decode_png(second_payload)
    if (first.width, first.height) != (second.width, second.height):
        raise ValueError(
            "Screenshot dimensions differ: "
            f"{first.width}x{first.height} versus {second.width}x{second.height}."
        )
    changed_pixels = 0
    total_delta = 0
    maximum_delta = 0
    for pixel_offset in range(0, len(first.rgba), 4):
        pixel_changed = False
        for channel_offset in range(4):
            delta = abs(
                first.rgba[pixel_offset + channel_offset]
                - second.rgba[pixel_offset + channel_offset]
            )
            total_delta += delta
            maximum_delta = max(maximum_delta, delta)
            if delta > channel_tolerance:
                pixel_changed = True
        if pixel_changed:
            changed_pixels += 1
    pixel_count = first.width * first.height
    return ImageDifference(
        changed_pixel_fraction=changed_pixels / pixel_count,
        mean_channel_delta=total_delta / (pixel_count * 4),
        maximum_channel_delta=maximum_delta,
    )


def _unfilter_row(
    filtered: bytes,
    previous: bytearray,
    bytes_per_pixel: int,
    filter_type: int,
) -> bytearray:
    """
    Reverse one PNG scanline filter.
    """
    row = bytearray(len(filtered))
    for index, value in enumerate(filtered):
        left = row[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
        up = previous[index]
        upper_left = previous[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
        if filter_type == 0:
            predictor = 0
        elif filter_type == 1:
            predictor = left
        elif filter_type == 2:
            predictor = up
        elif filter_type == 3:
            predictor = (left + up) // 2
        elif filter_type == 4:
            predictor = _paeth(left, up, upper_left)
        else:
            raise ValueError(f"PNG uses unknown scanline filter {filter_type}.")
        row[index] = (value + predictor) & 0xFF
    return row


def _paeth(left: int, up: int, upper_left: int) -> int:
    """
    Return the PNG Paeth predictor for one channel.
    """
    estimate = left + up - upper_left
    left_distance = abs(estimate - left)
    up_distance = abs(estimate - up)
    upper_left_distance = abs(estimate - upper_left)
    if left_distance <= up_distance and left_distance <= upper_left_distance:
        return left
    if up_distance <= upper_left_distance:
        return up
    return upper_left


def _to_rgba(raw_pixels: bytes, color_type: int) -> bytes:
    """
    Expand supported PNG color modes to RGBA.
    """
    rgba = bytearray()
    if color_type == 6:
        return raw_pixels
    channels = {0: 1, 2: 3, 4: 2}[color_type]
    for offset in range(0, len(raw_pixels), channels):
        if color_type == 0:
            gray = raw_pixels[offset]
            rgba.extend((gray, gray, gray, 255))
        elif color_type == 2:
            rgba.extend((*raw_pixels[offset : offset + 3], 255))
        else:
            gray, alpha = raw_pixels[offset : offset + 2]
            rgba.extend((gray, gray, gray, alpha))
    return bytes(rgba)
