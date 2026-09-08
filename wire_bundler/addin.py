"""
Fusion 360 lifecycle and command registration.
"""

from __future__ import annotations

import json
import traceback
from dataclasses import asdict
from pathlib import Path
from typing import Optional, cast
from uuid import UUID, uuid4

# noinspection PyUnresolvedReferences
import adsk.core

# noinspection PyUnresolvedReferences
import adsk.fusion

from .application import (
    RelationshipMap,
    add_external_end,
    add_junction,
    add_junction_pigtail_end,
    add_pathway,
    add_wire_batch,
    append_pathway_gates,
    attach_pathway_to_junction,
    branch_all_junction_members,
    build_relationship_map,
    cleanup_orphaned_topology,
    create_empty_harness,
    detach_pathway_from_junction,
    disconnect_junction_member,
    disconnect_pathway_extension,
    extend_pathway_member,
    load_harnesses,
    load_wire_material_catalog,
    move_junction,
    move_pathway_gate,
    move_wire_endpoint,
    remove_external_end,
    remove_junction,
    remove_pathway_gate,
    remove_wire,
    rename_junction,
    rename_pathway,
    rename_pathway_extension,
    rename_route_end,
    rename_wire,
    set_harness_material_defaults,
    set_junction_diameter_factor,
    set_junction_member_disposition,
    set_wire_diameter,
    set_wire_material_overrides,
    suggest_harness_name,
    suggest_pathway_name,
)
from .application.edit_harness import edit_end_members, set_interpolation
from .domain import (
    Connection,
    HarnessDefinition,
    JunctionDisposition,
    PathwayEnd,
    RoutingMode,
    StripePattern,
    WireAppearanceReference,
    WireColor,
    WireMaterialOverrides,
    WireMaterialSettings,
    WireStripe,
    loads,
    pathway_exit_states,
)
from .domain.codec import parse_interpolation
from .fusion import (
    FusionHarnessGateway,
    clear_junction_slices,
    clear_route_previews,
    highlight_route_preview,
    show_junction_slices,
    show_route_previews,
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

COMMAND_ID = "kev0_wire_bundler_harness_builder"
CREATE_COMMAND_ID = "kev0_wire_bundler_create_harness"
ADD_PATHWAY_COMMAND_ID = "kev0_wire_bundler_add_pathway"
APPEND_GATES_COMMAND_ID = "kev0_wire_bundler_append_pathway_gates"
EDIT_END_COMMAND_ID = "kev0_wire_bundler_edit_end_members"
PICK_JUNCTION_PATHWAY_COMMAND_ID = "kev0_wire_bundler_pick_junction_pathway"
ADD_WIRES_COMMAND_ID = "kev0_wire_bundler_add_wires"
COMMAND_NAME = "Harness Builder"
COMMAND_DESCRIPTION = "Create and edit wire, ribbon, and harness assemblies."
CREATE_COMMAND_NAME = "Create Harness"
ADD_PATHWAY_COMMAND_NAME = "Add Pathway"
APPEND_GATES_COMMAND_NAME = "Add Gates"
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
_pending_append_gate_ids: Optional[tuple[UUID, UUID]] = None
_pending_end_edit: Optional[dict[str, object]] = None
_pending_junction_pathway_pick: Optional[dict[str, object]] = None
_pending_wire_harness_id: Optional[UUID] = None
_pending_wire_pathway_id: Optional[UUID] = None
_pending_palette_edit: Optional[tuple[str, str, object]] = None
_last_command_error = ""
_history_handler: Optional[_HistoryChangedHandler] = None
_document_saving_handler: Optional[_DocumentSavingHandler] = None
_document_saved_handler: Optional[_DocumentSavedHandler] = None
_graphics_cache_restore_value: Optional[bool] = None
_graphics_cache_save_document: Optional[object] = None
_PALETTE_EDIT_NAMES = {
    "add_junction": "Add Pathway Junction",
    "move_junction": "Move Pathway Junction",
    "set_junction_diameter_factor": "Change Junction Diameter Factor",
    "remove_junction": "Delete Pathway Junction",
    "rename_junction": "Rename Pathway Junction",
    "attach_junction_pathway": "Attach Pathway to Junction",
    "detach_junction_pathway": "Detach Pathway from Junction",
    "set_junction_disposition": "Change Junction Membership",
    "branch_all_junction_members": "Branch All Junction Members",
    "disconnect_junction_member": "Disconnect Junction Member",
    "extend_pathway_member": "Extend Wire Through Pathway",
    "disconnect_pathway_extension": "Disconnect Pathway Extension",
    "rename_pathway_extension": "Rename Pathway Extension",
    "remove_external_end": "Remove Wire End",
    "cleanup_orphaned_topology": "Clean Orphaned Topology",
    "move_pathway_gate": "Reorder Pathway Gates",
    "remove_pathway_gate": "Remove Pathway Gate",
    "move_wire_endpoint": "Reorder Wire Ends",
    "remove_wire": "Delete Wire",
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
            notice = _apply_palette_edit(application, action, data)
            harness_id = _read_payload_uuid(_read_palette_payload(data), "harnessId", "harness")
            if action in {"set_harness_material_defaults", "set_wire_material_overrides"}:
                notice = f"{notice} {_apply_generated_materials(application, harness_id)}".strip()
            if action in {
                "add_junction",
                "move_junction",
                "remove_junction",
                "set_junction_diameter_factor",
                "attach_junction_pathway",
                "detach_junction_pathway",
                "set_junction_disposition",
                "branch_all_junction_members",
                "disconnect_junction_member",
            }:
                _refresh_junction_slice_graphics(application, harness_id)
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
            if design is None or not has_route_previews(design):
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

        Args:
            args: Command event arguments supplied by Fusion.
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

        Args:
            args: Validation event arguments supplied by Fusion.
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

        Args:
            args: Command-created event arguments supplied by Fusion.
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

        Args:
            harness_id: Stable identity of the owning harness.
        """
        super().__init__()
        self._harness_id = harness_id

    # noinspection PyMethodMayBeStatic
    def notify(self, args: adsk.core.CommandEventArgs) -> None:
        """
        Add the selected gate profiles to the owning harness as one pathway.

        Args:
            args: Command event arguments supplied by Fusion.
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

        Args:
            args: Validation event arguments supplied by Fusion.
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

        Args:
            args: Command-created event arguments supplied by Fusion.
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
            if self._payload.get("editAction") == "topology_add_end":
                _apply_topology_end_selection(application, self._payload, tokens)
            else:
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
        maximum = 1 if payload.get("editAction") in {"replace", "topology_add_end"} else 0
        if not selection.setSelectionLimits(1, maximum):
            raise RuntimeError("Fusion could not set end-member selection limits.")
        execute_handler = _EditEndExecuteHandler(payload)
        validate_handler = _AppendGatesValidateInputsHandler()
        if not args.command.execute.add(execute_handler):
            raise RuntimeError("Fusion could not register the end edit handler.")
        if not args.command.validateInputs.add(validate_handler):
            raise RuntimeError("Fusion could not register end edit validation.")
        _handlers.extend((execute_handler, validate_handler))


class _PickJunctionPathwayExecuteHandler(adsk.core.CommandEventHandler):
    """
    Create a junction on the pathway identified by a mouse-selected gate.
    """

    def __init__(self, payload: dict[str, object]) -> None:
        """
        Retain the pending harness and location while Fusion owns selection.
        """
        super().__init__()
        self._payload = payload

    def notify(self, args: adsk.core.CommandEventArgs) -> None:
        """
        Resolve the selected profile to exactly one pathway and add its junction.
        """
        try:
            application = adsk.core.Application.get()
            token = _read_pathway_gate_tokens(args.command.commandInputs)[0]
            harness_id = _read_payload_uuid(self._payload, "harnessId", "harness")
            gateway = _create_harness_gateway(application)
            definition = loads(gateway.read_harness_definition(harness_id))
            control_ids = {
                control.control_id
                for control in definition.controls
                if control.entity_token == token
            }
            matches = [
                (pathway, control_id)
                for pathway in definition.pathways
                for control_id in pathway.ordered_control_ids
                if control_id in control_ids
            ]
            if not matches:
                raise ValueError("The selected profile is not a gate in this harness.")
            pathway_ids = {pathway.pathway_id for pathway, _control_id in matches}
            if len(pathway_ids) != 1:
                raise ValueError("The selected gate belongs to more than one pathway.")
            pathway, control_id = matches[0]
            junction = add_junction(
                harness_id,
                pathway.pathway_id,
                _read_payload_number(self._payload, "distanceMm", "junction distance"),
                gateway,
                slice_control_id=control_id,
            )
            show_junction_slices(
                _require_active_design(application),
                loads(gateway.read_harness_definition(harness_id)),
            )
            application.activeViewport.refresh()
            _send_palette_state(application, f"Added {junction.name} on {pathway.name}.")
        except (AttributeError, RuntimeError, TypeError, ValueError):
            _report_failure("pick a junction pathway")


class _PickJunctionPathwayCreatedHandler(adsk.core.CommandCreatedEventHandler):
    """
    Open a single-profile mouse picker for selecting a pathway gate.
    """

    # noinspection PyMethodMayBeStatic
    def notify(self, args: adsk.core.CommandCreatedEventArgs) -> None:
        """
        Configure the profile picker and retain its execution handlers.
        """
        global _pending_junction_pathway_pick
        payload = _pending_junction_pathway_pick
        _pending_junction_pathway_pick = None
        if payload is None:
            raise RuntimeError("No junction pathway selection was requested.")
        selection = _add_profile_selection_input(
            args.command.commandInputs,
            PATHWAY_GATES_INPUT_ID,
            "Pathway Gate",
            "Select a visible gate profile on the junction's pathway",
        )
        if not selection.setSelectionLimits(1, 1):
            raise RuntimeError("Fusion could not configure junction pathway selection.")
        execute_handler = _PickJunctionPathwayExecuteHandler(payload)
        validate_handler = _AppendGatesValidateInputsHandler()
        if not args.command.execute.add(execute_handler):
            raise RuntimeError("Fusion could not register junction pathway selection.")
        if not args.command.validateInputs.add(validate_handler):
            raise RuntimeError("Fusion could not validate junction pathway selection.")
        _handlers.extend((execute_handler, validate_handler))


class _AppendGatesExecuteHandler(adsk.core.CommandEventHandler):
    """
    Append selected sketch profiles to an existing pathway.
    """

    def __init__(self, harness_id: UUID, pathway_id: UUID) -> None:
        """
        Bind the handler to the selected harness and pathway.

        Args:
            harness_id: Stable identity of the owning harness.
            pathway_id: Stable identity of the pathway being extended.
        """
        super().__init__()
        self._harness_id = harness_id
        self._pathway_id = pathway_id

    def notify(self, args: adsk.core.CommandEventArgs) -> None:
        """
        Persist the selected profiles at the end of the pathway.

        Args:
            args: Command event arguments supplied by Fusion.
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

        Args:
            args: Command-created event arguments supplied by Fusion.
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

        Args:
            args: Validation event arguments supplied by Fusion.
        """
        try:
            _read_pathway_gate_tokens(args.inputs)
        except ValueError:
            args.areInputsValid = False
            return
        args.areInputsValid = True


class _AddWiresExecuteHandler(adsk.core.CommandEventHandler):
    """
    Persist ordered End A-to-End B wire assignments.
    """

    def __init__(self, harness_id: UUID, pathway_ids_by_name: dict[str, UUID]) -> None:
        """
        Bind the handler to one harness and its displayed pathway choices.

        Args:
            harness_id: Stable identity of the owning harness.
            pathway_ids_by_name: Displayed pathway names mapped to stable identities.
        """
        super().__init__()
        self._harness_id = harness_id
        self._pathway_ids_by_name = pathway_ids_by_name

    def notify(self, args: adsk.core.CommandEventArgs) -> None:
        """
        Pair endpoint selections in order and add their logical wire mappings.

        Args:
            args: Command event arguments supplied by Fusion.
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

        Args:
            pathway_ids_by_name: Displayed pathway names mapped to stable identities.
        """
        super().__init__()
        self._pathway_ids_by_name = pathway_ids_by_name

    def notify(self, args: adsk.core.ValidateInputsEventArgs) -> None:
        """
        Validate the complete wire batch before Fusion enables execution.

        Args:
            args: Validation event arguments supplied by Fusion.
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

        Args:
            args: Command-created event arguments supplied by Fusion.
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

        Args:
            _args: Command-created event arguments supplied by Fusion.
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

        Args:
            args: HTML event arguments supplied by Fusion.
        """
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
            if html_args.action == "edit_end_members":
                _open_end_member_edit(application, html_args.data)
                html_args.returnData = json.dumps({"ok": True})
                return
            if html_args.action == "pick_junction_pathway":
                _open_junction_pathway_picker(application, html_args.data)
                html_args.returnData = json.dumps({"ok": True})
                return
            if html_args.action == "append_pathway_gates":
                _open_append_gates_command(application, html_args.data)
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

        Args:
            args: Navigation event arguments supplied by Fusion.
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

    Args:
        _context: Context object supplied by Fusion.
    """
    global _history_handler
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

        junction_picker_definition = user_interface.commandDefinitions.addButtonDefinition(
            PICK_JUNCTION_PATHWAY_COMMAND_ID,
            "Pick Junction Pathway",
            "Select a visible gate profile to identify a junction pathway.",
            ADD_PATHWAY_RESOURCE_FOLDER,
        )
        if junction_picker_definition is None:
            raise RuntimeError("Fusion could not create junction pathway selection.")
        junction_picker_handler = _PickJunctionPathwayCreatedHandler()
        if not junction_picker_definition.commandCreated.add(junction_picker_handler):
            raise RuntimeError("Fusion could not register junction pathway selection.")
        _handlers.append(junction_picker_handler)

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
    except Exception:
        _report_failure("start")
        raise


def stop(_context: object) -> None:
    """
    Remove the command and release retained Fusion event handlers.

    Args:
        _context: Context object supplied by Fusion.
    """
    global _pending_append_gate_ids, _pending_pathway_harness_id, _pending_end_edit
    global _pending_wire_harness_id, _pending_wire_pathway_id, _pending_palette_edit
    global _pending_junction_pathway_pick

    try:
        application = adsk.core.Application.get()
        design = adsk.fusion.Design.cast(application.activeProduct)
        if design is not None:
            clear_route_previews(design)
            clear_junction_slices(design)
        _remove_document_handlers(application)
        _remove_user_interface(application.userInterface)
        _handlers.clear()
        reset_preview_history()
        _pending_palette_edit = None
        _pending_append_gate_ids = None
        _pending_end_edit = None
        _pending_junction_pathway_pick = None
        _pending_pathway_harness_id = None
        _pending_wire_harness_id = None
        _pending_wire_pathway_id = None
    except Exception:
        _report_failure("stop")
        raise


def _remove_user_interface(user_interface: adsk.core.UserInterface) -> None:
    """
    Remove stale command controls and definitions if they exist.

    Args:
        user_interface: Active Fusion user interface.
    """
    global _history_handler
    if _history_handler is not None:
        user_interface.commandTerminated.remove(_history_handler)
        _history_handler = None
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
        APPEND_GATES_COMMAND_ID,
        EDIT_END_COMMAND_ID,
        PICK_JUNCTION_PATHWAY_COMMAND_ID,
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

    Args:
        application: Active Fusion application.
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
    palette.dockingOption = adsk.core.PaletteDockingOptions.PaletteDockOptionsToVerticalOnly
    palette.dockingState = adsk.core.PaletteDockingStates.PaletteDockStateRight
    palette.isVisible = True
    try:
        design = _require_active_design(application)
    except (AttributeError, RuntimeError):
        design = None
    if design is not None:
        for result in load_harnesses(_create_harness_gateway(application)):
            if result.definition is not None:
                show_junction_slices(design, result.definition)
    _send_palette_state(application)


def _refresh_junction_slice_graphics(
    application: adsk.core.Application,
    harness_id: UUID,
) -> None:
    """
    Synchronize visible gate-backed junction slices after one saved edit.
    """
    definition = loads(_create_harness_gateway(application).read_harness_definition(harness_id))
    show_junction_slices(_require_active_design(application), definition)


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

    Args:
        application: Active Fusion application.
        notice: Optional user-facing status message.
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

    Args:
        application: Active Fusion application.
        notice: Optional user-facing status message.

    Returns:
        JSON object consumed by the local palette.
    """
    gateway = _create_harness_gateway(application)
    results = load_harnesses(gateway)
    catalog = load_wire_material_catalog()
    harnesses: list[dict[str, object]] = []
    for result in results:
        definition = result.definition
        if definition is None:
            harnesses.append(
                {
                    "componentName": result.component_name,
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
                        "hasLinkedGeometry": gateway.is_entity_token_resolvable(
                            control.entity_token
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
                "topology": _topology_payload(definition),
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
        "units": _document_units_payload(application),
    }
    return json.dumps(payload, sort_keys=True)


def _document_units_payload(application: adsk.core.Application) -> dict[str, object]:
    """
    Describe the active document length unit and its canonical millimeter scale.
    """
    active_product = getattr(application, "activeProduct", None)
    design_type = getattr(adsk.fusion, "Design", None)
    design_cast = getattr(design_type, "cast", None)
    if not callable(design_cast):
        return {"length": "mm", "millimetersPerUnit": 1.0}
    # noinspection PyCallingNonCallable
    design = design_cast(active_product)
    units_manager = getattr(design, "unitsManager", None)
    unit_name = getattr(units_manager, "defaultLengthUnits", None)
    if not isinstance(unit_name, str) or not unit_name:
        return {"length": "mm", "millimetersPerUnit": 1.0}
    convert_units = getattr(units_manager, "convert", None)
    if not callable(convert_units):
        return {"length": "mm", "millimetersPerUnit": 1.0}
    # noinspection PyCallingNonCallable
    millimeters_per_unit = convert_units(1.0, unit_name, "mm")
    if (
        isinstance(millimeters_per_unit, bool)
        or not isinstance(millimeters_per_unit, (int, float))
        or millimeters_per_unit <= 0
    ):
        return {"length": "mm", "millimetersPerUnit": 1.0}
    return {
        "length": unit_name,
        "millimetersPerUnit": float(millimeters_per_unit),
    }


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
        "topologyNodes": [
            {
                "nodeId": node.node_id,
                "kind": node.kind.value,
                "memberId": str(node.member_id),
                "label": node.label,
                "missing": node.missing,
            }
            for node in relationship_map.topology_nodes
        ],
        "topologyEdges": [
            {
                "edgeId": edge.edge_id,
                "physicalWireId": str(edge.wire_id),
                "sourceNodeId": edge.source_node_id,
                "targetNodeId": edge.target_node_id,
                "sequence": edge.sequence,
            }
            for edge in relationship_map.topology_edges
        ],
        "topologyRoutes": [
            {
                "routeId": route.route_id,
                "physicalWireId": str(route.wire_id),
                "networkId": None if route.network_id is None else str(route.network_id),
                "primaryWireId": (
                    None if route.primary_wire_id is None else str(route.primary_wire_id)
                ),
                "wireNumber": route.wire_number,
                "label": route.label,
                "nodeIds": list(route.node_ids),
                "edgeIds": list(route.edge_ids),
            }
            for route in relationship_map.topology_routes
        ],
        "spanOccupancy": [
            {
                "pathwayId": str(item.pathway_id),
                "firstNodeId": str(item.first_node_id),
                "secondNodeId": str(item.second_node_id),
                "physicalWireIds": [str(wire_id) for wire_id in item.physical_wire_ids],
            }
            for item in relationship_map.span_occupancy
        ],
    }


def _topology_payload(definition: HarnessDefinition) -> Optional[dict[str, object]]:
    """
    Expose explicit editable topology metadata to the local palette.
    """
    topology = definition.topology
    if topology is None:
        return None
    return {
        "nodes": [
            {
                "nodeId": str(node.node_id),
                "kind": node.kind.value,
                "pathwayId": None if node.pathway_id is None else str(node.pathway_id),
                "pathwayEnd": None if node.pathway_end is None else node.pathway_end.value,
                "connectionId": (None if node.connection_id is None else str(node.connection_id)),
                "physicalWireId": (
                    None if node.physical_wire_id is None else str(node.physical_wire_id)
                ),
                "distanceMm": node.distance_mm,
                "sliceControlId": (
                    None if node.slice_control_id is None else str(node.slice_control_id)
                ),
                "diameterFactor": node.junction_diameter_factor_override,
                "name": node.name,
            }
            for node in topology.nodes
        ],
        "physicalWires": [
            {
                "physicalWireId": str(wire.physical_wire_id),
                "networkId": str(wire.network_id),
                "profileId": str(wire.profile_id),
            }
            for wire in topology.physical_wires
        ],
        "edges": [
            {
                "edgeId": str(edge.edge_id),
                "kind": edge.kind.value,
                "physicalWireId": str(edge.physical_wire_id),
                "startNodeId": str(edge.start_node_id),
                "endNodeId": str(edge.end_node_id),
                "pathwayId": None if edge.pathway_id is None else str(edge.pathway_id),
                "name": edge.name,
            }
            for edge in topology.edges
        ],
        "junctionAttachments": [
            {
                "junctionId": str(item.junction_id),
                "pathwayId": str(item.pathway_id),
                "pathwayEnd": item.pathway_end.value,
            }
            for item in topology.junction_attachments
        ],
        "junctionDispositions": [
            {
                "junctionId": str(item.junction_id),
                "pathwayId": str(item.attachment_pathway_id),
                "pathwayEnd": item.attachment_end.value,
                "incomingWireId": str(item.incoming_wire_id),
                "disposition": item.disposition.value,
                "branchWireId": (None if item.branch_wire_id is None else str(item.branch_wire_id)),
            }
            for item in topology.junction_dispositions
        ],
        "exitStates": [
            {
                "pathwayId": str(item.pathway_id),
                "pathwayEnd": item.pathway_end.value,
                "physicalWireId": str(item.physical_wire_id),
                "state": item.state.value,
            }
            for item in pathway_exit_states(topology)
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

    Args:
        operation: Lifecycle operation that failed.
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

    Args:
        message: Diagnostic text to record.
    """
    adsk.core.Application.log(
        message,
        adsk.core.LogLevels.InfoLogLevel,
        adsk.core.LogTypes.FileLogType,
    )


def _open_add_pathway_command(application: adsk.core.Application, serialized_data: str) -> None:
    """
    Open the native pathway command for the harness selected in the palette.

    Args:
        application: Active Fusion application.
        serialized_data: Palette JSON containing the selected harness identity.

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


def _open_end_member_edit(application: adsk.core.Application, serialized_data: str) -> None:
    """
    Open the native member picker for a validated palette request.
    """
    global _pending_end_edit
    payload = _read_palette_payload(serialized_data)
    if payload.get("editAction") not in {"add", "replace", "topology_add_end"}:
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


def _open_junction_pathway_picker(
    application: adsk.core.Application,
    serialized_data: str,
) -> None:
    """
    Open native profile selection used to identify a junction's pathway.
    """
    global _pending_junction_pathway_pick
    payload = _read_palette_payload(serialized_data)
    command = application.userInterface.commandDefinitions.itemById(
        PICK_JUNCTION_PATHWAY_COMMAND_ID
    )
    if command is None:
        raise RuntimeError("Junction pathway selection is unavailable.")
    _pending_junction_pathway_pick = payload
    try:
        if not command.execute():
            raise RuntimeError("Fusion could not open junction pathway selection.")
    except (AttributeError, RuntimeError, TypeError, ValueError):
        _pending_junction_pathway_pick = None
        raise


def _apply_topology_end_selection(
    application: adsk.core.Application,
    payload: dict[str, object],
    tokens: tuple[str, ...],
) -> None:
    """
    Turn one selected Fusion profile into a stable external topology end.
    """
    if len(tokens) != 1:
        raise ValueError("A wire end requires exactly one selected profile.")
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("A wire end requires a name.")
    connection = Connection(uuid4(), name.strip(), tokens[0])
    gateway = _create_harness_gateway(application)
    harness_id = _read_payload_uuid(payload, "harnessId", "harness")
    physical_wire_id = _read_payload_uuid(payload, "physicalWireId", "physical wire")
    if "junctionId" in payload:
        add_junction_pigtail_end(
            harness_id,
            _read_payload_uuid(payload, "junctionId", "junction"),
            physical_wire_id,
            connection,
            gateway,
        )
    else:
        add_external_end(
            harness_id,
            physical_wire_id,
            _read_payload_uuid(payload, "pathwayId", "pathway"),
            _read_pathway_end(payload),
            connection,
            gateway,
        )


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

    Args:
        application: Active Fusion application.
        serialized_data: Palette JSON containing harness and pathway identities.
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


def _open_add_wires_command(application: adsk.core.Application, serialized_data: str) -> None:
    """
    Open the native wire-assignment command for the selected harness.

    Args:
        application: Active Fusion application.
        serialized_data: Palette JSON containing the selected harness identity.

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

    Args:
        application: Active Fusion application.
        action: Supported edit action name.
        serialized_data: JSON payload containing stable member identities.

    Returns:
        Concise user-facing success notice.
    """
    payload = _read_palette_payload(serialized_data)
    harness_id = _read_payload_uuid(payload, "harnessId", "harness")
    gateway = _create_harness_gateway(application)
    if action == "add_junction":
        junction = add_junction(
            harness_id,
            _read_payload_uuid(payload, "pathwayId", "parent pathway"),
            _read_payload_number(payload, "distanceMm", "junction distance"),
            gateway,
            slice_control_id=_read_optional_payload_uuid(
                payload,
                "sliceControlId",
                "slice control",
            ),
            junction_diameter_factor_override=_read_optional_payload_number(
                payload,
                "diameterFactor",
                "junction diameter factor",
            ),
        )
        return f"Added junction {str(junction.node_id)[:8]}."
    if action == "move_junction":
        move_junction(
            harness_id,
            _read_payload_uuid(payload, "junctionId", "junction"),
            _read_payload_number(payload, "distanceMm", "junction distance"),
            gateway,
        )
        return "Moved junction."
    if action == "rename_junction":
        name = payload.get("name")
        if not isinstance(name, str):
            raise ValueError("Junction rename request requires a text name.")
        renamed = rename_junction(
            harness_id,
            _read_payload_uuid(payload, "junctionId", "junction"),
            name,
            gateway,
        )
        return f"Renamed junction to {renamed.name}."
    if action == "set_junction_diameter_factor":
        set_junction_diameter_factor(
            harness_id,
            _read_payload_uuid(payload, "junctionId", "junction"),
            _read_optional_payload_number(payload, "diameterFactor", "junction diameter factor"),
            gateway,
        )
        return "Updated junction diameter factor."
    if action == "remove_junction":
        remove_junction(
            harness_id,
            _read_payload_uuid(payload, "junctionId", "junction"),
            gateway,
        )
        return "Removed junction."
    if action == "attach_junction_pathway":
        attach_pathway_to_junction(
            harness_id,
            _read_payload_uuid(payload, "junctionId", "junction"),
            _read_payload_uuid(payload, "pathwayId", "pathway"),
            _read_pathway_end(payload),
            gateway,
        )
        return "Attached pathway to junction."
    if action == "detach_junction_pathway":
        detach_pathway_from_junction(
            harness_id,
            _read_payload_uuid(payload, "junctionId", "junction"),
            _read_payload_uuid(payload, "pathwayId", "pathway"),
            _read_pathway_end(payload),
            gateway,
        )
        return "Detached pathway from junction."
    if action == "set_junction_disposition":
        disposition = payload.get("disposition")
        if not isinstance(disposition, str):
            raise ValueError("Junction membership requires a disposition.")
        try:
            parsed_disposition = JunctionDisposition(disposition)
        except ValueError as error:
            raise ValueError("Junction disposition is unsupported.") from error
        set_junction_member_disposition(
            harness_id,
            _read_payload_uuid(payload, "junctionId", "junction"),
            _read_payload_uuid(payload, "pathwayId", "pathway"),
            _read_pathway_end(payload),
            _read_payload_uuid(payload, "physicalWireId", "physical wire"),
            parsed_disposition,
            gateway,
        )
        return "Updated junction membership."
    if action == "branch_all_junction_members":
        created = branch_all_junction_members(
            harness_id,
            _read_payload_uuid(payload, "junctionId", "junction"),
            _read_payload_uuid(payload, "pathwayId", "pathway"),
            _read_pathway_end(payload),
            gateway,
        )
        return f"Branched {len(created)} junction members."
    if action == "disconnect_junction_member":
        disconnect_junction_member(
            harness_id,
            _read_payload_uuid(payload, "junctionId", "junction"),
            _read_payload_uuid(payload, "pathwayId", "pathway"),
            _read_pathway_end(payload),
            _read_payload_uuid(payload, "physicalWireId", "physical wire"),
            gateway,
        )
        return "Disconnected junction member."
    if action == "cleanup_orphaned_topology":
        removed_ids = cleanup_orphaned_topology(harness_id, gateway)
        return f"Removed {len(removed_ids)} orphaned physical legs."
    if action == "extend_pathway_member":
        extend_pathway_member(
            harness_id,
            _read_payload_uuid(payload, "physicalWireId", "physical wire"),
            _read_payload_uuid(payload, "sourcePathwayId", "source pathway"),
            _read_pathway_end(payload, "sourceEnd"),
            _read_payload_uuid(payload, "targetPathwayId", "target pathway"),
            _read_pathway_end(payload, "targetEnd"),
            gateway,
        )
        return "Extended wire through pathway."
    if action == "disconnect_pathway_extension":
        disconnect_pathway_extension(
            harness_id,
            _read_payload_uuid(payload, "edgeId", "extension edge"),
            gateway,
        )
        return "Disconnected pathway extension."
    if action == "rename_pathway_extension":
        name = payload.get("name")
        if not isinstance(name, str):
            raise ValueError("Extension rename request requires a text name.")
        renamed = rename_pathway_extension(
            harness_id,
            _read_payload_uuid(payload, "edgeId", "extension"),
            name,
            gateway,
        )
        return f"Renamed extension to {renamed.name}."
    if action == "remove_external_end":
        remove_external_end(
            harness_id,
            _read_payload_uuid(payload, "nodeId", "external end"),
            gateway,
        )
        return "Removed wire end."
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
    if action in {"rename_pathway", "rename_wire"}:
        name = payload.get("name")
        if not isinstance(name, str):
            raise ValueError("Rename request requires a text name.")
        if action == "rename_wire":
            rename_wire(harness_id, _read_payload_uuid(payload, "wireId", "wire"), name, gateway)
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

    Args:
        application: Active Fusion application.
        serialized_data: JSON payload identifying the member to reveal.

    Returns:
        Number of preview lines, profiles, and bodies emphasized.
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
    if member_type in {"pathway", "pathway_gates", "pathway_wires"}:
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
        tokens = tuple(
            controls[control_id].entity_token
            for control_id in control_ids
            if control_id in controls
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
    return preview_count + len(profiles) + len(bodies)


def _clear_highlight(application: adsk.core.Application) -> None:
    """
    Clear palette-driven viewport selection.

    Args:
        application: Active Fusion application.
    """
    highlight_route_preview(_require_active_design(application), None)
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

    Args:
        definition: Parsed harness definition.
        member_type: ``control``, ``connection``, or ``wire``.
        member_id: Stable member identity.

    Returns:
        One gate/connection token or both endpoint tokens for a wire.
    """
    if member_type == "control":
        control = next(
            (item for item in definition.controls if item.control_id == member_id),
            None,
        )
        if control is None:
            raise ValueError("Selected routing gate no longer exists.")
        return (control.entity_token,)
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


def _read_optional_payload_uuid(
    payload: dict[str, object],
    key: str,
    label: str,
) -> Optional[UUID]:
    """
    Read one nullable stable identity from a palette payload.
    """
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"Harness Builder {label} identity must be text or null.")
    return UUID(value)


def _read_payload_number(
    payload: dict[str, object],
    key: str,
    label: str,
) -> float:
    """
    Read one required finite numeric palette value.
    """
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Harness Builder request requires a numeric {label}.")
    return float(value)


def _read_optional_payload_number(
    payload: dict[str, object],
    key: str,
    label: str,
) -> Optional[float]:
    """
    Read one nullable numeric palette value.
    """
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Harness Builder {label} must be numeric or null.")
    return float(value)


def _read_pathway_end(
    payload: dict[str, object],
    key: str = "pathwayEnd",
) -> PathwayEnd:
    """
    Read a stable A/B pathway endpoint from a topology request.
    """
    value = payload.get(key)
    if not isinstance(value, str):
        raise ValueError("Harness Builder request requires a pathway end.")
    try:
        return PathwayEnd(value.lower())
    except ValueError as error:
        raise ValueError("Pathway end must be A or B.") from error


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

    Args:
        application: Active Fusion application.
        serialized_data: Palette JSON containing the selected harness identity.

    Returns:
        Number of displayed wire routes.
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

    Args:
        application: Active Fusion application.

    Returns:
        Active Fusion design.
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

    Args:
        command_inputs: Inputs owned by the active Add Wires command.
        input_id: Stable input identity.
        name: User-facing field name.
        prompt: Selection prompt displayed by Fusion.

    Returns:
        Configured profile-selection input.
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

    Args:
        command_inputs: Inputs owned by the active Add Wires command.
        pathway_ids_by_name: Displayed pathway names mapped to stable identities.

    Returns:
        Selected pathway identity.
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

    Args:
        command_inputs: Inputs owned by the active Add Wires command.

    Returns:
        Wire diameter in millimeters.
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

    Args:
        command_inputs: Inputs owned by the active Add Wires command.
        input_id: Selection input identity.
        role: Endpoint role used in validation messages.

    Returns:
        Persistent entity tokens in selection order.
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

    Args:
        application: Active Fusion application.

    Returns:
        Gateway bound to the current design context.

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

    Args:
        command_inputs: Inputs owned by the active Add Pathway command.

    Returns:
        Non-empty normalized pathway name.
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

    Args:
        command_inputs: Inputs owned by the active Add Pathway command.

    Returns:
        Persistent entity tokens in Fusion selection order.
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

    Args:
        command_inputs: Inputs owned by the active Harness Builder command.

    Returns:
        Non-empty normalized harness name.
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

    Args:
        command_inputs: Inputs owned by the active Harness Builder command.

    Returns:
        Selected routing mode.
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
