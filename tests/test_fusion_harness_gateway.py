"""
Regression tests for Fusion design-intent handling at the host boundary.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Iterator
from types import ModuleType
from typing import Optional

import pytest

from wire_bundler.application import create_empty_harness
from wire_bundler.domain import RoutingMode


class _IntentTypes:
    """
    Provide stable stand-ins for Fusion's design-intent enum values.
    """

    PartDesignIntentType = object()
    HybridDesignIntentType = object()
    AssemblyDesignIntentType = object()


class _Attributes:
    """
    Record component attribute writes and optionally reject them.
    """

    def __init__(self, reject_write: bool = False) -> None:
        """
        Configure whether Fusion should appear to reject an attribute write.
        """
        self.reject_write = reject_write
        self.values: list[tuple[str, str, str]] = []

    def add(self, group: str, name: str, value: str) -> Optional[object]:
        """
        Record an attribute write or return null to simulate Fusion failure.
        """
        if self.reject_write:
            return None
        self.values.append((group, name, value))
        return object()

    # noinspection PyPep8Naming
    def itemByName(self, group: str, name: str) -> Optional[object]:
        """
        Return the most recently written matching fake attribute.
        """
        for stored_group, stored_name, stored_value in reversed(self.values):
            if stored_group == group and stored_name == name:
                return _Attribute(stored_value)
        return None


class _Attribute:
    """
    Provide a persisted string value for discovery tests.
    """

    def __init__(self, value: str) -> None:
        """
        Store a fake Fusion attribute value.
        """
        self.value = value


class _Occurrence:
    """
    Stand in for a newly created Fusion occurrence.
    """

    def __init__(
        self,
        reject_attribute_write: bool = False,
        component_name: str = "",
    ) -> None:
        """
        Create an occurrence with a component and controllable attributes.
        """
        self.component = _Component(reject_attribute_write)
        self.component.name = component_name
        self.was_deleted = False

    # noinspection PyPep8Naming
    def deleteMe(self) -> bool:
        """
        Record successful deletion.
        """
        self.was_deleted = True
        return True


class _Occurrences:
    """
    Stand in for Fusion's child-occurrence collection.
    """

    def __init__(
        self,
        reject_creation: bool = False,
        reject_attribute_write: bool = False,
        existing_names: tuple[str, ...] = (),
    ) -> None:
        """
        Configure component-creation and attribute-write outcomes.
        """
        self.reject_creation = reject_creation
        self.reject_attribute_write = reject_attribute_write
        self.created = [_Occurrence(component_name=name) for name in existing_names]
        self.external_creation_folders: list[_DataFolder] = []

    @property
    def count(self) -> int:
        """
        Return the current number of occurrences.
        """
        return len(self.created)

    def item(self, index: int) -> Optional[_Occurrence]:
        """
        Return an occurrence by index.
        """
        if 0 <= index < len(self.created):
            return self.created[index]
        return None

    # noinspection PyPep8Naming
    def addNewComponent(self, _transform: object) -> _Occurrence:
        """
        Create a fake occurrence or reproduce Fusion's creation failure.
        """
        if self.reject_creation:
            raise RuntimeError("Failed to create component")
        occurrence = _Occurrence(self.reject_attribute_write)
        self.created.append(occurrence)
        return occurrence

    # noinspection PyPep8Naming
    def addNewExternalComponent(
        self,
        component_name: str,
        target_folder: _DataFolder,
        _transform: object,
    ) -> _Occurrence:
        """
        Create and record a fake external component occurrence.
        """
        if self.reject_creation:
            raise RuntimeError("Failed to create external component")
        occurrence = _Occurrence(self.reject_attribute_write, component_name)
        self.created.append(occurrence)
        self.external_creation_folders.append(target_folder)
        return occurrence


class _Component:
    """
    Provide the component fields used by the gateway.
    """

    def __init__(self, reject_attribute_write: bool = False) -> None:
        """
        Create an unnamed component with child and attribute collections.
        """
        self.name = ""
        self.attributes = _Attributes(reject_attribute_write)
        self.occurrences = _Occurrences()


class _Components:
    """
    Stand in for Fusion's design-wide component collection.
    """

    def __init__(self, components: tuple[_Component, ...]) -> None:
        """
        Store the supplied components in Fusion collection order.
        """
        self._components = components

    @property
    def count(self) -> int:
        """
        Return the current number of components.
        """
        return len(self._components)

    def item(self, index: int) -> Optional[_Component]:
        """
        Return a component by index.
        """
        if 0 <= index < len(self._components):
            return self._components[index]
        return None


class _DataFile:
    """
    Stand in for a named Fusion cloud data file.
    """

    def __init__(self, name: str) -> None:
        """
        Store the displayed cloud file name.
        """
        self.name = name


class _DataFiles:
    """
    Stand in for Fusion's cloud data-file collection.
    """

    def __init__(self, names: tuple[str, ...] = ()) -> None:
        """
        Create cloud data files with the supplied names.
        """
        self._files = [_DataFile(name) for name in names]

    @property
    def count(self) -> int:
        """
        Return the current number of data files.
        """
        return len(self._files)

    def item(self, index: int) -> Optional[_DataFile]:
        """
        Return a data file by index.
        """
        if 0 <= index < len(self._files):
            return self._files[index]
        return None


class _DataFolder:
    """
    Stand in for the active Fusion cloud folder.
    """

    def __init__(self, file_names: tuple[str, ...] = ()) -> None:
        """
        Create a folder containing the supplied data-file names.
        """
        self.dataFiles = _DataFiles(file_names)


class _Design:
    """
    Provide mutable design intent and an active component.
    """

    def __init__(
        self,
        design_intent: object,
        reject_creation: bool = False,
        reject_attribute_write: bool = False,
        existing_names: tuple[str, ...] = (),
    ) -> None:
        """
        Configure the fake design and its active component.
        """
        self.designIntent = design_intent
        self.activeComponent = _Component()
        self.activeComponent.occurrences = _Occurrences(
            reject_creation,
            reject_attribute_write,
        )
        self.rootComponent = self.activeComponent
        existing_components: list[_Component] = [self.rootComponent]
        for name in existing_names:
            component = _Component()
            component.name = name
            existing_components.append(component)
        self.allComponents = _Components(tuple(existing_components))


@pytest.fixture
def fusion_gateway_type(monkeypatch: pytest.MonkeyPatch) -> Iterator[type]:
    """
    Import the Fusion gateway against a minimal deterministic ``adsk`` stub.
    """
    adsk_module = ModuleType("adsk")
    core_module = ModuleType("adsk.core")
    fusion_module = ModuleType("adsk.fusion")

    class _Matrix3D:
        """
        Provide the transform factory used during component creation.
        """

        @staticmethod
        def create() -> object:
            """
            Return an opaque transform.
            """
            return object()

    class _FusionOccurrence:
        """
        Provide Fusion's occurrence cast operation.
        """

        @staticmethod
        def cast(value: object) -> Optional[_Occurrence]:
            """
            Return fake occurrences and reject unrelated values.
            """
            if isinstance(value, _Occurrence):
                return value
            return None

    core_module.Matrix3D = _Matrix3D  # type: ignore[attr-defined]
    fusion_module.DesignIntentTypes = _IntentTypes  # type: ignore[attr-defined]
    fusion_module.Occurrence = _FusionOccurrence  # type: ignore[attr-defined]
    adsk_module.core = core_module  # type: ignore[attr-defined]
    adsk_module.fusion = fusion_module  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "adsk", adsk_module)
    monkeypatch.setitem(sys.modules, "adsk.core", core_module)
    monkeypatch.setitem(sys.modules, "adsk.fusion", fusion_module)
    sys.modules.pop("wire_bundler.fusion.harness_gateway", None)
    sys.modules.pop("wire_bundler.fusion", None)

    gateway_module = importlib.import_module("wire_bundler.fusion.harness_gateway")
    yield gateway_module.FusionHarnessGateway

    sys.modules.pop("wire_bundler.fusion.harness_gateway", None)
    sys.modules.pop("wire_bundler.fusion", None)


def test_converts_part_design_before_creating_internal_component(
    fusion_gateway_type: type,
) -> None:
    """
    Convert a Part design to Hybrid before adding a harness child.
    """
    design = _Design(_IntentTypes.PartDesignIntentType)
    gateway = fusion_gateway_type(design)

    resolved_name = gateway.resolve_harness_name("Harness_001")
    handle = gateway.create_harness_component(resolved_name)
    gateway.write_definition(handle, "definition-json")

    occurrence = design.activeComponent.occurrences.created[0]
    assert design.designIntent is _IntentTypes.HybridDesignIntentType
    assert occurrence.component.name == "Harness_001"
    assert occurrence.component.attributes.values == [
        ("kev0.wire_bundler", "harness_definition", "definition-json")
    ]


def test_restores_part_intent_when_component_creation_fails(
    fusion_gateway_type: type,
) -> None:
    """
    Undo automatic conversion if Fusion rejects the new component.
    """
    design = _Design(_IntentTypes.PartDesignIntentType, reject_creation=True)
    gateway = fusion_gateway_type(design)

    with pytest.raises(RuntimeError, match="Failed to create component"):
        gateway.create_harness_component("Harness_001")

    assert design.designIntent is _IntentTypes.PartDesignIntentType


def test_restores_part_intent_when_definition_persistence_fails(
    fusion_gateway_type: type,
) -> None:
    """
    Delete the incomplete child and restore Part intent on transaction rollback.
    """
    design = _Design(_IntentTypes.PartDesignIntentType, reject_attribute_write=True)
    gateway = fusion_gateway_type(design)

    with pytest.raises(RuntimeError, match="did not persist"):
        create_empty_harness("Harness_001", RoutingMode.ROUTING_GATES, gateway)

    occurrence = design.activeComponent.occurrences.created[0]
    assert occurrence.was_deleted
    assert design.designIntent is _IntentTypes.PartDesignIntentType


def test_creates_external_component_in_assembly_design(
    fusion_gateway_type: type,
) -> None:
    """
    Create Assembly-design harnesses as external components in the active folder.
    """
    design = _Design(_IntentTypes.AssemblyDesignIntentType)
    target_folder = _DataFolder()
    gateway = fusion_gateway_type(design, target_folder)

    handle = gateway.create_harness_component("Harness_001")
    gateway.write_definition(handle, "definition-json")

    occurrence = design.rootComponent.occurrences.created[0]
    assert occurrence.component.name == "Harness_001"
    assert design.rootComponent.occurrences.external_creation_folders == [target_folder]


def test_resolves_assembly_name_against_design_components_and_cloud_files(
    fusion_gateway_type: type,
) -> None:
    """
    Avoid both design-wide component names and target-folder file names.
    """
    design = _Design(
        _IntentTypes.AssemblyDesignIntentType,
        existing_names=("Harness_001",),
    )
    target_folder = _DataFolder(("Harness_002",))
    gateway = fusion_gateway_type(design, target_folder)

    assert gateway.resolve_harness_name("Harness_001") == "Harness_003"


def test_requires_cloud_folder_for_assembly_design(fusion_gateway_type: type) -> None:
    """
    Fail before creation when an external component has no target folder.
    """
    design = _Design(_IntentTypes.AssemblyDesignIntentType)
    gateway = fusion_gateway_type(design)

    with pytest.raises(RuntimeError, match="active Fusion cloud folder"):
        gateway.resolve_harness_name("Harness_001")


def test_lists_only_components_with_harness_metadata(fusion_gateway_type: type) -> None:
    """
    Discover marked definitions across the complete active design.
    """
    design = _Design(_IntentTypes.HybridDesignIntentType, existing_names=("Harness_001",))
    harness_component = design.allComponents.item(1)
    assert harness_component is not None
    harness_component.attributes.add(
        "kev0.wire_bundler",
        "harness_definition",
        "definition-json",
    )
    gateway = fusion_gateway_type(design)

    stored_harnesses = gateway.list_stored_harnesses()

    assert len(stored_harnesses) == 1
    assert stored_harnesses[0].component_name == "Harness_001"
    assert stored_harnesses[0].serialized_definition == "definition-json"
