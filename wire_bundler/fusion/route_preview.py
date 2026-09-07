"""
Translate Fusion profiles into routing frames and transient centerline graphics.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, replace
from typing import Optional
from uuid import UUID, uuid4

# noinspection PyUnresolvedReferences
import adsk.core

# noinspection PyUnresolvedReferences
import adsk.fusion

from ..domain import (
    ControlKind,
    ControlStructure,
    HarnessDefinition,
    StripePattern,
    WireColor,
    WireDefinition,
    WireStripe,
)
from ..routing import (
    GateFrame,
    RoutePreview,
    TransitionAdjustment,
    TransitionLengths,
    Vector3,
    WireRouteInput,
    fair_route,
    minimum_circular_bend_radius,
    sample_centerline,
    solve_parallel_routes,
)
from ..routing.geometry import cross, difference, dot, linear_combination, magnitude, unit

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
    Recognize cached, named, and explicitly identified Wire Bundler previews.

    Fusion may retain a host-assigned group ID, so the live cache and the name
    assigned during creation are authoritative fallbacks.
    """
    return (
        group.id in _preview_states
        or group.id == PREVIEW_GROUP_ID
        or group.id.startswith(f"{PREVIEW_GROUP_ID}:")
        or group.name.endswith(" Route Preview")
        or _has_wire_preview_children(group)
    )


def _has_wire_preview_children(group: adsk.fusion.CustomGraphicsGroup) -> bool:
    """
    Recognize an orphaned preview by the wire groups created beneath it.

    This supports graphics left by an earlier add-in session whose Python cache
    is gone and whose top-level ID or name was not retained by Fusion.
    """
    for index in range(group.count):
        child = adsk.fusion.CustomGraphicsGroup.cast(group.item(index))
        if child is not None and child.name.startswith("Wire ") and child.name.endswith(" Preview"):
            return True
    return False


def show_route_previews(
    design: adsk.fusion.Design,
    definition: HarnessDefinition,
    clearance_mm: float = 0.0,
    notices: Optional[list[str]] = None,
) -> tuple[RoutePreview, ...]:
    """
    Solve and display transient parallel-wire centerlines for one harness.

    Args:
        design: Active Fusion design used to resolve stored profile tokens.
        definition: Harness whose wire routes will be previewed.
        clearance_mm: Additional edge-to-edge separation between wires.
        notices: Optional collector for successful dynamic transition adjustments.

    Returns:
        Solved route previews in definition wire order.

    Raises:
        RuntimeError: If referenced geometry is unavailable or unsupported.
        ValueError: If route inputs or gate capacity are invalid.
    """
    routes = _solve_definition_routes(design, definition, clearance_mm, notices)
    root_component = design.rootComponent
    clear_route_previews(design)
    preview_group = root_component.customGraphicsGroups.add()
    if preview_group is None:
        raise RuntimeError("Fusion did not create the route-preview graphics group.")
    preview_group.id = f"{PREVIEW_GROUP_ID}:{uuid4()}"
    preview_group.name = f"{definition.name} Route Preview"
    wires = {wire.wire_id: wire for wire in definition.wires}
    profiles = {profile.profile_id: profile for profile in definition.profiles}
    try:
        for index, route in enumerate(routes):
            wire = wires[route.wire_id]
            materials = definition.wire_materials(wire)
            _add_route_graphics(
                preview_group,
                route,
                index,
                materials.main_color,
                materials.stripes,
                profiles[wire.profile_id].diameter_mm / 2.0,
            )
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


def clear_route_previews(design: adsk.fusion.Design) -> int:
    """
    Delete Wire Bundler route-preview graphics from the active design.

    Args:
        design: Fusion design whose transient previews should be removed.

    Returns:
        Number of deleted top-level preview graphics groups.
    """
    deleted_count = 0
    for groups in _design_graphics_collections(design):
        for index in range(groups.count - 1, -1, -1):
            group = groups.item(index)
            if group is not None and _is_preview_group(group):
                group_id = group.id
                state = _preview_states.get(group_id)
                if state is not None:
                    _remember_preview(group_id, state)
                _delete_graphics_group(group)
                _preview_states.pop(group_id, None)
                deleted_count += 1
    return deleted_count


