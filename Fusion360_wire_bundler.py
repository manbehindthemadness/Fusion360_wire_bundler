"""
Expose the Wire Bundler lifecycle entry points to Fusion 360.
"""

from __future__ import annotations

import sys
import traceback
from importlib import import_module
from pathlib import Path
from typing import Literal, Protocol, cast

# noinspection PyUnresolvedReferences
import adsk.core


class _AddinLifecycle(Protocol):
    """
    Define the lifecycle surface required from the bundled add-in module.
    """

    __name__: str

    def start(self, context: object) -> None:
        """
        Start the add-in.
        """

    def stop(self, context: object) -> None:
        """
        Stop the add-in.
        """


def run(context: object) -> None:
    """
    Start the add-in when Fusion loads it.
    """
    addin = _load_addin_for("start")
    addin.start(context)


def stop(context: object) -> None:
    """
    Stop the add-in when Fusion unloads it.
    """
    addin = _load_addin_for("stop")
    addin.stop(context)
    _unload_addin_package(addin)


def _load_addin_for(operation: Literal["start", "stop"]) -> _AddinLifecycle:
    """
    Load lifecycle code, reporting import failures through Fusion when possible.

    Imports can raise arbitrary exceptions; report them and re-raise unchanged.
    """
    try:
        addin = _load_addin()
    except Exception:
        _report_import_failure(operation)
        raise
    return addin


def _load_addin() -> _AddinLifecycle:
    """
    Load lifecycle code in either supported Fusion loader context.

    Standalone execution lacks ``__package__``, so make only the add-in directory
    importable explicitly.
    """
    if __package__:
        module = import_module(".wire_bundler.addin", package=__package__)
    else:
        addin_directory = str(Path(__file__).resolve().parent)
        if addin_directory not in sys.path:
            sys.path.insert(0, addin_directory)
        module = import_module("wire_bundler.addin")
    lifecycle = cast(_AddinLifecycle, cast(object, module))
    return lifecycle


def _unload_addin_package(addin: _AddinLifecycle) -> None:
    """
    Evict the stopped add-in package so the next run imports current source.
    """
    package_name = addin.__name__.rpartition(".")[0]
    if not package_name:
        raise RuntimeError("Wire Bundler lifecycle module has no package name.")

    package_prefix = f"{package_name}."
    loaded_names = tuple(sys.modules)
    for module_name in loaded_names:
        if module_name == package_name or module_name.startswith(package_prefix):
            sys.modules.pop(module_name, None)


def _report_import_failure(operation: str) -> None:
    """
    Display an import-time failure that occurs before lifecycle code loads.
    """
    application = adsk.core.Application.get()
    if application and application.userInterface:
        application.userInterface.messageBox(
            f"Wire Bundler failed to {operation}:\n{traceback.format_exc()}",
            "Harness Builder",
        )
