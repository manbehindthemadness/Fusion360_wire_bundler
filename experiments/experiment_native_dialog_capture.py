"""
Hold one native Add Pathway dialog for an external exact-window capture.

This development-only experiment owns the complete native-command lifetime inside one
Fusion MCP script request. A token selects a private project-local handshake directory;
callers cannot provide file paths. The command is always terminated before this module
returns, including capture failure and timeout paths.
"""

from __future__ import annotations

import importlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from time import monotonic, sleep
from typing import Optional
from uuid import UUID

# noinspection PyUnresolvedReferences
import adsk

# noinspection PyUnresolvedReferences
import adsk.core

# noinspection PyUnresolvedReferences
import adsk.fusion

from experiments.experiment_command_history import HARNESS_ID, build_single_wire_fixture, wait_for
from wire_bundler.addin import (
    ADD_PATHWAY_COMMAND_ID,
    PATHWAY_GATES_INPUT_ID,
    PATHWAY_NAME_INPUT_ID,
    ROUTING_MODE_INPUT_ID,
)

ADDIN_ROOT = Path(__file__).resolve().parent.parent
HANDSHAKE_ROOT = ADDIN_ROOT / "artifacts" / "native_dialog_handshake"
CAPTURE_TIMEOUT_SECONDS = 30.0
EXPECTED_INPUT_IDS = (
    PATHWAY_NAME_INPUT_ID,
    ROUTING_MODE_INPUT_ID,
    PATHWAY_GATES_INPUT_ID,
)


class _CommandCaptureHandler(adsk.core.CommandCreatedEventHandler):
    """
    Retain the production command created for the visual checkpoint.
    """

    def __init__(self) -> None:
        """
        Initialize an empty command slot.
        """
        super().__init__()
        self.command: Optional[adsk.core.Command] = None

    def notify(self, args: adsk.core.CommandCreatedEventArgs) -> None:
        """
        Capture the live command after its production handlers build the inputs.
        """
        self.command = args.command


@dataclass(frozen=True)
class NativeDialogCaptureResult:
    """
    Report the bounded handshake and command cleanup observed inside Fusion.
    """

    command_id: str
    input_ids: tuple[str, ...]
    phases: tuple[str, ...]
    terminated: bool
    document_restored: bool


def run_capture_handshake(
    application: adsk.core.Application,
    token: str,
) -> dict[str, object]:
    """
    Expose baseline and dialog checkpoints, then dismiss the command before returning.
    """
    handshake_directory = _handshake_directory(token)
    previous_document = application.activeDocument
    test_document: Optional[adsk.core.Document] = None
    definition: Optional[adsk.core.CommandDefinition] = None
    observer: Optional[_CommandCaptureHandler] = None
    terminated = False
    try:
        test_document = application.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
        if test_document is None:
            raise RuntimeError("Fusion did not create the native-dialog capture document.")
        design = adsk.fusion.Design.cast(application.activeProduct)
        if design is None:
            raise RuntimeError("Fusion did not activate the native-dialog capture design.")
        design.designIntent = adsk.fusion.DesignIntentTypes.HybridDesignIntentType
        build_single_wire_fixture(application, design)
        application.activeViewport.fit()
        for _index in range(3):
            adsk.doEvents()

        _publish_phase(handshake_directory, token, "baseline-ready", {})
        _wait_for_ack(handshake_directory, token, "baseline")

        user_interface = application.userInterface
        wait_for(
            application,
            lambda: str(user_interface.activeCommand) == "SelectCommand",
            "default command before native-dialog capture",
        )
        definition = user_interface.commandDefinitions.itemById(ADD_PATHWAY_COMMAND_ID)
        if definition is None:
            raise RuntimeError("The Add Pathway production command is unavailable.")
        observer = _CommandCaptureHandler()
        if not definition.commandCreated.add(observer):
            raise RuntimeError("Fusion could not observe the Add Pathway command.")
        addin = importlib.import_module("wire_bundler.addin")
        open_add_pathway = vars(addin)["_open_add_pathway_command"]
        open_add_pathway(
            application,
            json.dumps({"harnessId": str(HARNESS_ID)}),
        )
        wait_for(
            application,
            lambda: (
                observer is not None
                and observer.command is not None
                and str(user_interface.activeCommand) == ADD_PATHWAY_COMMAND_ID
            ),
            "open Add Pathway for native-dialog capture",
        )
        current_observer = observer
        if current_observer is None:
            raise RuntimeError("Fusion lost the Add Pathway command observer.")
        command = current_observer.command
        if command is None:
            raise RuntimeError("Fusion did not expose the live Add Pathway command.")
        labels = _validated_input_labels(command.commandInputs)
        for _index in range(3):
            adsk.doEvents()
        _publish_phase(
            handshake_directory,
            token,
            "dialog-ready",
            {"commandId": ADD_PATHWAY_COMMAND_ID, "inputLabels": labels},
        )
        _wait_for_ack(handshake_directory, token, "dialog")
    finally:
        user_interface = application.userInterface
        if str(user_interface.activeCommand) == ADD_PATHWAY_COMMAND_ID:
            terminated = bool(user_interface.terminateActiveCommand())
            wait_for(
                application,
                lambda: str(user_interface.activeCommand) != ADD_PATHWAY_COMMAND_ID,
                "terminate Add Pathway after native-dialog capture",
            )
        if observer is not None and definition is not None:
            definition.commandCreated.remove(observer)
        _restore_select_command(application)
        if test_document is not None and test_document.isValid:
            if not test_document.close(False):
                raise RuntimeError("Fusion did not close the native-dialog capture document.")
        if previous_document is not None and previous_document.isValid:
            if application.activeDocument != previous_document and not previous_document.activate():
                raise RuntimeError("Fusion did not restore the previous document after capture.")
    result = NativeDialogCaptureResult(
        command_id=ADD_PATHWAY_COMMAND_ID,
        input_ids=EXPECTED_INPUT_IDS,
        phases=("baseline", "dialog"),
        terminated=terminated,
        document_restored=application.activeDocument == previous_document,
    )
    return {
        "commandId": result.command_id,
        "inputIds": list(result.input_ids),
        "phases": list(result.phases),
        "terminated": result.terminated,
        "documentRestored": result.document_restored,
    }


