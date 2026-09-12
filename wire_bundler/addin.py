"""
Fusion 360 lifecycle and command registration.
"""

from __future__ import annotations

import json
import math
import traceback
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional, cast
from uuid import UUID, uuid4

# noinspection PyUnresolvedReferences
import adsk.core

# noinspection PyUnresolvedReferences
import adsk.fusion

from .application import (
    HarnessLoadResult,
    RelationshipMap,
    add_junction,
    add_junction_relationship,
    add_pathway,
    add_pathway_refine,
    add_wire_batch,
    append_pathway_gates,
    build_relationship_map,
    create_empty_harness,
    delete_damaged_harness,
    load_harnesses,
    load_wire_material_catalog,
    move_pathway_gate,
    move_wire_endpoint,
    remove_junction_relationship,
    remove_pathway_gate,
    remove_wire,
    rename_junction,
    rename_pathway,
    rename_route_end,
    rename_wire,
    segment_pathway,
    set_harness_material_defaults,
    set_wire_diameter,
    set_wire_material_overrides,
    suggest_harness_name,
    suggest_pathway_extension_name,
    suggest_pathway_name,
    update_junction_relationships,
    update_pathway_refine,
)
from .application.edit_harness import edit_end_members, set_interpolation
from .domain import (
    ControlKind,
    HarnessDefinition,
    JunctionPathwayRelationship,
    PathwayEndpoint,
    RefineGeometry,
    RoutingMode,
    StripePattern,
    WireAppearanceReference,
    WireColor,
    WireMaterialOverrides,
    WireMaterialSettings,
    WireStripe,
    loads,
)
from .domain.codec import parse_interpolation
from .fusion import (
    FusionHarnessGateway,
    clear_route_previews,
    highlight_route_preview,
    show_route_previews,
)
from .fusion.refine_graphics import (
    DEFAULT_REFINE_RADIUS_MM,
    REFINE_GRAPHICS_GROUP_ID,
    REFINE_SPINE_ENTITY_ID,
    PathwaySpine,
    RefinePlacement,
    build_pathway_spine,
    clear_candidate_refine,
    clear_refine_graphics,
    clear_refine_spine,
    draw_candidate_refine,
    draw_pathway_spine,
    draw_refine_editor,
    has_refine_graphics,
    highlight_refine_graphics,
    place_refine,
    reconcile_refine_graphics,
    update_candidate_refine,
    update_refine_editor,
)
from .fusion.route_preview import (
    has_route_previews,
    highlight_route_members,
    reconcile_preview_history,
    refresh_route_previews,
    reset_preview_history,
)
from .fusion.wire_solids import (
    apply_wire_materials,
    clear_wire_solids,
    generate_wire_solids,
    generated_wire_bodies,
)
from .routing import Vector3
from .routing.geometry import cross, unit

COMMAND_ID = "kev0_wire_bundler_harness_builder"
CREATE_COMMAND_ID = "kev0_wire_bundler_create_harness"
ADD_PATHWAY_COMMAND_ID = "kev0_wire_bundler_add_pathway"
ADD_JUNCTION_COMMAND_ID = "kev0_wire_bundler_add_junction"
ADD_JUNCTION_RELATIONSHIP_COMMAND_ID = "kev0_wire_bundler_add_junction_relationship"
APPEND_GATES_COMMAND_ID = "kev0_wire_bundler_append_pathway_gates"
ADD_REFINE_COMMAND_ID = "kev0_wire_bundler_add_pathway_refine"
SEGMENT_PATHWAY_COMMAND_ID = "kev0_wire_bundler_segment_pathway"
EDIT_REFINE_COMMAND_ID = "kev0_wire_bundler_edit_pathway_refine"
EDIT_END_COMMAND_ID = "kev0_wire_bundler_edit_end_members"
ADD_WIRES_COMMAND_ID = "kev0_wire_bundler_add_wires"
COMMAND_NAME = "Harness Builder"
COMMAND_DESCRIPTION = "Create and edit wire, ribbon, and harness assemblies."
CREATE_COMMAND_NAME = "Create Harness"
ADD_PATHWAY_COMMAND_NAME = "Add Pathway"
ADD_JUNCTION_COMMAND_NAME = "Add Junction"
ADD_JUNCTION_RELATIONSHIP_COMMAND_NAME = "Add Junction Relationship"
APPEND_GATES_COMMAND_NAME = "Add Gates"
ADD_REFINE_COMMAND_NAME = "Add Refine Point"
SEGMENT_PATHWAY_COMMAND_NAME = "Segment Pathway"
EDIT_REFINE_COMMAND_NAME = "Edit Refine Point"
ADD_WIRES_COMMAND_NAME = "Add Wires"
PALETTE_ID = "kev0_wire_bundler_harness_builder_palette"
PALETTE_HTML_URL = "palette.html"
PALETTE_INITIAL_WIDTH = 840
PALETTE_INITIAL_HEIGHT = 760
WORKSPACE_ID = "FusionSolidEnvironment"
PANEL_IDS = ("SolidScriptsAddinsPanel", "InsertAssemblePanel")
HARNESS_NAME_INPUT_ID = "harness_name"
PATHWAY_NAME_INPUT_ID = "pathway_name"
PATHWAY_GATES_INPUT_ID = "pathway_gates"
JUNCTION_PROFILE_INPUT_ID = "junction_profile"
JUNCTION_RELATIONSHIP_GEOMETRY_INPUT_ID = "junction_relationship_geometry"
JUNCTION_RELATIONSHIP_CHOICE_INPUT_ID = "junction_relationship_choice"
REFINE_SPINE_INPUT_ID = "refine_spine"
REFINE_RADIUS_INPUT_ID = "refine_radius"
REFINE_TRANSFORM_INPUT_ID = "refine_transform"
SEGMENT_CONTROL_INPUT_ID = "segment_control"
SEGMENT_PATHWAY_NAME_INPUT_ID = "segment_pathway_name"
WIRE_PATHWAY_INPUT_ID = "wire_pathway"
WIRE_DIAMETER_INPUT_ID = "wire_diameter"
SOURCE_CONNECTIONS_INPUT_ID = "source_connections"
DESTINATION_CONNECTIONS_INPUT_ID = "destination_connections"
ROUTING_MODE_INPUT_ID = "routing_mode"
DEFAULT_HARNESS_NAME = "Harness_001"
ADDIN_ROOT = Path(__file__).resolve().parent.parent
COMMAND_RESOURCE_FOLDER = str(ADDIN_ROOT / "resources" / "open_harness_builder")
ADD_PATHWAY_RESOURCE_FOLDER = str(ADDIN_ROOT / "resources" / "add_routing_gate")
ADD_WIRES_RESOURCE_FOLDER = str(ADDIN_ROOT / "resources" / "add_harness_wire")
PALETTE_HTML_FILE = ADDIN_ROOT / "palette.html"
PALETTE_RESOURCE_FILES = (
    PALETTE_HTML_FILE,
    ADDIN_ROOT / "palette" / "styles.css",
    ADDIN_ROOT / "palette" / "foundation.js",
    ADDIN_ROOT / "palette" / "route-editors.js",
    ADDIN_ROOT / "palette" / "materials.js",
    ADDIN_ROOT / "palette" / "relationship-audit.js",
    ADDIN_ROOT / "palette" / "wire-graphic.js",
    ADDIN_ROOT / "palette" / "master-graphic.js",
    ADDIN_ROOT / "palette" / "editor.js",
    ADDIN_ROOT / "palette" / "host.js",
)

_ROUTING_MODE_LABELS = {
    RoutingMode.ROUTING_GATES: "Routing Gates",
    RoutingMode.PROFILE_GATES: "Profile Gates",
}

_handlers: list[object] = []
_pending_pathway_harness_id: Optional[UUID] = None
_pending_junction_harness_id: Optional[UUID] = None
_pending_junction_relationship_ids: Optional[tuple[UUID, UUID]] = None
_pending_append_gate_ids: Optional[tuple[UUID, UUID]] = None
_pending_refine_ids: Optional[tuple[UUID, UUID]] = None
_pending_segment_ids: Optional[tuple[UUID, UUID]] = None
_pending_refine_edit_ids: Optional[tuple[UUID, UUID]] = None
_pending_end_edit: Optional[dict[str, object]] = None
_pending_wire_harness_id: Optional[UUID] = None
_pending_wire_pathway_id: Optional[UUID] = None
_pending_palette_edit: Optional[tuple[str, str, object]] = None
_last_command_error = ""
_last_diagram_qa_observation: Optional[dict[str, object]] = None
_damaged_harness_results: dict[str, HarnessLoadResult] = {}
_history_handler: Optional[_HistoryChangedHandler] = None
_active_selection_handler: Optional[_RefineActiveSelectionHandler] = None
_document_saving_handler: Optional[_DocumentSavingHandler] = None
_document_saved_handler: Optional[_DocumentSavedHandler] = None
_graphics_cache_restore_value: Optional[bool] = None
_graphics_cache_save_document: Optional[object] = None
_PALETTE_EDIT_NAMES = {
    "delete_damaged_harness": "Delete Damaged Harness",
    "move_pathway_gate": "Reorder Pathway Gates",
    "update_junction_relationships": "Edit Junction Relationships",
    "remove_junction_relationship": "Remove Junction Relationship",
    "remove_pathway_gate": "Remove Pathway Gate",
    "move_wire_endpoint": "Reorder Wire Ends",
    "remove_wire": "Delete Wire",
    "rename_junction": "Rename Junction",
    "rename_route_end": "Rename Wire End",
    "rename_pathway": "Rename Pathway",
    "rename_wire": "Rename Wire",
    "set_wire_diameter": "Change Wire Diameter",
    "set_harness_material_defaults": "Change Harness Wire Materials",
    "set_wire_material_overrides": "Change Wire Materials",
    "set_interpolation": "Change Interpolation Options",
    "remove_end_member": "Remove End Member",
    "move_end_member": "Reorder End Members",
    "preview_routes": "Preview Wire Routes",
    "generate_solids": "Generate Wire Solids",
    "clear_solids": "Clear Wire Solids",
}


class _PaletteEditExecuteHandler(adsk.core.CommandEventHandler):
    """
    Apply a palette edit and its preview inside one Fusion command transaction.
    """

    def __init__(self, request: tuple[str, str, object]) -> None:
        """
        Capture the immutable request and its originating document.
        """
        super().__init__()
        self.request = request
        self.clear_preview_after_destroy = False

    def notify(self, args: adsk.core.CommandEventArgs) -> None:
        """
        Execute against the original document or fail the command without editing.
        """
        global _last_command_error
        _last_command_error = ""
        action, data, document = self.request
        application = adsk.core.Application.get()
        try:
            if application.activeDocument != document:
                raise ValueError(
                    "The active document changed; retry the edit in its original document."
                )
            if action == "preview_routes":
                _preview_routes(application, data)
                return
            if action == "generate_solids":
                _generate_solids(application, data)
                self.clear_preview_after_destroy = True
                return
            if action == "clear_solids":
                _clear_solids(application, data)
                return
            if action == "delete_damaged_harness":
                notice = _delete_damaged_harness(application, data)
                application.activeViewport.refresh()
                _send_palette_state(application, notice)
                return
            notice = _apply_palette_edit(application, action, data)
            harness_id = _read_payload_uuid(_read_palette_payload(data), "harnessId", "harness")
            if action == "remove_pathway_gate":
                _reconcile_active_refines(application)
            if action in {"set_harness_material_defaults", "set_wire_material_overrides"}:
                notice = f"{notice} {_apply_generated_materials(application, harness_id)}".strip()
            warning = _refresh_active_preview(
                application,
                harness_id,
                ensure_visible=action
                in {"set_harness_material_defaults", "set_wire_material_overrides"},
            )
            application.activeViewport.refresh()
            _send_palette_state(application, f"{notice} {warning}".strip())
        except (AttributeError, RuntimeError, TypeError, ValueError) as error:
            args.executeFailed = True
            args.executeFailedMessage = str(error)
            _last_command_error = str(error)
            _log_to_fusion(f"Harness command failed: {error}\n{traceback.format_exc()}")


class _PaletteEditCreatedHandler(adsk.core.CommandCreatedEventHandler):
    """
    Attach execution to a dialog-free command without editing during creation.
    """

    # noinspection PyMethodMayBeStatic
    def notify(self, args: adsk.core.CommandCreatedEventArgs) -> None:
        """
        Consume the queued request once and let Fusion auto-execute the command.
        """
        global _pending_palette_edit
        request = _pending_palette_edit
        _pending_palette_edit = None
        if request is None:
            return
        handler = _PaletteEditExecuteHandler(request)
        if not args.command.execute.add(handler):
            raise RuntimeError("Fusion could not attach the palette edit handler.")
        cleanup = _PaletteEditDestroyedHandler(handler)
        if not args.command.destroy.add(cleanup):
            args.command.execute.remove(handler)
            raise RuntimeError("Fusion could not attach edit cleanup.")
        _handlers.extend((handler, cleanup))


class _PaletteEditDestroyedHandler(adsk.core.CommandEventHandler):
    """
    Release per-edit handlers when a short-lived palette command ends.
    """

    def __init__(self, execute_handler: _PaletteEditExecuteHandler) -> None:
        """
        Keep the paired execution handler alive until command destruction.
        """
        super().__init__()
        self.execute_handler = execute_handler

    def notify(self, _args: adsk.core.CommandEventArgs) -> None:
        """
        Clear a completed solid preview, then release the short-lived handlers.
        """
        if self.execute_handler.clear_preview_after_destroy:
            application = adsk.core.Application.get()
            _action, _data, document = self.execute_handler.request
            if application.activeDocument == document:
                try:
                    _clear_preview(application)
                except (AttributeError, RuntimeError, TypeError, ValueError) as error:
                    _log_to_fusion(f"Generated solids, but preview cleanup failed: {error}")
        for handler in (self.execute_handler, self):
            if handler in _handlers:
                _handlers.remove(handler)


class _HistoryChangedHandler(adsk.core.ApplicationCommandEventHandler):
    """
    Re-read restored state after commands, including native Undo and Redo.
    """

    # noinspection PyMethodMayBeStatic
    def notify(self, _args: adsk.core.ApplicationCommandEventArgs) -> None:
        """
        Synchronize only UI and Python caches so Redo history remains intact.
        """
        application = adsk.core.Application.get()
        try:
            design = adsk.fusion.Design.cast(application.activeProduct)
            if design is None:
                return
            results = load_harnesses(_create_harness_gateway(application))
            definitions = tuple(
                result.definition for result in results if result.definition is not None
            )
            reconcile_preview_history(design, definitions)
            _send_palette_state(application)
        except (AttributeError, RuntimeError, TypeError, ValueError) as error:
            _log_to_fusion(f"Could not synchronize harness history: {error}")


class _DocumentSavingHandler(adsk.core.DocumentEventHandler):
    """
    Prevent live route previews from entering Fusion's saved OGS scene cache.
    """

    # noinspection PyMethodMayBeStatic
    def notify(self, args: adsk.core.DocumentEventArgs) -> None:
        """
        Disable graphics caching only for a save containing an active preview.
        """
        global _graphics_cache_restore_value, _graphics_cache_save_document
        application = adsk.core.Application.get()
        try:
            design = _document_design(args.document)
            if design is None or not (has_route_previews(design) or has_refine_graphics(design)):
                return
            compatibility = application.preferences.compatibilityPreferences
            if _graphics_cache_restore_value is None:
                _graphics_cache_restore_value = compatibility.isCacheGraphicsOnDocumentSave
            _graphics_cache_save_document = args.document
            compatibility.isCacheGraphicsOnDocumentSave = False
        except (AttributeError, RuntimeError, TypeError, ValueError) as error:
            _log_to_fusion(f"Could not protect route previews during save: {error}")


class _DocumentSavedHandler(adsk.core.DocumentEventHandler):
    """
    Restore the user's graphics-cache preference after a protected save.
    """

    # noinspection PyMethodMayBeStatic
    def notify(self, args: adsk.core.DocumentEventArgs) -> None:
        """
        Restore only after the document whose save disabled graphics caching.
        """
        if args.document != _graphics_cache_save_document:
            return
        _restore_graphics_cache_preference(adsk.core.Application.get())


def _document_design(document: adsk.core.Document) -> Optional[adsk.fusion.Design]:
    """
    Resolve the Design product owned by a document event.
    """
    product = document.products.itemByProductType("DesignProductType")
    return adsk.fusion.Design.cast(product)


def _restore_graphics_cache_preference(application: adsk.core.Application) -> None:
    """
    Restore the compatibility preference captured before a protected save.
    """
    global _graphics_cache_restore_value, _graphics_cache_save_document
    if _graphics_cache_restore_value is None:
        return
    restore_value = _graphics_cache_restore_value
    _graphics_cache_restore_value = None
    _graphics_cache_save_document = None
    application.preferences.compatibilityPreferences.isCacheGraphicsOnDocumentSave = restore_value


def _register_document_handlers(application: adsk.core.Application) -> None:
    """
    Register save guards that keep transient previews out of saved documents.
    """
    global _document_saving_handler, _document_saved_handler
    _remove_document_handlers(application)
    saving_handler = _DocumentSavingHandler()
    if not application.documentSaving.add(saving_handler):
        raise RuntimeError("Fusion could not register route-preview save protection.")
    saved_handler = _DocumentSavedHandler()
    if not application.documentSaved.add(saved_handler):
        application.documentSaving.remove(saving_handler)
        raise RuntimeError("Fusion could not register graphics-cache restoration.")
    _document_saving_handler = saving_handler
    _document_saved_handler = saved_handler


def _remove_document_handlers(application: adsk.core.Application) -> None:
    """
    Remove save guards and restore any compatibility preference they changed.
    """
    global _document_saving_handler, _document_saved_handler
    if _document_saving_handler is not None:
        application.documentSaving.remove(_document_saving_handler)
        _document_saving_handler = None
    if _document_saved_handler is not None:
        application.documentSaved.remove(_document_saved_handler)
        _document_saved_handler = None
    _restore_graphics_cache_preference(application)


def _open_palette_edit(application: adsk.core.Application, action: str, data: str) -> None:
    """
    Queue one palette request for a named, dialog-free Fusion command.
    """
    global _pending_palette_edit
    if _pending_palette_edit is not None:
        raise RuntimeError("Another harness edit is starting; retry after it completes.")
    definition = application.userInterface.commandDefinitions.itemById(f"{COMMAND_ID}_{action}")
    if definition is None:
        raise RuntimeError("The harness edit command is unavailable; restart the add-in.")
    _pending_palette_edit = (action, data, application.activeDocument)
    try:
        if not definition.execute():
            raise RuntimeError("Fusion could not execute the harness edit command.")
    except (AttributeError, RuntimeError, TypeError, ValueError):
        _pending_palette_edit = None
        raise


class _HarnessBuilderExecuteHandler(adsk.core.CommandEventHandler):
    """
    Handle execution of the initial Harness Builder command.
    """

    # noinspection PyMethodMayBeStatic
    def notify(self, args: adsk.core.CommandEventArgs) -> None:
        """
        Create an empty harness component and persist its draft definition.
        """
        try:
            application = adsk.core.Application.get()
            name = _read_harness_name(args.command.commandInputs)
            routing_mode = _read_routing_mode(args.command.commandInputs)
            gateway = _create_harness_gateway(application)
            definition = create_empty_harness(
                name,
                routing_mode,
                gateway,
            )
            _send_palette_state(application, f"Created {definition.name}.")
        except (AttributeError, RuntimeError, TypeError, ValueError):
            _report_failure("create harness")


