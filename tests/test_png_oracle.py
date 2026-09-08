"""
Tests for dependency-free MCP screenshot decoding and comparison.
"""

from __future__ import annotations

import struct
import zlib

import pytest

from experiments.png_oracle import PNG_SIGNATURE, compare_pngs, decode_png


def test_decodes_rgba_png_across_every_scanline_filter() -> None:
    """
    Reverse all five PNG filters into stable RGBA pixels.
    """
    rows = (
        bytes((10, 20, 30, 255, 40, 50, 60, 255)),
        bytes((11, 22, 33, 255, 44, 55, 66, 255)),
        bytes((12, 24, 36, 255, 48, 60, 72, 255)),
        bytes((13, 26, 39, 255, 52, 65, 78, 255)),
        bytes((14, 28, 42, 255, 56, 70, 84, 255)),
    )
    payload = _png(2, rows, (0, 1, 2, 3, 4))

    decoded = decode_png(payload)

    assert (decoded.width, decoded.height) == (2, 5)
    assert decoded.rgba == b"".join(rows)


def test_compares_pixels_with_channel_tolerance() -> None:
    """
    Ignore tiny render noise while reporting materially changed pixels.
    """
    first = _png(2, (bytes((10, 20, 30, 255, 40, 50, 60, 255)),))
    second = _png(2, (bytes((12, 20, 30, 255, 40, 70, 60, 255)),))

    difference = compare_pngs(first, second, channel_tolerance=3)

    assert difference.changed_pixel_fraction == 0.5
    assert difference.mean_channel_delta == pytest.approx(22 / 8)
    assert difference.maximum_channel_delta == 20


def test_rejects_corrupt_png_crc() -> None:
    """
    Reject damaged screenshot evidence before comparing it.
    """
    payload = bytearray(_png(1, (bytes((10, 20, 30, 255)),)))
    payload[-1] ^= 0xFF

    with pytest.raises(ValueError, match="CRC"):
        decode_png(bytes(payload))


def _png(
    width: int,
    rows: tuple[bytes, ...],
    filters: tuple[int, ...] | None = None,
) -> bytes:
    """
    Encode a minimal 8-bit RGBA PNG fixture.
    """
    filter_types = filters or tuple(0 for _row in rows)
    previous = bytes(width * 4)
    filtered_rows = bytearray()
    for row, filter_type in zip(rows, filter_types):
        filtered_rows.append(filter_type)
        filtered_rows.extend(_filter(row, previous, 4, filter_type))
        previous = row
    ihdr = struct.pack(">IIBBBBB", width, len(rows), 8, 6, 0, 0, 0)
    return b"".join(
        (
            PNG_SIGNATURE,
            _chunk(b"IHDR", ihdr),
            _chunk(b"IDAT", zlib.compress(bytes(filtered_rows))),
            _chunk(b"IEND", b""),
        )
    )


def _filter(row: bytes, previous: bytes, bytes_per_pixel: int, filter_type: int) -> bytes:
    """
    Apply one PNG filter for a test fixture row.
    """
    filtered = bytearray()
    for index, value in enumerate(row):
        left = row[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
        up = previous[index]
        upper_left = previous[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
        predictors = (
            0,
            left,
            up,
            (left + up) // 2,
            _paeth(left, up, upper_left),
        )
        filtered.append((value - predictors[filter_type]) & 0xFF)
    return bytes(filtered)


def _paeth(left: int, up: int, upper_left: int) -> int:
    """
    Return the PNG Paeth predictor used by the fixture encoder.
    """
    estimate = left + up - upper_left
    distances = (abs(estimate - left), abs(estimate - up), abs(estimate - upper_left))
    return (left, up, upper_left)[distances.index(min(distances))]


def _chunk(chunk_type: bytes, data: bytes) -> bytes:
    """
    Encode one PNG chunk with its CRC.
    """
    checksum = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", checksum)
