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

from ..domain import (
    HarnessDefinition,
    WireAppearanceReference,
    WireColor,
    WireDefinition,
    WireMaterialSettings,
    WireStripe,
    validate_harness,
)
from ..routing import CubicBezier, RoutePreview, Vector3, tightest_bend
from ..routing.geometry import cross, difference, magnitude
from .harness_gateway import ATTRIBUTE_GROUP
from .route_preview import build_stripe_mesh, solve_route_centerlines

GENERATED_WIRE_ATTRIBUTE = "generated_wire"
GENERATED_STRIPE_GROUP_ID = "kev0.wire_bundler.generated_wire_stripes"


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
                    definition.wire_materials(wire),
                    design,
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


def generated_wire_bodies(
    root: adsk.fusion.Component,
    harness: adsk.fusion.Component,
    wire_ids: tuple[UUID, ...],
) -> tuple[adsk.fusion.BRepBody, ...]:
    """
    Resolve root-context body proxies for persistent wire identities.

    Malformed generated metadata is ignored here so viewport hover remains a
    harmless best-effort operation; generation and material updates validate it
    through their stricter paths.
    """
    selected_ids = {str(wire_id) for wire_id in wire_ids}
    bodies: list[adsk.fusion.BRepBody] = []
    for occurrence in generated_wire_occurrences(harness):
        component = occurrence.component
        attribute = component.attributes.itemByName(ATTRIBUTE_GROUP, GENERATED_WIRE_ATTRIBUTE)
        if attribute is None:
            continue
        try:
            wire_id = json.loads(attribute.value).get("wire_id")
        except (AttributeError, TypeError, json.JSONDecodeError):
            continue
        if wire_id not in selected_ids:
            continue
        root_occurrences = root.allOccurrencesByComponent(component)
        for occurrence_index in range(root_occurrences.count):
            root_occurrence = root_occurrences.item(occurrence_index)
            if root_occurrence is None:
                continue
            for body_index in range(root_occurrence.bRepBodies.count):
                body = root_occurrence.bRepBodies.item(body_index)
                if body is not None:
                    bodies.append(body)
    return tuple(bodies)


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


