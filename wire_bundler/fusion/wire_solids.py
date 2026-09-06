"""
Build persistent circular wire sweeps from the same exact curves used by previews.
"""

from __future__ import annotations

import json
import math
from typing import Optional
from uuid import UUID

# noinspection PyUnresolvedReferences
import adsk.core

# noinspection PyUnresolvedReferences
import adsk.fusion

from ..domain import HarnessDefinition, WireDefinition, validate_harness
from ..routing import CubicBezier, RoutePreview, Vector3, tightest_bend
from ..routing.geometry import cross, difference, magnitude
from .harness_gateway import ATTRIBUTE_GROUP
from .route_preview import solve_route_centerlines

GENERATED_WIRE_ATTRIBUTE = "generated_wire"


def generate_wire_solids(
    design: adsk.fusion.Design,
    harness: adsk.fusion.Component,
    definition: HarnessDefinition,
    replace_existing: bool = False,
    notices: Optional[list[str]] = None,
) -> int:
    """
    Build every wire before replacing marked output, inside a Fusion command transaction.

    Callers must explicitly authorize replacement because generated components may
    contain manual edits. Native transaction rollback covers any deletion failure.
    Sketches outside the marked generated components are never modified.

    Args:
        design: Active Fusion design used to resolve route geometry.
        harness: Component that owns generated wire child components.
        definition: Persisted harness definition to generate.
        replace_existing: Whether marked existing wire components may be replaced.
        notices: Optional collector for successful dynamic transition adjustments.

    Returns:
        Number of generated wire components.
    """
    issues = validate_harness(definition)
    if issues:
        raise ValueError("Cannot generate wires: " + "; ".join(issue.message for issue in issues))
    previous = generated_wire_occurrences(harness)
    if previous and not replace_existing:
        raise ValueError("Generated wires already exist; confirm rebuilding before replacing them.")
    routes = solve_route_centerlines(design, definition, notices)
    if not routes or len(routes) != len(definition.wires):
        raise ValueError("Every wire must have a complete route before generating solids.")
    local_transform = _world_to_harness(design, harness)
    profiles = {profile.profile_id: profile for profile in definition.profiles}
    routes_by_id = {route.wire_id: route for route in routes}
    created: list[adsk.fusion.Occurrence] = []
    try:
        for wire in definition.wires:
            occurrence = harness.occurrences.addNewComponent(adsk.core.Matrix3D.create())
            if occurrence is None:
                raise RuntimeError(
                    f"Fusion could not create a component for wire {wire.wire_number}."
                )
            created.append(occurrence)
            try:
                build_wire_sweep(
                    occurrence.component,
                    wire,
                    routes_by_id[wire.wire_id],
                    profiles[wire.profile_id].diameter_mm,
                    local_transform,
                    definition.harness_id,
                )
            except (AttributeError, RuntimeError, TypeError, ValueError) as error:
                raise RuntimeError(
                    f"Wire {wire.wire_number} could not be swept: {error}"
                ) from error
        for occurrence in previous:
            if not occurrence.deleteMe():
                raise RuntimeError("Fusion could not remove old generated wire geometry.")
    except Exception as error:
        # Any host failure must clean staged output; Fusion rolls back earlier deletions.
        for occurrence in reversed(created):
            if occurrence.isValid and not occurrence.deleteMe():
                raise RuntimeError(
                    "Fusion could not clean incomplete wire geometry; undo this command."
                ) from error
        raise
    return len(created)


def generated_wire_occurrences(
    harness: adsk.fusion.Component,
) -> tuple[adsk.fusion.Occurrence, ...]:
    """
    Find only direct children explicitly marked as generated wire output.
    """
    return tuple(
        occurrence
        for occurrence in harness.occurrences
        if occurrence.component.attributes.itemByName(ATTRIBUTE_GROUP, GENERATED_WIRE_ATTRIBUTE)
        is not None
    )


def clear_wire_solids(harness: adsk.fusion.Component) -> int:
    """
    Delete direct child components marked as generated wire output.

    Callers should invoke this inside a native Fusion command transaction so a
    failed deletion rolls the complete operation back and Undo can restore it.
    """
    occurrences = generated_wire_occurrences(harness)
    for occurrence in occurrences:
        if not occurrence.deleteMe():
            raise RuntimeError("Fusion could not delete a generated wire component.")
    return len(occurrences)


def _world_to_harness(
    design: adsk.fusion.Design, harness: adsk.fusion.Component
) -> adsk.core.Matrix3D:
    """
    Convert model-space preview coordinates into the unique harness placement.
    """
    if harness == design.rootComponent:
        return adsk.core.Matrix3D.create()
    placements = design.rootComponent.allOccurrencesByComponent(harness)
    if placements.count != 1:
        raise ValueError("Solid generation requires a single placement of the harness component.")
    transform = placements.item(0).transform2.copy()
    if not transform.invert():
        raise ValueError("Harness placement could not be inverted.")
    return transform


def _point(point: Vector3, transform: adsk.core.Matrix3D) -> adsk.core.Point3D:
    """
    Convert solver millimeters into Fusion centimeters and harness-local coordinates.
    """
    result = adsk.core.Point3D.create(point.x / 10, point.y / 10, point.z / 10)
    if not result.transformBy(transform):
        raise RuntimeError("Could not transform a wire control point.")
    return result