class _HarnessBuilderValidateInputsHandler(adsk.core.ValidateInputsEventHandler):
    """
    Keep command execution disabled until required draft values are present.
    """

    # noinspection PyMethodMayBeStatic
    def notify(self, args: adsk.core.ValidateInputsEventArgs) -> None:
        """
        Validate the harness name and routing-mode selection.
        """
        try:
            _read_harness_name(args.inputs)
            _read_routing_mode(args.inputs)
        except ValueError:
            args.areInputsValid = False
            return
        args.areInputsValid = True


class _CreateHarnessCreatedHandler(adsk.core.CommandCreatedEventHandler):
    """
    Attach per-command event handlers when Fusion creates a command.
    """

    # noinspection PyMethodMayBeStatic
    def notify(self, args: adsk.core.CommandCreatedEventArgs) -> None:
        """
        Build the initial dialog and retain its handlers for Fusion's event lifetime.
        """
        try:
            application = adsk.core.Application.get()
            gateway = _create_harness_gateway(application)
            initial_name = suggest_harness_name(DEFAULT_HARNESS_NAME, gateway)

            command_inputs = args.command.commandInputs
            name_input = command_inputs.addStringValueInput(
                HARNESS_NAME_INPUT_ID,
                "Harness Name",
                initial_name,
            )
            if name_input is None:
                raise RuntimeError("Fusion did not create the harness name input.")

            routing_mode_input = command_inputs.addDropDownCommandInput(
                ROUTING_MODE_INPUT_ID,
                "Routing Mode",
                adsk.core.DropDownStyles.TextListDropDownStyle,
            )
            if routing_mode_input is None:
                raise RuntimeError("Fusion did not create the routing mode input.")
            for index, label in enumerate(_ROUTING_MODE_LABELS.values()):
                list_item = routing_mode_input.listItems.add(label, index == 0)
                if list_item is None:
                    raise RuntimeError(f"Fusion did not add the routing mode option: {label}")

            execute_handler = _HarnessBuilderExecuteHandler()
            validate_handler = _HarnessBuilderValidateInputsHandler()
            if not args.command.execute.add(execute_handler):
                raise RuntimeError("Fusion did not register the harness execution handler.")
            if not args.command.validateInputs.add(validate_handler):
                raise RuntimeError("Fusion did not register the harness validation handler.")
            _handlers.extend((execute_handler, validate_handler))
        except (AttributeError, RuntimeError, TypeError, ValueError):
            _report_failure("open Harness Builder")
            raise


class _AddPathwayExecuteHandler(adsk.core.CommandEventHandler):
    """
    Persist an ordered pathway selected from Fusion sketch profiles.
    """

    def __init__(self, harness_id: UUID) -> None:
        """
        Bind the handler to the harness selected in the palette.
        """
        super().__init__()
        self._harness_id = harness_id

    # noinspection PyMethodMayBeStatic
    def notify(self, args: adsk.core.CommandEventArgs) -> None:
        """
        Add the selected gate profiles to the owning harness as one pathway.
        """
        try:
            application = adsk.core.Application.get()
            command_inputs = args.command.commandInputs
            pathway = add_pathway(
                self._harness_id,
                _read_pathway_name(command_inputs),
                _read_routing_mode(command_inputs),
                _read_pathway_gate_tokens(command_inputs),
                _create_harness_gateway(application),
            )
            _send_palette_state(application, f"Created {pathway.name}.")
        except (AttributeError, RuntimeError, TypeError, ValueError):
            _report_failure("add pathway")


class _AddPathwayValidateInputsHandler(adsk.core.ValidateInputsEventHandler):
    """
    Require a name, routing mode, and at least one selected profile.
    """

    # noinspection PyMethodMayBeStatic
    def notify(self, args: adsk.core.ValidateInputsEventArgs) -> None:
        """
        Validate the complete pathway draft before Fusion enables execution.
        """
        try:
            _read_pathway_name(args.inputs)
            _read_routing_mode(args.inputs)
            _read_pathway_gate_tokens(args.inputs)
        except ValueError:
            args.areInputsValid = False
            return
        args.areInputsValid = True


class _AddPathwayCreatedHandler(adsk.core.CommandCreatedEventHandler):
    """
    Build the ordered profile-selection command for the selected harness.
    """

    # noinspection PyMethodMayBeStatic
    def notify(self, args: adsk.core.CommandCreatedEventArgs) -> None:
        """
        Add pathway inputs and retain their event handlers.
        """
        global _pending_pathway_harness_id

        harness_id = _pending_pathway_harness_id
        _pending_pathway_harness_id = None
        try:
            if harness_id is None:
                raise RuntimeError("No harness was selected for pathway creation.")
            application = adsk.core.Application.get()
            gateway = _create_harness_gateway(application)
            definition = loads(gateway.read_harness_definition(harness_id))
            initial_name = suggest_pathway_name(harness_id, "Pathway_001", gateway)
            command_inputs = args.command.commandInputs

            name_input = command_inputs.addStringValueInput(
                PATHWAY_NAME_INPUT_ID,
                "Pathway Name",
                initial_name,
            )
            if name_input is None:
                raise RuntimeError("Fusion did not create the pathway name input.")

            routing_mode_input = command_inputs.addDropDownCommandInput(
                ROUTING_MODE_INPUT_ID,
                "Routing Mode",
                adsk.core.DropDownStyles.TextListDropDownStyle,
            )
            if routing_mode_input is None:
                raise RuntimeError("Fusion did not create the pathway routing-mode input.")
            for routing_mode, label in _ROUTING_MODE_LABELS.items():
                list_item = routing_mode_input.listItems.add(
                    label,
                    routing_mode is definition.routing_mode,
                )
                if list_item is None:
                    raise RuntimeError(f"Fusion did not add the routing mode option: {label}")

            gate_input = command_inputs.addSelectionInput(
                PATHWAY_GATES_INPUT_ID,
                "Ordered Gate Profiles",
                "Select sketch profiles in pathway traversal order",
            )
            if gate_input is None:
                raise RuntimeError("Fusion did not create the pathway gate selection input.")
            if not gate_input.addSelectionFilter("Profiles"):
                raise RuntimeError("Fusion did not apply the sketch-profile selection filter.")
            if not gate_input.setSelectionLimits(1, 0):
                raise RuntimeError("Fusion did not configure the pathway selection limits.")

            execute_handler = _AddPathwayExecuteHandler(harness_id)
            validate_handler = _AddPathwayValidateInputsHandler()
            if not args.command.execute.add(execute_handler):
                raise RuntimeError("Fusion did not register the pathway execution handler.")
            if not args.command.validateInputs.add(validate_handler):
                raise RuntimeError("Fusion did not register the pathway validation handler.")
            _handlers.extend((execute_handler, validate_handler))
        except (AttributeError, RuntimeError, TypeError, ValueError):
            _report_failure("open Add Pathway")
            raise


@dataclass(frozen=True)
class _AddJunctionCommandState:
    """
    Retain the selected harness and its already registered profile entities.
    """

    harness_id: UUID
    registered_profiles: tuple[object, ...]


def _junction_profile_token(
    command_inputs: adsk.core.CommandInputs,
    state: _AddJunctionCommandState,
) -> str:
    """
    Return one unregistered selected sketch-profile token.
    """
    selection_input = adsk.core.SelectionCommandInput.cast(
        command_inputs.itemById(JUNCTION_PROFILE_INPUT_ID)
    )
    if selection_input is None or selection_input.selectionCount != 1:
        raise ValueError("Select one unused sketch profile for the junction.")
    selection = selection_input.selection(0)
    profile = adsk.fusion.Profile.cast(selection.entity if selection is not None else None)
    if profile is None or not profile.entityToken.strip():
        raise ValueError("Junction selection is not a valid sketch profile.")
    selected = _native_fusion_entity(profile)
    if any(selected == registered for registered in state.registered_profiles):
        raise ValueError("Selected geometry is already registered in this harness.")
    return profile.entityToken


class _AddJunctionPreSelectHandler(adsk.core.SelectionEventHandler):
    """
    Prevent selection of profiles already registered in the owning harness.
    """

    def __init__(self, state: _AddJunctionCommandState) -> None:
        """
        Retain resolved registered profile entities.
        """
        super().__init__()
        self._state = state

    def notify(self, args: adsk.core.SelectionEventArgs) -> None:
        """
        Allow only an unused sketch profile.
        """
        selection = args.selection
        profile = adsk.fusion.Profile.cast(selection.entity if selection is not None else None)
        selected = _native_fusion_entity(profile) if profile is not None else None
        args.isSelectable = profile is not None and all(
            selected != registered for registered in self._state.registered_profiles
        )


class _AddJunctionValidateInputsHandler(adsk.core.ValidateInputsEventHandler):
    """
    Require exactly one currently unregistered sketch profile.
    """

    def __init__(self, state: _AddJunctionCommandState) -> None:
        """
        Retain the selection-validation state.
        """
        super().__init__()
        self._state = state

    def notify(self, args: adsk.core.ValidateInputsEventArgs) -> None:
        """
        Enable execution only for an eligible selection.
        """
        try:
            _junction_profile_token(args.inputs, self._state)
        except (AttributeError, TypeError, ValueError):
            args.areInputsValid = False
            return
        args.areInputsValid = True


class _AddJunctionExecuteHandler(adsk.core.CommandEventHandler):
    """
    Persist one isolated junction inside Fusion's command transaction.
    """

    def __init__(self, state: _AddJunctionCommandState) -> None:
        """
        Retain the selected harness and registered geometry state.
        """
        super().__init__()
        self._state = state

    def notify(self, args: adsk.core.CommandEventArgs) -> None:
        """
        Add the junction and refresh the palette projection.
        """
        application = adsk.core.Application.get()
        try:
            junction = add_junction(
                self._state.harness_id,
                _junction_profile_token(args.command.commandInputs, self._state),
                _create_harness_gateway(application),
            )
            _send_palette_state(application, f"Created {junction.name}.")
        except (AttributeError, RuntimeError, TypeError, ValueError) as error:
            args.executeFailed = True
            args.executeFailedMessage = str(error)
            _log_to_fusion(f"Add junction failed: {error}\n{traceback.format_exc()}")


class _AddJunctionCreatedHandler(adsk.core.CommandCreatedEventHandler):
    """
    Build the unused-profile selector for isolated junction creation.
    """

    # noinspection PyMethodMayBeStatic
    def notify(self, args: adsk.core.CommandCreatedEventArgs) -> None:
        """
        Resolve registered profiles and attach command-lifetime handlers.
        """
        global _pending_junction_harness_id

        harness_id = _pending_junction_harness_id
        _pending_junction_harness_id = None
        try:
            if harness_id is None:
                raise RuntimeError("No harness was selected for junction creation.")
            application = adsk.core.Application.get()
            design = _require_active_design(application)
            definition = loads(
                _create_harness_gateway(application).read_harness_definition(harness_id)
            )
            registered_tokens = {
                token for connection in definition.connections for token in connection.member_tokens
            } | {control.entity_token for control in definition.controls if control.entity_token}
            registered_profiles: list[object] = []
            for token in registered_tokens:
                for entity in design.findEntityByToken(token) or ():
                    profile = adsk.fusion.Profile.cast(entity)
                    if profile is not None:
                        registered_profiles.append(_native_fusion_entity(profile))
            state = _AddJunctionCommandState(harness_id, tuple(registered_profiles))
            selection_input = args.command.commandInputs.addSelectionInput(
                JUNCTION_PROFILE_INPUT_ID,
                "Junction Profile",
                "Select one sketch profile not already registered in this harness",
            )
            if selection_input is None or not selection_input.addSelectionFilter("Profiles"):
                raise RuntimeError("Fusion could not configure junction-profile selection.")
            if not selection_input.setSelectionLimits(1, 1):
                raise RuntimeError("Fusion could not limit junction-profile selection.")
            preselect_handler = _AddJunctionPreSelectHandler(state)
            validate_handler = _AddJunctionValidateInputsHandler(state)
            execute_handler = _AddJunctionExecuteHandler(state)
            if not args.command.preSelect.add(preselect_handler):
                raise RuntimeError("Fusion could not filter junction-profile selection.")
            if not args.command.validateInputs.add(validate_handler):
                raise RuntimeError("Fusion could not validate junction creation.")
            if not args.command.execute.add(execute_handler):
                raise RuntimeError("Fusion could not save the junction.")
            _handlers.extend((preselect_handler, validate_handler, execute_handler))
        except (AttributeError, RuntimeError, TypeError, ValueError):
            _report_failure("open Add Junction")
            raise


@dataclass(frozen=True)
class _JunctionRelationshipCandidate:
    """
    Bind one available pathway endpoint to its selectable Fusion geometry.
    """

    relationship: JunctionPathwayRelationship
    label: str
    control_id: UUID
    profile: Optional[object]


@dataclass(frozen=True)
class _AddJunctionRelationshipCommandState:
    """
    Retain one junction and its currently selectable pathway endpoints.
    """

    harness_id: UUID
    junction_id: UUID
    candidates: tuple[_JunctionRelationshipCandidate, ...]


def _junction_relationship_candidates(
    definition: HarnessDefinition,
    junction_id: UUID,
    design: adsk.fusion.Design,
) -> tuple[_JunctionRelationshipCandidate, ...]:
    """
    Resolve unclaimed pathway boundaries to profiles or persistent refine markers.
    """
    if all(junction.junction_id != junction_id for junction in definition.junctions):
        raise ValueError("Selected junction no longer exists.")
    claimed = {
        (relationship.pathway_id, relationship.endpoint)
        for junction in definition.junctions
        for relationship in junction.pathway_relationships
    }
    controls = {control.control_id: control for control in definition.controls}
    candidates: list[_JunctionRelationshipCandidate] = []
    for pathway in definition.pathways:
        if not pathway.ordered_control_ids:
            continue
        for endpoint, control_id, label in (
            (PathwayEndpoint.START, pathway.ordered_control_ids[0], "End A"),
            (PathwayEndpoint.END, pathway.ordered_control_ids[-1], "End B"),
        ):
            relationship = JunctionPathwayRelationship(pathway.pathway_id, endpoint)
            if (relationship.pathway_id, relationship.endpoint) in claimed:
                continue
            control = controls.get(control_id)
            if control is None:
                continue
            profile: Optional[object] = None
            if control.kind is not ControlKind.REFINE:
                entities = design.findEntityByToken(control.entity_token) or ()
                profile = next(
                    (
                        candidate
                        for entity in entities
                        if (candidate := adsk.fusion.Profile.cast(entity)) is not None
                    ),
                    None,
                )
                if profile is None:
                    continue
            candidates.append(
                _JunctionRelationshipCandidate(
                    relationship,
                    f"{pathway.name} · {label}",
                    control_id,
                    profile,
                )
            )
    return tuple(candidates)


def _matching_junction_relationship_candidates(
    entity: object,
    state: _AddJunctionRelationshipCommandState,
) -> tuple[_JunctionRelationshipCandidate, ...]:
    """
    Return available endpoint candidates represented by one selected entity.
    """
    marker_id = getattr(entity, "id", None)
    marker_control_id: Optional[UUID] = None
    if isinstance(marker_id, str):
        try:
            marker_control_id = UUID(marker_id)
        except ValueError:
            marker_control_id = None
    profile = adsk.fusion.Profile.cast(entity)
    selected_profile = _native_fusion_entity(profile) if profile is not None else None
    return tuple(
        candidate
        for candidate in state.candidates
        if (
            marker_control_id == candidate.control_id
            if candidate.profile is None
            else selected_profile is not None
            and selected_profile == _native_fusion_entity(candidate.profile)
        )
    )


def _read_junction_relationship_candidate(
    command_inputs: adsk.core.CommandInputs,
    state: _AddJunctionRelationshipCommandState,
) -> _JunctionRelationshipCandidate:
    """
    Resolve one selected boundary, requiring a choice only when geometry is ambiguous.
    """
    selection_input = adsk.core.SelectionCommandInput.cast(
        command_inputs.itemById(JUNCTION_RELATIONSHIP_GEOMETRY_INPUT_ID)
    )
    if selection_input is None or selection_input.selectionCount != 1:
        raise ValueError("Select one pathway-ending shape.")
    selection = selection_input.selection(0)
    entity = selection.entity if selection is not None else None
    matches = _matching_junction_relationship_candidates(entity, state)
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ValueError("Selected geometry is not an available pathway end.")
    choice_input = adsk.core.DropDownCommandInput.cast(
        command_inputs.itemById(JUNCTION_RELATIONSHIP_CHOICE_INPUT_ID)
    )
    selected_item = choice_input.selectedItem if choice_input is not None else None
    for candidate in matches:
        if selected_item is not None and selected_item.name == candidate.label:
            return candidate
    raise ValueError("Choose which matching pathway end to attach.")


def _update_junction_relationship_choices(
    command_inputs: adsk.core.CommandInputs,
    state: _AddJunctionRelationshipCommandState,
) -> None:
    """
    Show only endpoint choices represented by the currently selected geometry.
    """
    choice_input = adsk.core.DropDownCommandInput.cast(
        command_inputs.itemById(JUNCTION_RELATIONSHIP_CHOICE_INPUT_ID)
    )
    selection_input = adsk.core.SelectionCommandInput.cast(
        command_inputs.itemById(JUNCTION_RELATIONSHIP_GEOMETRY_INPUT_ID)
    )
    if choice_input is None or selection_input is None:
        raise RuntimeError("Junction relationship inputs are unavailable.")
    choice_input.listItems.clear()
    matches: tuple[_JunctionRelationshipCandidate, ...] = ()
    if selection_input.selectionCount == 1:
        selection = selection_input.selection(0)
        entity = selection.entity if selection is not None else None
        matches = _matching_junction_relationship_candidates(entity, state)
    for index, candidate in enumerate(matches):
        if choice_input.listItems.add(candidate.label, index == 0) is None:
            raise RuntimeError("Fusion could not add a pathway-end choice.")
    choice_input.isVisible = len(matches) > 1


class _AddJunctionRelationshipPreSelectHandler(adsk.core.SelectionEventHandler):
    """
    Restrict relationship selection to unclaimed pathway-ending geometry.
    """

    def __init__(self, state: _AddJunctionRelationshipCommandState) -> None:
        """
        Retain eligible endpoint geometry for the command lifetime.
        """
        super().__init__()
        self._state = state

    def notify(self, args: adsk.core.SelectionEventArgs) -> None:
        """
        Mark only geometry representing at least one available endpoint selectable.
        """
        selection = args.selection
        entity = selection.entity if selection is not None else None
        args.isSelectable = bool(_matching_junction_relationship_candidates(entity, self._state))


class _AddJunctionRelationshipInputChangedHandler(adsk.core.InputChangedEventHandler):
    """
    Narrow the endpoint choice after pathway-ending geometry is selected.
    """

    def __init__(self, state: _AddJunctionRelationshipCommandState) -> None:
        """
        Retain eligible endpoint geometry for the command lifetime.
        """
        super().__init__()
        self._state = state

    def notify(self, args: adsk.core.InputChangedEventArgs) -> None:
        """
        Refresh the ambiguity choice from the current selection.
        """
        if getattr(args.input, "id", None) != JUNCTION_RELATIONSHIP_GEOMETRY_INPUT_ID:
            return
        try:
            _update_junction_relationship_choices(args.inputs, self._state)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            _report_failure("choose junction pathway end")


