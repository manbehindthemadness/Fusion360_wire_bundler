"""
Fusion 360 entry point for the Wire Bundler add-in.
"""

import sys
import traceback
from importlib import import_module
from pathlib import Path
from typing import Protocol, cast

# noinspection PyUnresolvedReferences
import adsk.core


class _AddinLifecycle(Protocol):
    """
    Describe the lifecycle functions exposed by the bundled add-in module.
    """

    __name__: str

    def start(self, context: object) -> None:
        """
        Start the bundled add-in.
        """

    def stop(self, context: object) -> None:
        """
        Stop the bundled add-in.
        """


def run(context: object) -> None:
    """
    Start the add-in when Fusion loads it.

    Args:
        context: Context object supplied by Fusion.
    """
    try:
        addin = _load_addin()
    except Exception:
        _report_import_failure("start")
        raise
    addin.start(context)


def stop(context: object) -> None:
    """
    Stop the add-in when Fusion unloads it.

    Args:
        context: Context object supplied by Fusion.
    """
    try:
        addin = _load_addin()
    except Exception:
        _report_import_failure("stop")
        raise
    addin.stop(context)
    _unload_addin_package(addin)


def _load_addin() -> _AddinLifecycle:
    """
    Load the bundled module in either Fusion loader context.

    Fusion can load an add-in as a package or execute its entry file as a
    standalone module. The standalone mode does not supply ``__package__``, so
    its exact add-in directory must be made importable explicitly.

    Returns:
        Module implementing the add-in lifecycle.
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

    Args:
        addin: Loaded lifecycle module whose package should be evicted.
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

    Args:
        operation: Lifecycle operation Fusion attempted.
    """
    application = adsk.core.Application.get()
    if application and application.userInterface:
        application.userInterface.messageBox(
            f"Wire Bundler failed to {operation}:\n{traceback.format_exc()}",
            "Harness Builder",
        )
