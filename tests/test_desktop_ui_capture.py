"""
Tests for Fusion-only desktop UI capture safety clamps.
"""

from __future__ import annotations

import plistlib
import struct
import zlib
from pathlib import Path

import pytest

# noinspection PyProtectedMember
from experiments.desktop_ui_capture import (
    DesktopCaptureSafetyError,
    DesktopCaptureUnavailable,
    FusionProcess,
    FusionWindow,
    PaletteBounds,
    _select_verified_main_window,
    _select_verified_window,
    _verified_fusion_processes,
    capture_harness_builder_window,
    desktop_capture_observation,
)
from experiments.png_oracle import PNG_SIGNATURE


def test_selects_only_harness_window_owned_by_verified_fusion_process() -> None:
    """
    Reject matching titles from any process outside the Fusion whitelist.
    """
    trusted = {42: FusionProcess(42, Path("/trusted/Fusion"), Path("/trusted/Fusion.app"))}
    windows = (
        FusionWindow(5, 99, "Other App", "Harness Builder", 10, 30, 840, 760),
        FusionWindow(6, 42, "Fusion", "", 10, 50, 840, 760),
    )

    selected = _select_verified_window(trusted, windows, PaletteBounds(10, 20, 840, 760))

    assert selected.window_id == 6


def test_rejects_spoofed_harness_window() -> None:
    """
    Treat a matching title with unverified ownership as a safety failure.
    """
    window = FusionWindow(5, 99, "Other App", "Harness Builder", 10, 20, 840, 760)

    with pytest.raises(DesktopCaptureSafetyError, match="ownership"):
        _select_verified_window({}, (window,), PaletteBounds(10, 20, 840, 760))


def test_reports_absent_harness_window_as_unavailable() -> None:
    """
    Defer cleanly when Fusion has no visible Harness Builder window.
    """
    trusted = {42: FusionProcess(42, Path("/trusted/Fusion"), Path("/trusted/Fusion.app"))}

    with pytest.raises(DesktopCaptureUnavailable, match="No Fusion window"):
        _select_verified_window(trusted, (), PaletteBounds(10, 20, 840, 760))


def test_selects_unique_largest_verified_fusion_main_window() -> None:
    """
    Select the large Fusion frame while excluding its narrower palette window.
    """
    trusted = {42: FusionProcess(42, Path("/trusted/Fusion"), Path("/trusted/Fusion.app"))}
    windows = (
        FusionWindow(5, 42, "Fusion", "Harness Builder", 0, 0, 840, 1200),
        FusionWindow(6, 42, "Fusion", "Design", 100, 20, 2560, 1400),
        FusionWindow(7, 99, "Fusion", "Spoof", 0, 0, 3000, 1600),
    )

    selected = _select_verified_main_window(trusted, windows)

    assert selected.window_id == 6


def test_rejects_ambiguous_largest_fusion_main_windows() -> None:
    """
    Refuse capture when two verified Fusion frames have indistinguishable area.
    """
    trusted = {42: FusionProcess(42, Path("/trusted/Fusion"), Path("/trusted/Fusion.app"))}
    windows = (
        FusionWindow(5, 42, "Fusion", "One", 0, 0, 1600, 900),
        FusionWindow(6, 42, "Fusion", "Two", 100, 20, 1600, 900),
    )

    with pytest.raises(DesktopCaptureSafetyError, match="ambiguous"):
        _select_verified_main_window(trusted, windows)


def test_process_verification_requires_exact_bundle_metadata(
    tmp_path: Path,
) -> None:
    """
    Accept only the main executable inside an exact Autodesk Fusion bundle.
    """
    executable = _fusion_executable(tmp_path)
    bundle = executable.parents[2]
    output = f"123 {executable}\n124 {bundle}/Contents/Helpers/Autodesk Fusion\n"

    processes = _verified_fusion_processes(output)

    assert tuple(processes) == (123,)


def test_process_verification_rejects_wrong_bundle_identifier(
    tmp_path: Path,
) -> None:
    """
    Reject an identically named application with different bundle metadata.
    """
    executable = _fusion_executable(tmp_path, bundle_id="example.spoof")

    with pytest.raises(DesktopCaptureUnavailable, match="No verified"):
        _verified_fusion_processes(f"123 {executable}\n")


def test_capture_uses_exact_window_id_and_purges_temporary_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Capture no arbitrary rectangle and delete the private file before returning.
    """
    executable = _fusion_executable(tmp_path)
    process_output = f"123 {executable}\n"
    window_output = (
        '[{"ownerName":"Fusion","ownerPid":123,'
        '"title":"","windowId":456,'
        '"x":10,"y":50,"width":840,"height":760}]'
    )
    captured_path: Path | None = None
    captured_command: tuple[str, ...] | None = None

    def run(command: tuple[str, ...], capture_operation: bool = False) -> str:
        """
        Return fixed process/window data and emulate an exact-window screenshot.
        """
        nonlocal captured_command, captured_path
        if command[:2] == ("/bin/ps", "-axo"):
            return process_output
        if (
            command[:2] == ("/usr/bin/xcrun", "swift")
            and Path(command[2]).name == "macos_fusion_windows.swift"
        ):
            return window_output
        assert capture_operation
        captured_command = command
        output_path = Path(command[-1])
        captured_path = output_path
        output_path.write_bytes(_rgba_png())
        return ""

    monkeypatch.setattr("experiments.desktop_ui_capture.platform.system", lambda: "Darwin")
    monkeypatch.setattr("experiments.desktop_ui_capture._run", run)

    capture = capture_harness_builder_window(PaletteBounds(10, 20, 840, 760))
    observation = desktop_capture_observation(capture)

    assert captured_command is not None
    assert captured_command[:2] == ("/usr/bin/xcrun", "swift")
    assert Path(captured_command[2]).name == "macos_fusion_window_capture.swift"
    assert captured_command[3:5] == ("456", "123")
    assert "-R" not in captured_command
    assert captured_path is not None and not captured_path.exists()
    assert observation["ownerVerified"] is True
    assert observation["purged"] is True
    assert "png" not in observation


def _fusion_executable(
    tmp_path: Path,
    bundle_id: str = "com.autodesk.fusion360",
) -> Path:
    """
    Create the minimal trusted-bundle metadata used by process-verification tests.
    """
    bundle = tmp_path / "Autodesk Fusion.app"
    info_path = bundle / "Contents" / "Info.plist"
    info_path.parent.mkdir(parents=True)
    info_path.write_bytes(
        plistlib.dumps(
            {
                "CFBundleIdentifier": bundle_id,
                "CFBundleExecutable": "Autodesk Fusion",
            }
        )
    )
    return bundle / "Contents" / "MacOS" / "Autodesk Fusion"


def _rgba_png() -> bytes:
    """
    Encode one valid 1×1 RGBA PNG for capture-retention tests.
    """
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    pixels = zlib.compress(bytes((0, 10, 20, 30, 255)))
    return b"".join(
        (
            PNG_SIGNATURE,
            _chunk(b"IHDR", ihdr),
            _chunk(b"IDAT", pixels),
            _chunk(b"IEND", b""),
        )
    )


def _chunk(chunk_type: bytes, data: bytes) -> bytes:
    """
    Encode one PNG chunk for the desktop capture fixture.
    """
    checksum = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", checksum)