class _AddJunctionRelationshipValidateInputsHandler(adsk.core.ValidateInputsEventHandler):
    """
    Require one eligible geometry selection and resolved endpoint choice.
    """

    def __init__(self, state: _AddJunctionRelationshipCommandState) -> None:
        """
        Retain eligible endpoint geometry for validation.
        """
        super().__init__()
        self._state = state

    def notify(self, args: adsk.core.ValidateInputsEventArgs) -> None:
        """
        Enable execution only when the selection resolves unambiguously.
        """
        try:
            _read_junction_relationship_candidate(args.inputs, self._state)
        except (AttributeError, TypeError, ValueError):
            args.areInputsValid = False
            return
        args.areInputsValid = True


class _AddJunctionRelationshipExecuteHandler(adsk.core.CommandEventHandler):
    """
    Persist one geometry-selected junction relationship.
    """

    def __init__(self, state: _AddJunctionRelationshipCommandState) -> None:
        """
        Retain the target junction and eligible endpoint set.
        """
        super().__init__()
        self._state = state

    def notify(self, args: adsk.core.CommandEventArgs) -> None:
        """
        Revalidate and attach the selected endpoint in the native transaction.
        """
        application = adsk.core.Application.get()
        try:
            candidate = _read_junction_relationship_candidate(
                args.command.commandInputs,
                self._state,
            )
            add_junction_relationship(
                self._state.harness_id,
                self._state.junction_id,
                candidate.relationship,
                _create_harness_gateway(application),
            )
            _send_palette_state(application, f"Attached {candidate.label}.")
        except (AttributeError, RuntimeError, TypeError, ValueError) as error:
            args.executeFailed = True
            args.executeFailedMessage = str(error)
            _log_to_fusion(f"Add junction relationship failed: {error}\n{traceback.format_exc()}")


class _AddJunctionRelationshipCreatedHandler(adsk.core.CommandCreatedEventHandler):
    """
    Build the pathway-ending geometry selector for one junction.
    """

    # noinspection PyMethodMayBeStatic
    def notify(self, args: adsk.core.CommandCreatedEventArgs) -> None:
        """
        Resolve available boundaries and attach command-lifetime handlers.
        """
        global _pending_junction_relationship_ids

        pending_ids = _pending_junction_relationship_ids
        _pending_junction_relationship_ids = None
        try:
            if pending_ids is None:
                raise RuntimeError("No junction was selected for relationship editing.")
            harness_id, junction_id = pending_ids
            application = adsk.core.Application.get()
            design = _require_active_design(application)
            definition = loads(
                _create_harness_gateway(application).read_harness_definition(harness_id)
            )
            candidates = _junction_relationship_candidates(definition, junction_id, design)
            if not candidates:
                raise ValueError("No unclaimed pathway-ending geometry is available.")
            state = _AddJunctionRelationshipCommandState(
                harness_id,
                junction_id,
                candidates,
            )
            command_inputs = args.command.commandInputs
            selection_input = command_inputs.addSelectionInput(
                JUNCTION_RELATIONSHIP_GEOMETRY_INPUT_ID,
                "Pathway End",
                "Select pathway-ending shape geometry",
            )
            if selection_input is None:
                raise RuntimeError("Fusion could not create pathway-end selection.")
            if not selection_input.addSelectionFilter("Profiles"):
                raise RuntimeError("Fusion could not allow pathway profile selection.")
            if not selection_input.addSelectionFilter("CustomGraphics"):
                raise RuntimeError("Fusion could not allow refine-marker selection.")
            if not selection_input.setSelectionLimits(1, 1):
                raise RuntimeError("Fusion could not limit pathway-end selection.")
            choice_input = command_inputs.addDropDownCommandInput(
                JUNCTION_RELATIONSHIP_CHOICE_INPUT_ID,
                "Matching Pathway End",
                adsk.core.DropDownStyles.TextListDropDownStyle,
            )
            if choice_input is None:
                raise RuntimeError("Fusion could not create the pathway-end choice.")
            choice_input.isVisible = False
            preselect_handler = _AddJunctionRelationshipPreSelectHandler(state)
            input_handler = _AddJunctionRelationshipInputChangedHandler(state)
            validate_handler = _AddJunctionRelationshipValidateInputsHandler(state)
            execute_handler = _AddJunctionRelationshipExecuteHandler(state)
            if not args.command.preSelect.add(preselect_handler):
                raise RuntimeError("Fusion could not filter pathway-end selection.")
            if not args.command.inputChanged.add(input_handler):
                raise RuntimeError("Fusion could not watch pathway-end selection.")
            if not args.command.validateInputs.add(validate_handler):
                raise RuntimeError("Fusion could not validate pathway-end selection.")
            if not args.command.execute.add(execute_handler):
                raise RuntimeError("Fusion could not save the junction relationship.")
            _handlers.extend((preselect_handler, input_handler, validate_handler, execute_handler))
        except (AttributeError, RuntimeError, TypeError, ValueError):
            _report_failure("open Add Junction Relationship")
            raise


class _EditEndExecuteHandler(adsk.core.CommandEventHandler):
    """
    Persist profiles selected for a connection-member edit.
    """

    def __init__(self, payload: dict[str, object]) -> None:
        """
        Retain the selected end and member identity for the native command.
        """
        super().__init__()
        self._payload = payload

    def notify(self, args: adsk.core.CommandEventArgs) -> None:
        """
        Apply the profile selection and refresh the palette after success.
        """
        try:
            application = adsk.core.Application.get()
            tokens = _read_pathway_gate_tokens(args.command.commandInputs)
            _apply_end_member_edit(application, self._payload, tokens)
            warning = _refresh_active_preview(
                application, _read_payload_uuid(self._payload, "harnessId", "harness")
            )
            application.activeViewport.refresh()
            _send_palette_state(application, f"Updated end members. {warning}".strip())
        except (AttributeError, RuntimeError, TypeError, ValueError):
            _report_failure("edit end members")


class _EditEndCreatedHandler(adsk.core.CommandCreatedEventHandler):
    """
    Open native profile selection for adding or replacing end members.
    """

    # noinspection PyMethodMayBeStatic
    def notify(self, args: adsk.core.CommandCreatedEventArgs) -> None:
        """
        Configure ordered profile selection and retain execution handlers.
        """
        global _pending_end_edit
        payload = _pending_end_edit
        _pending_end_edit = None
        if payload is None:
            raise RuntimeError("No end was selected.")
        selection = _add_profile_selection_input(
            args.command.commandInputs,
            PATHWAY_GATES_INPUT_ID,
            "Connection Profiles",
            "Select profiles for this end sequence",
        )
        if not selection.setSelectionLimits(1, 1 if payload.get("editAction") == "replace" else 0):
            raise RuntimeError("Fusion could not set end-member selection limits.")
        execute_handler = _EditEndExecuteHandler(payload)
        validate_handler = _AppendGatesValidateInputsHandler()
        if not args.command.execute.add(execute_handler):
            raise RuntimeError("Fusion could not register the end edit handler.")
        if not args.command.validateInputs.add(validate_handler):
            raise RuntimeError("Fusion could not register end edit validation.")
        _handlers.extend((execute_handler, validate_handler))


class _AppendGatesExecuteHandler(adsk.core.CommandEventHandler):
    """
    Append selected sketch profiles to an existing pathway.
    """

    def __init__(self, harness_id: UUID, pathway_id: UUID) -> None:
        """
        Bind the handler to the selected harness and pathway.
        """
        super().__init__()
        self._harness_id = harness_id
        self._pathway_id = pathway_id

    def notify(self, args: adsk.core.CommandEventArgs) -> None:
        """
        Persist the selected profiles at the end of the pathway.
        """
        try:
            application = adsk.core.Application.get()
            controls = append_pathway_gates(
                self._harness_id,
                self._pathway_id,
                _read_pathway_gate_tokens(args.command.commandInputs),
                _create_harness_gateway(application),
            )
            warning = _refresh_active_preview(application, self._harness_id)
            application.activeViewport.refresh()
            _send_palette_state(application, f"Added {len(controls)} gates. {warning}".strip())
        except (AttributeError, RuntimeError, TypeError, ValueError):
            _report_failure("add pathway gates")


class _AppendGatesCreatedHandler(adsk.core.CommandCreatedEventHandler):
    """
    Build the ordered gate-selection command for one existing pathway.
    """

    # noinspection PyMethodMayBeStatic
    def notify(self, args: adsk.core.CommandCreatedEventArgs) -> None:
        """
        Add gate selection input and retain its event handlers.
        """
        global _pending_append_gate_ids

        pending_ids = _pending_append_gate_ids
        _pending_append_gate_ids = None
        try:
            if pending_ids is None:
                raise RuntimeError("No pathway was selected for gate creation.")
            harness_id, pathway_id = pending_ids
            gate_input = args.command.commandInputs.addSelectionInput(
                PATHWAY_GATES_INPUT_ID,
                "Additional Gate Profiles",
                "Select additional sketch profiles in traversal order",
            )
            if gate_input is None:
                raise RuntimeError("Fusion did not create the gate selection input.")
            if not gate_input.addSelectionFilter("Profiles"):
                raise RuntimeError("Fusion did not apply the sketch-profile selection filter.")
            if not gate_input.setSelectionLimits(1, 0):
                raise RuntimeError("Fusion did not configure the gate selection limits.")

            execute_handler = _AppendGatesExecuteHandler(harness_id, pathway_id)
            validate_handler = _AppendGatesValidateInputsHandler()
            if not args.command.execute.add(execute_handler):
                raise RuntimeError("Fusion did not register the add-gates execution handler.")
            if not args.command.validateInputs.add(validate_handler):
                raise RuntimeError("Fusion did not register the add-gates validation handler.")
            _handlers.extend((execute_handler, validate_handler))
        except (AttributeError, RuntimeError, TypeError, ValueError):
            _report_failure("open Add Gates")
            raise


class _AppendGatesValidateInputsHandler(adsk.core.ValidateInputsEventHandler):
    """
    Require at least one selected gate profile.
    """

    # noinspection PyMethodMayBeStatic
    def notify(self, args: adsk.core.ValidateInputsEventArgs) -> None:
        """
        Validate gate selections before Fusion enables execution.
        """
        try:
            _read_pathway_gate_tokens(args.inputs)
        except ValueError:
            args.areInputsValid = False
            return
        args.areInputsValid = True


@dataclass(frozen=True)
class _SegmentCommandState:
    """
    Retain eligible resolved controls for one pathway-segmentation command.
    """

    harness_id: UUID
    pathway_id: UUID
    profile_controls: tuple[tuple[UUID, object], ...]
    refine_control_ids: frozenset[UUID]


class _SegmentPreSelectHandler(adsk.core.SelectionEventHandler):
    """
    Restrict segmentation selection to supported interior pathway controls.
    """

    def __init__(self, state: _SegmentCommandState) -> None:
        """
        Retain the resolved eligible controls.
        """
        super().__init__()
        self._state = state

    def notify(self, args: adsk.core.SelectionEventArgs) -> None:
        """
        Accept an eligible profile or persistent refine marker.
        """
        selection = args.selection
        entity = selection.entity if selection is not None else None
        args.isSelectable = _segment_entity_control_id(entity, self._state) is not None


class _SegmentValidateInputsHandler(adsk.core.ValidateInputsEventHandler):
    """
    Require a new pathway name and exactly one eligible control.
    """

    def __init__(self, state: _SegmentCommandState) -> None:
        """
        Retain the eligible command controls.
        """
        super().__init__()
        self._state = state

    def notify(self, args: adsk.core.ValidateInputsEventArgs) -> None:
        """
        Enable execution only for a complete segmentation request.
        """
        try:
            _read_segment_pathway_name(args.inputs)
            _read_segment_control_id(args.inputs, self._state)
        except (AttributeError, TypeError, ValueError):
            args.areInputsValid = False
            return
        args.areInputsValid = True


class _SegmentExecuteHandler(adsk.core.CommandEventHandler):
    """
    Persist one pathway split inside Fusion's command transaction.
    """

    def __init__(self, state: _SegmentCommandState) -> None:
        """
        Retain the selected harness and pathway identities.
        """
        super().__init__()
        self._state = state

    def notify(self, args: adsk.core.CommandEventArgs) -> None:
        """
        Segment the pathway and refresh logical and graphical projections.
        """
        application = adsk.core.Application.get()
        try:
            result = segment_pathway(
                self._state.harness_id,
                self._state.pathway_id,
                _read_segment_control_id(args.command.commandInputs, self._state),
                _read_segment_pathway_name(args.command.commandInputs),
                _create_harness_gateway(application),
            )
            warning = _refresh_active_preview(application, self._state.harness_id)
            _reconcile_active_refines(application)
            application.activeViewport.refresh()
            _send_palette_state(
                application,
                f"Created {result.following_pathway.name} and {result.junction.name}. "
                f"{warning}".strip(),
            )
        except (AttributeError, RuntimeError, TypeError, ValueError) as error:
            args.executeFailed = True
            args.executeFailedMessage = str(error)
            _log_to_fusion(f"Segment pathway failed: {error}\n{traceback.format_exc()}")


class _SegmentCreatedHandler(adsk.core.CommandCreatedEventHandler):
    """
    Build the native name-and-member pathway-segmentation command.
    """

    # noinspection PyMethodMayBeStatic
    def notify(self, args: adsk.core.CommandCreatedEventArgs) -> None:
        """
        Resolve eligible interior controls and attach command handlers.
        """
        global _pending_segment_ids
        pending_ids = _pending_segment_ids
        _pending_segment_ids = None
        try:
            if pending_ids is None:
                raise RuntimeError("No pathway was selected for segmentation.")
            harness_id, pathway_id = pending_ids
            application = adsk.core.Application.get()
            design = _require_active_design(application)
            gateway = _create_harness_gateway(application)
            definition = loads(gateway.read_harness_definition(harness_id))
            pathway = next(
                (item for item in definition.pathways if item.pathway_id == pathway_id),
                None,
            )
            if pathway is None:
                raise ValueError("Selected pathway no longer exists.")
            controls = {control.control_id: control for control in definition.controls}
            profile_controls: list[tuple[UUID, object]] = []
            refine_control_ids: set[UUID] = set()
            for control_id in pathway.ordered_control_ids[1:-1]:
                control = controls.get(control_id)
                if control is None:
                    continue
                if control.kind is ControlKind.REFINE:
                    refine_control_ids.add(control_id)
                elif control.kind is ControlKind.ROUTING_GATE:
                    entities = design.findEntityByToken(control.entity_token)
                    profile = adsk.fusion.Profile.cast(entities[0] if entities else None)
                    if profile is not None:
                        profile_controls.append((control_id, profile))
            if not profile_controls and not refine_control_ids:
                raise ValueError("This pathway has no supported interior control to segment.")

            command_inputs = args.command.commandInputs
            name_input = command_inputs.addStringValueInput(
                SEGMENT_PATHWAY_NAME_INPUT_ID,
                "New Pathway Name",
                suggest_pathway_extension_name(harness_id, pathway_id, gateway),
            )
            if name_input is None:
                raise RuntimeError("Fusion could not create the extension-name input.")
            selection_input = command_inputs.addSelectionInput(
                SEGMENT_CONTROL_INPUT_ID,
                "Junction Control",
                "Select an interior routing gate or refine point",
            )
            if selection_input is None:
                raise RuntimeError("Fusion could not create the junction-control input.")
            if not selection_input.addSelectionFilter("Profiles"):
                raise RuntimeError("Fusion could not allow routing-gate selection.")
            if not selection_input.addSelectionFilter("CustomGraphics"):
                raise RuntimeError("Fusion could not allow refine-point selection.")
            if not selection_input.setSelectionLimits(1, 1):
                raise RuntimeError("Fusion could not limit junction-control selection.")
            state = _SegmentCommandState(
                harness_id,
                pathway_id,
                tuple(profile_controls),
                frozenset(refine_control_ids),
            )
            preselect_handler = _SegmentPreSelectHandler(state)
            validate_handler = _SegmentValidateInputsHandler(state)
            execute_handler = _SegmentExecuteHandler(state)
            if not args.command.preSelect.add(preselect_handler):
                raise RuntimeError("Fusion could not filter pathway segmentation selection.")
            if not args.command.validateInputs.add(validate_handler):
                raise RuntimeError("Fusion could not validate pathway segmentation.")
            if not args.command.execute.add(execute_handler):
                raise RuntimeError("Fusion could not save pathway segmentation.")
            _handlers.extend((preselect_handler, validate_handler, execute_handler))
        except (AttributeError, RuntimeError, TypeError, ValueError):
            _report_failure("open Segment Pathway")
            raise


@dataclass
class _RefineCommandState:
    """
    Share the temporary spine and current placement across command handlers.
    """

    harness_id: UUID
    pathway_id: UUID
    spine: PathwaySpine
    group: adsk.fusion.CustomGraphicsGroup
    placement: Optional[RefinePlacement] = None
    candidate: Optional[adsk.fusion.CustomGraphicsLines] = None


class _RefinePreSelectHandler(adsk.core.SelectionEventHandler):
    """
    Restrict Custom Graphics selection to the command-owned pathway spine.
    """

    # noinspection PyMethodMayBeStatic
    def notify(self, args: adsk.core.SelectionEventArgs) -> None:
        """
        Reject persistent markers and unrelated selectable graphics.
        """
        selection = args.selection
        entity = selection.entity if selection is not None else None
        args.isSelectable = getattr(entity, "id", None) == REFINE_SPINE_ENTITY_ID


def _update_refine_placement(
    state: _RefineCommandState,
    command_inputs: adsk.core.CommandInputs,
    *,
    position_manipulator: bool = True,
) -> None:
    """
    Synchronize selection, radius input, and the transformable candidate marker.
    """
    radius_input = adsk.core.DistanceValueCommandInput.cast(
        command_inputs.itemById(REFINE_RADIUS_INPUT_ID)
    )
    if radius_input is None:
        raise RuntimeError("Refine radius input is unavailable.")
    try:
        placement = _read_refine_placement(command_inputs, state.spine)
    except ValueError:
        state.placement = None
        state.candidate = None
        radius_input.isEnabled = False
        radius_input.isVisible = False
        clear_candidate_refine(state.group)
        adsk.core.Application.get().activeViewport.refresh()
        return
    state.placement = placement
    radius_input.isEnabled = True
    radius_input.isVisible = True
    if position_manipulator:
        origin = placement.geometry.origin_mm
        direction = placement.geometry.u_direction
        if not radius_input.setManipulator(
            adsk.core.Point3D.create(*(coordinate / 10.0 for coordinate in origin)),
            adsk.core.Vector3D.create(*direction),
        ):
            raise RuntimeError("Fusion could not position the refine-radius manipulator.")
    if state.candidate is None or not state.candidate.isValid:
        state.candidate = draw_candidate_refine(state.group, placement.geometry)
    else:
        update_candidate_refine(state.candidate, placement.geometry)
    adsk.core.Application.get().activeViewport.refresh()


class _RefineInputChangedHandler(adsk.core.InputChangedEventHandler):
    """
    Project the selected Custom Graphics point and redraw its marker.
    """

    def __init__(self, state: _RefineCommandState) -> None:
        """
        Retain the command-local placement state.
        """
        super().__init__()
        self._state = state

    def notify(self, args: adsk.core.InputChangedEventArgs) -> None:
        """
        Update placement after either spine selection or marker-radius changes.
        """
        try:
            _update_refine_placement(self._state, args.inputs)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            _report_failure("place refine point")


