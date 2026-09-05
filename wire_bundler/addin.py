"""
Fusion 360 lifecycle and command registration.
"""

from __future__ import annotations

import json
import traceback
from pathlib import Path
from typing import Optional
from uuid import UUID

# noinspection PyUnresolvedReferences
import adsk.core

# noinspection PyUnresolvedReferences
import adsk.fusion

from .application import (
    add_pathway,
    add_wire_batch,
    create_empty_harness,
    load_harnesses,
    suggest_harness_name,
    suggest_pathway_name,
)
from .domain import RoutingMode, loads
from .fusion import FusionHarnessGateway, clear_route_previews, show_route_previews

COMMAND_ID = "kev0_wire_bundler_harness_builder"
CREATE_COMMAND_ID = "kev0_wire_bundler_create_harness"
ADD_PATHWAY_COMMAND_ID = "kev0_wire_bundler_add_pathway"
ADD_WIRES_COMMAND_ID = "kev0_wire_bundler_add_wires"
COMMAND_NAME = "Harness Builder"
COMMAND_DESCRIPTION = "Create and edit wire, ribbon, and harness assemblies."
CREATE_COMMAND_NAME = "Create Harness"
ADD_PATHWAY_COMMAND_NAME = "Add Pathway"
ADD_WIRES_COMMAND_NAME = "Add Wires"
PALETTE_ID = "kev0_wire_bundler_harness_builder_palette"
PALETTE_HTML_URL = "palette.html"
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

_ROUTING_MODE_LABELS = {
    RoutingMode.ROUTING_GATES: "Routing Gates",
    RoutingMode.PROFILE_GATES: "Profile Gates",
}

_handlers: list[object] = []
_pending_pathway_harness_id: Optional[UUID] = None
_pending_wire_harness_id: Optional[UUID] = None


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