def _is_straight(curve: CubicBezier) -> bool:
    """
    Identify monotone collinear cubic spans that Fusion can represent as sketch lines.
    """
    chord = difference(curve.end, curve.start)
    length = magnitude(chord)
    if length <= 1e-9:
        raise ValueError("A wire curve has coincident endpoints.")
    return all(
        magnitude(cross(difference(point, curve.start), chord)) / length < 1e-9
        for point in (curve.control_a, curve.control_b)
    )


def build_wire_sweep(
    component: adsk.fusion.Component,
    wire: WireDefinition,
    route: RoutePreview,
    diameter_mm: float,
    transform: adsk.core.Matrix3D,
    harness_id: UUID,
) -> None:
    """
    Create editable cubic control-point splines, a normal circular profile, and one sweep.
    """
    if not route.curves:
        raise ValueError("The smooth route contains no curves.")
    stage = "create centerline sketch"
    try:
        sketch = component.sketches.add(component.xYConstructionPlane)
        if sketch is None:
            raise RuntimeError("Fusion did not create the wire centerline sketch.")
        sketch.name = "Wire Centerline"
        curves = adsk.core.ObjectCollection.create()
        length_mm = 0.0
        for index, curve in enumerate(route.curves):
            stage = f"create centerline segment {index + 1}"
            points = [
                sketch.modelToSketchSpace(_point(point, transform))
                for point in (curve.start, curve.control_a, curve.control_b, curve.end)
            ]
            if _is_straight(curve):
                entity = sketch.sketchCurves.sketchLines.addByTwoPoints(points[0], points[3])
            else:
                entity = sketch.sketchCurves.sketchControlPointSplines.add(
                    points, adsk.fusion.SplineDegrees.SplineDegreeThree
                )
            if entity is None or not curves.add(entity):
                raise RuntimeError("Fusion could not create a wire centerline segment.")
            length_mm += entity.length * 10
        stage = "join centerline path"
        path = component.features.createPath(curves, False)
        if path is None:
            raise RuntimeError("Fusion could not join the ordered centerline segments.")
        stage = "define cross-section plane"
        plane_input = component.constructionPlanes.createInput()
        if not plane_input.setByDistanceOnPath(
            curves.item(0), adsk.core.ValueInput.createByReal(0)
        ):
            raise RuntimeError("Fusion could not orient the wire cross-section.")
        stage = "create cross-section plane"
        plane = component.constructionPlanes.add(plane_input)
        if plane is None:
            raise RuntimeError("Fusion did not create the wire cross-section plane.")
        stage = "create diameter sketch"
        section = component.sketches.add(plane)
        if section is None:
            raise RuntimeError("Fusion did not create the wire cross-section sketch.")
        section.name = "Wire Diameter"
        center = section.modelToSketchSpace(_point(route.curves[0].start, transform))
        circle = section.sketchCurves.sketchCircles.addByCenterRadius(center, diameter_mm / 20)
        if circle is None or section.profiles.count != 1:
            raise RuntimeError("Fusion could not create one circular sweep profile.")
        sweeps = component.features.sweepFeatures
        stage = "define sweep"
        sweep_input = sweeps.createInput(
            section.profiles.item(0), path, adsk.fusion.FeatureOperations.NewBodyFeatureOperation
        )
        stage = "create solid sweep"
        sweep = sweeps.add(sweep_input)
        if sweep is None or sweep.bodies.count != 1:
            raise RuntimeError("Fusion did not produce one wire solid.")
        body = sweep.bodies.item(0)
        if not body.isSolid or not math.isfinite(body.volume) or body.volume <= 0:
            raise RuntimeError("Fusion produced an invalid or empty wire solid.")
        component.name = wire.display_name or f"{wire.wire_number}_{length_mm:.2f}mm"
        body.name = component.name
        sweep.name = "Wire Sweep"
        sketch.isLightBulbOn = False
        section.isLightBulbOn = False
        plane.isLightBulbOn = False
        stage = "store wire metadata"
        metadata = json.dumps(
            {
                "harness_id": str(harness_id),
                "wire_id": str(wire.wire_id),
                "wire_number": wire.wire_number,
                "diameter_mm": diameter_mm,
                "length_mm": length_mm,
            },
            sort_keys=True,
        )
        if component.attributes.add(ATTRIBUTE_GROUP, GENERATED_WIRE_ATTRIBUTE, metadata) is None:
            raise RuntimeError("Fusion could not store the generated wire identity.")
    except (AttributeError, RuntimeError, TypeError, ValueError) as error:
        if stage == "create solid sweep":
            bend = tightest_bend(route)
            if bend is not None:
                diagnostic = (
                    f"tightest sampled bend radius {bend.radius_mm:.3f} mm on centerline "
                    f"curve {bend.curve_index + 1} at t={bend.parameter:.3f}; "
                    f"wire radius {diameter_mm / 2:.3f} mm"
                )
                raise RuntimeError(f"{stage}: {error}; route diagnostic: {diagnostic}") from error
        raise RuntimeError(f"{stage}: {error}") from error