class _RefineMouseDragHandler(adsk.core.MouseEventHandler):
    """
    Refresh the placement marker while Fusion's radius manipulator is dragged.
    """

    def __init__(
        self,
        state: _RefineCommandState,
        command_inputs: adsk.core.CommandInputs,
    ) -> None:
        """
        Retain placement state and its command inputs for drag notifications.
        """
        super().__init__()
        self._state = state
        self._command_inputs = command_inputs

    def notify(self, _args: adsk.core.MouseEventArgs) -> None:
        """
        Apply the manipulator's current value without repositioning it mid-drag.
        """
        try:
            _update_refine_placement(
                self._state,
                self._command_inputs,
                position_manipulator=False,
            )
        except (AttributeError, RuntimeError, TypeError, ValueError):
            _report_failure("preview refine radius")


class _RefineValidateInputsHandler(adsk.core.ValidateInputsEventHandler):
    """
    Enable execution only after a valid point is selected on the pathway spine.
    """

    def __init__(self, state: _RefineCommandState) -> None:
        """
        Retain the command-local placement state.
        """
        super().__init__()
        self._state = state

    def notify(self, args: adsk.core.ValidateInputsEventArgs) -> None:
        """
        Revalidate the selection and positive display radius.
        """
        try:
            self._state.placement = _read_refine_placement(args.inputs, self._state.spine)
        except (AttributeError, TypeError, ValueError):
            self._state.placement = None
        args.areInputsValid = self._state.placement is not None


class _RefineExecuteHandler(adsk.core.CommandEventHandler):
    """
    Persist one selected refine point inside the Fusion command transaction.
    """

    def __init__(self, state: _RefineCommandState) -> None:
        """
        Retain the command-local placement state.
        """
        super().__init__()
        self._state = state

    def notify(self, args: adsk.core.CommandEventArgs) -> None:
        """
        Insert the refine, synchronize occupied wires, and refresh the UI.
        """
        application = adsk.core.Application.get()
        try:
            placement = _read_refine_placement(args.command.commandInputs, self._state.spine)
            add_pathway_refine(
                self._state.harness_id,
                self._state.pathway_id,
                placement.insertion_index,
                placement.geometry,
                _create_harness_gateway(application),
            )
            warning = _refresh_active_preview(application, self._state.harness_id)
            _reconcile_active_refines(application)
            application.activeViewport.refresh()
            _send_palette_state(application, f"Added refine point. {warning}".strip())
        except (AttributeError, RuntimeError, TypeError, ValueError) as error:
            args.executeFailed = True
            args.executeFailedMessage = str(error)
            _log_to_fusion(f"Add refine point failed: {error}\n{traceback.format_exc()}")


class _RefineDestroyedHandler(adsk.core.CommandEventHandler):
    """
    Remove command-only graphics and release its short-lived handlers.
    """

    def __init__(self, handlers: list[object]) -> None:
        """
        Retain the handlers that must remain alive until destruction.
        """
        super().__init__()
        self._command_handlers = handlers

    def notify(self, _args: adsk.core.CommandEventArgs) -> None:
        """
        Clear the temporary spine for Save and Cancel alike.
        """
        application = adsk.core.Application.get()
        design = adsk.fusion.Design.cast(application.activeProduct)
        if design is not None:
            clear_refine_spine(design)
            application.activeViewport.refresh()
        for handler in (*self._command_handlers, self):
            if handler in _handlers:
                _handlers.remove(handler)


class _RefineCreatedHandler(adsk.core.CommandCreatedEventHandler):
    """
    Build a selectable pathway spine and radius input for refine placement.
    """

    # noinspection PyMethodMayBeStatic
    def notify(self, args: adsk.core.CommandCreatedEventArgs) -> None:
        """
        Resolve the selected pathway and attach command-lifetime handlers.
        """
        global _pending_refine_ids
        pending_ids = _pending_refine_ids
        _pending_refine_ids = None
        try:
            if pending_ids is None:
                raise RuntimeError("No pathway was selected for refine placement.")
            harness_id, pathway_id = pending_ids
            application = adsk.core.Application.get()
            design = _require_active_design(application)
            definition = loads(
                _create_harness_gateway(application).read_harness_definition(harness_id)
            )
            spine = build_pathway_spine(design, definition, pathway_id)
            group, _lines = draw_pathway_spine(design, spine)
            selection_input = args.command.commandInputs.addSelectionInput(
                REFINE_SPINE_INPUT_ID,
                "Pathway Point",
                "Select a point on the cyan pathway spine",
            )
            if selection_input is None or not selection_input.addSelectionFilter("CustomGraphics"):
                raise RuntimeError("Fusion could not configure refine-path selection.")
            if not selection_input.setSelectionLimits(1, 1):
                raise RuntimeError("Fusion could not limit refine-path selection.")
            radius_input = args.command.commandInputs.addDistanceValueCommandInput(
                REFINE_RADIUS_INPUT_ID,
                "Marker Radius",
                adsk.core.ValueInput.createByString(f"{DEFAULT_REFINE_RADIUS_MM:g} mm"),
            )
            if radius_input is None:
                raise RuntimeError("Fusion could not create the refine-radius input.")
            radius_input.isVisible = False
            radius_input.isEnabled = False
            state = _RefineCommandState(harness_id, pathway_id, spine, group)
            preselect_handler = _RefinePreSelectHandler()
            input_handler = _RefineInputChangedHandler(state)
            drag_handler = _RefineMouseDragHandler(state, args.command.commandInputs)
            validate_handler = _RefineValidateInputsHandler(state)
            execute_handler = _RefineExecuteHandler(state)
            command_handlers: list[object] = [
                preselect_handler,
                input_handler,
                drag_handler,
                validate_handler,
                execute_handler,
            ]
            destroyed = _RefineDestroyedHandler(command_handlers)
            if not args.command.preSelect.add(preselect_handler):
                raise RuntimeError("Fusion could not filter refine-path selection.")
            if not args.command.inputChanged.add(input_handler):
                raise RuntimeError("Fusion could not watch refine placement.")
            if not args.command.mouseDrag.add(drag_handler):
                raise RuntimeError("Fusion could not watch refine radius dragging.")
            if not args.command.validateInputs.add(validate_handler):
                raise RuntimeError("Fusion could not validate refine placement.")
            if not args.command.execute.add(execute_handler):
                raise RuntimeError("Fusion could not save refine placement.")
            if not args.command.destroy.add(destroyed):
                raise RuntimeError("Fusion could not register refine cleanup.")
            _handlers.extend((*command_handlers, destroyed))
            application.activeViewport.refresh()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            application = adsk.core.Application.get()
            design = adsk.fusion.Design.cast(application.activeProduct)
            if design is not None:
                clear_refine_spine(design)
            _report_failure("open Add Refine Point")
            raise


@dataclass
class _EditRefineCommandState:
    """
    Share the edited refine identity and temporary marker across handlers.
    """

    harness_id: UUID
    control_id: UUID
    group: adsk.fusion.CustomGraphicsGroup
    geometry: RefineGeometry


def _preview_edited_refine(
    state: _EditRefineCommandState,
    command_inputs: adsk.core.CommandInputs,
) -> None:
    """
    Apply current triad and radius values to the live editor marker.
    """
    geometry = _read_edited_refine_geometry(command_inputs)
    state.geometry = geometry
    update_refine_editor(state.group, geometry)
    adsk.core.Application.get().activeViewport.refresh()


class _EditRefineInputChangedHandler(adsk.core.InputChangedEventHandler):
    """
    Update the editor marker throughout graphical and typed manipulation.
    """

    def __init__(self, state: _EditRefineCommandState) -> None:
        """
        Retain the command-local edit state.
        """
        super().__init__()
        self._state = state

    def notify(self, args: adsk.core.InputChangedEventArgs) -> None:
        """
        Apply the changed command values directly to the existing marker.
        """
        try:
            _preview_edited_refine(self._state, args.inputs)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            _report_failure("preview edited refine point")


class _EditRefineExecutePreviewHandler(adsk.core.CommandEventHandler):
    """
    Redraw an edited refine in Fusion's command-preview transaction.
    """

    def __init__(self, state: _EditRefineCommandState) -> None:
        """
        Retain the command-local edit state.
        """
        super().__init__()
        self._state = state

    def notify(self, args: adsk.core.CommandEventArgs) -> None:
        """
        Reapply current geometry when Fusion requests a command preview.
        """
        try:
            _preview_edited_refine(self._state, args.command.commandInputs)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            _report_failure("preview edited refine point")


class _EditRefineValidateInputsHandler(adsk.core.ValidateInputsEventHandler):
    """
    Require a valid rigid transform and positive marker radius.
    """

    # noinspection PyMethodMayBeStatic
    def notify(self, args: adsk.core.ValidateInputsEventArgs) -> None:
        """
        Disable execution while either edit input is invalid.
        """
        try:
            _read_edited_refine_geometry(args.inputs)
        except (AttributeError, TypeError, ValueError):
            args.areInputsValid = False
            return
        args.areInputsValid = True


class _EditRefineExecuteHandler(adsk.core.CommandEventHandler):
    """
    Persist an edited refine inside the Fusion command transaction.
    """

    def __init__(self, state: _EditRefineCommandState) -> None:
        """
        Retain the selected harness and refine identities.
        """
        super().__init__()
        self._state = state

    def notify(self, args: adsk.core.CommandEventArgs) -> None:
        """
        Save the final transform and radius, then refresh affected routes.
        """
        application = adsk.core.Application.get()
        try:
            geometry = _read_edited_refine_geometry(args.command.commandInputs)
            update_pathway_refine(
                self._state.harness_id,
                self._state.control_id,
                geometry,
                _create_harness_gateway(application),
            )
            warning = _refresh_active_preview(application, self._state.harness_id)
            _send_palette_state(application, f"Updated refine point. {warning}".strip())
        except (AttributeError, RuntimeError, TypeError, ValueError) as error:
            args.executeFailed = True
            args.executeFailedMessage = str(error)
            _log_to_fusion(f"Edit refine point failed: {error}\n{traceback.format_exc()}")


class _EditRefineDestroyedHandler(adsk.core.CommandEventHandler):
    """
    Restore persistent refine graphics after Save or Cancel.
    """

    def __init__(self, handlers: list[object]) -> None:
        """
        Retain the command handlers until destruction.
        """
        super().__init__()
        self._command_handlers = handlers

    def notify(self, _args: adsk.core.CommandEventArgs) -> None:
        """
        Remove the editor marker and redraw all saved refine geometry.
        """
        application = adsk.core.Application.get()
        design = adsk.fusion.Design.cast(application.activeProduct)
        if design is not None:
            clear_refine_spine(design)
            _reconcile_active_refines(application)
            application.activeViewport.refresh()
        for handler in (*self._command_handlers, self):
            if handler in _handlers:
                _handlers.remove(handler)


class _EditRefineCreatedHandler(adsk.core.CommandCreatedEventHandler):
    """
    Build a triad editor for one already-persisted refine marker.
    """

    # noinspection PyMethodMayBeStatic
    def notify(self, args: adsk.core.CommandCreatedEventArgs) -> None:
        """
        Resolve the refine and attach live redraw, validation, and persistence.
        """
        global _pending_refine_edit_ids
        pending_ids = _pending_refine_edit_ids
        _pending_refine_edit_ids = None
        try:
            if pending_ids is None:
                raise RuntimeError("No refine point was selected for editing.")
            harness_id, control_id = pending_ids
            application = adsk.core.Application.get()
            design = _require_active_design(application)
            definition = loads(
                _create_harness_gateway(application).read_harness_definition(harness_id)
            )
            control = next(
                (item for item in definition.controls if item.control_id == control_id),
                None,
            )
            if (
                control is None
                or control.kind is not ControlKind.REFINE
                or control.refine_geometry is None
            ):
                raise ValueError("Selected refine point no longer exists.")
            geometry = control.refine_geometry
            group = draw_refine_editor(design, geometry)
            triad = _add_refine_transform_input(args.command.commandInputs, geometry)
            triad.hideAllScaling()
            triad.setTranslateVisibility(True)
            triad.setPlanarMoveVisibility(True)
            triad.setRotateVisibility(True)
            triad.isOriginTranslationVisible = True
            triad.isVisible = True
            radius = args.command.commandInputs.addDistanceValueCommandInput(
                REFINE_RADIUS_INPUT_ID,
                "Marker Radius",
                adsk.core.ValueInput.createByString(f"{geometry.display_radius_mm:g} mm"),
            )
            if radius is None:
                raise RuntimeError("Fusion could not create the refine-radius input.")
            state = _EditRefineCommandState(harness_id, control_id, group, geometry)
            input_handler = _EditRefineInputChangedHandler(state)
            preview_handler = _EditRefineExecutePreviewHandler(state)
            validate_handler = _EditRefineValidateInputsHandler()
            execute_handler = _EditRefineExecuteHandler(state)
            command_handlers: list[object] = [
                input_handler,
                preview_handler,
                validate_handler,
                execute_handler,
            ]
            destroyed = _EditRefineDestroyedHandler(command_handlers)
            if not args.command.inputChanged.add(input_handler):
                raise RuntimeError("Fusion could not watch refine edits.")
            if not args.command.executePreview.add(preview_handler):
                raise RuntimeError("Fusion could not preview refine edits.")
            if not args.command.validateInputs.add(validate_handler):
                raise RuntimeError("Fusion could not validate refine edits.")
            if not args.command.execute.add(execute_handler):
                raise RuntimeError("Fusion could not save refine edits.")
            if not args.command.destroy.add(destroyed):
                raise RuntimeError("Fusion could not register refine edit cleanup.")
            _handlers.extend((*command_handlers, destroyed))
            application.activeViewport.refresh()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            application = adsk.core.Application.get()
            design = adsk.fusion.Design.cast(application.activeProduct)
            if design is not None:
                clear_refine_spine(design)
                _reconcile_active_refines(application)
            _report_failure("open Edit Refine Point")
            raise


class _RefineActiveSelectionHandler(adsk.core.ActiveSelectionEventHandler):
    """
    Open the transform editor when a persistent refine marker is selected.
    """

    # noinspection PyMethodMayBeStatic
    def notify(self, args: adsk.core.ActiveSelectionEventArgs) -> None:
        """
        Resolve one selected marker by its graphics-group and control identities.
        """
        try:
            selections = args.currentSelection
            if len(selections) != 1:
                return
            entity = selections[0].entity
            parent = getattr(entity, "parent", None)
            if getattr(parent, "id", None) != REFINE_GRAPHICS_GROUP_ID:
                return
            control_id = UUID(entity.id)
            application = adsk.core.Application.get()
            results = load_harnesses(_create_harness_gateway(application))
            match = None
            for result in results:
                definition = result.definition
                if definition is None:
                    continue
                if any(
                    control.control_id == control_id and control.kind is ControlKind.REFINE
                    for control in definition.controls
                ):
                    match = (definition.harness_id, control_id)
                    break
            if match is None:
                return
            application.userInterface.activeSelections.clear()
            _open_refine_edit_command(application, *match)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            _report_failure("select refine point")


class _AddWiresExecuteHandler(adsk.core.CommandEventHandler):
    """
    Persist ordered End A-to-End B wire assignments.
    """

    def __init__(self, harness_id: UUID, pathway_ids_by_name: dict[str, UUID]) -> None:
        """
        Bind the handler to one harness and its displayed pathway choices.
        """
        super().__init__()
        self._harness_id = harness_id
        self._pathway_ids_by_name = pathway_ids_by_name

    def notify(self, args: adsk.core.CommandEventArgs) -> None:
        """
        Pair endpoint selections in order and add their logical wire mappings.
        """
        try:
            application = adsk.core.Application.get()
            command_inputs = args.command.commandInputs
            result = add_wire_batch(
                self._harness_id,
                _read_wire_pathway_id(command_inputs, self._pathway_ids_by_name),
                _read_profile_tokens(command_inputs, SOURCE_CONNECTIONS_INPUT_ID, "End A"),
                _read_profile_tokens(
                    command_inputs,
                    DESTINATION_CONNECTIONS_INPUT_ID,
                    "End B",
                ),
                _read_wire_diameter_mm(command_inputs),
                _create_harness_gateway(application),
            )
            warning = _refresh_active_preview(application, self._harness_id)
            application.activeViewport.refresh()
            _send_palette_state(
                application, f"Created {len(result.wires)} wires. {warning}".strip()
            )
        except (AttributeError, RuntimeError, TypeError, ValueError):
            _report_failure("add wires")


class _AddWiresValidateInputsHandler(adsk.core.ValidateInputsEventHandler):
    """
    Require a pathway, valid diameter, and equally sized endpoint selections.
    """

    def __init__(self, pathway_ids_by_name: dict[str, UUID]) -> None:
        """
        Retain the displayed pathway choices for identity validation.
        """
        super().__init__()
        self._pathway_ids_by_name = pathway_ids_by_name

    def notify(self, args: adsk.core.ValidateInputsEventArgs) -> None:
        """
        Validate the complete wire batch before Fusion enables execution.
        """
        try:
            _read_wire_pathway_id(args.inputs, self._pathway_ids_by_name)
            _read_wire_diameter_mm(args.inputs)
            end_a_profiles = _read_profile_tokens(
                args.inputs,
                SOURCE_CONNECTIONS_INPUT_ID,
                "End A",
            )
            end_b_profiles = _read_profile_tokens(
                args.inputs,
                DESTINATION_CONNECTIONS_INPUT_ID,
                "End B",
            )
            if len(end_a_profiles) != len(end_b_profiles):
                raise ValueError("End A and End B profile counts must match.")
        except ValueError:
            args.areInputsValid = False
            return
        args.areInputsValid = True


class _AddWiresCreatedHandler(adsk.core.CommandCreatedEventHandler):
    """
    Build the native ordered endpoint-selection command.
    """

    # noinspection PyMethodMayBeStatic
    def notify(self, args: adsk.core.CommandCreatedEventArgs) -> None:
        """
        Add wire inputs and retain their event handlers.
        """
        global _pending_wire_harness_id, _pending_wire_pathway_id

        harness_id = _pending_wire_harness_id
        selected_pathway_id = _pending_wire_pathway_id
        _pending_wire_harness_id = None
        _pending_wire_pathway_id = None
        try:
            if harness_id is None:
                raise RuntimeError("No harness was selected for wire assignment.")
            application = adsk.core.Application.get()
            gateway = _create_harness_gateway(application)
            definition = loads(gateway.read_harness_definition(harness_id))
            if not definition.pathways:
                raise RuntimeError("Create a pathway before adding wires.")
            if selected_pathway_id is not None and all(
                pathway.pathway_id != selected_pathway_id for pathway in definition.pathways
            ):
                raise RuntimeError("The selected pathway is no longer available.")
            pathway_ids_by_name = {
                pathway.name: pathway.pathway_id for pathway in definition.pathways
            }
            command_inputs = args.command.commandInputs

            pathway_input = command_inputs.addDropDownCommandInput(
                WIRE_PATHWAY_INPUT_ID,
                "Pathway",
                adsk.core.DropDownStyles.TextListDropDownStyle,
            )
            if pathway_input is None:
                raise RuntimeError("Fusion did not create the wire pathway input.")
            for index, pathway in enumerate(definition.pathways):
                is_selected = (
                    pathway.pathway_id == selected_pathway_id
                    if selected_pathway_id is not None
                    else index == 0
                )
                if pathway_input.listItems.add(pathway.name, is_selected) is None:
                    raise RuntimeError(f"Fusion did not add the pathway option: {pathway.name}")

            diameter_value = adsk.core.ValueInput.createByString("1.5 mm")
            diameter_input = command_inputs.addValueInput(
                WIRE_DIAMETER_INPUT_ID,
                "Wire Diameter",
                "mm",
                diameter_value,
            )
            if diameter_input is None:
                raise RuntimeError("Fusion did not create the wire diameter input.")

            end_a_input = _add_profile_selection_input(
                command_inputs,
                SOURCE_CONNECTIONS_INPUT_ID,
                "Ordered End A Profiles",
                "Select each End A profile in wire order",
            )
            end_b_input = _add_profile_selection_input(
                command_inputs,
                DESTINATION_CONNECTIONS_INPUT_ID,
                "Ordered End B Profiles",
                "Select matching End B profiles in the same order",
            )
            end_a_input.hasFocus = True
            end_b_input.hasFocus = False

            execute_handler = _AddWiresExecuteHandler(harness_id, pathway_ids_by_name)
            validate_handler = _AddWiresValidateInputsHandler(pathway_ids_by_name)
            if not args.command.execute.add(execute_handler):
                raise RuntimeError("Fusion did not register the wire execution handler.")
            if not args.command.validateInputs.add(validate_handler):
                raise RuntimeError("Fusion did not register the wire validation handler.")
            _handlers.extend((execute_handler, validate_handler))
        except (AttributeError, RuntimeError, TypeError, ValueError):
            _report_failure("open Add Wires")
            raise


