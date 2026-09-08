"""
Expose generated striped-wire presentation as externally captured MCP phases.

The external orchestrator advances one phase at a time and captures the active viewport
between phases. Module state exists only as development test infrastructure inside the
running Fusion process.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

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
    WIRE_ID,
    build_single_wire_fixture,
)
from wire_bundler.application import set_harness_material_defaults  # noqa: E402
from wire_bundler.domain import (  # noqa: E402
    HarnessDefinition,
    StripePattern,
    WireColor,
    WireMaterialSettings,
    WireStripe,
    loads,
)
from wire_bundler.fusion.wire_solids import (  # noqa: E402
    GENERATED_STRIPE_GROUP_ID,
    clear_wire_solids,
    generate_wire_solids,
    generated_wire_occurrences,
)

TRANSLATION_CM = (2.0, -1.5, 0.75)


@dataclass
class _GeneratedVisualSession:
    """
    Retain resources owned by one externally orchestrated generated-wire scenario.
    """

    application: adsk.core.Application
    previous_document: Optional[adsk.core.Document]
    initial_document_count: int
    document: Optional[adsk.core.Document]
    design: Optional[adsk.fusion.Design]
    harness: adsk.fusion.Component
    definition: HarnessDefinition


_SESSION: Optional[_GeneratedVisualSession] = None


def dispatch(action: str) -> dict[str, object]:
    """
    Advance or clean the generated-wire visual fixture.

    Args:
        action: One of begin, normalize, generate, hide-stripes, show-stripes,
            rebuild, move, reset-position, clear, or cleanup.

    Returns:
        JSON-safe structural state after the requested phase.
    """
    actions = {
        "begin": _begin,
        "normalize": _normalize,
        "generate": _generate,
        "hide-stripes": _hide_stripes,
        "show-stripes": _show_stripes,
        "rebuild": _rebuild,
        "move": _move,
        "reset-position": _reset_position,
        "clear": _clear,
        "cleanup": _cleanup,
    }
    handler = actions.get(action)
    if handler is None:
        raise ValueError(f"Unknown generated visual phase: {action!r}.")
    return handler()


def _begin() -> dict[str, object]:
    """
    Create an isolated unsaved one-wire fixture with deterministic stripe settings.
    """
    global _SESSION
    if _SESSION is not None:
        _cleanup()
    application = _require_application()
    previous_document = application.activeDocument
    initial_document_count = application.documents.count
    document: Optional[adsk.core.Document] = None
    try:
        document = application.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
        if document is None:
            raise RuntimeError("Fusion did not create the generated visual fixture.")
        design = adsk.fusion.Design.cast(application.activeProduct)
        if design is None:
            raise RuntimeError("Fusion did not activate the generated visual fixture.")
        design.designIntent = adsk.fusion.DesignIntentTypes.HybridDesignIntentType
        gateway = build_single_wire_fixture(application, design)
        materials = WireMaterialSettings(
            insulation_material="QA ETFE",
            main_color=WireColor("QA Blue", 30, 90, 210),
            stripes=(
                WireStripe(
                    color=WireColor("QA Yellow", 250, 210, 20),
                    width_mm=0.35,
                    pattern=StripePattern.HELICAL,
                    angle_deg=35.0,
                    repeat_mm=8.0,
                ),
                WireStripe(
                    color=WireColor("QA White", 245, 245, 245),
                    width_mm=0.2,
                    pattern=StripePattern.LONGITUDINAL,
                    angle_deg=180.0,
                ),
            ),
            conductor_material="Copper",
            manufacturer="Wire Bundler QA",
            part_number="QA-STRIPED-VISUAL-001",
        )
        set_harness_material_defaults(HARNESS_ID, materials, gateway)
        definition = loads(gateway.read_harness_definition(HARNESS_ID))
        harness = gateway.harness_component(HARNESS_ID)
        if harness is None:
            raise AssertionError("Generated visual harness was not created.")
        sketches = design.rootComponent.sketches
        for index in range(sketches.count):
            sketch = sketches.item(index)
            if sketch is not None:
                sketch.isVisible = False
        _SESSION = _GeneratedVisualSession(
            application=application,
            previous_document=previous_document,
            initial_document_count=initial_document_count,
            document=document,
            design=design,
            harness=harness,
            definition=definition,
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
        raise RuntimeError("Fusion has no active viewport for generated visual QA.")
    viewport.fit()
    viewport.refresh()
    for _index in range(3):
        adsk.doEvents()
    return _state("normalized")


def _generate() -> dict[str, object]:
    """
    Generate one solid wire and its two component-owned stripe meshes.
    """
    session = _require_session()
    design = _require_design(session)
    if generate_wire_solids(design, session.harness, session.definition) != 1:
        raise AssertionError("Generated visual fixture did not create exactly one wire.")
    _require_stripe_group(session)
    return _state("generated")


def _hide_stripes() -> dict[str, object]:
    """
    Hide only the stripe group so the insulation body remains visible.
    """
    session = _require_session()
    _require_stripe_group(session).isVisible = False
    session.application.activeViewport.refresh()
    return _state("stripes-hidden")


def _show_stripes() -> dict[str, object]:
    """
    Restore the component-owned stripe group.
    """
    session = _require_session()
    _require_stripe_group(session).isVisible = True
    session.application.activeViewport.refresh()
    return _state("stripes-visible")


def _rebuild() -> dict[str, object]:
    """
    Replace the generated component and validate its stripe presentation.
    """
    session = _require_session()
    design = _require_design(session)
    if (
        generate_wire_solids(
            design,
            session.harness,
            session.definition,
            replace_existing=True,
        )
        != 1
    ):
        raise AssertionError("Generated visual rebuild did not replace exactly one wire.")
    _require_stripe_group(session)
    return _state("rebuilt")


def _move() -> dict[str, object]:
    """
    Move the parent harness occurrence while preserving generated ownership.
    """
    session = _require_session()
    occurrence = _require_harness_occurrence(session)
    transform = occurrence.transform2
    transform.translation = adsk.core.Vector3D.create(*TRANSLATION_CM)
    occurrence.transform2 = transform
    session.application.activeViewport.refresh()
    _require_stripe_group(session)
    return _state("moved")


def _reset_position() -> dict[str, object]:
    """
    Restore the harness occurrence transform before baseline-equivalence checks.
    """
    session = _require_session()
    occurrence = _require_harness_occurrence(session)
    occurrence.transform2 = adsk.core.Matrix3D.create()
    session.application.activeViewport.refresh()
    _require_stripe_group(session)
    return _state("position-restored")


def _clear() -> dict[str, object]:
    """
    Clear the generated component while leaving the baseline fixture open for capture.
    """
    session = _require_session()
    if clear_wire_solids(session.harness) != 1:
        raise AssertionError("Generated visual clear did not remove exactly one wire.")
    session.application.activeViewport.refresh()
    return _state("cleared")


def _cleanup() -> dict[str, object]:
    """
    Close the unsaved fixture and restore the previous document and document count.
    """
    global _SESSION
    session = _SESSION
    if session is None:
        return {"phase": "cleanup", "clean": True, "hadSession": False}
    cleanup_errors: list[str] = []
    if session.document is not None and session.document.isValid:
        if not session.document.close(False):
            cleanup_errors.append("Fusion did not close the generated visual fixture.")
    session.document = None
    session.design = None
    if (
        session.previous_document is not None
        and session.previous_document.isValid
        and session.application.activeDocument != session.previous_document
        and not session.previous_document.activate()
    ):
        cleanup_errors.append("Fusion did not restore the document active before visual QA.")
    if session.application.documents.count != session.initial_document_count:
        cleanup_errors.append(
            "Generated visual QA changed the open document count: "
            f"before={session.initial_document_count}, "
            f"after={session.application.documents.count}."
        )
    _SESSION = None
    if cleanup_errors:
        raise RuntimeError(" ".join(cleanup_errors))
    return {"phase": "cleanup", "clean": True, "hadSession": True}


def _state(phase: str) -> dict[str, object]:
    """
    Return the current phase and structural generated-wire state.
    """
    session = _require_session()
    occurrences = generated_wire_occurrences(session.harness)
    stripe_count = 0
    stripes_visible = False
    if occurrences:
        group = _require_stripe_group(session)
        stripe_count = group.count
        stripes_visible = group.isVisible
    return {
        "phase": phase,
        "generatedWireCount": len(occurrences),
        "stripeMeshCount": stripe_count,
        "stripesVisible": stripes_visible,
        "documentName": _require_document(session).name,
    }


def _require_stripe_group(
    session: _GeneratedVisualSession,
) -> adsk.fusion.CustomGraphicsGroup:
    """
    Return the expected two-mesh stripe group from the one generated wire.
    """
    occurrences = generated_wire_occurrences(session.harness)
    if len(occurrences) != 1:
        raise AssertionError("Generated visual fixture does not contain exactly one wire.")
    expected_id = f"{GENERATED_STRIPE_GROUP_ID}:{WIRE_ID}"
    groups = occurrences[0].component.customGraphicsGroups
    group: Optional[adsk.fusion.CustomGraphicsGroup] = None
    for candidate in groups:
        if candidate.id == expected_id:
            group = candidate
            break
    if group is None or group.count != 2:
        raise AssertionError("Generated visual wire does not own both stripe meshes.")
    return group


def _require_harness_occurrence(
    session: _GeneratedVisualSession,
) -> adsk.fusion.Occurrence:
    """
    Return the fixture harness's single root-context occurrence.
    """
    design = _require_design(session)
    root_occurrences = design.rootComponent.allOccurrencesByComponent(session.harness)
    if root_occurrences.count != 1:
        raise AssertionError("Generated visual harness does not have one root occurrence.")
    occurrence = root_occurrences.item(0)
    if occurrence is None:
        raise RuntimeError("Fusion did not expose the generated visual harness occurrence.")
    return occurrence


def _require_session() -> _GeneratedVisualSession:
    """
    Return the active generated visual session.
    """
    if _SESSION is None:
        raise RuntimeError("Generated visual QA has no active session.")
    return _SESSION


def _require_document(session: _GeneratedVisualSession) -> adsk.core.Document:
    """
    Return the session's valid open document.
    """
    if session.document is None or not session.document.isValid:
        raise RuntimeError("Generated visual QA has no valid open document.")
    return session.document


def _require_design(session: _GeneratedVisualSession) -> adsk.fusion.Design:
    """
    Return the session's valid active design.
    """
    if session.design is None or not session.design.isValid:
        raise RuntimeError("Generated visual QA has no valid active design.")
    return session.design


def _require_application() -> adsk.core.Application:
    """
    Return the active Fusion application or reject standalone execution.
    """
    application = adsk.core.Application.get()
    if application is None:
        raise RuntimeError("Generated visual verification must run inside Autodesk Fusion.")
    return application
