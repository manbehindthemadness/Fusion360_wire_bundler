"""
Fusion 360 lifecycle and command registration.
"""

from __future__ import annotations

import traceback
from pathlib import Path

# noinspection PyUnresolvedReferences
import adsk.core

# noinspection PyUnresolvedReferences
import adsk.fusion

from .application import create_empty_harness, suggest_harness_name
from .domain import RoutingMode
from .fusion import FusionHarnessGateway

COMMAND_ID = "kev0_wire_bundler_harness_builder"
COMMAND_NAME = "Harness Builder"
COMMAND_DESCRIPTION = "Create and edit wire, ribbon, and harness assemblies."
WORKSPACE_ID = "FusionSolidEnvironment"
PANEL_IDS = ("SolidScriptsAddinsPanel", "InsertAssemblePanel")
HARNESS_NAME_INPUT_ID = "harness_name"
ROUTING_MODE_INPUT_ID = "routing_mode"
DEFAULT_HARNESS_NAME = "Harness_001"
COMMAND_RESOURCE_FOLDER = str(
    Path(__file__).resolve().parent.parent / "resources" / "open_harness_builder"
)

_ROUTING_MODE_LABELS = {
    RoutingMode.ROUTING_GATES: "Routing Gates",
    RoutingMode.PROFILE_GATES: "Profile Gates",
}

_handlers: list[object] = []


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
            application.userInterface.messageBox(
                f"Created {definition.name} and stored its versioned harness definition.",
                COMMAND_NAME,
            )
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


class _HarnessBuilderCreatedHandler(adsk.core.CommandCreatedEventHandler):
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
        created_handler = _HarnessBuilderCreatedHandler()
        if not command_definition.commandCreated.add(created_handler):
            raise RuntimeError("Fusion did not register the command-created handler.")
        _handlers.append(created_handler)

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
    try:
        application = adsk.core.Application.get()
        _remove_user_interface(application.userInterface)
        _handlers.clear()
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