class _ShowPaletteCreatedHandler(adsk.core.CommandCreatedEventHandler):
    """
    Show the persistent palette when Fusion creates the launcher command.
    """

    # noinspection PyMethodMayBeStatic
    def notify(self, _args: adsk.core.CommandCreatedEventArgs) -> None:
        """
        Create or reveal the palette immediately for this input-free command.
        """
        try:
            application = adsk.core.Application.get()
            _show_palette(application)
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
            _report_failure("open Harness Builder")
            raise


class _PaletteIncomingHandler(adsk.core.HTMLEventHandler):
    """
    Handle requests sent by the local Harness Builder palette.
    """

    # noinspection PyMethodMayBeStatic
    def notify(self, args: adsk.core.HTMLEventArgs) -> None:
        """
        Return current harness state or open the native creation dialog.
        """
        global _last_diagram_qa_observation

        html_args = None
        try:
            html_args = adsk.core.HTMLEventArgs.cast(args)
            if html_args is None:
                raise TypeError("Fusion did not provide valid palette event arguments.")
            application = adsk.core.Application.get()
            if html_args.action == "get_state":
                html_args.returnData = _serialize_palette_state(application)
                return
            if html_args.action == "get_appearance_libraries":
                html_args.returnData = json.dumps(
                    {"ok": True, "libraries": _appearance_libraries_payload(application)},
                    sort_keys=True,
                )
                return
            if html_args.action == "get_library_appearances":
                payload = _read_palette_payload(html_args.data)
                library_id = payload.get("libraryId")
                if not isinstance(library_id, str) or not library_id.strip():
                    raise ValueError("Appearance-library request requires a library ID.")
                html_args.returnData = json.dumps(
                    {
                        "ok": True,
                        "appearances": _library_appearances_payload(application, library_id),
                    },
                    sort_keys=True,
                )
                return
            if html_args.action == "create_harness":
                command_definition = application.userInterface.commandDefinitions.itemById(
                    CREATE_COMMAND_ID
                )
                if command_definition is None or not command_definition.execute():
                    raise RuntimeError("Fusion did not open the Create Harness command.")
                html_args.returnData = json.dumps({"ok": True})
                return
            if html_args.action == "add_pathway":
                _open_add_pathway_command(application, html_args.data)
                html_args.returnData = json.dumps({"ok": True})
                return
            if html_args.action == "add_junction":
                _open_add_junction_command(application, html_args.data)
                html_args.returnData = json.dumps({"ok": True})
                return
            if html_args.action == "add_junction_relationship":
                _open_add_junction_relationship_command(application, html_args.data)
                html_args.returnData = json.dumps({"ok": True})
                return
            if html_args.action == "edit_end_members":
                _open_end_member_edit(application, html_args.data)
                html_args.returnData = json.dumps({"ok": True})
                return
            if html_args.action == "append_pathway_gates":
                _open_append_gates_command(application, html_args.data)
                html_args.returnData = json.dumps({"ok": True})
                return
            if html_args.action == "add_pathway_refine":
                _open_refine_command(application, html_args.data)
                html_args.returnData = json.dumps({"ok": True})
                return
            if html_args.action == "segment_pathway":
                _open_segment_command(application, html_args.data)
                html_args.returnData = json.dumps({"ok": True})
                return
            if html_args.action == "edit_pathway_refine":
                payload = _read_palette_payload(html_args.data)
                _open_refine_edit_command(
                    application,
                    _read_payload_uuid(payload, "harnessId", "harness"),
                    _read_payload_uuid(payload, "controlId", "refine point"),
                )
                html_args.returnData = json.dumps({"ok": True})
                return
            if html_args.action == "add_wires":
                _open_add_wires_command(application, html_args.data)
                html_args.returnData = json.dumps({"ok": True})
                return
            if html_args.action == "clear_preview":
                count = _clear_preview(application)
                label = "group" if count == 1 else "groups"
                html_args.returnData = json.dumps(
                    {
                        "ok": True,
                        "notice": f"Cleared {count} route-preview graphics {label}.",
                    }
                )
                return
            if html_args.action in _PALETTE_EDIT_NAMES:
                _open_palette_edit(application, html_args.action, html_args.data)
                html_args.returnData = json.dumps({"ok": True})
                return
            if html_args.action == "highlight_member":
                try:
                    count = _highlight_member(application, html_args.data)
                except (RuntimeError, TypeError, ValueError) as error:
                    html_args.returnData = json.dumps({"ok": False, "error": str(error)})
                    _log_to_fusion(f"Harness highlight rejected: {error}")
                    return
                html_args.returnData = json.dumps({"ok": True, "selectionCount": count})
                return
            if html_args.action == "clear_preview_highlight":
                highlight_route_preview(_require_active_design(application), None)
                application.activeViewport.refresh()
                html_args.returnData = json.dumps({"ok": True})
                return
            if html_args.action == "clear_highlight":
                _clear_highlight(application)
                html_args.returnData = json.dumps({"ok": True})
                return
            if html_args.action == "qa_diagram_observation":
                payload = _read_palette_payload(html_args.data)
                status = payload.get("status")
                connector_count = payload.get("connectorCount")
                maximum_gap = payload.get("maximumEndpointGap")
                contract_version = payload.get("contractVersion")
                layout = payload.get("layout")
                if status not in {"passed", "failed", "skipped"}:
                    raise ValueError("Diagram QA observation has an invalid status.")
                if (
                    isinstance(connector_count, bool)
                    or not isinstance(connector_count, int)
                    or connector_count < 0
                ):
                    raise ValueError("Diagram QA connector count must be nonnegative.")
                if (
                    isinstance(maximum_gap, bool)
                    or not isinstance(maximum_gap, (int, float))
                    or not math.isfinite(float(maximum_gap))
                    or float(maximum_gap) < 0
                ):
                    raise ValueError("Diagram QA endpoint gap must be finite and nonnegative.")
                if contract_version != "2":
                    raise ValueError("Diagram QA contract version is unsupported.")
                if layout != "endpoint-junction-forest":
                    raise ValueError("Diagram QA layout is unsupported.")
                _last_diagram_qa_observation = {
                    "status": status,
                    "connectorCount": connector_count,
                    "maximumEndpointGap": float(maximum_gap),
                    "contractVersion": contract_version,
                    "layout": layout,
                }
                html_args.returnData = json.dumps({"ok": True})
                return
            html_args.returnData = json.dumps(
                {"ok": False, "error": f"Unsupported palette action: {html_args.action}"}
            )
        except (AttributeError, RuntimeError, TypeError, ValueError):
            if html_args is not None:
                html_args.returnData = json.dumps(
                    {"ok": False, "error": "Harness Builder could not complete the request."}
                )
            _report_failure("handle Harness Builder palette request")


class _PaletteNavigationHandler(adsk.core.NavigationEventHandler):
    """
    Record palette navigation in Fusion's application log.
    """

    # noinspection PyMethodMayBeStatic
    def notify(self, args: adsk.core.NavigationEventArgs) -> None:
        """
        Log the URL Fusion's embedded browser attempts to load.
        """
        try:
            navigation_args = adsk.core.NavigationEventArgs.cast(args)
            if navigation_args is None:
                raise TypeError("Fusion did not provide valid palette navigation arguments.")
            _log_to_fusion(f"Harness Builder navigating to: {navigation_args.navigationURL}")
        except (AttributeError, RuntimeError, TypeError, ValueError):
            _report_failure("record Harness Builder palette navigation")


def start(_context: object) -> None:
    """
    Register the Harness Builder command with Fusion.
    """
    global _active_selection_handler, _history_handler
    try:
        application = adsk.core.Application.get()
        user_interface = application.userInterface
        _remove_user_interface(user_interface)
        for action, name in _PALETTE_EDIT_NAMES.items():
            edit_definition = user_interface.commandDefinitions.addButtonDefinition(
                f"{COMMAND_ID}_{action}", name, name, COMMAND_RESOURCE_FOLDER
            )
            created = _PaletteEditCreatedHandler()
            if edit_definition is None or not edit_definition.commandCreated.add(created):
                raise RuntimeError(f"Fusion could not register {name}.")
            _handlers.append(created)
        _history_handler = _HistoryChangedHandler()
        if not user_interface.commandTerminated.add(_history_handler):
            raise RuntimeError("Fusion could not register history synchronization.")
        _active_selection_handler = _RefineActiveSelectionHandler()
        if not user_interface.activeSelectionChanged.add(_active_selection_handler):
            raise RuntimeError("Fusion could not register refine selection editing.")
        _register_document_handlers(application)

        workspace = user_interface.workspaces.itemById(WORKSPACE_ID)
        if workspace is None:
            raise RuntimeError(f"Fusion workspace is unavailable: {WORKSPACE_ID}")

        command_definition = user_interface.commandDefinitions.addButtonDefinition(
            COMMAND_ID,
            COMMAND_NAME,
            COMMAND_DESCRIPTION,
            COMMAND_RESOURCE_FOLDER,
        )
        if command_definition is None:
            raise RuntimeError("Fusion did not create the Harness Builder command definition.")
        created_handler = _ShowPaletteCreatedHandler()
        if not command_definition.commandCreated.add(created_handler):
            raise RuntimeError("Fusion did not register the command-created handler.")
        _handlers.append(created_handler)

        create_command_definition = user_interface.commandDefinitions.addButtonDefinition(
            CREATE_COMMAND_ID,
            CREATE_COMMAND_NAME,
            "Create an empty procedural harness definition.",
            COMMAND_RESOURCE_FOLDER,
        )
        if create_command_definition is None:
            raise RuntimeError("Fusion did not create the Create Harness command definition.")
        create_handler = _CreateHarnessCreatedHandler()
        if not create_command_definition.commandCreated.add(create_handler):
            raise RuntimeError("Fusion did not register the harness creation handler.")
        _handlers.append(create_handler)

        pathway_command_definition = user_interface.commandDefinitions.addButtonDefinition(
            ADD_PATHWAY_COMMAND_ID,
            ADD_PATHWAY_COMMAND_NAME,
            "Create a reusable pathway from ordered sketch profiles.",
            ADD_PATHWAY_RESOURCE_FOLDER,
        )
        if pathway_command_definition is None:
            raise RuntimeError("Fusion did not create the Add Pathway command definition.")
        pathway_handler = _AddPathwayCreatedHandler()
        if not pathway_command_definition.commandCreated.add(pathway_handler):
            raise RuntimeError("Fusion did not register the pathway creation handler.")
        _handlers.append(pathway_handler)

        junction_command_definition = user_interface.commandDefinitions.addButtonDefinition(
            ADD_JUNCTION_COMMAND_ID,
            ADD_JUNCTION_COMMAND_NAME,
            "Create an unconnected junction from an unused sketch profile.",
            ADD_PATHWAY_RESOURCE_FOLDER,
        )
        if junction_command_definition is None:
            raise RuntimeError("Fusion did not create the Add Junction command definition.")
        junction_handler = _AddJunctionCreatedHandler()
        if not junction_command_definition.commandCreated.add(junction_handler):
            raise RuntimeError("Fusion did not register the junction creation handler.")
        _handlers.append(junction_handler)

        relationship_command_definition = user_interface.commandDefinitions.addButtonDefinition(
            ADD_JUNCTION_RELATIONSHIP_COMMAND_ID,
            ADD_JUNCTION_RELATIONSHIP_COMMAND_NAME,
            "Attach a junction to selected pathway-ending geometry.",
            ADD_PATHWAY_RESOURCE_FOLDER,
        )
        if relationship_command_definition is None:
            raise RuntimeError("Fusion did not create the relationship command definition.")
        relationship_handler = _AddJunctionRelationshipCreatedHandler()
        if not relationship_command_definition.commandCreated.add(relationship_handler):
            raise RuntimeError("Fusion did not register the relationship creation handler.")
        _handlers.append(relationship_handler)

        append_gates_definition = user_interface.commandDefinitions.addButtonDefinition(
            APPEND_GATES_COMMAND_ID,
            APPEND_GATES_COMMAND_NAME,
            "Append ordered sketch profiles to an existing pathway.",
            ADD_PATHWAY_RESOURCE_FOLDER,
        )
        if append_gates_definition is None:
            raise RuntimeError("Fusion did not create the Add Gates command definition.")
        append_gates_handler = _AppendGatesCreatedHandler()
        if not append_gates_definition.commandCreated.add(append_gates_handler):
            raise RuntimeError("Fusion did not register the Add Gates command handler.")
        _handlers.append(append_gates_handler)

        refine_definition = user_interface.commandDefinitions.addButtonDefinition(
            ADD_REFINE_COMMAND_ID,
            ADD_REFINE_COMMAND_NAME,
            "Insert an unconstrained routing point on a pathway spine.",
            ADD_PATHWAY_RESOURCE_FOLDER,
        )
        if refine_definition is None:
            raise RuntimeError("Fusion did not create the Add Refine Point command definition.")
        refine_handler = _RefineCreatedHandler()
        if not refine_definition.commandCreated.add(refine_handler):
            raise RuntimeError("Fusion did not register the Add Refine Point command handler.")
        _handlers.append(refine_handler)

        segment_definition = user_interface.commandDefinitions.addButtonDefinition(
            SEGMENT_PATHWAY_COMMAND_ID,
            SEGMENT_PATHWAY_COMMAND_NAME,
            "Split a pathway at an interior routing control.",
            ADD_PATHWAY_RESOURCE_FOLDER,
        )
        if segment_definition is None:
            raise RuntimeError("Fusion did not create the Segment Pathway command definition.")
        segment_handler = _SegmentCreatedHandler()
        if not segment_definition.commandCreated.add(segment_handler):
            raise RuntimeError("Fusion did not register the Segment Pathway command handler.")
        _handlers.append(segment_handler)

        edit_refine_definition = user_interface.commandDefinitions.addButtonDefinition(
            EDIT_REFINE_COMMAND_ID,
            EDIT_REFINE_COMMAND_NAME,
            "Move, rotate, or resize an existing refine point.",
            ADD_PATHWAY_RESOURCE_FOLDER,
        )
        if edit_refine_definition is None:
            raise RuntimeError("Fusion did not create the Edit Refine Point command definition.")
        edit_refine_handler = _EditRefineCreatedHandler()
        if not edit_refine_definition.commandCreated.add(edit_refine_handler):
            raise RuntimeError("Fusion did not register the Edit Refine Point command handler.")
        _handlers.append(edit_refine_handler)

        end_definition = user_interface.commandDefinitions.addButtonDefinition(
            EDIT_END_COMMAND_ID,
            "Edit End Members",
            "Add or replace connection profiles.",
            ADD_WIRES_RESOURCE_FOLDER,
        )
        if end_definition is None:
            raise RuntimeError("Fusion could not create the end-member command.")
        end_handler = _EditEndCreatedHandler()
        if not end_definition.commandCreated.add(end_handler):
            raise RuntimeError("Fusion could not register the end-member command.")
        _handlers.append(end_handler)

        wire_command_definition = user_interface.commandDefinitions.addButtonDefinition(
            ADD_WIRES_COMMAND_ID,
            ADD_WIRES_COMMAND_NAME,
            "Assign ordered End A and End B profiles to an existing pathway.",
            ADD_WIRES_RESOURCE_FOLDER,
        )
        if wire_command_definition is None:
            raise RuntimeError("Fusion did not create the Add Wires command definition.")
        wire_handler = _AddWiresCreatedHandler()
        if not wire_command_definition.commandCreated.add(wire_handler):
            raise RuntimeError("Fusion did not register the wire creation handler.")
        _handlers.append(wire_handler)

        registered_panel_ids: list[str] = []
        for panel_id in PANEL_IDS:
            panel = workspace.toolbarPanels.itemById(panel_id)
            if panel is None:
                continue
            control = panel.controls.addCommand(command_definition)
            if control is None:
                raise RuntimeError(f"Fusion did not add Harness Builder to panel: {panel_id}")
            control.isPromotedByDefault = True
            control.isPromoted = True
            registered_panel_ids.append(panel_id)
        if not registered_panel_ids:
            raise RuntimeError(f"Fusion toolbar panels are unavailable: {', '.join(PANEL_IDS)}")
        design = adsk.fusion.Design.cast(application.activeProduct)
        if design is not None:
            _reconcile_active_refines(application)
    except Exception:
        _report_failure("start")
        raise


def stop(_context: object) -> None:
    """
    Remove the command and release retained Fusion event handlers.
    """
    global _pending_append_gate_ids, _pending_refine_ids, _pending_pathway_harness_id
    global _pending_junction_harness_id
    global _pending_segment_ids
    global _pending_refine_edit_ids
    global _pending_end_edit
    global _pending_wire_harness_id, _pending_wire_pathway_id, _pending_palette_edit

    try:
        application = adsk.core.Application.get()
        design = adsk.fusion.Design.cast(application.activeProduct)
        if design is not None:
            clear_route_previews(design)
            clear_refine_spine(design)
            clear_refine_graphics(design)
        _remove_document_handlers(application)
        _remove_user_interface(application.userInterface)
        _handlers.clear()
        reset_preview_history()
        _pending_palette_edit = None
        _pending_append_gate_ids = None
        _pending_refine_ids = None
        _pending_segment_ids = None
        _pending_refine_edit_ids = None
        _pending_end_edit = None
        _pending_pathway_harness_id = None
        _pending_junction_harness_id = None
        _pending_wire_harness_id = None
        _pending_wire_pathway_id = None
        _damaged_harness_results.clear()
    except Exception:
        _report_failure("stop")
        raise


def _remove_user_interface(user_interface: adsk.core.UserInterface) -> None:
    """
    Remove stale command controls and definitions if they exist.
    """
    global _active_selection_handler, _history_handler
    if _history_handler is not None:
        user_interface.commandTerminated.remove(_history_handler)
        _history_handler = None
    if _active_selection_handler is not None:
        user_interface.activeSelectionChanged.remove(_active_selection_handler)
        _active_selection_handler = None
    workspace = user_interface.workspaces.itemById(WORKSPACE_ID)
    if workspace is not None:
        for panel_id in PANEL_IDS:
            panel = workspace.toolbarPanels.itemById(panel_id)
            if panel is not None:
                control = panel.controls.itemById(COMMAND_ID)
                if control is not None:
                    control.deleteMe()

    for command_id in (
        *(f"{COMMAND_ID}_{action}" for action in _PALETTE_EDIT_NAMES),
        COMMAND_ID,
        CREATE_COMMAND_ID,
        ADD_PATHWAY_COMMAND_ID,
        ADD_JUNCTION_COMMAND_ID,
        ADD_JUNCTION_RELATIONSHIP_COMMAND_ID,
        APPEND_GATES_COMMAND_ID,
        ADD_REFINE_COMMAND_ID,
        SEGMENT_PATHWAY_COMMAND_ID,
        EDIT_REFINE_COMMAND_ID,
        EDIT_END_COMMAND_ID,
        ADD_WIRES_COMMAND_ID,
    ):
        command_definition = user_interface.commandDefinitions.itemById(command_id)
        if command_definition:
            command_definition.deleteMe()
    palette = user_interface.palettes.itemById(PALETTE_ID)
    if palette:
        palette.deleteMe()