class _AddWiresExecuteHandler(adsk.core.CommandEventHandler):
    """
    Persist ordered source-to-destination wire assignments.
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
                _read_profile_tokens(command_inputs, SOURCE_CONNECTIONS_INPUT_ID, "source"),
                _read_profile_tokens(
                    command_inputs,
                    DESTINATION_CONNECTIONS_INPUT_ID,
                    "destination",
                ),
                _read_wire_diameter_mm(command_inputs),
                _create_harness_gateway(application),
            )
            _send_palette_state(application, f"Created {len(result.wires)} wires.")
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
            sources = _read_profile_tokens(args.inputs, SOURCE_CONNECTIONS_INPUT_ID, "source")
            destinations = _read_profile_tokens(
                args.inputs,
                DESTINATION_CONNECTIONS_INPUT_ID,
                "destination",
            )
            if len(sources) != len(destinations):
                raise ValueError("Source and destination profile counts must match.")
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
        global _pending_wire_harness_id

        harness_id = _pending_wire_harness_id
        _pending_wire_harness_id = None
        try:
            if harness_id is None:
                raise RuntimeError("No harness was selected for wire assignment.")
            application = adsk.core.Application.get()
            gateway = _create_harness_gateway(application)
            definition = loads(gateway.read_harness_definition(harness_id))
            if not definition.pathways:
                raise RuntimeError("Create a pathway before adding wires.")
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
                if pathway_input.listItems.add(pathway.name, index == 0) is None:
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

            source_input = _add_profile_selection_input(
                command_inputs,
                SOURCE_CONNECTIONS_INPUT_ID,
                "Ordered Source Profiles",
                "Select each source profile in wire order",
            )
            destination_input = _add_profile_selection_input(
                command_inputs,
                DESTINATION_CONNECTIONS_INPUT_ID,
                "Ordered Destination Profiles",
                "Select matching destination profiles in the same order",
            )
            source_input.hasFocus = True
            destination_input.hasFocus = False

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
            if html_args.action == "add_wires":
                _open_add_wires_command(application, html_args.data)
                html_args.returnData = json.dumps({"ok": True})
                return
            if html_args.action == "preview_routes":
                try:
                    route_count = _preview_routes(application, html_args.data)
                except (RuntimeError, ValueError) as error:
                    html_args.returnData = json.dumps({"ok": False, "error": str(error)})
                    _log_to_fusion(f"Harness route preview rejected: {error}")
                    return
                html_args.returnData = json.dumps({"ok": True, "routeCount": route_count})
                return
            if html_args.action == "clear_preview":
                design = _require_active_design(application)
                clear_route_previews(design)
                application.activeViewport.refresh()
                _send_palette_state(application, "Cleared route preview.")
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
    try:
        application = adsk.core.Application.get()
        user_interface = application.userInterface
        _remove_user_interface(user_interface)

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

        wire_command_definition = user_interface.commandDefinitions.addButtonDefinition(
            ADD_WIRES_COMMAND_ID,
            ADD_WIRES_COMMAND_NAME,
            "Assign ordered source and destination profiles to an existing pathway.",
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
    global _pending_pathway_harness_id, _pending_wire_harness_id

    try:
        application = adsk.core.Application.get()
        design = adsk.fusion.Design.cast(application.activeProduct)
        if design is not None:
            clear_route_previews(design)
        _remove_user_interface(application.userInterface)
        _handlers.clear()
        _pending_pathway_harness_id = None
        _pending_wire_harness_id = None
    except Exception:
        _report_failure("stop")
        raise


def _remove_user_interface(user_interface: adsk.core.UserInterface) -> None:
    """
    Remove stale command controls and definitions if they exist.

    Args:
        user_interface: Active Fusion user interface.
    """
    workspace = user_interface.workspaces.itemById(WORKSPACE_ID)
    if workspace is not None:
        for panel_id in PANEL_IDS:
            panel = workspace.toolbarPanels.itemById(panel_id)
            if panel is not None:
                control = panel.controls.itemById(COMMAND_ID)
                if control is not None:
                    control.deleteMe()

    command_definition = user_interface.commandDefinitions.itemById(COMMAND_ID)
    if command_definition:
        command_definition.deleteMe()
    create_command_definition = user_interface.commandDefinitions.itemById(CREATE_COMMAND_ID)
    if create_command_definition:
        create_command_definition.deleteMe()
    pathway_command_definition = user_interface.commandDefinitions.itemById(ADD_PATHWAY_COMMAND_ID)
    if pathway_command_definition:
        pathway_command_definition.deleteMe()
    wire_command_definition = user_interface.commandDefinitions.itemById(ADD_WIRES_COMMAND_ID)
    if wire_command_definition:
        wire_command_definition.deleteMe()
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
        if not PALETTE_HTML_FILE.is_file():
            raise RuntimeError(f"Harness Builder palette file is missing: {PALETTE_HTML_FILE}")
        palette = user_interface.palettes.add(
            PALETTE_ID,
            COMMAND_NAME,
            PALETTE_HTML_URL,
            True,
            True,
            True,
            420,
            620,
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
    else:
        palette.isVisible = True
    _send_palette_state(application)


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
        harnesses.append(
            {
                "componentName": result.component_name,
                "definitionName": definition.name,
                "harnessId": str(definition.harness_id),
                "schemaVersion": definition.schema_version,
                "routingMode": _ROUTING_MODE_LABELS[definition.routing_mode],
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
                        "connectionId": str(connection.connection_id),
                        "name": connection.name,
                        "hasLinkedGeometry": gateway.is_entity_token_resolvable(
                            connection.entity_token
                        ),
                    }
                    for connection in definition.connections
                ],
                "controls": [
                    {
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
                        "startConnectionId": str(wire.start_connection_id),
                        "endConnectionId": str(wire.end_connection_id),
                        "profileId": str(wire.profile_id),
                        "orderedPathwayIds": [
                            str(pathway_id) for pathway_id in wire.ordered_pathway_ids
                        ],
                        "orderedControlIds": [
                            str(control_id) for control_id in wire.ordered_control_ids
                        ],
                    }
                    for wire in definition.wires
                ],
                "status": "draft" if result.validation_messages else "valid",
                "validationMessages": result.validation_messages,
            }
        )
    payload = {"harnesses": harnesses, "notice": notice, "ok": True}
    return json.dumps(payload, sort_keys=True)


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
    global _pending_wire_harness_id

    payload = json.loads(serialized_data)
    if not isinstance(payload, dict):
        raise ValueError("Add Wires request must be a JSON object.")
    raw_harness_id = payload.get("harnessId")
    if not isinstance(raw_harness_id, str):
        raise ValueError("Add Wires request is missing a harness identity.")
    harness_id = UUID(raw_harness_id)
    command_definition = application.userInterface.commandDefinitions.itemById(ADD_WIRES_COMMAND_ID)
    if command_definition is None:
        raise RuntimeError("Fusion Add Wires command is unavailable.")

    _pending_wire_harness_id = harness_id
    try:
        if not command_definition.execute():
            raise RuntimeError("Fusion did not open the Add Wires command.")
    except Exception:
        _pending_wire_harness_id = None
        raise


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
    routes = show_route_previews(design, definition)
    application.activeViewport.refresh()
    _send_palette_state(application, f"Previewing {len(routes)} wire routes.")
    return len(routes)


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