def has_route_previews(design: adsk.fusion.Design) -> bool:
    """
    Report whether the live Fusion object model exposes a Wire Bundler preview.

    Fusion can serialize Custom Graphics into its OGS scene cache while dropping
    their API objects on reload. This check intentionally covers only graphics
    that are still reachable and can therefore be protected before a save.
    """
    for groups in _design_graphics_collections(design):
        for index in range(groups.count):
            group = groups.item(index)
            if group is not None and _is_preview_group(group):
                return True
    return False


def _design_graphics_collections(
    design: adsk.fusion.Design,
) -> tuple[adsk.fusion.CustomGraphicsGroups, ...]:
    """
    Return Custom Graphics collections for every component in the design.

    A preview restored with a document can belong to an assembly or external
    component even though new previews are currently created on the design root.
    """
    root_groups = design.rootComponent.customGraphicsGroups
    collections = [root_groups]
    all_components = design.allComponents
    for index in range(all_components.count):
        component = all_components.item(index)
        if component is None or component == design.rootComponent:
            continue
        collections.append(component.customGraphicsGroups)
    return tuple(collections)


def _delete_graphics_group(group: adsk.fusion.CustomGraphicsGroup) -> None:
    """
    Hide and explicitly empty a preview group before deleting its container.

    Hiding removes the graphics from the viewport immediately. Explicit child
    deletion avoids relying on Fusion to cascade nested groups after a palette
    event has returned.
    """
    group.isVisible = False
    for index in range(group.count - 1, -1, -1):
        child = group.item(index)
        if child is not None and child.deleteMe() is False:
            raise RuntimeError("Fusion could not delete a route-preview graphics entity.")
    if group.deleteMe() is False:
        raise RuntimeError("Fusion could not delete a route-preview graphics group.")


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
    main_color = definition.wire_materials(wire).main_color
    stripes = definition.wire_materials(wire).stripes
    return (
        wire.wire_id,
        wire.wire_number,
        wire.ordered_control_ids,
        start.member_tokens if start else None,
        end.member_tokens if end else None,
        start.member_settings if start else None,
        end.member_settings if end else None,
        profile.diameter_mm if profile else None,
        main_color,
        stripes,
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
                        design,
                        replace(definition, wires=eligible),
                        state.clearance_mm,
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
                old_wire = old_wires.get(wire_id)
                new_wire = new_wires[wire_id]
                appearance_changed = old_wire is None or (
                    (
                        state.definition.wire_materials(old_wire).main_color,
                        state.definition.wire_materials(old_wire).stripes,
                    )
                    != (
                        definition.wire_materials(new_wire).main_color,
                        definition.wire_materials(new_wire).stripes,
                    )
                )
                if state.routes.get(wire_id) == route and not appearance_changed:
                    continue
                previous = _wire_graphics(group, {wire_id})
                color_index = state.color_indices.setdefault(
                    wire_id, max(state.color_indices.values(), default=-1) + 1
                )
                try:
                    profile = next(
                        item
                        for item in definition.profiles
                        if item.profile_id == new_wire.profile_id
                    )
                    materials = definition.wire_materials(new_wire)
                    _add_route_graphics(
                        group,
                        route,
                        color_index,
                        materials.main_color,
                        materials.stripes,
                        profile.diameter_mm / 2.0,
                    )
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
    notices: Optional[list[str]] = None,
) -> tuple[RoutePreview, ...]:
    """
    Resolve definition references and solve each distinct pathway bundle.

    End-member profiles and pathway controls all contribute oriented crossings
    to diameter-aware fairing. Aperture packing applies only to the pathway
    controls represented by ``GateFrame`` objects.

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
        route_transitions: dict[UUID, tuple[TransitionLengths, ...]] = {}
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
            route_transitions[wire.wire_id] = (
                *(
                    TransitionLengths(settings.approach_mm, settings.departure_mm)
                    for settings in start_connection.member_settings
                ),
                *(
                    TransitionLengths(
                        controls[identity].interpolation.approach_mm,
                        controls[identity].interpolation.departure_mm,
                    )
                    for identity in control_ids
                ),
                *(
                    TransitionLengths(settings.departure_mm, settings.approach_mm)
                    for settings in reversed(end_connection.member_settings)
                ),
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
        for wire, route in zip(untyped_wires, routes):
            adjustments: list[TransitionAdjustment] = []
            normals = route_normals[route.wire_id]
            transitions = route_transitions[route.wire_id]
            minimum_bend_radius_mm = minimum_circular_bend_radius(
                profiles[wire.profile_id].diameter_mm
            )
            try:
                solved_by_id[route.wire_id] = fair_route(
                    route,
                    normals,
                    transitions,
                    minimum_bend_radius_mm=minimum_bend_radius_mm,
                    adjustments=adjustments,
                )
            except ValueError as error:
                diagnostic = _fairing_failure_diagnostic(
                    route,
                    normals,
                    transitions,
                    minimum_bend_radius_mm,
                )
                raise ValueError(f"{error} Routing diagnostic: {diagnostic}") from error
            if notices is not None:
                notices.extend(_adjustment_notice(item) for item in adjustments)
    return tuple(solved_by_id[wire.wire_id] for wire in definition.wires)


def _fairing_failure_diagnostic(
    route: RoutePreview,
    normals: tuple[Vector3, ...],
    transitions: tuple[TransitionLengths, ...],
    minimum_bend_radius_mm: float,
) -> str:
    """
    Preserve the exact host-derived inputs needed to reproduce a fairing failure.
    """
    points_text = ", ".join(_vector_diagnostic(point) for point in route.points)
    normals_text = ", ".join(_vector_diagnostic(normal) for normal in normals)
    transitions_text = ", ".join(
        f"({_optional_float_diagnostic(item.approach_mm)}, "
        f"{_optional_float_diagnostic(item.departure_mm)})"
        for item in transitions
    )
    return (
        f"wire={route.wire_number}; minimum_bend_radius_mm={minimum_bend_radius_mm:.12g}; "
        f"points_mm=[{points_text}]; normals=[{normals_text}]; "
        f"transitions_mm=[{transitions_text}]"
    )


def _vector_diagnostic(vector: Vector3) -> str:
    """
    Format one routing vector without discarding useful floating-point precision.
    """
    return f"({vector.x:.12g}, {vector.y:.12g}, {vector.z:.12g})"


def _optional_float_diagnostic(value: Optional[float]) -> str:
    """
    Format an optional transition value for a reproducible diagnostic.
    """
    return "None" if value is None else f"{value:.12g}"


def _adjustment_notice(adjustment: TransitionAdjustment) -> str:
    """
    Format a dynamic transition correction for the palette event console.
    """
    return (
        f"Wire {adjustment.wire_number}: dynamically adjusted transitions between profiles "
        f"{adjustment.start_profile} and {adjustment.end_profile} from "
        f"{adjustment.required_mm:.3f} mm to {adjustment.applied_mm:.3f} mm; "
        f"the {adjustment.minimum_bend_radius_mm:.3f} mm sweep radius is preserved."
    )


def _gate_frame(
    design: adsk.fusion.Design,
    control: Optional[ControlStructure],
    control_id: UUID,
) -> GateFrame:
    """
    Build a circular aperture frame from one stored pathway control.

    Connection-owned end profiles are resolved separately as centroid/normal
    frames. Their position and orientation guide fairing and the resulting sweep,
    but they are not apertures against which the wire bundle is fit-tested.

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
    wire_color: Optional[WireColor] = None,
    stripes: tuple[WireStripe, ...] = (),
    wire_radius_mm: float = 0.0,
) -> None:
    """
    Add one selectable colored line strip to a preview group.

    Args:
        preview_group: Owning top-level graphics group.
        route: Route points expressed in millimeters.
        color_index: Stable fallback palette index for legacy callers.
        wire_color: Resolved insulation color, when stored on the harness.
        stripes: Ordered procedural insulation stripes.
        wire_radius_mm: Radius used to place stripes on the wire surface.
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
    red, green, blue = (
        (wire_color.red, wire_color.green, wire_color.blue)
        if wire_color is not None
        else _PREVIEW_COLORS[color_index % len(_PREVIEW_COLORS)]
    )
    color = adsk.core.Color.create(red, green, blue, 255)
    color_effect = adsk.fusion.CustomGraphicsSolidColorEffect.create(color)
    if color_effect is None:
        raise RuntimeError(f"Fusion did not create a color for wire {route.wire_number}.")
    lines.color = color_effect
    for index, stripe in enumerate(stripes):
        vertices, triangle_indices = _stripe_mesh(route, stripe, wire_radius_mm)
        if not vertices or not triangle_indices:
            continue
        stripe_coordinates = adsk.fusion.CustomGraphicsCoordinates.create(
            [coordinate / 10.0 for point in vertices for coordinate in (point.x, point.y, point.z)]
        )
        if stripe_coordinates is None:
            raise RuntimeError(f"Fusion did not create stripe {index + 1} coordinates.")
        stripe_mesh = wire_group.addMesh(stripe_coordinates, triangle_indices, [], [])
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


def _stripe_mesh(
    route: RoutePreview,
    stripe: WireStripe,
    wire_radius_mm: float,
) -> tuple[tuple[Vector3, ...], list[int]]:
    """
    Build a model-space surface band with physical width for one stripe.

    Every sampled section follows the circular cross-section with angularly
    subdivided vertices. Fusion renders the resulting triangles with ordinary
    depth testing, so the wire body hides rear stripes and broad bands do not
    chord through the insulation.
    """
    if wire_radius_mm <= 0:
        return (), []
    points, tangents, normals, distances = _stripe_frame_samples(route, stripe, wire_radius_mm)
    if len(points) < 2:
        return (), []
    surface_radius = wire_radius_mm + max(0.02, wire_radius_mm * 0.01)
    half_angle = min(stripe.width_mm / (2.0 * surface_radius), math.pi * 0.49)
    width_segments = max(1, math.ceil(half_angle * 2.0 / math.radians(10.0)))
    section_size = width_segments + 1
    vertices: list[Vector3] = []
    for point, tangent, frame_normal, distance in zip(points, tangents, normals, distances):
        center_angle = math.radians(stripe.angle_deg)
        if stripe.pattern is StripePattern.HELICAL and stripe.repeat_mm is not None:
            center_angle += math.tau * distance / stripe.repeat_mm
        for width_index in range(section_size):
            angle = center_angle - half_angle + half_angle * 2.0 * width_index / width_segments
            radial = _stripe_radial(tangent, frame_normal, angle)
            vertices.append(point.translated(radial, surface_radius))
    indices: list[int] = []
    for index in range(len(points) - 1):
        midpoint = (distances[index] + distances[index + 1]) / 2.0
        if (
            stripe.pattern is StripePattern.DASHED
            and stripe.repeat_mm is not None
            and midpoint % stripe.repeat_mm >= stripe.repeat_mm / 2.0
        ):
            continue
        section_start = index * section_size
        next_section = section_start + section_size
        for width_index in range(width_segments):
            left = section_start + width_index
            next_left = next_section + width_index
            indices.extend((left, left + 1, next_left, left + 1, next_left + 1, next_left))
    return tuple(vertices), indices


def _stripe_paths(
    route: RoutePreview,
    stripe: WireStripe,
    wire_radius_mm: float,
) -> tuple[tuple[Vector3, ...], ...]:
    """
    Build visible surface paths for one longitudinal, dashed, or helical stripe.

    The frame is parallel-transported along the sampled centerline so a stripe
    remains stable through three-dimensional bends without depending on Fusion.
    """
    points, tangents, normals, distances = _stripe_frame_samples(route, stripe, wire_radius_mm)
    if len(points) < 2:
        return ()
    surface_radius = max(wire_radius_mm, 0.0) + 0.01
    stripe_points: list[Vector3] = []
    for point, tangent, frame_normal, distance in zip(points, tangents, normals, distances):
        angle = math.radians(stripe.angle_deg)
        if stripe.pattern is StripePattern.HELICAL and stripe.repeat_mm is not None:
            angle += math.tau * distance / stripe.repeat_mm
        radial = _stripe_radial(tangent, frame_normal, angle)
        stripe_points.append(point.translated(radial, surface_radius))
    if stripe.pattern is not StripePattern.DASHED or stripe.repeat_mm is None:
        return (tuple(stripe_points),)
    paths: list[tuple[Vector3, ...]] = []
    current: list[Vector3] = []
    for index in range(len(stripe_points) - 1):
        midpoint = (distances[index] + distances[index + 1]) / 2.0
        visible = midpoint % stripe.repeat_mm < stripe.repeat_mm / 2.0
        if visible:
            if not current:
                current.append(stripe_points[index])
            current.append(stripe_points[index + 1])
        elif len(current) >= 2:
            paths.append(tuple(current))
            current = []
    if len(current) >= 2:
        paths.append(tuple(current))
    return tuple(paths)


def _stripe_radial(tangent: Vector3, frame_normal: Vector3, angle: float) -> Vector3:
    """
    Rotate one transported frame normal around its centerline tangent.
    """
    binormal = unit(cross(tangent, frame_normal))
    return linear_combination(frame_normal, math.cos(angle), binormal, math.sin(angle))


def _stripe_frame_samples(
    route: RoutePreview,
    stripe: WireStripe,
    wire_radius_mm: float,
) -> tuple[
    tuple[Vector3, ...],
    tuple[Vector3, ...],
    tuple[Vector3, ...],
    tuple[float, ...],
]:
    """
    Densely sample the exact centerline and transport one circumferential frame.

    Stripe meshes need a tighter chord tolerance than the lightweight centerline
    graphic because any centerline error is magnified at the wire surface.
    """
    chord_tolerance_mm = min(0.005, max(0.0005, wire_radius_mm * 0.005))
    points = sample_centerline(route, chord_tolerance_mm)
    step_mm = 1.0
    if stripe.pattern is StripePattern.HELICAL and stripe.repeat_mm is not None:
        step_mm = min(step_mm, stripe.repeat_mm / 32.0)
    elif stripe.repeat_mm is not None:
        step_mm = min(step_mm, stripe.repeat_mm / 8.0)
    points = _densify_polyline(points, max(step_mm, 0.01))
    if len(points) < 2:
        return (), (), (), ()
    tangents = tuple(_polyline_tangent(points, index) for index in range(len(points)))
    normal = _initial_stripe_normal(tangents[0])
    normals = [normal]
    for tangent in tangents[1:]:
        projected = Vector3(
            normal.x - tangent.x * dot(normal, tangent),
            normal.y - tangent.y * dot(normal, tangent),
            normal.z - tangent.z * dot(normal, tangent),
        )
        normal = unit(projected) if magnitude(projected) > 1e-9 else _initial_stripe_normal(tangent)
        normals.append(normal)
    distances = [0.0]
    for start, end in zip(points, points[1:]):
        distances.append(distances[-1] + magnitude(difference(end, start)))
    return points, tangents, tuple(normals), tuple(distances)


def _densify_polyline(points: tuple[Vector3, ...], step_mm: float) -> tuple[Vector3, ...]:
    """
    Insert linear samples so procedural repeats remain visible on straight spans.
    """
    dense = [points[0]]
    for start, end in zip(points, points[1:]):
        delta = difference(end, start)
        length = magnitude(delta)
        divisions = max(1, math.ceil(length / step_mm))
        for index in range(1, divisions + 1):
            fraction = index / divisions
            dense.append(
                Vector3(
                    start.x + delta.x * fraction,
                    start.y + delta.y * fraction,
                    start.z + delta.z * fraction,
                )
            )
    return tuple(dense)


def _polyline_tangent(points: tuple[Vector3, ...], index: int) -> Vector3:
    """
    Return a centered tangent for one sampled centerline point.
    """
    if index == 0:
        return unit(difference(points[1], points[0]))
    if index == len(points) - 1:
        return unit(difference(points[-1], points[-2]))
    return unit(difference(points[index + 1], points[index - 1]))


def _initial_stripe_normal(tangent: Vector3) -> Vector3:
    """
    Choose a deterministic perpendicular frame direction for a route start.
    """
    axis = min(
        (Vector3(1.0, 0.0, 0.0), Vector3(0.0, 1.0, 0.0), Vector3(0.0, 0.0, 1.0)),
        key=lambda candidate: abs(dot(tangent, candidate)),
    )
    return unit(cross(tangent, axis))


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


def solve_route_centerlines(
    design: adsk.fusion.Design,
    definition: HarnessDefinition,
    notices: Optional[list[str]] = None,
) -> tuple[RoutePreview, ...]:
    """
    Resolve and fair current geometry without changing preview visibility or caches.

    Args:
        design: Active Fusion design used to resolve stored profile tokens.
        definition: Harness whose wire routes will be solved.
        notices: Optional collector for successful dynamic transition adjustments.

    Returns:
        Solved centerlines in definition wire order.
    """
    return _solve_definition_routes(design, definition, 0.0, notices)