def _handshake_directory(token: str) -> Path:
    """
    Derive the only permitted handshake directory from a canonical UUID token.
    """
    try:
        parsed = UUID(hex=token)
    except (AttributeError, ValueError) as error:
        raise ValueError("Native-dialog capture token is not a UUID hex value.") from error
    if parsed.hex != token:
        raise ValueError("Native-dialog capture token must be canonical lowercase UUID hex.")
    directory = HANDSHAKE_ROOT / token
    if not directory.is_dir() or directory.is_symlink():
        raise RuntimeError("Native-dialog capture handshake directory is unavailable.")
    return directory


def _publish_phase(
    directory: Path,
    token: str,
    phase: str,
    detail: dict[str, object],
) -> None:
    """
    Atomically announce one fixed visual checkpoint to the external worker.
    """
    destination = directory / f"{phase}.json"
    temporary = directory / f".{phase}.tmp"
    payload = {"token": token, "phase": phase, **detail}
    temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(destination)


def _wait_for_ack(
    directory: Path,
    token: str,
    phase: str,
) -> None:
    """
    Pump Fusion events until the external worker acknowledges a captured checkpoint.
    """
    acknowledgement = directory / f"{phase}-ack.json"
    deadline = monotonic() + CAPTURE_TIMEOUT_SECONDS
    while monotonic() < deadline:
        adsk.doEvents()
        if acknowledgement.is_file():
            try:
                payload = json.loads(acknowledgement.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                sleep(0.01)
                continue
            if not isinstance(payload, dict) or payload.get("token") != token:
                raise RuntimeError(f"Invalid {phase} capture acknowledgement.")
            if payload.get("status") != "captured":
                raise RuntimeError(str(payload.get("error", f"{phase} capture failed.")))
            return
        sleep(0.01)
    raise RuntimeError(f"Timed out waiting for the external {phase} capture.")


def _validated_input_labels(inputs: adsk.core.CommandInputs) -> dict[str, str]:
    """
    Require each fixed Add Pathway input and a readable visible label.
    """
    labels: dict[str, str] = {}
    for input_id in EXPECTED_INPUT_IDS:
        command_input = inputs.itemById(input_id)
        if command_input is None:
            raise RuntimeError(f"Add Pathway omitted command input: {input_id}")
        label = str(command_input.name).strip()
        if not label:
            raise RuntimeError(f"Add Pathway input has no readable label: {input_id}")
        if not command_input.isVisible:
            raise RuntimeError(f"Add Pathway input is not visible: {input_id}")
        labels[input_id] = label
    return labels


def _restore_select_command(application: adsk.core.Application) -> None:
    """
    Restore Fusion's default selection command after native dialog termination.
    """
    user_interface = application.userInterface
    if str(user_interface.activeCommand) == "SelectCommand":
        return
    select_definition = user_interface.commandDefinitions.itemById("SelectCommand")
    if select_definition is None or not select_definition.execute():
        raise RuntimeError("Fusion could not restore selection after native-dialog capture.")
    wait_for(
        application,
        lambda: str(user_interface.activeCommand) == "SelectCommand",
        "restore selection after native-dialog capture",
    )
