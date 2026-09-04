"""
Regression tests for the Fusion entry-point reload lifecycle.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Iterator
from types import ModuleType
from typing import Protocol, cast

import pytest


class _BootstrapModule(Protocol):
    """
    Describe the entry-point operations exercised by these tests.
    """

    def stop(self, context: object) -> None:
        """
        Stop the loaded add-in package.
        """

    def _load_addin(self) -> object:
        """
        Load the add-in lifecycle module.
        """


@pytest.fixture
def bootstrap_module(monkeypatch: pytest.MonkeyPatch) -> Iterator[_BootstrapModule]:
    """
    Import the Fusion entry point against a minimal ``adsk`` stub.
    """
    adsk_module = ModuleType("adsk")
    core_module = ModuleType("adsk.core")
    adsk_module.core = core_module  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "adsk", adsk_module)
    monkeypatch.setitem(sys.modules, "adsk.core", core_module)
    sys.modules.pop("Fusion360_wire_bundler", None)

    module = importlib.import_module("Fusion360_wire_bundler")
    yield cast(_BootstrapModule, cast(object, module))

    sys.modules.pop("Fusion360_wire_bundler", None)


def test_successful_stop_evicts_only_the_loaded_addin_package(
    bootstrap_module: _BootstrapModule,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Clean up lifecycle state before evicting package modules for the next run.
    """
    package_name = "wire_bundler_reload_test"
    lifecycle_name = f"{package_name}.addin"
    package = ModuleType(package_name)
    lifecycle = ModuleType(lifecycle_name)
    child = ModuleType(f"{package_name}.domain")
    unrelated = ModuleType("unrelated_reload_test")
    stop_observations: list[bool] = []

    def stop(_context: object) -> None:
        """
        Record that the lifecycle module remains loaded during cleanup.
        """
        stop_observations.append(lifecycle_name in sys.modules)

    lifecycle.stop = stop  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, package_name, package)
    monkeypatch.setitem(sys.modules, lifecycle_name, lifecycle)
    monkeypatch.setitem(sys.modules, child.__name__, child)
    monkeypatch.setitem(sys.modules, unrelated.__name__, unrelated)
    monkeypatch.setattr(bootstrap_module, "_load_addin", lambda: lifecycle)

    bootstrap_module.stop({})

    assert stop_observations == [True]
    assert package_name not in sys.modules
    assert lifecycle_name not in sys.modules
    assert child.__name__ not in sys.modules
    assert unrelated.__name__ in sys.modules


def test_failed_stop_keeps_package_loaded_for_diagnosis(
    bootstrap_module: _BootstrapModule,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Preserve loaded modules when lifecycle cleanup does not complete.
    """
    package_name = "wire_bundler_failed_stop_test"
    lifecycle_name = f"{package_name}.addin"
    lifecycle = ModuleType(lifecycle_name)

    def stop(_context: object) -> None:
        """
        Reproduce a lifecycle cleanup failure.
        """
        raise RuntimeError("cleanup failed")

    lifecycle.stop = stop  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, package_name, ModuleType(package_name))
    monkeypatch.setitem(sys.modules, lifecycle_name, lifecycle)
    monkeypatch.setattr(bootstrap_module, "_load_addin", lambda: lifecycle)

    with pytest.raises(RuntimeError, match="cleanup failed"):
        bootstrap_module.stop({})

    assert package_name in sys.modules
    assert lifecycle_name in sys.modules
