"""
Translate Fusion profiles into routing frames and transient centerline graphics.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Optional
from uuid import UUID

# noinspection PyUnresolvedReferences
import adsk.core

# noinspection PyUnresolvedReferences
import adsk.fusion

from ..domain import ControlKind, ControlStructure, HarnessDefinition, WireDefinition
from ..routing import GateFrame, RoutePreview, Vector3, WireRouteInput, solve_parallel_routes

PREVIEW_GROUP_ID = "kev0.wire_bundler.route_preview"
_PREVIEW_COLORS = (
    (23, 119, 200),
    (220, 92, 66),
    (40, 145, 85),
    (154, 87, 190),
    (220, 153, 42),
    (37, 153, 165),
)


def show_route_previews(
    design: adsk.fusion.Design,
    definition: HarnessDefinition,
    clearance_mm: float = 0.0,
) -> tuple[RoutePreview, ...]:
    """
    Solve and display transient parallel-wire centerlines for one harness.

    Args:
        design: Active Fusion design used to resolve stored profile tokens.
        definition: Harness whose wire routes will be previewed.
        clearance_mm: Additional edge-to-edge separation between wires.

    Returns:
        Solved route previews in definition wire order.

    Raises:
        RuntimeError: If referenced geometry is unavailable or unsupported.
        ValueError: If route inputs or gate capacity are invalid.
    """
    routes = _solve_definition_routes(design, definition, clearance_mm)
    root_component = design.rootComponent
    clear_route_previews(design)
    preview_group = root_component.customGraphicsGroups.add()
    if preview_group is None:
        raise RuntimeError("Fusion did not create the route-preview graphics group.")
    preview_group.id = PREVIEW_GROUP_ID
    preview_group.name = f"{definition.name} Route Preview"
    try:
        for index, route in enumerate(routes):
            _add_route_graphics(preview_group, route, index)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        preview_group.deleteMe()
        raise
    return routes


def clear_route_previews(design: adsk.fusion.Design) -> None:
    """
    Delete Wire Bundler route-preview graphics from the active design.

    Args:
        design: Fusion design whose transient previews should be removed.
    """
    groups = design.rootComponent.customGraphicsGroups
    for index in range(groups.count - 1, -1, -1):
        group = groups.item(index)
        if group is not None and group.id == PREVIEW_GROUP_ID:
            group.deleteMe()


def _solve_definition_routes(
    design: adsk.fusion.Design,
    definition: HarnessDefinition,
    clearance_mm: float,
) -> tuple[RoutePreview, ...]:
    """
    Resolve definition references and solve each distinct pathway bundle.

    Args:
        design: Fusion design used to resolve entity tokens.
        definition: Harness definition to translate.
        clearance_mm: Additional edge-to-edge separation between wires.

    Returns:
        Route previews restored to definition wire order.
    """
    if not definition.wires:
        raise ValueError("Add at least one wire before previewing routes.")
    connections = {connection.connection_id: connection for connection in definition.connections}
    profiles = {profile.profile_id: profile for profile in definition.profiles}
    controls = {control.control_id: control for control in definition.controls}
    grouped_wires: dict[tuple[UUID, ...], list[WireDefinition]] = defaultdict(list)
    for wire in definition.wires:
        grouped_wires[wire.ordered_control_ids].append(wire)

    solved_by_id: dict[UUID, RoutePreview] = {}
    for control_ids, untyped_wires in grouped_wires.items():
        gates = tuple(
            _gate_frame(design, controls.get(control_id), control_id) for control_id in control_ids
        )
        route_inputs: list[WireRouteInput] = []
        for wire in untyped_wires:
            start_connection = connections.get(wire.start_connection_id)
            end_connection = connections.get(wire.end_connection_id)
            profile = profiles.get(wire.profile_id)
            if start_connection is None or end_connection is None or profile is None:
                raise RuntimeError(f"Wire {wire.wire_number} has incomplete definition references.")
            route_inputs.append(
                WireRouteInput(
                    wire_id=wire.wire_id,
                    wire_number=wire.wire_number,
                    start=_profile_center(design, start_connection.entity_token),
                    end=_profile_center(design, end_connection.entity_token),
                    diameter_mm=profile.diameter_mm,
                )
            )
        routes = solve_parallel_routes(tuple(route_inputs), gates, clearance_mm)
        solved_by_id.update((route.wire_id, route) for route in routes)
    return tuple(solved_by_id[wire.wire_id] for wire in definition.wires)


def _gate_frame(
    design: adsk.fusion.Design,
    control: Optional[ControlStructure],
    control_id: UUID,
) -> GateFrame:
    """
    Build a circular gate frame from one stored routing control.

    Args:
        design: Fusion design used to resolve the gate profile.
        control: Resolved domain control.
        control_id: Expected control identity for errors.

    Returns:
        Host-independent gate frame in millimeters.
    """
    if control is None:
        raise RuntimeError(f"Routing control is missing: {control_id}")
    if control.kind is not ControlKind.ROUTING_GATE:
        raise RuntimeError(
            f"{control.name} is not a routing gate; profile-gate preview is not supported yet."
        )
    profile = _resolve_profile(design, control.entity_token)
    profile_loops = profile.profileLoops
    if profile_loops.count != 1:
        raise RuntimeError(f"{control.name} must be one circular profile.")
    profile_curves = profile_loops.item(0).profileCurves
    if profile_curves.count != 1:
        raise RuntimeError(f"{control.name} must be one circular profile.")
    profile_curve = profile_curves.item(0)
    circle = adsk.fusion.SketchCircle.cast(
        profile_curve.sketchEntity if profile_curve is not None else None
    )
    if circle is None:
        raise RuntimeError(f"{control.name} must be one circular profile.")
    sketch = profile.parentSketch
    center = sketch.sketchToModelSpace(circle.geometry.center)
    return GateFrame(
        gate_id=control.control_id,
        name=control.name,
        origin=_point_to_mm(center),
        u_direction=_vector(sketch.xDirection),
        v_direction=_vector(sketch.yDirection),
        usable_radius_mm=circle.geometry.radius * 10.0,
    )


def _profile_center(design: adsk.fusion.Design, entity_token: str) -> Vector3:
    """
    Return a profile centroid in model-space millimeters.

    Args:
        design: Fusion design used to resolve the profile.
        entity_token: Stored persistent profile token.

    Returns:
        Model-space centroid.
    """
    profile = _resolve_profile(design, entity_token)
    area_properties = profile.areaProperties()
    if area_properties is None:
        raise RuntimeError("Fusion could not calculate connection-profile area properties.")
    model_centroid = profile.parentSketch.sketchToModelSpace(area_properties.centroid)
    return _point_to_mm(model_centroid)


def _resolve_profile(design: adsk.fusion.Design, entity_token: str) -> adsk.fusion.Profile:
    """
    Resolve one stored token to a Fusion sketch profile.

    Args:
        design: Fusion design used for persistent-token resolution.
        entity_token: Stored persistent profile token.

    Returns:
        Resolved Fusion profile.
    """
    entities = design.findEntityByToken(entity_token)
    profile = adsk.fusion.Profile.cast(entities[0] if entities else None)
    if profile is None:
        raise RuntimeError("A route profile is missing or no longer resolves in Fusion.")
    return profile


def _add_route_graphics(
    preview_group: adsk.fusion.CustomGraphicsGroup,
    route: RoutePreview,
    color_index: int,
) -> None:
    """
    Add one selectable colored line strip to a preview group.

    Args:
        preview_group: Owning top-level graphics group.
        route: Route points expressed in millimeters.
        color_index: Stable palette index for this wire.
    """
    wire_group = preview_group.addGroup()
    if wire_group is None:
        raise RuntimeError(f"Fusion did not create graphics for wire {route.wire_number}.")
    wire_group.id = str(route.wire_id)
    wire_group.name = f"Wire {route.wire_number} Preview"
    coordinates = adsk.fusion.CustomGraphicsCoordinates.create(
        [coordinate / 10.0 for point in route.points for coordinate in (point.x, point.y, point.z)]
    )
    if coordinates is None:
        raise RuntimeError(f"Fusion did not create coordinates for wire {route.wire_number}.")
    lines = wire_group.addLines(coordinates, [], True)
    if lines is None:
        raise RuntimeError(f"Fusion did not draw wire {route.wire_number}.")
    lines.name = f"Wire {route.wire_number} Centerline"
    red, green, blue = _PREVIEW_COLORS[color_index % len(_PREVIEW_COLORS)]
    color = adsk.core.Color.create(red, green, blue, 255)
    color_effect = adsk.fusion.CustomGraphicsSolidColorEffect.create(color)
    if color_effect is None:
        raise RuntimeError(f"Fusion did not create a color for wire {route.wire_number}.")
    lines.color = color_effect


def _point_to_mm(point: adsk.core.Point3D) -> Vector3:
    """
    Convert a Fusion point from centimeters to millimeters.

    Args:
        point: Fusion point in internal database units.

    Returns:
        Host-independent point in millimeters.
    """
    return Vector3(point.x * 10.0, point.y * 10.0, point.z * 10.0)


def _vector(vector: adsk.core.Vector3D) -> Vector3:
    """
    Copy a Fusion model-space direction into the routing model.

    Args:
        vector: Fusion direction vector.

    Returns:
        Host-independent direction vector.
    """
    return Vector3(vector.x, vector.y, vector.z)
