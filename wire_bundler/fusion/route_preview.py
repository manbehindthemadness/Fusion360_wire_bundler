"""
Translate Fusion profiles into routing frames and transient centerline graphics.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from typing import Optional
from uuid import UUID, uuid4

# noinspection PyUnresolvedReferences
import adsk.core

# noinspection PyUnresolvedReferences
import adsk.fusion

from ..domain import ControlKind, ControlStructure, HarnessDefinition, WireDefinition
from ..routing import (
    GateFrame,
    RoutePreview,
    Vector3,
    WireRouteInput,
    fair_route,
    sample_centerline,
    solve_parallel_routes,
)
from ..routing.geometry import cross, unit

PREVIEW_GROUP_ID = "kev0.wire_bundler.route_preview"
_PREVIEW_COLORS = (
    (23, 119, 200),
    (220, 92, 66),
    (40, 145, 85),
    (154, 87, 190),
    (220, 153, 42),
    (37, 153, 165),
)


@dataclass
class _PreviewState:
    """
    Retain the inputs and paths actually displayed by one transient preview.
    """

    definition: HarnessDefinition
    routes: dict[UUID, RoutePreview]
    color_indices: dict[UUID, int]
    clearance_mm: float


_preview_states: dict[str, _PreviewState] = {}
_preview_history: dict[tuple[str, HarnessDefinition], _PreviewState] = {}


def _remember_preview(group_id: str, state: _PreviewState) -> None:
    """
    Preserve a cache snapshot for graphics restored by Fusion Undo/Redo.
    """
    _preview_history[group_id, state.definition] = replace(
        state, routes=dict(state.routes), color_indices=dict(state.color_indices)
    )


def reset_preview_history() -> None:
    """
    Release session-only snapshots when the add-in stops.
    """
    _preview_states.clear()
    _preview_history.clear()


def reconcile_preview_history(
    design: adsk.fusion.Design, definitions: tuple[HarnessDefinition, ...]
) -> None:
    """
    Adopt caches matching restored graphics without any Fusion model writes.

    Fusion restores graphics in the edit transaction. Recreating them here would
    create a new edit and risk clearing Redo. Unknown states force a fresh solve
    on the next explicit edit instead.
    """
    by_id = {definition.harness_id: definition for definition in definitions}
    groups = design.rootComponent.customGraphicsGroups
    for index in range(groups.count):
        group = groups.item(index)
        if group is None or not _is_preview_group(group):
            continue
        candidates = [
            state for (identity, _), state in _preview_history.items() if identity == group.id
        ]
        if not candidates:
            continue
        latest = candidates[-1]
        definition = by_id.get(latest.definition.harness_id)
        if definition is None:
            _preview_states.pop(group.id, None)
            continue
        saved = _preview_history.get((group.id, definition))
        _preview_states[group.id] = replace(
            saved or latest,
            definition=definition,
            routes=dict(saved.routes) if saved else {},
            color_indices=dict((saved or latest).color_indices),
        )


def _is_preview_group(group: adsk.fusion.CustomGraphicsGroup) -> bool:
    """
    Recognize both current uniquely identified groups and older preview groups.
    """
    return group.id == PREVIEW_GROUP_ID or group.id.startswith(f"{PREVIEW_GROUP_ID}:")


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
    preview_group.id = f"{PREVIEW_GROUP_ID}:{uuid4()}"
    preview_group.name = f"{definition.name} Route Preview"
    try:
        for index, route in enumerate(routes):
            _add_route_graphics(preview_group, route, index)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        preview_group.deleteMe()
        raise
    _preview_states[preview_group.id] = _PreviewState(
        definition,
        {route.wire_id: route for route in routes},
        {route.wire_id: index for index, route in enumerate(routes)},
        clearance_mm,
    )
    _remember_preview(preview_group.id, _preview_states[preview_group.id])
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
        if group is not None and _is_preview_group(group):
            if group.id in _preview_states:
                _remember_preview(group.id, _preview_states[group.id])
            _preview_states.pop(group.id, None)
            group.deleteMe()


def _routing_signature(definition: HarnessDefinition, wire: WireDefinition) -> tuple[object, ...]:
    """
    Compare all ordered routing members while ignoring organizational labels.
    """
    connections = {item.connection_id: item for item in definition.connections}
    profiles = {item.profile_id: item for item in definition.profiles}
    controls = {item.control_id: item for item in definition.controls}
    start = connections.get(wire.start_connection_id)
    end = connections.get(wire.end_connection_id)
    profile = profiles.get(wire.profile_id)
    return (
        wire.wire_id,
        wire.wire_number,
        wire.ordered_control_ids,
        start.member_tokens if start else None,
        end.member_tokens if end else None,
        profile.diameter_mm if profile else None,
        tuple(controls.get(identity) for identity in wire.ordered_control_ids),
    )


def _wire_graphics(
    group: adsk.fusion.CustomGraphicsGroup,
    wire_ids: set[UUID],
) -> tuple[adsk.fusion.CustomGraphicsGroup, ...]:
    """
    Find existing children by stable wire identity without touching other paths.
    """
    identities = {str(identity) for identity in wire_ids}
    children = []
    for index in range(group.count):
        child = adsk.fusion.CustomGraphicsGroup.cast(group.item(index))
        if child is not None and child.id in identities:
            children.append(child)
    return tuple(children)


def refresh_route_previews(
    design: adsk.fusion.Design,
    definition: HarnessDefinition,
) -> tuple[str, ...]:
    """
    Recompute affected bundles of an active preview and redraw only changed paths.

    Missing ends are excluded from packing. Failed bundles lose stale graphics;
    unrelated bundles stay visible. Return warnings without undoing a saved edit.
    """
    groups = design.rootComponent.customGraphicsGroups
    warnings: list[str] = []
    for index in range(groups.count):
        group = groups.item(index)
        if group is None:
            continue
        state = _preview_states.get(group.id)
        if state is None or state.definition.harness_id != definition.harness_id:
            continue
        _remember_preview(group.id, state)
        old_wires = {wire.wire_id: wire for wire in state.definition.wires}
        new_wires = {wire.wire_id: wire for wire in definition.wires}
        relocated_ids = {
            identity
            for identity, wire in old_wires.items()
            if identity not in new_wires
            or new_wires[identity].ordered_control_ids != wire.ordered_control_ids
        }
        for child in _wire_graphics(group, relocated_ids):
            child.deleteMe()
        for identity in relocated_ids:
            state.routes.pop(identity, None)
        affected: set[tuple[UUID, ...]] = set()
        for wire_id in old_wires.keys() | new_wires.keys():
            old = old_wires.get(wire_id)
            new = new_wires.get(wire_id)
            if (
                old is None
                or new is None
                or wire_id not in state.routes
                or _routing_signature(state.definition, old) != _routing_signature(definition, new)
            ):
                if old is not None:
                    affected.add(old.ordered_control_ids)
                if new is not None:
                    affected.add(new.ordered_control_ids)
        connection_ids = {item.connection_id for item in definition.connections}
        for control_ids in sorted(affected, key=lambda ids: tuple(str(item) for item in ids)):
            bundle = tuple(
                wire for wire in definition.wires if wire.ordered_control_ids == control_ids
            )
            eligible = tuple(
                wire
                for wire in bundle
                if wire.start_connection_id in connection_ids
                and wire.end_connection_id in connection_ids
            )
            affected_ids = {wire.wire_id for wire in bundle}
            solved: dict[UUID, RoutePreview] = {}
            try:
                if eligible:
                    routes = _solve_definition_routes(
                        design, replace(definition, wires=eligible), state.clearance_mm
                    )
                    solved = {route.wire_id: route for route in routes}
            except (AttributeError, RuntimeError, TypeError, ValueError) as error:
                warnings.append(f"Preview update failed for a routing group: {error}")
            removed_ids = affected_ids - solved.keys()
            for child in _wire_graphics(group, removed_ids):
                child.deleteMe()
            for wire_id in removed_ids:
                state.routes.pop(wire_id, None)
            for wire_id, route in solved.items():
                if state.routes.get(wire_id) == route:
                    continue
                previous = _wire_graphics(group, {wire_id})
                color_index = state.color_indices.setdefault(
                    wire_id, max(state.color_indices.values(), default=-1) + 1
                )
                try:
                    _add_route_graphics(group, route, color_index)
                except (AttributeError, RuntimeError, TypeError, ValueError) as error:
                    for child in _wire_graphics(group, {wire_id}):
                        child.deleteMe()
                    state.routes.pop(wire_id, None)
                    warnings.append(f"Could not draw wire {route.wire_number}: {error}")
                    continue
                for child in previous:
                    child.deleteMe()
                state.routes[wire_id] = route
        state.definition = definition
        _remember_preview(group.id, state)
    return tuple(warnings)


def highlight_route_preview(design: adsk.fusion.Design, wire_id: Optional[UUID]) -> int:
    """
    Emphasize one existing wire centerline and restore all other preview widths.

    A missing preview is a harmless no-op; None clears hover emphasis.
    """
    return highlight_route_members(design, (wire_id,) if wire_id is not None else ())


def highlight_route_members(design: adsk.fusion.Design, wire_ids: tuple[UUID, ...]) -> int:
    """
    Emphasize a set of existing wire previews and restore all other widths.
    """
    selected_ids = {str(wire_id) for wire_id in wire_ids}
    selected_count = 0
    groups = design.rootComponent.customGraphicsGroups
    for index in range(groups.count):
        group = groups.item(index)
        if group is None or not _is_preview_group(group):
            continue
        for child_index in range(group.count):
            wire_group = adsk.fusion.CustomGraphicsGroup.cast(group.item(child_index))
            if wire_group is None:
                continue
            selected = wire_group.id in selected_ids
            for line_index in range(wire_group.count):
                lines = adsk.fusion.CustomGraphicsLines.cast(wire_group.item(line_index))
                if lines is not None:
                    lines.weight = 5.0 if selected else 1.0
                    if selected:
                        selected_count += 1
    return selected_count


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
    profile_frames: dict[str, tuple[Vector3, Vector3]] = {}
    for control_ids, untyped_wires in grouped_wires.items():
        gates = tuple(
            _gate_frame(design, controls.get(control_id), control_id) for control_id in control_ids
        )
        route_inputs: list[WireRouteInput] = []
        route_normals: dict[UUID, tuple[Vector3, ...]] = {}
        for wire in untyped_wires:
            start_connection = connections.get(wire.start_connection_id)
            end_connection = connections.get(wire.end_connection_id)
            profile = profiles.get(wire.profile_id)
            if start_connection is None or end_connection is None or profile is None:
                raise RuntimeError(f"Wire {wire.wire_number} has incomplete definition references.")
            for token in (*start_connection.member_tokens, *end_connection.member_tokens):
                if token not in profile_frames:
                    profile_frames[token] = _profile_frame(design, token)
            start_frames = tuple(profile_frames[token] for token in start_connection.member_tokens)
            end_frames = tuple(profile_frames[token] for token in end_connection.member_tokens)
            route_normals[wire.wire_id] = (
                *(frame[1] for frame in start_frames),
                *(cross(gate.u_direction, gate.v_direction) for gate in gates),
                *(frame[1] for frame in reversed(end_frames)),
            )
            route_inputs.append(
                WireRouteInput(
                    wire_id=wire.wire_id,
                    wire_number=wire.wire_number,
                    start=start_frames[0][0],
                    end=end_frames[0][0],
                    diameter_mm=profile.diameter_mm,
                    start_guides=tuple(frame[0] for frame in start_frames[1:]),
                    end_guides=tuple(frame[0] for frame in end_frames[1:]),
                )
            )
        routes = solve_parallel_routes(tuple(route_inputs), gates, clearance_mm)
        solved_by_id.update(
            (route.wire_id, fair_route(route, route_normals[route.wire_id])) for route in routes
        )
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


def _profile_frame(design: adsk.fusion.Design, entity_token: str) -> tuple[Vector3, Vector3]:
    """
    Return a profile centroid and unit plane normal in model coordinates.

    Args:
        design: Fusion design used to resolve the profile.
        entity_token: Stored persistent profile token.

    Returns:
        Model-space centroid in millimeters and a dimensionless unit normal.
    """
    profile = _resolve_profile(design, entity_token)
    area_properties = profile.areaProperties()
    if area_properties is None:
        raise RuntimeError("Fusion could not calculate connection-profile area properties.")
    model_centroid = profile.parentSketch.sketchToModelSpace(area_properties.centroid)
    sketch = profile.parentSketch
    normal = unit(cross(_vector(sketch.xDirection), _vector(sketch.yDirection)))
    return _point_to_mm(model_centroid), normal


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
    sampled_points = sample_centerline(route)
    coordinates = adsk.fusion.CustomGraphicsCoordinates.create(
        [
            coordinate / 10.0
            for point in sampled_points
            for coordinate in (point.x, point.y, point.z)
        ]
    )
    if coordinates is None:
        raise RuntimeError(f"Fusion did not create coordinates for wire {route.wire_number}.")
    lines = wire_group.addLines(coordinates, [], True)
    if lines is None:
        raise RuntimeError(f"Fusion did not draw wire {route.wire_number}.")
    lines.name = f"Wire {route.wire_number} Centerline"
    lines.weight = 1.0
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