def _show_palette(application: adsk.core.Application) -> None:
    """
    Create or reveal the persistent Harness Builder palette.
    """
    user_interface = application.userInterface
    palette = user_interface.palettes.itemById(PALETTE_ID)
    if palette is None:
        missing_resources = [path for path in PALETTE_RESOURCE_FILES if not path.is_file()]
        if missing_resources:
            missing_list = ", ".join(str(path) for path in missing_resources)
            raise RuntimeError(f"Harness Builder palette resources are missing: {missing_list}")
        palette = user_interface.palettes.add(
            PALETTE_ID,
            COMMAND_NAME,
            PALETTE_HTML_URL,
            False,
            True,
            True,
            PALETTE_INITIAL_WIDTH,
            PALETTE_INITIAL_HEIGHT,
            True,
        )
        if palette is None:
            raise RuntimeError("Fusion did not create the Harness Builder palette.")
        incoming_handler = _PaletteIncomingHandler()
        if not palette.incomingFromHTML.add(incoming_handler):
            palette.deleteMe()
            raise RuntimeError("Fusion did not register the palette event handler.")
        navigation_handler = _PaletteNavigationHandler()
        if not palette.navigatingURL.add(navigation_handler):
            palette.deleteMe()
            raise RuntimeError("Fusion did not register the palette navigation handler.")
        _handlers.extend((incoming_handler, navigation_handler))
        _log_to_fusion(f"Harness Builder requested palette file: {palette.htmlFileURL}")
    try:
        palette.dockingOption = adsk.core.PaletteDockingOptions.PaletteDockOptionsToVerticalOnly
        palette.dockingState = adsk.core.PaletteDockingStates.PaletteDockStateRight
    except (AttributeError, RuntimeError) as error:
        _log_to_fusion(f"Harness Builder could not restore right docking: {error}")
    palette.isVisible = True
    _send_palette_state(application)


def _read_refine_placement(
    command_inputs: adsk.core.CommandInputs,
    spine: PathwaySpine,
) -> RefinePlacement:
    """
    Read a selected spine point and marker radius in millimeters.
    """
    selection_input = adsk.core.SelectionCommandInput.cast(
        command_inputs.itemById(REFINE_SPINE_INPUT_ID)
    )
    radius_input = adsk.core.DistanceValueCommandInput.cast(
        command_inputs.itemById(REFINE_RADIUS_INPUT_ID)
    )
    if selection_input is None or selection_input.selectionCount != 1:
        raise ValueError("Select one point on the pathway spine.")
    if radius_input is None or not radius_input.isValidExpression or radius_input.value <= 0.0:
        raise ValueError("Refine marker radius must be positive.")
    selection = selection_input.selection(0)
    if selection is None:
        raise ValueError("Select a point on the displayed pathway spine.")
    entity = selection.entity
    point = selection.point
    if getattr(entity, "id", None) != REFINE_SPINE_ENTITY_ID:
        raise ValueError("Select a point on the displayed pathway spine.")
    if point is None:
        raise ValueError("Select a point on the displayed pathway spine.")
    selected_point = Vector3(
        point.x * 10.0,
        point.y * 10.0,
        point.z * 10.0,
    )
    return place_refine(spine, selected_point, radius_input.value * 10.0)


def _native_fusion_entity(entity: object) -> object:
    """
    Normalize an assembly-context proxy to its native Fusion entity.
    """
    native = getattr(entity, "nativeObject", None)
    return native if native is not None else entity


def _segment_entity_control_id(
    entity: object,
    state: _SegmentCommandState,
) -> Optional[UUID]:
    """
    Resolve an eligible selected profile or refine marker to its control identity.
    """
    marker_id = getattr(entity, "id", None)
    if isinstance(marker_id, str):
        try:
            marker_control_id = UUID(marker_id)
        except ValueError:
            marker_control_id = None
        if marker_control_id in state.refine_control_ids:
            return marker_control_id
    profile = adsk.fusion.Profile.cast(entity)
    if profile is None:
        return None
    selected_entity = _native_fusion_entity(profile)
    for control_id, eligible_profile in state.profile_controls:
        if selected_entity == _native_fusion_entity(eligible_profile):
            return control_id
    return None


def _read_segment_control_id(
    command_inputs: adsk.core.CommandInputs,
    state: _SegmentCommandState,
) -> UUID:
    """
    Return the single eligible pathway control selected for segmentation.
    """
    selection_input = adsk.core.SelectionCommandInput.cast(
        command_inputs.itemById(SEGMENT_CONTROL_INPUT_ID)
    )
    if selection_input is None or selection_input.selectionCount != 1:
        raise ValueError("Select one interior routing gate or refine point.")
    selection = selection_input.selection(0)
    control_id = _segment_entity_control_id(
        selection.entity if selection is not None else None,
        state,
    )
    if control_id is None:
        raise ValueError("Selected geometry is not a supported interior pathway control.")
    return control_id


def _read_segment_pathway_name(command_inputs: adsk.core.CommandInputs) -> str:
    """
    Read the required friendly name for the new pathway half.
    """
    name_input = adsk.core.StringValueCommandInput.cast(
        command_inputs.itemById(SEGMENT_PATHWAY_NAME_INPUT_ID)
    )
    if name_input is None or not name_input.value.strip():
        raise ValueError("New pathway name must not be empty.")
    return name_input.value.strip()


def _refine_geometry_transform(geometry: RefineGeometry) -> adsk.core.Matrix3D:
    """
    Convert saved millimeter geometry into a centimeter-based Fusion triad.
    """
    u_direction = Vector3(*geometry.u_direction)
    v_direction = Vector3(*geometry.v_direction)
    tangent = unit(cross(u_direction, v_direction))
    transform = adsk.core.Matrix3D.create()
    if transform is None or not transform.setWithCoordinateSystem(
        adsk.core.Point3D.create(*(value / 10.0 for value in geometry.origin_mm)),
        adsk.core.Vector3D.create(*geometry.u_direction),
        adsk.core.Vector3D.create(*geometry.v_direction),
        adsk.core.Vector3D.create(tangent.x, tangent.y, tangent.z),
    ):
        raise RuntimeError("Fusion could not orient the refine transform controls.")
    return transform


def _add_refine_transform_input(
    command_inputs: adsk.core.CommandInputs,
    geometry: RefineGeometry,
) -> adsk.core.TriadCommandInput:
    """
    Add a triad and explicitly initialize its writable world transform.

    Fusion can ignore the initial matrix passed to ``addTriadCommandInput``;
    assigning the same matrix to ``transform`` prevents the dialog and the first
    manipulation from falling back to the global origin.
    """
    initial_transform = _refine_geometry_transform(geometry)
    triad = command_inputs.addTriadCommandInput(
        REFINE_TRANSFORM_INPUT_ID,
        initial_transform,
    )
    if triad is None:
        raise RuntimeError("Fusion could not create the refine transform controls.")
    triad.transform = initial_transform
    return triad


def _read_edited_refine_geometry(command_inputs: adsk.core.CommandInputs) -> RefineGeometry:
    """
    Read a rigid triad and marker radius as persistent millimeter geometry.
    """
    triad = adsk.core.TriadCommandInput.cast(command_inputs.itemById(REFINE_TRANSFORM_INPUT_ID))
    radius = adsk.core.DistanceValueCommandInput.cast(
        command_inputs.itemById(REFINE_RADIUS_INPUT_ID)
    )
    if triad is None or not triad.isValidExpressions:
        raise ValueError("Refine position and rotation must be valid.")
    if radius is None or not radius.isValidExpression or radius.value <= 0.0:
        raise ValueError("Refine marker radius must be positive.")
    origin, u_direction, v_direction, _tangent = triad.transform.getAsCoordinateSystem()
    return RefineGeometry(
        origin_mm=(origin.x * 10.0, origin.y * 10.0, origin.z * 10.0),
        u_direction=(u_direction.x, u_direction.y, u_direction.z),
        v_direction=(v_direction.x, v_direction.y, v_direction.z),
        display_radius_mm=radius.value * 10.0,
    )


def _reconcile_active_refines(application: adsk.core.Application) -> None:
    """
    Recreate persistent refine markers from every healthy active definition.
    """
    design = _require_active_design(application)
    results = load_harnesses(_create_harness_gateway(application))
    definitions = tuple(result.definition for result in results if result.definition is not None)
    reconcile_refine_graphics(design, definitions)


def _refresh_active_preview(
    application: adsk.core.Application,
    harness_id: UUID,
    *,
    ensure_visible: bool = False,
) -> str:
    """
    Refresh a harness preview after its edit has been saved.

    Material edits can request a visible preview so their stripe presentation is
    immediate even when Preview Routes was not already active. Preview failures
    are notices, not failures of the persisted edit itself.
    """
    design = _require_active_design(application)
    definition = loads(_create_harness_gateway(application).read_harness_definition(harness_id))
    if (
        ensure_visible
        and definition.wires
        and any(definition.wire_materials(wire).stripes for wire in definition.wires)
    ):
        warnings: tuple[str, ...] = ()
        show_route_previews(design, definition)
    else:
        warnings = refresh_route_previews(design, definition)
    for warning in warnings:
        _log_to_fusion(warning)
    return " ".join(warnings)


def _apply_generated_materials(application: adsk.core.Application, harness_id: UUID) -> str:
    """
    Update existing generated bodies after a material definition is saved.
    """
    design = _require_active_design(application)
    gateway = _create_harness_gateway(application)
    definition = loads(gateway.read_harness_definition(harness_id))
    count = apply_wire_materials(
        design,
        gateway.harness_component(harness_id),
        definition,
    )
    return f"Applied materials to {count} generated wire{'s' if count != 1 else ''}."


def _send_palette_state(
    application: adsk.core.Application,
    notice: str = "",
) -> None:
    """
    Push the current harness library to an existing palette.
    """
    palette = application.userInterface.palettes.itemById(PALETTE_ID)
    if palette is None:
        return
    palette.sendInfoToHTML("state", _serialize_palette_state(application, notice))


def _serialize_palette_state(
    application: adsk.core.Application,
    notice: str = "",
) -> str:
    """
    Serialize discovered harness summaries for the palette boundary.
    """
    gateway = _create_harness_gateway(application)
    results = load_harnesses(gateway)
    catalog = load_wire_material_catalog()
    harnesses: list[dict[str, object]] = []
    for result in results:
        definition = result.definition
        if definition is None:
            deletion_token = _register_damaged_harness(result)
            harnesses.append(
                {
                    "componentName": result.component_name,
                    "deletionToken": deletion_token,
                    "error": result.error,
                    "status": "damaged",
                }
            )
            continue
        relationship_map = build_relationship_map(definition)
        harnesses.append(
            {
                "componentName": result.component_name,
                "definitionName": definition.name,
                "harnessId": str(definition.harness_id),
                "schemaVersion": definition.schema_version,
                "routingMode": _ROUTING_MODE_LABELS[definition.routing_mode],
                "gateDefaults": asdict(definition.gate_defaults),
                "endDefaults": asdict(definition.end_defaults),
                "materialDefaults": _material_settings_payload(definition.material_defaults),
                "profiles": [
                    {
                        "profileId": str(profile.profile_id),
                        "name": profile.name,
                        "diameterMm": profile.diameter_mm,
                    }
                    for profile in definition.profiles
                ],
                "connections": [
                    {
                        "interpolation": asdict(connection.interpolation),
                        "connectionId": str(connection.connection_id),
                        "name": connection.name,
                        "hasLinkedGeometry": all(
                            gateway.is_entity_token_resolvable(token)
                            for token in connection.member_tokens
                        ),
                        "members": [
                            {
                                "index": index,
                                "memberId": str(connection.member_identities[index]),
                                "interpolation": asdict(connection.member_settings[index]),
                                "usesDefaults": not connection.member_interpolations
                                or connection.member_interpolations[index] is None,
                                "hasLinkedGeometry": gateway.is_entity_token_resolvable(token),
                            }
                            for index, token in enumerate(connection.member_tokens)
                        ],
                    }
                    for connection in definition.connections
                ],
                "controls": [
                    {
                        "interpolation": asdict(control.interpolation),
                        "usesDefaults": not control.interpolation_is_override,
                        "controlId": str(control.control_id),
                        "name": control.name,
                        "kind": control.kind.value,
                        "hasLinkedGeometry": (
                            control.refine_geometry is not None
                            if control.kind.value == "refine"
                            else gateway.is_entity_token_resolvable(control.entity_token)
                        ),
                        "displayRadiusMm": (
                            control.refine_geometry.display_radius_mm
                            if control.refine_geometry is not None
                            else None
                        ),
                    }
                    for control in definition.controls
                ],
                "pathways": [
                    {
                        "pathwayId": str(pathway.pathway_id),
                        "name": pathway.name,
                        "startName": pathway.start_name,
                        "endName": pathway.end_name,
                        "routingMode": _ROUTING_MODE_LABELS[pathway.routing_mode],
                        "orderedControlIds": [
                            str(control_id) for control_id in pathway.ordered_control_ids
                        ],
                    }
                    for pathway in definition.pathways
                ],
                "junctions": [
                    {
                        "junctionId": str(junction.junction_id),
                        "name": junction.name,
                        "controlId": str(junction.control_id),
                        "pathwayRelationships": [
                            {
                                "pathwayId": str(relationship.pathway_id),
                                "endpoint": relationship.endpoint.value,
                            }
                            for relationship in junction.pathway_relationships
                        ],
                    }
                    for junction in definition.junctions
                ],
                "wires": [
                    {
                        "wireId": str(wire.wire_id),
                        "wireNumber": wire.wire_number,
                        "displayName": wire.display_name,
                        "startConnectionId": str(wire.start_connection_id),
                        "endConnectionId": str(wire.end_connection_id),
                        "startEndName": wire.start_end_name,
                        "endEndName": wire.end_end_name,
                        "profileId": str(wire.profile_id),
                        "orderedPathwayIds": [
                            str(pathway_id) for pathway_id in wire.ordered_pathway_ids
                        ],
                        "orderedControlIds": [
                            str(control_id) for control_id in wire.ordered_control_ids
                        ],
                        "materials": _material_settings_payload(definition.wire_materials(wire)),
                        "materialOverrides": _material_overrides_payload(wire.material_overrides),
                    }
                    for wire in definition.wires
                ],
                "relationshipMap": _relationship_map_payload(relationship_map),
                "status": "draft" if result.validation_messages else "valid",
                "validationMessages": result.validation_messages,
            }
        )
    payload = {
        "catalog": {
            "insulationMaterials": list(catalog.insulation_materials),
            "conductorMaterials": list(catalog.conductor_materials),
            "colors": [_color_payload(color) for color in catalog.colors],
            "stripePatterns": [pattern.value for pattern in catalog.stripe_patterns],
        },
        "harnesses": harnesses,
        "notice": notice or _last_command_error,
        "ok": True,
    }
    return json.dumps(payload, sort_keys=True)


def _register_damaged_harness(result: HarnessLoadResult) -> Optional[str]:
    """
    Retain a refresh-stable token for one damaged component during this add-in session.

    Results without a component handle cannot be registered and return ``None``.
    """
    if result.component_handle is None:
        return None
    for deletion_token, registered in _damaged_harness_results.items():
        if registered.component_handle is result.component_handle:
            _damaged_harness_results[deletion_token] = result
            return deletion_token
    deletion_token = str(uuid4())
    _damaged_harness_results[deletion_token] = result
    return deletion_token


def _delete_damaged_harness(
    application: adsk.core.Application,
    serialized_data: str,
) -> str:
    """
    Delete one exact unreadable harness component selected from the current palette state.
    """
    payload = _read_palette_payload(serialized_data)
    deletion_token = payload.get("deletionToken")
    if not isinstance(deletion_token, str) or not deletion_token:
        raise ValueError("Damaged harness deletion requires a current deletion token.")
    result = _damaged_harness_results.get(deletion_token)
    if result is None:
        raise ValueError("The damaged harness selection is stale; refresh and try again.")
    gateway = _create_harness_gateway(application)
    delete_damaged_harness(result, gateway)
    del _damaged_harness_results[deletion_token]
    return f"Deleted damaged harness {result.component_name}."


def _relationship_map_payload(relationship_map: RelationshipMap) -> dict[str, object]:
    """
    Convert the host-independent relationship projection for the HTML palette.
    """
    return {
        "nodes": [
            {
                "nodeId": node.node_id,
                "kind": node.kind.value,
                "memberId": str(node.member_id),
                "label": node.label,
                "missing": node.missing,
            }
            for node in relationship_map.nodes
        ],
        "structuralEdges": [
            {
                "edgeId": edge.edge_id,
                "sourceNodeId": edge.source_node_id,
                "targetNodeId": edge.target_node_id,
            }
            for edge in relationship_map.structural_edges
        ],
        "edges": [
            {
                "edgeId": edge.edge_id,
                "wireId": str(edge.wire_id),
                "sourceNodeId": edge.source_node_id,
                "targetNodeId": edge.target_node_id,
                "sequence": edge.sequence,
            }
            for edge in relationship_map.edges
        ],
        "routes": [
            {
                "routeId": route.route_id,
                "wireId": str(route.wire_id),
                "wireNumber": route.wire_number,
                "label": route.label,
                "nodeIds": list(route.node_ids),
                "edgeIds": list(route.edge_ids),
            }
            for route in relationship_map.routes
        ],
        "pathwayOccupancy": [
            {
                "pathwayId": str(occupancy.pathway_id),
                "wireIds": [str(wire_id) for wire_id in occupancy.wire_ids],
            }
            for occupancy in relationship_map.pathway_occupancy
        ],
        "connectionUsage": [
            {
                "connectionId": str(usage.connection_id),
                "endpoints": [
                    {"wireId": str(wire_id), "end": endpoint}
                    for wire_id, endpoint in usage.endpoints
                ],
            }
            for usage in relationship_map.connection_usage
        ],
        "auditIssues": [
            {
                "code": issue.code,
                "message": issue.message,
                "memberType": issue.member_type,
                "memberId": issue.member_id,
            }
            for issue in relationship_map.audit_issues
        ],
    }


def _color_payload(color: WireColor) -> dict[str, object]:
    """
    Convert a stored wire color for the HTML palette.
    """
    return {
        "name": color.name,
        "red": color.red,
        "green": color.green,
        "blue": color.blue,
        "hex": color.hex_rgb,
    }


def _appearance_reference_payload(
    appearance: Optional[WireAppearanceReference],
) -> Optional[dict[str, str]]:
    """
    Convert an optional stored Fusion appearance reference for the palette.
    """
    if appearance is None:
        return None
    return {
        "libraryId": appearance.library_id,
        "libraryName": appearance.library_name,
        "appearanceId": appearance.appearance_id,
        "appearanceName": appearance.appearance_name,
    }


