# =============================================================================
# DEVELOPMENT-ONLY EXTERNAL UI CAPTURE — SECURITY AND PRIVACY BOUNDARY
#
# This module runs only when a developer explicitly invokes QA with --desktop-ui.
# The Fusion add-in never imports this module. Normal QA may import its inert definitions
# but does not execute the capture operation, and therefore requests no macOS permission.
#
# It may capture only the fixed Harness Builder palette or Fusion's unique largest
# visible application window after independently proving the owning process is Autodesk
# Fusion by executable path, bundle metadata, PID, and Core Graphics owner. Callers
# cannot supply an app, PID, window ID, or screen rectangle. The temporary PNG is
# private and is deleted in finally; only non-image metrics may enter a report.
# =============================================================================

"""
Capture only fixed verified Fusion windows on an opted-in development host.

This module is external test infrastructure. Fusion API bounds identify the palette,
and strict size plus uniqueness constraints identify the main application frame. The
caller cannot choose an application, PID, window ID, or screen rectangle. The adapter
retains no image after returning comparison-ready bytes to the in-memory caller.
"""

from __future__ import annotations

import json
import os
import platform
import plistlib
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from experiments.png_oracle import PNG_SIGNATURE, decode_png

FUSION_BUNDLE_ID = "com.autodesk.fusion360"
FUSION_EXECUTABLE = "Autodesk Fusion"
FUSION_OWNER_NAME = "Fusion"
MACOS_WINDOW_HELPER = Path(__file__).with_name("macos_fusion_windows.swift")
MACOS_CAPTURE_HELPER = Path(__file__).with_name("macos_fusion_window_capture.swift")


class DesktopCaptureUnavailable(RuntimeError):
    """
    Report a missing platform, permission, visible window, or capture facility.
    """


class DesktopCaptureSafetyError(RuntimeError):
    """
    Reject any window that does not prove it belongs to Autodesk Fusion.
    """


@dataclass(frozen=True)
class FusionProcess:
    """
    Store a verified Autodesk Fusion process identity.
    """

    pid: int
    executable: Path
    bundle_path: Path


@dataclass(frozen=True)
class FusionWindow:
    """
    Store a Core Graphics window identity and layout bounds.
    """

    window_id: int
    owner_pid: int
    owner_name: str
    title: str
    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class PaletteBounds:
    """
    Store trusted Harness Builder geometry read from Fusion's Palette API.
    """

    left: float
    top: float
    width: float
    height: float


@dataclass(frozen=True)
class DesktopCapture:
    """
    Return ephemeral pixels and non-sensitive window metadata to the caller.
    """

    png: bytes
    window: FusionWindow


def capture_harness_builder_window(palette_bounds: PaletteBounds) -> DesktopCapture:
    """
    Capture the exact visible Harness Builder window on a macOS development host.

    Raises:
        DesktopCaptureUnavailable: If the host, permission, or window is unavailable.
        DesktopCaptureSafetyError: If ownership cannot be proven as Autodesk Fusion.
    """
    if platform.system() != "Darwin":
        raise DesktopCaptureUnavailable(
            "Desktop UI capture currently has no verified adapter for this platform."
        )
    processes = _verified_fusion_processes(_run(("/bin/ps", "-axo", "pid=,comm=")))
    windows = _parse_fusion_windows(_run(("/usr/bin/xcrun", "swift", str(MACOS_WINDOW_HELPER))))
    window = _select_verified_window(processes, windows, palette_bounds)
    return _capture_verified_window(window)


def capture_fusion_main_window() -> DesktopCapture:
    """
    Capture Fusion's unique largest visible application window on macOS.

    Raises:
        DesktopCaptureUnavailable: If the host, permission, or window is unavailable.
        DesktopCaptureSafetyError: If ownership or unique main-window identity fails.
    """
    if platform.system() != "Darwin":
        raise DesktopCaptureUnavailable(
            "Desktop UI capture currently has no verified adapter for this platform."
        )
    processes = _verified_fusion_processes(_run(("/bin/ps", "-axo", "pid=,comm=")))
    windows = _parse_fusion_windows(_run(("/usr/bin/xcrun", "swift", str(MACOS_WINDOW_HELPER))))
    window = _select_verified_main_window(processes, windows)
    return _capture_verified_window(window)


def _capture_verified_window(window: FusionWindow) -> DesktopCapture:
    """
    Capture one internally selected and verified Fusion window by exact ID.
    """
    with TemporaryDirectory(prefix="wire-bundler-ui-") as temporary_directory:
        directory = Path(temporary_directory)
        os.chmod(directory, 0o700)
        image_path = directory / "fusion-window.png"
        try:
            _run(
                (
                    "/usr/bin/xcrun",
                    "swift",
                    str(MACOS_CAPTURE_HELPER),
                    str(window.window_id),
                    str(window.owner_pid),
                    str(image_path),
                ),
                capture_operation=True,
            )
            if not image_path.is_file():
                raise DesktopCaptureUnavailable(
                    "macOS did not create the Fusion window capture; grant Screen Recording "
                    "permission to the development terminal or IDE."
                )
            payload = image_path.read_bytes()
            if not payload.startswith(PNG_SIGNATURE):
                raise DesktopCaptureUnavailable("macOS did not return a PNG window capture.")
            decoded = decode_png(payload)
            if decoded.width <= 0 or decoded.height <= 0:
                raise DesktopCaptureUnavailable("Fusion window capture has invalid dimensions.")
            return DesktopCapture(payload, window)
        finally:
            image_path.unlink(missing_ok=True)


