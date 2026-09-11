"""
Expose a cleanup-safe preview lifecycle as externally captured MCP phases.

The external orchestrator advances one phase at a time and captures the active viewport
between phases. Module state exists only as development test infrastructure inside the
running Fusion process.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from uuid import uuid4

ADDIN_ROOT = Path(__file__).resolve().parent.parent
if str(ADDIN_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDIN_ROOT))

# noinspection PyUnresolvedReferences
import adsk  # noqa: E402

# noinspection PyUnresolvedReferences
import adsk.core  # noqa: E402

# noinspection PyUnresolvedReferences
import adsk.fusion  # noqa: E402

from experiments.experiment_command_history import (  # noqa: E402
    HARNESS_ID,
    build_single_wire_fixture,
    execute_palette_action,
    wait_for,
)
from experiments.experiment_preview_reload import (  # noqa: E402
    _delete_temporary_data_file,
    _wait_for_cloud_processing,
)
from wire_bundler.fusion import FusionHarnessGateway  # noqa: E402
from wire_bundler.fusion.route_preview import (  # noqa: E402
    clear_route_previews,
    has_route_previews,
)


@dataclass
class _VisualSession:
    """
    Retain resources owned by one externally orchestrated visual scenario.
    """

    application: adsk.core.Application
    previous_document: Optional[adsk.core.Document]
    initial_document_count: int
    active_folder: adsk.core.DataFolder
    document: Optional[adsk.core.Document]
    design: Optional[adsk.fusion.Design]
    data_file: Optional[adsk.core.DataFile]
    fixture_name: str
    payload: str


_SESSION: Optional[_VisualSession] = None


def dispatch(action: str) -> dict[str, object]:
    """
    Advance or clean the visual lifecycle fixture.
    """
    actions = {
        "begin": _begin,
        "normalize": _normalize,
        "show-preview": _show_preview,
        "save-reload": _save_reload,
        "show-fresh": _show_fresh,
        "clear": _clear,
        "cleanup": _cleanup,
    }
    handler = actions.get(action)
    if handler is None:
        raise ValueError(f"Unknown preview visual phase: {action!r}.")
    return handler()


def _begin() -> dict[str, object]:
    """
    Create the isolated unsaved one-wire fixture.
    """
    global _SESSION
    if _SESSION is not None:
        _cleanup()
    application = _require_application()
    active_folder = application.data.activeFolder
    if active_folder is None:
        raise RuntimeError("Fusion has no active cloud folder for visual QA data.")
    previous_document = application.activeDocument
    initial_document_count = application.documents.count
    document: Optional[adsk.core.Document] = None
    try:
        document = application.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
        if document is None:
            raise RuntimeError("Fusion did not create the visual preview fixture.")
        design = adsk.fusion.Design.cast(application.activeProduct)
        if design is None:
            raise RuntimeError("Fusion did not activate the visual preview fixture.")
        design.designIntent = adsk.fusion.DesignIntentTypes.HybridDesignIntentType
        gateway = build_single_wire_fixture(application, design)
        if gateway.harness_component(HARNESS_ID) is None:
            raise AssertionError("Visual preview harness was not created.")
        _SESSION = _VisualSession(
            application=application,
            previous_document=previous_document,
            initial_document_count=initial_document_count,
            active_folder=active_folder,
            document=document,
            design=design,
            data_file=None,
            fixture_name=f"WB_QA_Preview_Visual_{uuid4().hex[:12]}",
            payload=json.dumps({"harnessId": str(HARNESS_ID)}),
        )
        return _state("baseline")
    except (AssertionError, AttributeError, RuntimeError, TypeError, ValueError):
        if document is not None and document.isValid:
            document.close(False)
        if (
            previous_document is not None
            and previous_document.isValid
            and application.activeDocument != previous_document
        ):
            previous_document.activate()
        raise


def _normalize() -> dict[str, object]:
    """
    Fit and refresh the active viewport after MCP establishes the camera direction.
    """
    session = _require_session()
    viewport = session.application.activeViewport
    if viewport is None:
        raise RuntimeError("Fusion has no active viewport for visual QA.")
    viewport.fit()
    viewport.refresh()
    for _index in range(3):
        adsk.doEvents()
    return _state("normalized")


def _show_preview() -> dict[str, object]:
    """
    Create the first route preview before saving.
    """
    session = _require_session()
    design = _require_design(session)
    execute_palette_action(session.application, "preview_routes", session.payload)
    wait_for(session.application, lambda: has_route_previews(design), "visual preview")
    return _state("preview")


def _save_reload() -> dict[str, object]:
    """
    Save with a preview active, then close and reopen the exact cloud file.
    """
    session = _require_session()
    document = _require_document(session)
    if not document.saveAs(
        session.fixture_name,
        session.active_folder,
        "Wire Bundler automated visual preview verification",
        "wire-bundler-qa",
    ):
        raise RuntimeError("Fusion declined to save the visual preview fixture.")
    fusion_document = adsk.fusion.FusionDocument.cast(document)
    if fusion_document is None or fusion_document.dataFile is None:
        raise RuntimeError("Saved visual preview fixture has no cloud DataFile.")
    session.data_file = fusion_document.dataFile
    _wait_for_cloud_processing(session.data_file)
    if not document.close(False):
        raise RuntimeError("Fusion did not close the visual preview fixture.")
    session.document = None
    session.design = None
    reopened_document = session.application.documents.open(session.data_file, True)
    if reopened_document is None:
        raise RuntimeError("Fusion did not reopen the visual preview fixture.")
    session.document = reopened_document
    reopened_design = adsk.fusion.Design.cast(session.application.activeProduct)
    if reopened_design is None:
        raise RuntimeError("Reopened visual preview item is not a Fusion design.")
    session.design = reopened_design
    gateway = FusionHarnessGateway(reopened_design, session.active_folder)
    if len(gateway.list_stored_harnesses()) != 1:
        raise AssertionError("Reopened visual fixture did not retain one harness.")
    if has_route_previews(reopened_design):
        raise AssertionError("Saved preview remained API-visible after visual reload.")
    return _state("reloaded")


def _show_fresh() -> dict[str, object]:
    """
    Create a fresh preview in the reopened document.
    """
    session = _require_session()
    design = _require_design(session)
    execute_palette_action(session.application, "preview_routes", session.payload)
    wait_for(session.application, lambda: has_route_previews(design), "fresh visual preview")
    return _state("fresh-preview")


def _clear() -> dict[str, object]:
    """
    Clear the fresh preview while leaving the fixture open for capture.
    """
    session = _require_session()
    design = _require_design(session)
    if clear_route_previews(design) != 1:
        raise AssertionError("Visual clear did not remove exactly one preview group.")
    session.application.activeViewport.refresh()
    if has_route_previews(design):
        raise AssertionError("Visual preview remained API-visible after clear.")
    return _state("cleared")


def _cleanup() -> dict[str, object]:
    """
    Release and delete every resource owned by the active visual fixture.
    """
    global _SESSION
    session = _SESSION
    if session is None:
        return {"phase": "cleanup", "clean": True, "hadSession": False}
    cleanup_errors: list[str] = []
    if session.document is not None and session.document.isValid:
        if not session.document.close(False):
            cleanup_errors.append("Fusion did not close the visual fixture.")
    session.document = None
    session.design = None
    if session.data_file is not None and session.data_file.isValid:
        try:
            _delete_temporary_data_file(session.data_file)
        except RuntimeError as error:
            cleanup_errors.append(str(error))
    if (
        session.previous_document is not None
        and session.previous_document.isValid
        and session.application.activeDocument != session.previous_document
        and not session.previous_document.activate()
    ):
        cleanup_errors.append("Fusion did not restore the document active before visual QA.")
    if session.application.documents.count != session.initial_document_count:
        cleanup_errors.append(
            "Visual QA changed the open document count: "
            f"before={session.initial_document_count}, "
            f"after={session.application.documents.count}."
        )
    _SESSION = None
    if cleanup_errors:
        raise RuntimeError(" ".join(cleanup_errors))
    return {"phase": "cleanup", "clean": True, "hadSession": True}


def _state(phase: str) -> dict[str, object]:
    """
    Return the current phase and structural preview state.
    """
    session = _require_session()
    design = _require_design(session)
    return {
        "phase": phase,
        "previewVisibleToApi": has_route_previews(design),
        "documentName": _require_document(session).name,
        "saved": session.data_file is not None,
    }


def _require_session() -> _VisualSession:
    """
    Return the active visual session.
    """
    if _SESSION is None:
        raise RuntimeError("Preview visual QA has no active session.")
    return _SESSION


def _require_document(session: _VisualSession) -> adsk.core.Document:
    """
    Return the session's valid open document.
    """
    if session.document is None or not session.document.isValid:
        raise RuntimeError("Preview visual QA has no valid open document.")
    return session.document


def _require_design(session: _VisualSession) -> adsk.fusion.Design:
    """
    Return the session's valid active design.
    """
    if session.design is None or not session.design.isValid:
        raise RuntimeError("Preview visual QA has no valid active design.")
    return session.design


def _require_application() -> adsk.core.Application:
    """
    Return the active Fusion application or reject standalone execution.
    """
    application = adsk.core.Application.get()
    if application is None:
        raise RuntimeError("Preview visual verification must run inside Autodesk Fusion.")
    return application