def _appearance_libraries_payload(
    application: adsk.core.Application,
) -> list[dict[str, str]]:
    """
    List installed Fusion appearance libraries without loading their contents.
    """
    libraries = application.materialLibraries
    result: list[dict[str, str]] = []
    for index in range(libraries.count):
        library = libraries.item(index)
        if library is not None:
            result.append({"id": library.id, "name": library.name})
    result.sort(key=lambda item: item["name"].casefold())
    return result


def _library_appearances_payload(
    application: adsk.core.Application,
    library_id: str,
) -> list[dict[str, str]]:
    """
    List appearances from one explicitly selected installed Fusion library.
    """
    library = application.materialLibraries.itemById(library_id)
    if library is None:
        raise ValueError("The selected Fusion appearance library is unavailable.")
    appearances = library.appearances
    result: list[dict[str, str]] = []
    for index in range(appearances.count):
        appearance = appearances.item(index)
        if appearance is not None:
            result.append({"id": appearance.id, "name": appearance.name})
    result.sort(key=lambda item: item["name"].casefold())
    return result


def _stripe_payload(stripe: WireStripe) -> dict[str, object]:
    """
    Convert one ordered procedural stripe for the HTML palette.
    """
    return {
        "color": _color_payload(stripe.color),
        "widthMm": stripe.width_mm,
        "pattern": stripe.pattern.value,
        "angleDeg": stripe.angle_deg,
        "repeatMm": stripe.repeat_mm,
    }


def _material_settings_payload(settings: WireMaterialSettings) -> dict[str, object]:
    """
    Convert resolved material settings for editing and display.
    """
    return {
        "insulationMaterial": settings.insulation_material,
        "mainColor": _color_payload(settings.main_color),
        "appearance": _appearance_reference_payload(settings.appearance),
        "stripes": [_stripe_payload(stripe) for stripe in settings.stripes],
        "conductorMaterial": settings.conductor_material,
        "manufacturer": settings.manufacturer,
        "partNumber": settings.part_number,
        "notes": settings.notes,
    }


def _material_overrides_payload(overrides: WireMaterialOverrides) -> dict[str, object]:
    """
    Preserve null inheritance markers at the palette boundary.
    """
    return {
        "insulationMaterial": overrides.insulation_material,
        "mainColor": (
            None if overrides.main_color is None else _color_payload(overrides.main_color)
        ),
        "appearance": _appearance_reference_payload(overrides.appearance),
        "stripes": (
            None
            if overrides.stripes is None
            else [_stripe_payload(stripe) for stripe in overrides.stripes]
        ),
        "conductorMaterial": overrides.conductor_material,
        "manufacturer": overrides.manufacturer,
        "partNumber": overrides.part_number,
        "notes": overrides.notes,
    }


def _report_failure(operation: str) -> None:
    """
    Report a lifecycle failure at the Fusion host boundary.
    """
    application = adsk.core.Application.get()
    if application and application.userInterface:
        application.userInterface.messageBox(
            f"Wire Bundler failed to {operation}:\n{traceback.format_exc()}",
            COMMAND_NAME,
        )


def _log_to_fusion(message: str) -> None:
    """
    Write a diagnostic message to Fusion's application log.
    """
    adsk.core.Application.log(
        message,
        adsk.core.LogLevels.InfoLogLevel,
        adsk.core.LogTypes.FileLogType,
    )


def _open_add_pathway_command(application: adsk.core.Application, serialized_data: str) -> None:
    """
    Open the native pathway command for the harness selected in the palette.

    Raises:
        RuntimeError: If Fusion cannot open the command.
        ValueError: If the palette payload is malformed.
    """
    global _pending_pathway_harness_id

    payload = json.loads(serialized_data)
    if not isinstance(payload, dict):
        raise ValueError("Add Pathway request must be a JSON object.")
    raw_harness_id = payload.get("harnessId")
    if not isinstance(raw_harness_id, str):
        raise ValueError("Add Pathway request is missing a harness identity.")
    harness_id = UUID(raw_harness_id)
    command_definition = application.userInterface.commandDefinitions.itemById(
        ADD_PATHWAY_COMMAND_ID
    )
    if command_definition is None:
        raise RuntimeError("Fusion Add Pathway command is unavailable.")

    _pending_pathway_harness_id = harness_id
    try:
        if not command_definition.execute():
            raise RuntimeError("Fusion did not open the Add Pathway command.")
    except Exception:
        _pending_pathway_harness_id = None
        raise


def _open_add_junction_command(application: adsk.core.Application, serialized_data: str) -> None:
    """
    Open the native isolated-junction command for the palette-selected harness.

    Raises:
        RuntimeError: If Fusion cannot open the command.
        ValueError: If the palette payload is malformed.
    """
    global _pending_junction_harness_id

    payload = _read_palette_payload(serialized_data)
    harness_id = _read_payload_uuid(payload, "harnessId", "harness")
    command_definition = application.userInterface.commandDefinitions.itemById(
        ADD_JUNCTION_COMMAND_ID
    )
    if command_definition is None:
        raise RuntimeError("Fusion Add Junction command is unavailable.")
    _pending_junction_harness_id = harness_id
    try:
        if not command_definition.execute():
            raise RuntimeError("Fusion did not open the Add Junction command.")
    except (AttributeError, RuntimeError, TypeError, ValueError):
        _pending_junction_harness_id = None
        raise


def _open_add_junction_relationship_command(
    application: adsk.core.Application,
    serialized_data: str,
) -> None:
    """
    Open the native pathway-end selector for one palette-selected junction.
    """
    global _pending_junction_relationship_ids

    payload = _read_palette_payload(serialized_data)
    harness_id = _read_payload_uuid(payload, "harnessId", "harness")
    junction_id = _read_payload_uuid(payload, "junctionId", "junction")
    command_definition = application.userInterface.commandDefinitions.itemById(
        ADD_JUNCTION_RELATIONSHIP_COMMAND_ID
    )
    if command_definition is None:
        raise RuntimeError("Fusion Add Junction Relationship command is unavailable.")
    _pending_junction_relationship_ids = (harness_id, junction_id)
    try:
        if not command_definition.execute():
            raise RuntimeError("Fusion did not open the junction relationship command.")
    except (AttributeError, RuntimeError, TypeError, ValueError):
        _pending_junction_relationship_ids = None
        raise


def _open_end_member_edit(application: adsk.core.Application, serialized_data: str) -> None:
    """
    Open the native member picker for a validated palette request.
    """
    global _pending_end_edit
    payload = _read_palette_payload(serialized_data)
    if payload.get("editAction") not in {"add", "replace"}:
        raise ValueError("Unsupported profile selection action.")
    command = application.userInterface.commandDefinitions.itemById(EDIT_END_COMMAND_ID)
    if command is None:
        raise RuntimeError("End-member selection is unavailable.")
    _pending_end_edit = payload
    try:
        if not command.execute():
            raise RuntimeError("Fusion could not open profile selection.")
    except (AttributeError, RuntimeError, TypeError, ValueError):
        _pending_end_edit = None
        raise


def _apply_end_member_edit(
    application: adsk.core.Application,
    payload: dict[str, object],
    tokens: tuple[str, ...] = (),
) -> None:
    """
    Validate member indices and persist a connection edit through its gateway.
    """
    endpoint = payload.get("endpoint")
    action = payload.get("editAction")
    index = payload.get("memberIndex", 0)
    count = payload.get("expectedMembers")
    target = payload.get("targetIndex", 0)
    if not isinstance(endpoint, str) or not isinstance(action, str):
        raise ValueError("End edit requires an endpoint and action.")
    if (
        isinstance(index, bool)
        or not isinstance(index, int)
        or isinstance(count, bool)
        or not isinstance(count, int)
        or isinstance(target, bool)
        or not isinstance(target, int)
    ):
        raise ValueError("End edit requires integer member indices and counts.")
    edit_end_members(
        _read_payload_uuid(payload, "harnessId", "harness"),
        _read_payload_uuid(payload, "wireId", "wire"),
        endpoint,
        action,
        _create_harness_gateway(application),
        tokens,
        index,
        count,
        target,
    )


def _open_append_gates_command(application: adsk.core.Application, serialized_data: str) -> None:
    """
    Open native profile selection for the palette-selected pathway.
    """
    global _pending_append_gate_ids

    payload = _read_palette_payload(serialized_data)
    harness_id = _read_payload_uuid(payload, "harnessId", "harness")
    pathway_id = _read_payload_uuid(payload, "pathwayId", "pathway")
    command_definition = application.userInterface.commandDefinitions.itemById(
        APPEND_GATES_COMMAND_ID
    )
    if command_definition is None:
        raise RuntimeError("Fusion Add Gates command is unavailable.")
    _pending_append_gate_ids = (harness_id, pathway_id)
    try:
        if not command_definition.execute():
            raise RuntimeError("Fusion did not open the Add Gates command.")
    except Exception:
        _pending_append_gate_ids = None
        raise


def _open_refine_command(application: adsk.core.Application, serialized_data: str) -> None:
    """
    Open interactive refine placement for the palette-selected pathway.
    """
    global _pending_refine_ids
    payload = _read_palette_payload(serialized_data)
    harness_id = _read_payload_uuid(payload, "harnessId", "harness")
    pathway_id = _read_payload_uuid(payload, "pathwayId", "pathway")
    command_definition = application.userInterface.commandDefinitions.itemById(
        ADD_REFINE_COMMAND_ID
    )
    if command_definition is None:
        raise RuntimeError("Fusion Add Refine Point command is unavailable.")
    _pending_refine_ids = (harness_id, pathway_id)
    try:
        if not command_definition.execute():
            raise RuntimeError("Fusion did not open the Add Refine Point command.")
    except (AttributeError, RuntimeError, TypeError, ValueError):
        _pending_refine_ids = None
        raise


def _open_segment_command(application: adsk.core.Application, serialized_data: str) -> None:
    """
    Open interactive segmentation for the palette-selected pathway.
    """
    global _pending_segment_ids
    payload = _read_palette_payload(serialized_data)
    harness_id = _read_payload_uuid(payload, "harnessId", "harness")
    pathway_id = _read_payload_uuid(payload, "pathwayId", "pathway")
    command_definition = application.userInterface.commandDefinitions.itemById(
        SEGMENT_PATHWAY_COMMAND_ID
    )
    if command_definition is None:
        raise RuntimeError("Fusion Segment Pathway command is unavailable.")
    _pending_segment_ids = (harness_id, pathway_id)
    try:
        if not command_definition.execute():
            raise RuntimeError("Fusion did not open the Segment Pathway command.")
    except (AttributeError, RuntimeError, TypeError, ValueError):
        _pending_segment_ids = None
        raise


def _open_refine_edit_command(
    application: adsk.core.Application,
    harness_id: UUID,
    control_id: UUID,
) -> None:
    """
    Open translation, rotation, and radius controls for one saved refine.
    """
    global _pending_refine_edit_ids
    command_definition = application.userInterface.commandDefinitions.itemById(
        EDIT_REFINE_COMMAND_ID
    )
    if command_definition is None:
        raise RuntimeError("Fusion Edit Refine Point command is unavailable.")
    _pending_refine_edit_ids = (harness_id, control_id)
    try:
        if not command_definition.execute():
            raise RuntimeError("Fusion did not open the Edit Refine Point command.")
    except (AttributeError, RuntimeError, TypeError, ValueError):
        _pending_refine_edit_ids = None
        raise


def _open_add_wires_command(application: adsk.core.Application, serialized_data: str) -> None:
    """
    Open the native wire-assignment command for the selected harness.

    Raises:
        RuntimeError: If Fusion cannot open the command.
        ValueError: If the palette payload is malformed.
    """
    global _pending_wire_harness_id, _pending_wire_pathway_id

    payload = json.loads(serialized_data)
    if not isinstance(payload, dict):
        raise ValueError("Add Wires request must be a JSON object.")
    raw_harness_id = payload.get("harnessId")
    if not isinstance(raw_harness_id, str):
        raise ValueError("Add Wires request is missing a harness identity.")
    harness_id = UUID(raw_harness_id)
    raw_pathway_id = payload.get("pathwayId")
    if raw_pathway_id is not None and not isinstance(raw_pathway_id, str):
        raise ValueError("Add Wires request has an invalid pathway identity.")
    pathway_id = UUID(raw_pathway_id) if raw_pathway_id else None
    command_definition = application.userInterface.commandDefinitions.itemById(ADD_WIRES_COMMAND_ID)
    if command_definition is None:
        raise RuntimeError("Fusion Add Wires command is unavailable.")

    _pending_wire_harness_id = harness_id
    _pending_wire_pathway_id = pathway_id
    try:
        if not command_definition.execute():
            raise RuntimeError("Fusion did not open the Add Wires command.")
    except Exception:
        _pending_wire_harness_id = None
        _pending_wire_pathway_id = None
        raise


def _apply_palette_edit(
    application: adsk.core.Application,
    action: str,
    serialized_data: str,
) -> str:
    """
    Apply one ordered palette edit and return its success notice.
    """
    payload = _read_palette_payload(serialized_data)
    harness_id = _read_payload_uuid(payload, "harnessId", "harness")
    gateway = _create_harness_gateway(application)
    if action == "remove_end_member":
        _apply_end_member_edit(application, {**payload, "editAction": "remove"})
        return "Removed end member."
    if action == "move_end_member":
        _apply_end_member_edit(application, {**payload, "editAction": "reorder"})
        return "Reordered end member."
    if action == "move_pathway_gate":
        move_pathway_gate(
            harness_id,
            _read_payload_uuid(payload, "pathwayId", "pathway"),
            _read_payload_uuid(payload, "controlId", "gate"),
            _read_payload_offset(payload),
            gateway,
        )
        return "Reordered pathway gate."
    if action == "remove_junction_relationship":
        endpoint = payload.get("endpoint")
        if endpoint not in {member.value for member in PathwayEndpoint}:
            raise ValueError("Junction relationship has an invalid endpoint.")
        remove_junction_relationship(
            harness_id,
            _read_payload_uuid(payload, "junctionId", "junction"),
            JunctionPathwayRelationship(
                _read_payload_uuid(payload, "pathwayId", "pathway"),
                PathwayEndpoint(endpoint),
            ),
            gateway,
        )
        return "Removed junction relationship."
    if action == "update_junction_relationships":
        raw_relationships = payload.get("pathwayRelationships")
        if not isinstance(raw_relationships, list):
            raise ValueError("Junction relationships must be a list.")
        relationships: list[JunctionPathwayRelationship] = []
        for index, raw_relationship in enumerate(raw_relationships):
            if not isinstance(raw_relationship, dict):
                raise ValueError(f"Junction relationship {index + 1} must be an object.")
            endpoint = raw_relationship.get("endpoint")
            if endpoint not in {member.value for member in PathwayEndpoint}:
                raise ValueError(f"Junction relationship {index + 1} has an invalid endpoint.")
            relationships.append(
                JunctionPathwayRelationship(
                    _read_payload_uuid(raw_relationship, "pathwayId", "pathway"),
                    PathwayEndpoint(endpoint),
                )
            )
        update_junction_relationships(
            harness_id,
            _read_payload_uuid(payload, "junctionId", "junction"),
            tuple(relationships),
            gateway,
        )
        return "Saved junction relationships."
    if action == "remove_pathway_gate":
        remove_pathway_gate(
            harness_id,
            _read_payload_uuid(payload, "pathwayId", "pathway"),
            _read_payload_uuid(payload, "controlId", "gate"),
            gateway,
        )
        return "Removed pathway gate."
    if action == "set_interpolation":
        target = payload.get("target")
        if target not in ("gate", "end", "defaults"):
            raise ValueError("Unsupported interpolation target.")
        use_defaults = payload.get("useDefaults", False)
        if not isinstance(use_defaults, bool):
            raise ValueError("Use defaults must be a boolean.")
        apply_existing = payload.get("applyExisting", False)
        if not isinstance(apply_existing, bool):
            raise ValueError("Apply to existing sections must be a boolean.")
        settings = parse_interpolation(payload.get("settings"), "settings")
        set_interpolation(
            harness_id,
            target,
            settings,
            gateway,
            apply_existing=apply_existing,
            use_defaults=use_defaults,
            member_id=(
                _read_payload_uuid(payload, "memberId", "end member") if target == "end" else None
            ),
            target_id=(
                None if target == "defaults" else _read_payload_uuid(payload, "targetId", "section")
            ),
            end_defaults=(
                parse_interpolation(payload.get("endDefaults"), "endDefaults")
                if target == "defaults"
                else None
            ),
        )
        return "Saved interpolation options."
    if action == "set_wire_diameter":
        diameter = payload.get("diameterMm")
        if isinstance(diameter, bool) or not isinstance(diameter, (int, float)):
            raise ValueError("Wire diameter must be a number in millimeters.")
        set_wire_diameter(
            harness_id, _read_payload_uuid(payload, "wireId", "wire"), diameter, gateway
        )
        return "Saved wire diameter."
    if action == "set_harness_material_defaults":
        set_harness_material_defaults(
            harness_id,
            _read_material_settings(payload.get("materials")),
            gateway,
        )
        return "Saved harness wire-material defaults."
    if action == "set_wire_material_overrides":
        set_wire_material_overrides(
            harness_id,
            _read_payload_uuid(payload, "wireId", "wire"),
            _read_material_overrides(payload.get("overrides")),
            gateway,
        )
        return "Saved wire-material overrides."
    if action in {"rename_junction", "rename_pathway", "rename_wire"}:
        name = payload.get("name")
        if not isinstance(name, str):
            raise ValueError("Rename request requires a text name.")
        if action == "rename_wire":
            rename_wire(harness_id, _read_payload_uuid(payload, "wireId", "wire"), name, gateway)
        elif action == "rename_junction":
            rename_junction(
                harness_id,
                _read_payload_uuid(payload, "junctionId", "junction"),
                name,
                gateway,
            )
        else:
            field = payload.get("field")
            if not isinstance(field, str):
                raise ValueError("Pathway rename request requires a field.")
            rename_pathway(
                harness_id,
                _read_payload_uuid(payload, "pathwayId", "pathway"),
                field,
                name,
                gateway,
            )
        return "Saved name."
    if action == "rename_route_end":
        endpoint = payload.get("endpoint")
        name = payload.get("name")
        if not isinstance(endpoint, str) or not isinstance(name, str):
            raise ValueError("End name request requires an endpoint and a text name.")
        rename_route_end(
            harness_id,
            _read_payload_uuid(payload, "wireId", "wire"),
            endpoint,
            name,
            gateway,
        )
        return "Saved end name."
    if action == "move_wire_endpoint":
        endpoint = payload.get("endpoint")
        if not isinstance(endpoint, str):
            raise ValueError("Wire endpoint request is missing an endpoint sequence.")
        move_wire_endpoint(
            harness_id,
            _read_payload_uuid(payload, "wireId", "wire"),
            endpoint,
            _read_payload_offset(payload),
            gateway,
        )
        return f"Reordered {endpoint} connection sequence."
    if action == "remove_wire":
        remove_wire(
            harness_id,
            _read_payload_uuid(payload, "wireId", "wire"),
            gateway,
        )
        return "Removed wire pair."
    raise ValueError(f"Unsupported harness edit: {action}")