def desktop_capture_observation(capture: DesktopCapture) -> dict[str, object]:
    """
    Return report-safe metadata without retaining or serializing image pixels.
    """
    decoded = decode_png(capture.png)
    return {
        "window": asdict(capture.window),
        "pixels": {"width": decoded.width, "height": decoded.height},
        "ownerVerified": True,
        "storage": "private-temporary-file-then-memory",
        "purged": True,
    }


def _verified_fusion_processes(output: str) -> dict[int, FusionProcess]:
    """
    Parse processes and retain only exact executable and bundle-metadata matches.
    """
    processes: dict[int, FusionProcess] = {}
    executable_suffix = f"/{FUSION_EXECUTABLE}.app/Contents/MacOS/{FUSION_EXECUTABLE}"
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        pid_text, separator, executable_text = stripped.partition(" ")
        if not separator or not pid_text.isdigit():
            continue
        executable = Path(executable_text.strip())
        executable_string = str(executable)
        if not executable_string.endswith(executable_suffix):
            continue
        bundle_path_text = executable_string.removesuffix(f"/Contents/MacOS/{FUSION_EXECUTABLE}")
        bundle_path = Path(bundle_path_text)
        info_path = bundle_path / "Contents" / "Info.plist"
        try:
            with info_path.open("rb") as info_file:
                info = plistlib.load(info_file)
        except (OSError, plistlib.InvalidFileException):
            continue
        if (
            info.get("CFBundleIdentifier") != FUSION_BUNDLE_ID
            or info.get("CFBundleExecutable") != FUSION_EXECUTABLE
        ):
            continue
        pid = int(pid_text)
        processes[pid] = FusionProcess(pid, executable, bundle_path)
    if not processes:
        raise DesktopCaptureUnavailable("No verified Autodesk Fusion process is running.")
    return processes


def _parse_fusion_windows(output: str) -> tuple[FusionWindow, ...]:
    """
    Parse the fixed Core Graphics helper output with strict field validation.
    """
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as error:
        raise DesktopCaptureUnavailable("macOS returned an invalid window inventory.") from error
    if not isinstance(payload, list):
        raise DesktopCaptureUnavailable("macOS window inventory is not a list.")
    windows: list[FusionWindow] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            raw_title = item.get("title")
            title = raw_title if isinstance(raw_title, str) else ""
            window = FusionWindow(
                window_id=_positive_int(item.get("windowId"), "window ID"),
                owner_pid=_positive_int(item.get("ownerPid"), "owner PID"),
                owner_name=_required_text(item.get("ownerName"), "owner name"),
                title=title,
                x=float(item["x"]),
                y=float(item["y"]),
                width=float(item["width"]),
                height=float(item["height"]),
            )
        except (KeyError, TypeError, ValueError):
            continue
        if window.width > 0 and window.height > 0:
            windows.append(window)
    return tuple(windows)


def _select_verified_window(
    processes: dict[int, FusionProcess],
    windows: tuple[FusionWindow, ...],
    palette_bounds: PaletteBounds,
) -> FusionWindow:
    """
    Match trusted Palette API bounds to a window owned by verified Fusion.
    """
    geometry_matches = tuple(
        window
        for window in windows
        if abs(window.x - palette_bounds.left) <= 4.0
        and abs(window.y - palette_bounds.top) <= 64.0
        and abs(window.width - palette_bounds.width) <= 2.0
        and abs(window.height - palette_bounds.height) <= 2.0
    )
    candidates = tuple(
        window
        for window in geometry_matches
        if window.owner_pid in processes and window.owner_name == FUSION_OWNER_NAME
    )
    if not candidates:
        if geometry_matches:
            raise DesktopCaptureSafetyError(
                "Palette-sized window ownership did not match the verified Fusion process."
            )
        raise DesktopCaptureUnavailable(
            "No Fusion window matches the visible Harness Builder Palette API bounds."
        )
    return min(
        candidates,
        key=lambda window: abs(window.x - palette_bounds.left) + abs(window.y - palette_bounds.top),
    )


def _select_verified_main_window(
    processes: dict[int, FusionProcess],
    windows: tuple[FusionWindow, ...],
) -> FusionWindow:
    """
    Select the unique largest usable window owned by the verified Fusion process.
    """
    candidates = tuple(
        window
        for window in windows
        if window.owner_pid in processes
        and window.owner_name == FUSION_OWNER_NAME
        and window.width >= 1200.0
        and window.height >= 700.0
    )
    if not candidates:
        raise DesktopCaptureUnavailable("No usable visible Fusion application window was found.")
    largest_area = max(window.width * window.height for window in candidates)
    largest = tuple(
        window for window in candidates if abs((window.width * window.height) - largest_area) <= 1.0
    )
    if len(largest) != 1:
        raise DesktopCaptureSafetyError(
            "Fusion main-window identity is ambiguous; expected one largest visible window."
        )
    return largest[0]


def _run(command: tuple[str, ...], capture_operation: bool = False) -> str:
    """
    Run one fixed development adapter command without shell interpretation.
    """
    completed = subprocess.run(
        command,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=30.0,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        if capture_operation:
            raise DesktopCaptureUnavailable(
                "macOS Fusion-window capture failed; verify Screen Recording permission. " + detail
            )
        raise DesktopCaptureUnavailable(
            f"Desktop capture capability command failed ({completed.returncode}): {detail}"
        )
    return completed.stdout


def _positive_int(value: object, label: str) -> int:
    """
    Parse a positive integer from external window data.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Fusion {label} is not numeric.")
    parsed = int(value)
    if parsed <= 0 or parsed != value:
        raise ValueError(f"Fusion {label} is not a positive integer.")
    return parsed


def _required_text(value: object, label: str) -> str:
    """
    Parse required text from external window data.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Fusion {label} is empty.")
    return value
