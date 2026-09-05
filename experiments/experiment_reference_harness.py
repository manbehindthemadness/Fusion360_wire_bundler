"""
Build and verify the evolving reference harness inside Autodesk Fusion.

This experiment intentionally leaves its unsaved document open for inspection.
Run it through a Fusion API script facility, never with standalone Python.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import Optional
from uuid import UUID

# Make the repository importable when Fusion loads this file as a standalone script.
ADDIN_ROOT = Path(__file__).resolve().parent.parent
if str(ADDIN_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDIN_ROOT))

# noinspection PyUnresolvedReferences
import adsk.core  # noqa: E402

# noinspection PyUnresolvedReferences
import adsk.fusion  # noqa: E402

from experiments.scenario_report import ScenarioReport  # noqa: E402
from wire_bundler.application import add_pathway, add_wire_batch, create_empty_harness  # noqa: E402
from wire_bundler.domain import (  # noqa: E402
    RoutingMode,
    loads,
    validate_harness,
)
from wire_bundler.fusion import FusionHarnessGateway, show_route_previews  # noqa: E402

SCENARIO_NAME = "reference_harness"
ARTIFACT_ROOT = ADDIN_ROOT / "artifacts" / "verification"
HARNESS_ID = UUID("71000000-0000-0000-0000-000000000001")
PATHWAY_ID = UUID("72000000-0000-0000-0000-000000000001")
WIRE_PROFILE_ID = UUID("73000000-0000-0000-0000-000000000001")
CONTROL_IDS = tuple(UUID(f"74000000-0000-0000-0000-{index:012d}") for index in range(1, 4))
SOURCE_CONNECTION_IDS = tuple(
    UUID(f"75000000-0000-0000-0000-{index:012d}") for index in range(1, 4)
)
DESTINATION_CONNECTION_IDS = tuple(
    UUID(f"76000000-0000-0000-0000-{index:012d}") for index in range(1, 4)
)
WIRE_IDS = tuple(UUID(f"77000000-0000-0000-0000-{index:012d}") for index in range(1, 4))


def run(_context: object) -> None:
    """
    Create an isolated Fusion document and verify the current backend pipeline.

    Args:
        _context: Context supplied by the Fusion script host.
    """
    report = ScenarioReport(SCENARIO_NAME, ARTIFACT_ROOT, _log_to_fusion)
    application: Optional[adsk.core.Application] = None
    try:
        application = _require_application()
        with report.step("Create isolated Hybrid design"):
            document = application.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
            if document is None:
                raise RuntimeError("Fusion did not create the verification document.")
            design = adsk.fusion.Design.cast(application.activeProduct)
            if design is None:
                raise RuntimeError("Fusion did not activate the verification design.")
            design.designIntent = adsk.fusion.DesignIntentTypes.HybridDesignIntentType

        with report.step("Create source, gate, and destination profiles"):
            root_component = design.rootComponent
            source_profiles = tuple(
                _create_circular_profile(
                    root_component,
                    offset_cm=0.0,
                    center_x_cm=center_x,
                    center_y_cm=0.0,
                    radius_cm=0.12,
                    name=f"WB Source {index:02d}",
                )
                for index, center_x in enumerate((-0.4, 0.0, 0.4), start=1)
            )
            gate_profiles = tuple(
                _create_circular_profile(
                    root_component,
                    offset_cm=offset_cm,
                    center_x_cm=center_x,
                    center_y_cm=center_y,
                    radius_cm=0.8,
                    name=f"WB Routing Gate {index:02d}",
                )
                for index, (offset_cm, center_x, center_y) in enumerate(
                    ((5.0, 0.0, 0.0), (15.0, 1.5, 0.8), (25.0, -0.8, 1.4)),
                    start=1,
                )
            )
            destination_profiles = tuple(
                _create_circular_profile(
                    root_component,
                    offset_cm=30.0,
                    center_x_cm=center_x,
                    center_y_cm=1.4,
                    radius_cm=0.12,
                    name=f"WB Destination {index:02d}",
                )
                for index, center_x in enumerate((-1.2, -0.8, -0.4), start=1)
            )

        gateway = FusionHarnessGateway(design, application.data.activeFolder)
        with report.step("Create persistent harness definition"):
            definition = create_empty_harness(
                "WB_Verification_Harness",
                RoutingMode.ROUTING_GATES,
                gateway,
                id_factory=lambda: HARNESS_ID,
            )
            if definition.harness_id != HARNESS_ID:
                raise AssertionError("Harness identity was not preserved.")

        with report.step("Create ordered reusable pathway"):
            pathway_identifiers = iter((*CONTROL_IDS, PATHWAY_ID))
            pathway = add_pathway(
                HARNESS_ID,
                "Reference_Pathway",
                RoutingMode.ROUTING_GATES,
                tuple(profile.entityToken for profile in gate_profiles),
                gateway,
                id_factory=lambda: next(pathway_identifiers),
            )
            if pathway.ordered_control_ids != CONTROL_IDS:
                raise AssertionError("Pathway control order changed during persistence.")

        with report.step("Assign ordered source and destination profiles"):
            wire_identifiers = iter(
                (
                    WIRE_PROFILE_ID,
                    SOURCE_CONNECTION_IDS[0],
                    DESTINATION_CONNECTION_IDS[0],
                    WIRE_IDS[0],
                    SOURCE_CONNECTION_IDS[1],
                    DESTINATION_CONNECTION_IDS[1],
                    WIRE_IDS[1],
                    SOURCE_CONNECTION_IDS[2],
                    DESTINATION_CONNECTION_IDS[2],
                    WIRE_IDS[2],
                )
            )
            wire_batch = add_wire_batch(
                HARNESS_ID,
                PATHWAY_ID,
                tuple(profile.entityToken for profile in source_profiles),
                tuple(profile.entityToken for profile in destination_profiles),
                1.5,
                gateway,
                id_factory=lambda: next(wire_identifiers),
            )
            if tuple(wire.wire_id for wire in wire_batch.wires) != WIRE_IDS:
                raise AssertionError("Wire identities changed during ordered assignment.")

        with report.step("Validate backend definition"):
            stored_definition = loads(gateway.read_harness_definition(HARNESS_ID))
            issues = validate_harness(stored_definition)
            if issues:
                details = "; ".join(f"{issue.path}: {issue.message}" for issue in issues)
                raise AssertionError(f"Reference harness is not generation-ready: {details}")

        with report.step("Resolve persisted Fusion geometry in traversal order"):
            controls_by_id = {control.control_id: control for control in stored_definition.controls}
            for expected_profile, control_id in zip(gate_profiles, CONTROL_IDS):
                stored_control = controls_by_id[control_id]
                resolved_entities = design.findEntityByToken(stored_control.entity_token)
                if not resolved_entities or resolved_entities[0] != expected_profile:
                    raise AssertionError(f"Gate geometry did not resolve in order: {control_id}")
            for connection in stored_definition.connections:
                if not gateway.is_entity_token_resolvable(connection.entity_token):
                    raise AssertionError(f"Connection geometry did not resolve: {connection.name}")

        with report.step("Solve and display lightweight route previews"):
            route_previews = show_route_previews(design, stored_definition)
            if tuple(route.wire_id for route in route_previews) != WIRE_IDS:
                raise AssertionError("Route preview changed stable wire order.")
            if any(len(route.points) != 5 for route in route_previews):
                raise AssertionError("Route preview did not traverse every ordered gate.")
            application.activeViewport.refresh()

        with report.step("Rediscover harness through Fusion metadata"):
            matching_harnesses = tuple(
                stored
                for stored in gateway.list_stored_harnesses()
                if loads(stored.serialized_definition).harness_id == HARNESS_ID
            )
            if len(matching_harnesses) != 1:
                raise AssertionError(
                    f"Expected one rediscovered harness, found {len(matching_harnesses)}."
                )

        report.finish(True)
        application.userInterface.messageBox(
            "Reference harness verification passed.\n\n"
            "The unsaved verification design remains open for inspection.\n"
            f"Log: {report.log_path}\n"
            f"Report: {report.json_path}",
            "Wire Bundler Verification",
        )
    except (
        AssertionError,
        AttributeError,
        KeyError,
        OSError,
        RuntimeError,
        StopIteration,
        TypeError,
        ValueError,
    ):
        failure = traceback.format_exc()
        report.finish(False, failure)
        if application is not None and application.userInterface is not None:
            application.userInterface.messageBox(
                "Reference harness verification failed.\n\n"
                f"Log: {report.log_path}\n"
                f"Report: {report.json_path}\n\n"
                f"{failure}",
                "Wire Bundler Verification",
            )


def _require_application() -> adsk.core.Application:
    """
    Return the active Fusion application.

    Returns:
        Active Fusion application.

    Raises:
        RuntimeError: If the experiment is not running inside Fusion.
    """
    application = adsk.core.Application.get()
    if application is None:
        raise RuntimeError("Reference harness verification must run inside Fusion.")
    return application


def _create_circular_profile(
    component: adsk.fusion.Component,
    offset_cm: float,
    center_x_cm: float,
    center_y_cm: float,
    radius_cm: float,
    name: str,
) -> adsk.fusion.Profile:
    """
    Create one named circular sketch profile on an XY-offset plane.

    Args:
        component: Component that will own the sketch and construction plane.
        offset_cm: Plane offset in Fusion's internal centimeter units.
        center_x_cm: Circle-center X coordinate in sketch space.
        center_y_cm: Circle-center Y coordinate in sketch space.
        radius_cm: Circle radius in Fusion's internal centimeter units.
        name: Sketch name used for visual diagnosis.

    Returns:
        Computed circular sketch profile.
    """
    planar_entity = component.xYConstructionPlane
    if offset_cm != 0.0:
        plane_input = component.constructionPlanes.createInput()
        offset = adsk.core.ValueInput.createByReal(offset_cm)
        if not plane_input.setByOffset(component.xYConstructionPlane, offset):
            raise RuntimeError(f"Fusion rejected the offset plane for {name}.")
        planar_entity = component.constructionPlanes.add(plane_input)
        if planar_entity is None:
            raise RuntimeError(f"Fusion did not create the offset plane for {name}.")

    sketch = component.sketches.add(planar_entity)
    if sketch is None:
        raise RuntimeError(f"Fusion did not create the sketch for {name}.")
    sketch.name = name
    center = adsk.core.Point3D.create(center_x_cm, center_y_cm, 0.0)
    circle = sketch.sketchCurves.sketchCircles.addByCenterRadius(center, radius_cm)
    if circle is None or sketch.profiles.count != 1:
        raise RuntimeError(f"Fusion did not compute one circular profile for {name}.")
    profile = sketch.profiles.item(0)
    if profile is None or not profile.entityToken:
        raise RuntimeError(f"Fusion did not provide a persistent profile for {name}.")
    return profile


def _log_to_fusion(message: str) -> None:
    """
    Mirror experiment diagnostics into Fusion's application log.

    Args:
        message: Timestamped scenario log line.
    """
    adsk.core.Application.log(
        f"Wire Bundler verification: {message}",
        adsk.core.LogLevels.InfoLogLevel,
        adsk.core.LogTypes.FileLogType,
    )