def _highlight_member(application: adsk.core.Application, serialized_data: str) -> int:
    """
    Emphasize linked profiles, route previews, and generated wire bodies.
    """
    payload = _read_palette_payload(serialized_data)
    harness_id = _read_payload_uuid(payload, "harnessId", "harness")
    member_type = payload.get("memberType")
    if not isinstance(member_type, str):
        raise ValueError("Highlight request is missing a member type.")
    member_id = _read_payload_uuid(payload, "memberId", "member")
    design = _require_active_design(application)
    gateway = _create_harness_gateway(application)
    definition = loads(gateway.read_harness_definition(harness_id))
    wire_ids: tuple[UUID, ...] = ()
    refine_ids: tuple[UUID, ...] = ()
    if member_type == "junction":
        junction = next(
            (item for item in definition.junctions if item.junction_id == member_id),
            None,
        )
        if junction is None:
            raise ValueError("Selected junction no longer exists.")
        control = next(
            (item for item in definition.controls if item.control_id == junction.control_id),
            None,
        )
        if control is None:
            raise ValueError("Selected junction has a missing routing control.")
        refine_ids = (control.control_id,) if control.kind is ControlKind.REFINE else ()
        tokens = (control.entity_token,) if control.entity_token else ()
    elif member_type in {"pathway", "pathway_gates", "pathway_wires"}:
        pathway = next((item for item in definition.pathways if item.pathway_id == member_id), None)
        if pathway is None:
            raise ValueError("Selected pathway no longer exists.")
        wire_ids = (
            tuple(
                wire.wire_id for wire in definition.wires if member_id in wire.ordered_pathway_ids
            )
            if member_type != "pathway_gates"
            else ()
        )
        control_ids = pathway.ordered_control_ids if member_type != "pathway_wires" else ()
        controls = {control.control_id: control for control in definition.controls}
        refine_ids = tuple(
            control_id
            for control_id in control_ids
            if control_id in controls and controls[control_id].kind is ControlKind.REFINE
        )
        tokens = tuple(
            controls[control_id].entity_token
            for control_id in control_ids
            if control_id in controls and controls[control_id].entity_token
        )
    elif member_type == "preview_wire":
        if all(wire.wire_id != member_id for wire in definition.wires):
            raise ValueError("Selected wire no longer exists.")
        wire_ids = (member_id,)
        tokens = ()
    else:
        tokens = _member_entity_tokens(definition, member_type, member_id)
        if member_type == "wire":
            wire_ids = (member_id,)
        elif member_type == "connection":
            wire_ids = tuple(
                wire.wire_id
                for wire in definition.wires
                if member_id in {wire.start_connection_id, wire.end_connection_id}
            )
        elif member_type == "control":
            wire_ids = tuple(
                wire.wire_id for wire in definition.wires if member_id in wire.ordered_control_ids
            )
            control = next(
                (item for item in definition.controls if item.control_id == member_id),
                None,
            )
            if control is not None and control.kind is ControlKind.REFINE:
                refine_ids = (member_id,)
        if member_type == "connection" and "memberIndex" in payload:
            index = payload["memberIndex"]
            if (
                isinstance(index, bool)
                or not isinstance(index, int)
                or not 0 <= index < len(tokens)
            ):
                raise ValueError("Selected connection member no longer exists.")
            tokens = (tokens[index],)
    preview_count = highlight_route_members(design, wire_ids)
    refine_count = highlight_refine_graphics(design, refine_ids)
    profiles: list[adsk.fusion.Profile] = []
    for token in tokens:
        entities = design.findEntityByToken(token)
        profile = adsk.fusion.Profile.cast(entities[0] if entities else None)
        if profile is None:
            raise ValueError("The selected item no longer resolves to a sketch profile.")
        profiles.append(profile)

    selections = application.userInterface.activeSelections
    if not selections.clear():
        raise RuntimeError("Fusion could not clear the prior viewport selection.")
    bodies = generated_wire_bodies(
        design.rootComponent,
        gateway.harness_component(harness_id),
        wire_ids,
    )
    for entity in (*profiles, *bodies):
        if not selections.add(entity):
            selections.clear()
            highlight_route_preview(design, None)
            raise RuntimeError("Fusion could not highlight the selected harness geometry.")
    application.activeViewport.refresh()
    return preview_count + refine_count + len(profiles) + len(bodies)


def _clear_highlight(application: adsk.core.Application) -> None:
    """
    Clear palette-driven viewport selection.
    """
    highlight_route_preview(_require_active_design(application), None)
    highlight_refine_graphics(_require_active_design(application), ())
    if not application.userInterface.activeSelections.clear():
        raise RuntimeError("Fusion could not clear the viewport selection.")
    application.activeViewport.refresh()


def _member_entity_tokens(
    definition: HarnessDefinition,
    member_type: str,
    member_id: UUID,
) -> tuple[str, ...]:
    """
    Resolve a stable palette member identity to persisted entity tokens.

    Controls and connections yield their members; wires yield both endpoint stacks.
    """
    if member_type == "control":
        control = next(
            (item for item in definition.controls if item.control_id == member_id),
            None,
        )
        if control is None:
            raise ValueError("Selected routing gate no longer exists.")
        return (control.entity_token,) if control.entity_token else ()
    connections = {item.connection_id: item for item in definition.connections}
    if member_type == "connection":
        connection = connections.get(member_id)
        if connection is None:
            raise ValueError("Selected connection no longer exists.")
        return connection.member_tokens
    if member_type == "wire":
        wire = next((item for item in definition.wires if item.wire_id == member_id), None)
        if wire is None:
            raise ValueError("Selected wire no longer exists.")
        start_connection = connections.get(wire.start_connection_id)
        end_connection = connections.get(wire.end_connection_id)
        if start_connection is None or end_connection is None:
            raise ValueError("Selected wire has a missing connection reference.")
        tokens = (*start_connection.member_tokens, *end_connection.member_tokens)
        return tokens
    raise ValueError(f"Unsupported highlight member type: {member_type}")


def _read_palette_payload(serialized_data: str) -> dict[str, object]:
    """
    Parse a palette payload and require a JSON object.
    """
    payload = json.loads(serialized_data)
    if not isinstance(payload, dict):
        raise ValueError("Harness Builder request must be a JSON object.")
    return payload


def _read_payload_uuid(payload: dict[str, object], key: str, label: str) -> UUID:
    """
    Read one required stable identity from a palette payload.
    """
    value = payload.get(key)
    if not isinstance(value, str):
        raise ValueError(f"Harness Builder request is missing a {label} identity.")
    return UUID(value)


def _read_payload_offset(payload: dict[str, object]) -> int:
    """
    Read a required single-position movement from a palette payload.
    """
    value = payload.get("offset")
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("Harness Builder move request is missing an integer offset.")
    return value


def _read_material_color(raw_value: object) -> WireColor:
    """
    Parse one named RGB color supplied by the local HTML palette.
    """
    if not isinstance(raw_value, dict):
        raise ValueError("Wire color must be an object.")
    name = raw_value.get("name")
    red = raw_value.get("red")
    green = raw_value.get("green")
    blue = raw_value.get("blue")
    if not isinstance(name, str):
        raise ValueError("Wire color requires a name.")
    if any(isinstance(value, bool) or not isinstance(value, int) for value in (red, green, blue)):
        raise ValueError("Wire color requires integer red, green, and blue channels.")
    return WireColor(name, cast(int, red), cast(int, green), cast(int, blue))


def _read_appearance_reference(raw_value: object) -> Optional[WireAppearanceReference]:
    """
    Parse an optional Fusion library appearance supplied by the local palette.
    """
    if raw_value is None:
        return None
    if not isinstance(raw_value, dict):
        raise ValueError("Wire appearance must be an object or null.")
    values = []
    for key in ("libraryId", "libraryName", "appearanceId", "appearanceName"):
        value = raw_value.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Wire appearance requires complete library and appearance details.")
        values.append(value)
    return WireAppearanceReference(*values)


def _read_material_stripes(raw_value: object) -> tuple[WireStripe, ...]:
    """
    Parse ordered procedural stripes supplied by the local HTML palette.
    """
    if not isinstance(raw_value, list):
        raise ValueError("Wire stripes must be a list.")
    stripes: list[WireStripe] = []
    for index, raw_stripe in enumerate(raw_value):
        if not isinstance(raw_stripe, dict):
            raise ValueError(f"Stripe {index + 1} must be an object.")
        width = raw_stripe.get("widthMm")
        angle = raw_stripe.get("angleDeg", 0.0)
        repeat = raw_stripe.get("repeatMm")
        pattern = raw_stripe.get("pattern")
        if (
            isinstance(width, bool)
            or not isinstance(width, (int, float))
            or isinstance(angle, bool)
            or not isinstance(angle, (int, float))
            or (
                repeat is not None
                and (isinstance(repeat, bool) or not isinstance(repeat, (int, float)))
            )
            or not isinstance(pattern, str)
        ):
            raise ValueError(f"Stripe {index + 1} has invalid dimensions or pattern.")
        stripes.append(
            WireStripe(
                color=_read_material_color(raw_stripe.get("color")),
                width_mm=float(width),
                pattern=StripePattern(pattern),
                angle_deg=float(angle),
                repeat_mm=None if repeat is None else float(repeat),
            )
        )
    return tuple(stripes)


def _read_material_text(
    values: dict[str, object],
    key: str,
    label: str,
    *,
    required: bool,
) -> str:
    """
    Read a material text field and optionally require non-whitespace content.
    """
    value = values.get(key)
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text.")
    if required and not value.strip():
        raise ValueError(f"{label} must not be empty.")
    return value


def _read_material_settings(raw_value: object) -> WireMaterialSettings:
    """
    Parse complete parent material settings supplied by the palette.
    """
    if not isinstance(raw_value, dict):
        raise ValueError("Harness wire-material settings must be an object.")
    return WireMaterialSettings(
        insulation_material=_read_material_text(
            raw_value, "insulationMaterial", "Insulation material", required=True
        ),
        main_color=_read_material_color(raw_value.get("mainColor")),
        appearance=_read_appearance_reference(raw_value.get("appearance")),
        stripes=_read_material_stripes(raw_value.get("stripes")),
        conductor_material=_read_material_text(
            raw_value, "conductorMaterial", "Conductor material", required=True
        ),
        manufacturer=_read_material_text(raw_value, "manufacturer", "Manufacturer", required=False),
        part_number=_read_material_text(raw_value, "partNumber", "Part number", required=False),
        notes=_read_material_text(raw_value, "notes", "Notes", required=False),
    )


def _read_material_overrides(raw_value: object) -> WireMaterialOverrides:
    """
    Parse nullable wire overrides; null values retain parent inheritance.
    """
    if not isinstance(raw_value, dict):
        raise ValueError("Wire-material overrides must be an object.")
    values = raw_value

    def optional_text(key: str, label: str, required: bool = False) -> Optional[str]:
        """
        Preserve null inheritance or validate one explicit text override.
        """
        value = values.get(key)
        if value is None:
            return None
        return _read_material_text(values, key, label, required=required)

    return WireMaterialOverrides(
        insulation_material=optional_text(
            "insulationMaterial", "Insulation material", required=True
        ),
        main_color=(
            None
            if values.get("mainColor") is None
            else _read_material_color(values.get("mainColor"))
        ),
        appearance=_read_appearance_reference(values.get("appearance")),
        stripes=(
            None if values.get("stripes") is None else _read_material_stripes(values.get("stripes"))
        ),
        conductor_material=optional_text("conductorMaterial", "Conductor material", required=True),
        manufacturer=optional_text("manufacturer", "Manufacturer"),
        part_number=optional_text("partNumber", "Part number"),
        notes=optional_text("notes", "Notes"),
    )


def _preview_routes(application: adsk.core.Application, serialized_data: str) -> int:
    """
    Solve and display route previews for the palette-selected harness.
    """
    payload = json.loads(serialized_data)
    if not isinstance(payload, dict):
        raise ValueError("Preview Routes request must be a JSON object.")
    raw_harness_id = payload.get("harnessId")
    if not isinstance(raw_harness_id, str):
        raise ValueError("Preview Routes request is missing a harness identity.")
    harness_id = UUID(raw_harness_id)
    design = _require_active_design(application)
    gateway = _create_harness_gateway(application)
    definition = loads(gateway.read_harness_definition(harness_id))
    notices: list[str] = []
    routes = show_route_previews(design, definition, notices=notices)
    application.activeViewport.refresh()
    summary = f"Previewing {len(routes)} wire routes."
    _send_palette_state(application, "\n".join((summary, *notices)))
    return len(routes)


def _clear_preview(application: adsk.core.Application) -> int:
    """
    Remove transient route graphics outside a Fusion model-edit transaction.
    """
    _clear_highlight(application)
    count = clear_route_previews(_require_active_design(application))
    application.activeViewport.refresh()
    return count


def _require_active_design(application: adsk.core.Application) -> adsk.fusion.Design:
    """
    Return the active Fusion design or report the missing host context.
    """
    design = adsk.fusion.Design.cast(application.activeProduct)
    if design is None:
        raise RuntimeError("Harness Builder requires an active Fusion design.")
    return design


def _add_profile_selection_input(
    command_inputs: adsk.core.CommandInputs,
    input_id: str,
    name: str,
    prompt: str,
) -> adsk.core.SelectionCommandInput:
    """
    Add a required multi-profile selection input.
    """
    selection_input = command_inputs.addSelectionInput(input_id, name, prompt)
    if selection_input is None:
        raise RuntimeError(f"Fusion did not create the {name} input.")
    if not selection_input.addSelectionFilter("Profiles"):
        raise RuntimeError(f"Fusion did not apply the sketch-profile filter to {name}.")
    if not selection_input.setSelectionLimits(1, 0):
        raise RuntimeError(f"Fusion did not configure the selection limits for {name}.")
    return selection_input


def _read_wire_pathway_id(
    command_inputs: adsk.core.CommandInputs,
    pathway_ids_by_name: dict[str, UUID],
) -> UUID:
    """
    Resolve the selected pathway label to its stable identity.
    """
    pathway_input = adsk.core.DropDownCommandInput.cast(
        command_inputs.itemById(WIRE_PATHWAY_INPUT_ID)
    )
    if pathway_input is None or pathway_input.selectedItem is None:
        raise ValueError("Select a pathway.")
    pathway_id = pathway_ids_by_name.get(pathway_input.selectedItem.name)
    if pathway_id is None:
        raise ValueError("Selected pathway is unavailable.")
    return pathway_id


def _read_wire_diameter_mm(command_inputs: adsk.core.CommandInputs) -> float:
    """
    Read a valid positive wire diameter and convert Fusion centimeters to millimeters.
    """
    diameter_input = adsk.core.ValueCommandInput.cast(
        command_inputs.itemById(WIRE_DIAMETER_INPUT_ID)
    )
    if diameter_input is None or not diameter_input.isValidExpression:
        raise ValueError("Wire diameter must be a valid length expression.")
    diameter_mm = diameter_input.value * 10.0
    if diameter_mm <= 0.0:
        raise ValueError("Wire diameter must be positive.")
    return diameter_mm


def _read_profile_tokens(
    command_inputs: adsk.core.CommandInputs,
    input_id: str,
    role: str,
) -> tuple[str, ...]:
    """
    Return selected Fusion profile tokens in user selection order.
    """
    selection_input = adsk.core.SelectionCommandInput.cast(command_inputs.itemById(input_id))
    if selection_input is None or selection_input.selectionCount < 1:
        raise ValueError(f"Select at least one {role} profile.")
    tokens: list[str] = []
    for index in range(selection_input.selectionCount):
        selection = selection_input.selection(index)
        profile = adsk.fusion.Profile.cast(selection.entity if selection is not None else None)
        if profile is None or not profile.entityToken.strip():
            raise ValueError(f"{role.title()} selection {index + 1} is not a valid sketch profile.")
        tokens.append(profile.entityToken)
    return tuple(tokens)


def _create_harness_gateway(application: adsk.core.Application) -> FusionHarnessGateway:
    """
    Create a gateway for the active Fusion design and cloud folder.

    Raises:
        RuntimeError: If no Fusion design is active.
    """
    design = adsk.fusion.Design.cast(application.activeProduct)
    if design is None:
        raise RuntimeError("Harness Builder requires an active Fusion design.")
    return FusionHarnessGateway(design, application.data.activeFolder)


def _read_pathway_name(command_inputs: adsk.core.CommandInputs) -> str:
    """
    Read and normalize the required pathway name input.
    """
    name_input = adsk.core.StringValueCommandInput.cast(
        command_inputs.itemById(PATHWAY_NAME_INPUT_ID)
    )
    if name_input is None:
        raise ValueError("Pathway name input is unavailable.")
    name = name_input.value.strip()
    if not name:
        raise ValueError("Pathway name must not be empty.")
    return name


def _read_pathway_gate_tokens(command_inputs: adsk.core.CommandInputs) -> tuple[str, ...]:
    """
    Return selected Fusion profile tokens in traversal order.
    """
    gate_input = adsk.core.SelectionCommandInput.cast(
        command_inputs.itemById(PATHWAY_GATES_INPUT_ID)
    )
    if gate_input is None or gate_input.selectionCount < 1:
        raise ValueError("Select at least one pathway gate profile.")

    tokens: list[str] = []
    for index in range(gate_input.selectionCount):
        selection = gate_input.selection(index)
        profile = adsk.fusion.Profile.cast(selection.entity if selection is not None else None)
        if profile is None or not profile.entityToken.strip():
            raise ValueError(f"Pathway gate selection {index + 1} is not a valid sketch profile.")
        tokens.append(profile.entityToken)
    return tuple(tokens)


def _read_harness_name(command_inputs: adsk.core.CommandInputs) -> str:
    """
    Read and normalize the required harness name input.
    """
    name_input = adsk.core.StringValueCommandInput.cast(
        command_inputs.itemById(HARNESS_NAME_INPUT_ID)
    )
    if name_input is None:
        raise ValueError("Harness name input is unavailable.")
    name = name_input.value.strip()
    if not name:
        raise ValueError("Harness name must not be empty.")
    return name


def _read_routing_mode(command_inputs: adsk.core.CommandInputs) -> RoutingMode:
    """
    Map the selected Fusion label to its routing-mode domain value.
    """
    mode_input = adsk.core.DropDownCommandInput.cast(command_inputs.itemById(ROUTING_MODE_INPUT_ID))
    if mode_input is None or mode_input.selectedItem is None:
        raise ValueError("Routing mode input is unavailable.")

    selected_label = mode_input.selectedItem.name
    for routing_mode, label in _ROUTING_MODE_LABELS.items():
        if selected_label == label:
            return routing_mode
    raise ValueError(f"Unsupported routing mode selection: {selected_label}")


def _generate_solids(application: adsk.core.Application, serialized_data: str) -> int:
    """
    Generate persistent wire bodies inside the palette command transaction.
    """
    payload = _read_palette_payload(serialized_data)
    harness_id = _read_payload_uuid(payload, "harnessId", "harness")
    replace_existing = payload.get("replaceExisting", False)
    if not isinstance(replace_existing, bool):
        raise ValueError("Rebuild confirmation must be a boolean.")
    gateway = _create_harness_gateway(application)
    definition = loads(gateway.read_harness_definition(harness_id))
    notices: list[str] = []
    count = generate_wire_solids(
        _require_active_design(application),
        gateway.harness_component(harness_id),
        definition,
        replace_existing,
        notices,
    )
    application.activeViewport.refresh()
    summary = f"Generated {count} wire solids."
    _send_palette_state(application, "\n".join((summary, *notices)))
    return count


def _clear_solids(application: adsk.core.Application, serialized_data: str) -> int:
    """
    Remove marked wire bodies inside the palette command transaction.
    """
    payload = _read_palette_payload(serialized_data)
    harness_id = _read_payload_uuid(payload, "harnessId", "harness")
    gateway = _create_harness_gateway(application)
    count = clear_wire_solids(gateway.harness_component(harness_id))
    application.activeViewport.refresh()
    _send_palette_state(application, f"Cleared {count} wire solids.")
    return count
