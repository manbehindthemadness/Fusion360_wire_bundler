"""
Autodesk Fusion component and attribute operations for harness creation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, cast
from uuid import UUID

# noinspection PyUnresolvedReferences
import adsk.core

# noinspection PyUnresolvedReferences
import adsk.fusion

from ..application import StoredHarness
from ..domain import DefinitionParseError, loads, next_available_name

ATTRIBUTE_GROUP = "kev0.wire_bundler"
DEFINITION_ATTRIBUTE_NAME = "harness_definition"


class _FusionAttributes(Protocol):
    """
    Describe the Fusion attribute operation used by this gateway.
    """

    def add(self, group: str, name: str, value: str) -> Optional[object]:
        """
        Add a persistent string attribute.
        """

    # noinspection PyPep8Naming
    def itemByName(self, group: str, name: str) -> Optional[_FusionAttribute]:
        """
        Return a persistent attribute by group and name.
        """


class _FusionAttribute(Protocol):
    """
    Describe the stored string exposed by a Fusion attribute.
    """

    value: str


class _FusionComponent(Protocol):
    """
    Describe the Fusion component fields used by this gateway.
    """

    name: str
    attributes: _FusionAttributes
    occurrences: _FusionOccurrences

    # noinspection PyPep8Naming
    def allOccurrencesByComponent(self, component: _FusionComponent) -> _FusionOccurrences:
        """
        Return every design occurrence referencing one component.
        """


class _FusionComponents(Protocol):
    """
    Describe the design-wide component collection used for collision checks.
    """

    count: int

    def item(self, index: int) -> Optional[_FusionComponent]:
        """
        Return a component by zero-based index.
        """


class _FusionOccurrences(Protocol):
    """
    Describe the Fusion occurrence collection operations used by this gateway.
    """

    count: int

    def item(self, index: int) -> Optional[_FusionOccurrence]:
        """
        Return an occurrence by zero-based index.
        """

    # noinspection PyPep8Naming
    def addNewComponent(self, transform: object) -> Optional[_FusionOccurrence]:
        """
        Create an internal component occurrence.
        """

    # noinspection PyPep8Naming
    def addNewExternalComponent(
        self,
        component_name: str,
        target_folder: _DataFolder,
        transform: object,
    ) -> Optional[_FusionOccurrence]:
        """
        Create an unsaved external component occurrence.
        """


class _FusionOccurrence(Protocol):
    """
    Describe the Fusion occurrence operations used by this gateway.
    """

    component: _FusionComponent

    # noinspection PyPep8Naming
    def deleteMe(self) -> bool:
        """
        Delete this occurrence from its parent component.
        """


class _NamedDataFile(Protocol):
    """
    Describe a cloud data file name used for collision checks.
    """

    name: str


class _DataFiles(Protocol):
    """
    Describe the cloud data-file collection used for collision checks.
    """

    count: int

    def item(self, index: int) -> Optional[_NamedDataFile]:
        """
        Return a data file by zero-based index.
        """


class _DataFolder(Protocol):
    """
    Describe the active cloud folder used for external harness components.
    """

    dataFiles: _DataFiles


@dataclass(frozen=True)
class _HarnessComponentHandle:
    """
    Retain the created occurrence and any design-intent change for rollback.
    """

    occurrence: _FusionOccurrence
    original_design_intent: object


class FusionHarnessGateway:
    """
    Persist harness definitions in internal or external child components.
    """

    def __init__(
        self,
        design: adsk.fusion.Design,
        external_component_folder: Optional[_DataFolder] = None,
    ) -> None:
        """
        Initialize the gateway for an active Fusion design.

        Args:
            design: Active Fusion design that will own the harness component.
            external_component_folder: Active cloud folder for assembly-external
                harness components.
        """
        self._design = design
        self._external_component_folder = external_component_folder

    def resolve_harness_name(self, requested_name: str) -> str:
        """
        Resolve a name against design components and external cloud files.

        Args:
            requested_name: Preferred harness name.

        Returns:
            First available case-insensitive name.
        """
        unavailable_names: list[str] = []
        components = cast(_FusionComponents, self._design.allComponents)
        for index in range(components.count):
            component = components.item(index)
            if component is not None:
                unavailable_names.append(component.name)

        if self._is_assembly_design():
            data_files = self._require_external_component_folder().dataFiles
            for index in range(data_files.count):
                data_file = data_files.item(index)
                if data_file is not None:
                    unavailable_names.append(data_file.name)

        return next_available_name(requested_name, unavailable_names)

    def list_stored_harnesses(self) -> tuple[StoredHarness, ...]:
        """
        Return definitions stored on every marked component in the active design.

        Returns:
            Component names and their serialized definition attributes.
        """
        stored_harnesses: list[StoredHarness] = []
        components = cast(_FusionComponents, self._design.allComponents)
        for index in range(components.count):
            component = components.item(index)
            if component is None:
                continue
            attribute = component.attributes.itemByName(
                ATTRIBUTE_GROUP,
                DEFINITION_ATTRIBUTE_NAME,
            )
            if attribute is None:
                continue
            stored_harnesses.append(
                StoredHarness(
                    component_name=component.name,
                    serialized_definition=attribute.value,
                    component_handle=component,
                )
            )
        return tuple(stored_harnesses)

    def delete_stored_harness_component(self, component_handle: object) -> None:
        """
        Delete the exact marked harness component selected during discovery.

        Args:
            component_handle: Opaque component identity returned by discovery.

        Raises:
            RuntimeError: If the component is stale, unmarked, reused, or cannot be deleted.
        """
        component = adsk.fusion.Component.cast(component_handle)
        if component is None:
            raise RuntimeError("The damaged harness component is no longer available.")
        attribute = component.attributes.itemByName(
            ATTRIBUTE_GROUP,
            DEFINITION_ATTRIBUTE_NAME,
        )
        if attribute is None:
            raise RuntimeError("The selected component is no longer a procedural harness.")
        occurrences = self._design.rootComponent.allOccurrencesByComponent(component)
        if occurrences.count != 1:
            raise RuntimeError(
                "The damaged harness component must have exactly one design occurrence before deletion."
            )
        occurrence = occurrences.item(0)
        if occurrence is None or not occurrence.deleteMe():
            raise RuntimeError("Fusion did not delete the damaged harness component.")

    def read_harness_definition(self, harness_id: UUID) -> str:
        """
        Return the serialized definition owned by one harness.

        Args:
            harness_id: Persistent harness identity to find.

        Returns:
            Stored definition JSON.
        """
        _component, attribute = self._find_harness_component(harness_id)
        return attribute.value

    def replace_harness_definition(
        self,
        harness_id: UUID,
        serialized_definition: str,
    ) -> None:
        """
        Replace the serialized definition owned by one harness.

        Args:
            harness_id: Persistent harness identity to update.
            serialized_definition: Complete replacement definition JSON.
        """
        component, _attribute = self._find_harness_component(harness_id)
        updated_attribute = component.attributes.add(
            ATTRIBUTE_GROUP,
            DEFINITION_ATTRIBUTE_NAME,
            serialized_definition,
        )
        if updated_attribute is None:
            raise RuntimeError("Fusion did not update the harness definition attribute.")

    def is_entity_token_resolvable(self, entity_token: str) -> bool:
        """
        Return whether Fusion can still resolve a persisted entity token.

        Args:
            entity_token: Persistent token previously obtained from Fusion geometry.

        Returns:
            ``True`` when the active design resolves at least one matching entity.
        """
        if not entity_token.strip():
            return False
        resolved_entities = self._design.findEntityByToken(entity_token)
        return bool(resolved_entities)

    def create_harness_component(self, name: str) -> object:
        """
        Create an empty child component under the active component.

        Part designs are converted to hybrid intent because Fusion prohibits child
        components in a part. Assembly designs create an unsaved external component
        in the active cloud folder.

        Args:
            name: Name assigned to the new component.

        Returns:
            An opaque handle for the occurrence that owns the new component.
        """
        original_design_intent = self._prepare_design_intent()
        uses_external_component = self._is_assembly_design()
        occurrence: Optional[_FusionOccurrence] = None
        try:
            transform = adsk.core.Matrix3D.create()
            occurrences = self._parent_component().occurrences
            if uses_external_component:
                target_folder = self._require_external_component_folder()
                created_occurrence = occurrences.addNewExternalComponent(
                    name,
                    target_folder,
                    transform,
                )
            else:
                created_occurrence = occurrences.addNewComponent(transform)
            occurrence = cast(
                Optional[_FusionOccurrence],
                adsk.fusion.Occurrence.cast(created_occurrence),
            )
            if occurrence is None:
                raise RuntimeError("Fusion did not create the harness component.")
            if not uses_external_component:
                occurrence.component.name = name
        except (AttributeError, RuntimeError, TypeError):
            if occurrence is not None:
                occurrence.deleteMe()
            self._restore_design_intent(original_design_intent)
            raise
        return _HarnessComponentHandle(occurrence, original_design_intent)

    def write_definition(self, component: object, serialized_definition: str) -> None:
        """
        Write versioned harness JSON to the component's Fusion attributes.

        Args:
            component: Opaque handle returned by ``create_harness_component``.
            serialized_definition: Versioned harness JSON.
        """
        handle = self._require_handle(component)
        occurrence = handle.occurrence
        attribute = occurrence.component.attributes.add(
            ATTRIBUTE_GROUP,
            DEFINITION_ATTRIBUTE_NAME,
            serialized_definition,
        )
        if attribute is None:
            raise RuntimeError("Fusion did not persist the harness definition attribute.")

    def delete_harness_component(self, component: object) -> None:
        """
        Delete an incomplete harness occurrence during rollback.

        Args:
            component: Opaque handle returned by ``create_harness_component``.
        """
        handle = self._require_handle(component)
        occurrence = handle.occurrence
        if not occurrence.deleteMe():
            raise RuntimeError("Fusion did not delete the incomplete harness component.")
        self._restore_design_intent(handle.original_design_intent)

    def harness_component(self, harness_id: UUID) -> adsk.fusion.Component:
        """
        Resolve the native component owned by a persisted harness definition.
        """
        component, _attribute = self._find_harness_component(harness_id)
        resolved = adsk.fusion.Component.cast(component)
        if resolved is None:
            raise RuntimeError("Harness owner is not a Fusion component.")
        return resolved

    def _find_harness_component(
        self,
        harness_id: UUID,
    ) -> tuple[_FusionComponent, _FusionAttribute]:
        """
        Find the marked Fusion component owning one valid harness definition.

        Args:
            harness_id: Persistent harness identity to locate.

        Returns:
            Matching component and definition attribute.

        Raises:
            RuntimeError: If no matching readable harness exists.
        """
        components = cast(_FusionComponents, self._design.allComponents)
        for index in range(components.count):
            component = components.item(index)
            if component is None:
                continue
            attribute = component.attributes.itemByName(
                ATTRIBUTE_GROUP,
                DEFINITION_ATTRIBUTE_NAME,
            )
            if attribute is None:
                continue
            try:
                definition = loads(attribute.value)
            except (DefinitionParseError, TypeError, ValueError):
                continue
            if definition.harness_id == harness_id:
                return component, attribute
        raise RuntimeError(f"Harness definition is unavailable: {harness_id}")

    @staticmethod
    def _require_handle(component: object) -> _HarnessComponentHandle:
        """
        Cast an opaque application-layer value to a gateway component handle.

        Args:
            component: Opaque component handle from the application service.

        Returns:
            Valid gateway component handle.
        """
        if not isinstance(component, _HarnessComponentHandle):
            raise TypeError("Harness component handle was not created by this gateway.")
        return component

    def _prepare_design_intent(self) -> object:
        """
        Ensure Fusion permits the appropriate harness-component workflow.

        Returns:
            Original design intent, retained so failed creation can be rolled back.
        """
        intent_types = adsk.fusion.DesignIntentTypes
        original_design_intent = self._design.designIntent
        if original_design_intent == intent_types.PartDesignIntentType:
            self._design.designIntent = intent_types.HybridDesignIntentType

        supported_intents = (
            intent_types.HybridDesignIntentType,
            intent_types.AssemblyDesignIntentType,
        )
        if self._design.designIntent not in supported_intents:
            raise RuntimeError("Harness Builder encountered an unsupported design intent.")
        if self._is_assembly_design():
            self._require_external_component_folder()
        return original_design_intent

    def _is_assembly_design(self) -> bool:
        """
        Return whether the active design requires an external component.
        """
        return self._design.designIntent == adsk.fusion.DesignIntentTypes.AssemblyDesignIntentType

    def _parent_component(self) -> _FusionComponent:
        """
        Return the component that will own the new occurrence.
        """
        if self._is_assembly_design():
            return cast(_FusionComponent, self._design.rootComponent)
        return cast(_FusionComponent, self._design.activeComponent)

    def _require_external_component_folder(self) -> _DataFolder:
        """
        Return the cloud folder required for assembly-external components.

        Raises:
            RuntimeError: If Fusion has no active cloud folder.
        """
        if self._external_component_folder is None:
            raise RuntimeError("Assembly harness creation requires an active Fusion cloud folder.")
        return self._external_component_folder

    def _restore_design_intent(self, original_design_intent: object) -> None:
        """
        Restore an automatically converted design after failed creation.

        Args:
            original_design_intent: Intent observed before component creation.
        """
        if self._design.designIntent != original_design_intent:
            self._design.designIntent = original_design_intent