def apply_wire_materials(
    design: adsk.fusion.Design,
    harness: adsk.fusion.Component,
    definition: HarnessDefinition,
) -> int:
    """
    Apply resolved colors, stripe overlays, and metadata to generated wire bodies.

    This updates material presentation without rebuilding centerlines or replacing
    generated components, so it is safe to run from the material-save transaction.
    """
    wires = {wire.wire_id: wire for wire in definition.wires}
    profiles = {profile.profile_id: profile for profile in definition.profiles}
    applied = 0
    for occurrence in generated_wire_occurrences(harness):
        component = occurrence.component
        attribute = component.attributes.itemByName(ATTRIBUTE_GROUP, GENERATED_WIRE_ATTRIBUTE)
        if attribute is None:
            continue
        try:
            metadata = json.loads(attribute.value)
            wire_id = UUID(metadata["wire_id"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise RuntimeError("A generated wire has invalid identity metadata.") from error
        wire = wires.get(wire_id)
        if wire is None:
            continue
        materials = definition.wire_materials(wire)
        appearance = _wire_appearance(design, materials.main_color, materials.appearance)
        bodies = component.bRepBodies
        if bodies.count == 0:
            raise RuntimeError(f"Generated wire {wire.wire_number} has no body to color.")
        for index in range(bodies.count):
            body = bodies.item(index)
            if body is not None:
                body.appearance = appearance
        route = _route_from_metadata(wire, metadata)
        if route is None and materials.stripes:
            raise RuntimeError(
                f"Generated wire {wire.wire_number} predates solid-owned stripes; "
                "rebuild its solids once before applying a stripe pattern."
            )
        if route is not None:
            _replace_stripe_graphics(
                component,
                route,
                materials.stripes,
                profiles[wire.profile_id].diameter_mm / 2.0,
            )
        metadata.update(_material_metadata(materials))
        attribute.value = json.dumps(metadata, sort_keys=True)
        applied += 1
    return applied


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


def _route_in_component_space(
    route: RoutePreview,
    transform: adsk.core.Matrix3D,
) -> RoutePreview:
    """
    Transform exact model-space curves into the generated component's coordinates.
    """

    def local(point: Vector3) -> Vector3:
        """
        Convert one model-space point into component-local millimeters.
        """
        transformed = _point(point, transform)
        return Vector3(transformed.x * 10.0, transformed.y * 10.0, transformed.z * 10.0)

    curves = tuple(
        CubicBezier(
            local(curve.start),
            local(curve.control_a),
            local(curve.control_b),
            local(curve.end),
        )
        for curve in route.curves
    )
    points = (curves[0].start, *(curve.end for curve in curves))
    return RoutePreview(route.wire_id, route.wire_number, points, curves)


def _route_metadata(route: RoutePreview) -> list[list[list[float]]]:
    """
    Serialize component-local curve controls used by a generated stripe overlay.
    """
    return [
        [
            [point.x, point.y, point.z]
            for point in (curve.start, curve.control_a, curve.control_b, curve.end)
        ]
        for curve in route.curves
    ]


def _route_from_metadata(
    wire: WireDefinition,
    metadata: dict[str, object],
) -> Optional[RoutePreview]:
    """
    Restore a generated component's exact local route, retaining legacy readability.
    """
    encoded = metadata.get("route_curves_mm")
    if encoded is None:
        return None
    if not isinstance(encoded, list) or not encoded:
        raise RuntimeError("Generated wire route metadata is malformed.")
    curves: list[CubicBezier] = []
    for encoded_curve in encoded:
        if not isinstance(encoded_curve, list) or len(encoded_curve) != 4:
            raise RuntimeError("Generated wire route metadata is malformed.")
        points: list[Vector3] = []
        for encoded_point in encoded_curve:
            if not isinstance(encoded_point, list) or len(encoded_point) != 3:
                raise RuntimeError("Generated wire route metadata is malformed.")
            if any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                for value in encoded_point
            ):
                raise RuntimeError("Generated wire route metadata is malformed.")
            points.append(Vector3(*(float(value) for value in encoded_point)))
        curves.append(CubicBezier(*points))
    if any(left.end != right.start for left, right in zip(curves, curves[1:])):
        raise RuntimeError("Generated wire route metadata is discontinuous.")
    route_points = (curves[0].start, *(curve.end for curve in curves))
    return RoutePreview(wire.wire_id, wire.wire_number, route_points, tuple(curves))


def _replace_stripe_graphics(
    component: adsk.fusion.Component,
    route: RoutePreview,
    stripes: tuple[WireStripe, ...],
    wire_radius_mm: float,
) -> int:
    """
    Replace procedural stripes owned in the same component as their wire solid.
    """
    groups = component.customGraphicsGroups
    for group_index in range(groups.count - 1, -1, -1):
        group = groups.item(group_index)
        if group is None or (
            group.id != GENERATED_STRIPE_GROUP_ID
            and not group.id.startswith(f"{GENERATED_STRIPE_GROUP_ID}:")
            and not group.name.endswith(" Solid Stripes")
        ):
            continue
        for child_index in range(group.count - 1, -1, -1):
            child = group.item(child_index)
            if child is not None and child.deleteMe() is False:
                raise RuntimeError("Fusion could not delete an obsolete wire stripe.")
        if group.deleteMe() is False:
            raise RuntimeError("Fusion could not delete obsolete wire stripe graphics.")
    if not stripes:
        return 0
    group = groups.add()
    if group is None:
        raise RuntimeError(f"Fusion did not create stripe graphics for wire {route.wire_number}.")
    group.id = f"{GENERATED_STRIPE_GROUP_ID}:{route.wire_id}"
    group.name = f"Wire {route.wire_number} Solid Stripes"
    created = 0
    for index, stripe in enumerate(stripes):
        vertices, triangle_indices = build_stripe_mesh(route, stripe, wire_radius_mm)
        if not vertices or not triangle_indices:
            continue
        coordinates = adsk.fusion.CustomGraphicsCoordinates.create(
            [coordinate / 10.0 for point in vertices for coordinate in (point.x, point.y, point.z)]
        )
        if coordinates is None:
            raise RuntimeError(f"Fusion did not create stripe {index + 1} coordinates.")
        stripe_mesh = group.addMesh(coordinates, triangle_indices, [], [])
        if stripe_mesh is None:
            raise RuntimeError(f"Fusion did not draw stripe {index + 1}.")
        stripe_mesh.name = f"Wire {route.wire_number} Stripe {index + 1}"
        stripe_mesh.cullMode = adsk.fusion.CustomGraphicsCullModes.CustomGraphicsCullNone
        stripe_color = adsk.core.Color.create(
            stripe.color.red,
            stripe.color.green,
            stripe.color.blue,
            255,
        )
        stripe_effect = adsk.fusion.CustomGraphicsSolidColorEffect.create(stripe_color)
        if stripe_effect is None:
            raise RuntimeError(f"Fusion did not create stripe {index + 1} color.")
        stripe_mesh.color = stripe_effect
        created += 1
    return created


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
    materials: Optional[WireMaterialSettings] = None,
    design: Optional[adsk.fusion.Design] = None,
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
        if materials is not None and design is not None:
            stage = "apply insulation appearance"
            body.appearance = _wire_appearance(design, materials.main_color, materials.appearance)
        local_route = _route_in_component_space(route, transform)
        if materials is not None:
            stage = "create component-owned stripe graphics"
            _replace_stripe_graphics(component, local_route, materials.stripes, diameter_mm / 2.0)
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
                "route_curves_mm": _route_metadata(local_route),
                **(
                    {
                        **_material_metadata(materials),
                    }
                    if materials is not None
                    else {}
                ),
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


def _material_metadata(materials: WireMaterialSettings) -> dict[str, object]:
    """
    Serialize the resolved material values stored with generated output.
    """
    return {
        "insulation_material": materials.insulation_material,
        "main_color": materials.main_color.hex_rgb,
        "appearance": (
            None
            if materials.appearance is None
            else {
                "library_id": materials.appearance.library_id,
                "library_name": materials.appearance.library_name,
                "appearance_id": materials.appearance.appearance_id,
                "appearance_name": materials.appearance.appearance_name,
            }
        ),
        "conductor_material": materials.conductor_material,
        "manufacturer": materials.manufacturer,
        "part_number": materials.part_number,
        "notes": materials.notes,
        "stripes": [
            {
                "color": stripe.color.hex_rgb,
                "color_name": stripe.color.name,
                "width_mm": stripe.width_mm,
                "pattern": stripe.pattern.value,
                "angle_deg": stripe.angle_deg,
                "repeat_mm": stripe.repeat_mm,
            }
            for stripe in materials.stripes
        ],
    }


def _wire_appearance(
    design: adsk.fusion.Design,
    color: WireColor,
    reference: Optional[WireAppearanceReference] = None,
) -> adsk.core.Appearance:
    """
    Return a document-owned library appearance or opaque stored insulation color.

    Fusion's released appearance API requires copying a library appearance into
    the design before changing its ``opaque_albedo`` property.
    """
    name = (
        f"Wire Bundler {reference.library_name} · {reference.appearance_name} "
        f"[{reference.appearance_id}]"
        if reference is not None
        else f"Wire Bundler Insulation {color.hex_rgb}"
    )
    appearance = design.appearances.itemByName(name)
    if appearance is not None:
        return appearance
    application = adsk.core.Application.get()
    if reference is not None:
        library = application.materialLibraries.itemById(reference.library_id)
        if library is None:
            raise RuntimeError(
                f"Fusion appearance library '{reference.library_name}' is unavailable."
            )
        source = library.appearances.itemById(reference.appearance_id)
        if source is None:
            raise RuntimeError(
                f"Fusion appearance '{reference.appearance_name}' is unavailable in "
                f"'{reference.library_name}'."
            )
        appearance = design.appearances.addByCopy(source, name)
        if appearance is None:
            raise RuntimeError("Fusion could not copy the selected wire appearance.")
        return appearance
    library = application.materialLibraries.itemById("BA5EE55E-9982-449B-9D66-9F036540E140")
    if library is None:
        raise RuntimeError("Fusion's built-in appearance library is unavailable.")
    generic = library.appearances.itemById("Prism-129")
    if generic is None:
        raise RuntimeError("Fusion's generic opaque appearance is unavailable.")
    appearance = design.appearances.addByCopy(generic, name)
    if appearance is None:
        raise RuntimeError("Fusion could not create the wire insulation appearance.")
    color_property = appearance.appearanceProperties.itemById("opaque_albedo")
    if color_property is None:
        raise RuntimeError("Fusion's wire appearance has no editable color property.")
    color_property.value = adsk.core.Color.create(color.red, color.green, color.blue, 255)
    return appearance
