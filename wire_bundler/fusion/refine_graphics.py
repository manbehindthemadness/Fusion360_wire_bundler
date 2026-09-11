"""
Display and place persistent unconstrained pathway refines in Fusion.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Union
from uuid import UUID

# noinspection PyUnresolvedReferences
import adsk.core

# noinspection PyUnresolvedReferences
import adsk.fusion

from ..domain import ControlKind, HarnessDefinition, RefineGeometry
from ..routing import (
    GateFrame,
    RefineFrame,
    RoutePreview,
    TransitionLengths,
    Vector3,
    fair_route,
    sample_centerline,
)
from ..routing.geometry import cross, difference, dot, magnitude, unit
from .route_preview import _routing_frame

REFINE_GRAPHICS_GROUP_ID = "kev0.wire_bundler.refines"
REFINE_SPINE_GROUP_ID = "kev0.wire_bundler.refine_spine"
REFINE_SPINE_ENTITY_ID = "kev0.wire_bundler.refine_spine.curve"
DEFAULT_REFINE_RADIUS_MM = 10.0
_REFINE_COLOR = (232, 78, 180)
_SPINE_COLOR = (42, 214, 226)


@dataclass(frozen=True)
class PathwaySpine:
    """
    Retain a selectable pathway-center preview and its ordered source frames.
    """

    points: tuple[Vector3, ...]
    frames: tuple[Union[GateFrame, RefineFrame], ...]


@dataclass(frozen=True)
class RefinePlacement:
    """
    Pair a saved refine frame with its traversal insertion position.
    """

    insertion_index: int
    geometry: RefineGeometry


def build_pathway_spine(
    design: adsk.fusion.Design,
    definition: HarnessDefinition,
    pathway_id: UUID,
) -> PathwaySpine:
    """
    Solve a wire-independent center spine through one pathway's controls.
    """
    pathway = next(
        (candidate for candidate in definition.pathways if candidate.pathway_id == pathway_id),
        None,
    )
    if pathway is None:
        raise ValueError("Selected pathway does not exist in this harness.")
    controls = {control.control_id: control for control in definition.controls}
    frames = tuple(
        _routing_frame(design, controls.get(control_id), control_id)
        for control_id in pathway.ordered_control_ids
    )
    if not frames:
        raise ValueError("A pathway requires a routing gate before it can be refined.")
    if len(frames) == 1:
        normal = unit(cross(frames[0].u_direction, frames[0].v_direction))
        extent = max(DEFAULT_REFINE_RADIUS_MM * 2.0, _frame_display_radius(frames[0]) * 2.0)
        points = (
            frames[0].origin.translated(normal, -extent),
            frames[0].origin,
            frames[0].origin.translated(normal, extent),
        )
        return PathwaySpine(points, frames)
    route = RoutePreview(
        wire_id=UUID(int=0),
        wire_number="Pathway",
        points=tuple(frame.origin for frame in frames),
    )
    normals = tuple(unit(cross(frame.u_direction, frame.v_direction)) for frame in frames)
    transitions = tuple(
        TransitionLengths(
            controls[control_id].interpolation.approach_mm,
            controls[control_id].interpolation.departure_mm,
        )
        for control_id in pathway.ordered_control_ids
    )
    smooth = fair_route(route, normals, transitions)
    return PathwaySpine(sample_centerline(smooth), frames)


def place_refine(
    spine: PathwaySpine,
    selected_point_mm: Vector3,
    display_radius_mm: float,
) -> RefinePlacement:
    """
    Project one selection onto the spine and derive a stable oriented frame.
    """
    if len(spine.points) < 2:
        raise ValueError("The pathway spine has no selectable span.")
    best_distance = math.inf
    best_point = spine.points[0]
    best_tangent = difference(spine.points[1], spine.points[0])
    for start, end in zip(spine.points, spine.points[1:]):
        segment = difference(end, start)
        length_squared = dot(segment, segment)
        if length_squared <= 1e-12:
            continue
        fraction = max(
            0.0,
            min(1.0, dot(difference(selected_point_mm, start), segment) / length_squared),
        )
        candidate = start.translated(segment, fraction)
        distance = magnitude(difference(selected_point_mm, candidate))
        if distance < best_distance:
            best_distance = distance
            best_point = candidate
            best_tangent = segment
    tangent = unit(best_tangent)
    insertion_index = _insertion_index(spine.frames, best_point)
    reference = spine.frames[min(max(insertion_index - 1, 0), len(spine.frames) - 1)]
    projected_u = Vector3(
        reference.u_direction.x - tangent.x * dot(reference.u_direction, tangent),
        reference.u_direction.y - tangent.y * dot(reference.u_direction, tangent),
        reference.u_direction.z - tangent.z * dot(reference.u_direction, tangent),
    )
    if magnitude(projected_u) <= 1e-9:
        projected_u = Vector3(
            reference.v_direction.x - tangent.x * dot(reference.v_direction, tangent),
            reference.v_direction.y - tangent.y * dot(reference.v_direction, tangent),
            reference.v_direction.z - tangent.z * dot(reference.v_direction, tangent),
        )
    u_direction = unit(projected_u)
    v_direction = unit(cross(tangent, u_direction))
    geometry = RefineGeometry(
        origin_mm=(best_point.x, best_point.y, best_point.z),
        u_direction=(u_direction.x, u_direction.y, u_direction.z),
        v_direction=(v_direction.x, v_direction.y, v_direction.z),
        display_radius_mm=display_radius_mm,
    )
    return RefinePlacement(insertion_index, geometry)


def draw_pathway_spine(
    design: adsk.fusion.Design, spine: PathwaySpine
) -> tuple[adsk.fusion.CustomGraphicsGroup, adsk.fusion.CustomGraphicsLines]:
    """
    Draw one bright selectable temporary pathway-center line strip.
    """
    clear_refine_spine(design)
    group = design.rootComponent.customGraphicsGroups.add()
    if group is None:
        raise RuntimeError("Fusion did not create the refine-path graphics group.")
    group.id = REFINE_SPINE_GROUP_ID
    group.name = "Refine Pathway Spine"
    lines = _add_polyline(group, spine.points, _SPINE_COLOR, 4.0)
    lines.id = REFINE_SPINE_ENTITY_ID
    lines.name = "Select a point on the pathway"
    lines.isSelectable = True
    return group, lines


def draw_candidate_refine(
    group: adsk.fusion.CustomGraphicsGroup, geometry: RefineGeometry
) -> adsk.fusion.CustomGraphicsLines:
    """
    Replace the temporary candidate circle within the command group.
    """
    for index in range(group.count - 1, -1, -1):
        entity = group.item(index)
        if entity is not None and entity.id == "candidate_refine":
            entity.deleteMe()
    circle = _add_polyline(group, _circle_points(geometry), _REFINE_COLOR, 4.0)
    circle.id = "candidate_refine"
    circle.name = "Refine preview"
    circle.isSelectable = False
    return circle


def reconcile_refine_graphics(
    design: adsk.fusion.Design, definitions: tuple[HarnessDefinition, ...]
) -> None:
    """
    Recreate persistent refine markers when their saved identity set changes.
    """
    expected = tuple(
        str(control.control_id)
        for definition in definitions
        for control in definition.controls
        if control.kind is ControlKind.REFINE and control.refine_geometry is not None
    )
    group = _find_group(design, REFINE_GRAPHICS_GROUP_ID)
    current = ()
    if group is not None:
        current = tuple(
            group.item(index).id for index in range(group.count) if group.item(index) is not None
        )
    if current == expected:
        return
    clear_refine_graphics(design)
    if not expected:
        return
    group = design.rootComponent.customGraphicsGroups.add()
    if group is None:
        raise RuntimeError("Fusion did not create the refine graphics group.")
    group.id = REFINE_GRAPHICS_GROUP_ID
    group.name = "Wire Bundler Refines"
    for definition in definitions:
        for control in definition.controls:
            if control.kind is not ControlKind.REFINE or control.refine_geometry is None:
                continue
            marker = _add_polyline(
                group, _circle_points(control.refine_geometry), _REFINE_COLOR, 4.0
            )
            marker.id = str(control.control_id)
            marker.name = control.name
            marker.isSelectable = True


def clear_refine_spine(design: adsk.fusion.Design) -> None:
    """
    Delete the temporary pathway spine and candidate marker.
    """
    _clear_group(design, REFINE_SPINE_GROUP_ID)


def clear_refine_graphics(design: adsk.fusion.Design) -> None:
    """
    Delete all persistent refine marker graphics.
    """
    _clear_group(design, REFINE_GRAPHICS_GROUP_ID)


def has_refine_graphics(design: adsk.fusion.Design) -> bool:
    """
    Report whether persistent refine Custom Graphics are API-visible.
    """
    return _find_group(design, REFINE_GRAPHICS_GROUP_ID) is not None


def _frame_display_radius(frame: Union[GateFrame, RefineFrame]) -> float:
    """
    Return a useful one-control spine extent.
    """
    return frame.usable_radius_mm if isinstance(frame, GateFrame) else DEFAULT_REFINE_RADIUS_MM


def _insertion_index(frames: tuple[Union[GateFrame, RefineFrame], ...], point: Vector3) -> int:
    """
    Choose the ordered span nearest the selected pathway-center point.
    """
    if len(frames) == 1:
        normal = unit(cross(frames[0].u_direction, frames[0].v_direction))
        return 1 if dot(difference(point, frames[0].origin), normal) >= 0.0 else 0
    best_index = 1
    best_distance = math.inf
    for index, (start, end) in enumerate(zip(frames, frames[1:]), start=1):
        distance = _point_segment_distance(point, start.origin, end.origin)
        if distance < best_distance:
            best_distance = distance
            best_index = index
    return best_index


def _point_segment_distance(point: Vector3, start: Vector3, end: Vector3) -> float:
    """
    Return distance to one finite line segment.
    """
    segment = difference(end, start)
    length_squared = dot(segment, segment)
    if length_squared <= 1e-12:
        return magnitude(difference(point, start))
    fraction = max(0.0, min(1.0, dot(difference(point, start), segment) / length_squared))
    return magnitude(difference(point, start.translated(segment, fraction)))


def _circle_points(geometry: RefineGeometry) -> tuple[Vector3, ...]:
    """
    Tessellate the display-only refine circle in its saved plane.
    """
    origin = Vector3(*geometry.origin_mm)
    u_direction = Vector3(*geometry.u_direction)
    v_direction = Vector3(*geometry.v_direction)
    return tuple(
        origin.translated(u_direction, geometry.display_radius_mm * math.cos(angle)).translated(
            v_direction, geometry.display_radius_mm * math.sin(angle)
        )
        for angle in (math.tau * index / 48.0 for index in range(49))
    )


def _add_polyline(
    group: adsk.fusion.CustomGraphicsGroup,
    points: tuple[Vector3, ...],
    rgb: tuple[int, int, int],
    weight: float,
) -> adsk.fusion.CustomGraphicsLines:
    """
    Add one colored model-space line strip to a Custom Graphics group.
    """
    coordinates = adsk.fusion.CustomGraphicsCoordinates.create(
        [coordinate / 10.0 for point in points for coordinate in (point.x, point.y, point.z)]
    )
    if coordinates is None:
        raise RuntimeError("Fusion did not create refine graphics coordinates.")
    lines = group.addLines(coordinates, [], True)
    if lines is None:
        raise RuntimeError("Fusion did not draw refine graphics.")
    color = adsk.core.Color.create(*rgb, 255)
    effect = adsk.fusion.CustomGraphicsSolidColorEffect.create(color)
    if effect is None:
        raise RuntimeError("Fusion did not create the refine graphics color.")
    lines.color = effect
    lines.weight = weight
    return lines


def _find_group(
    design: adsk.fusion.Design, group_id: str
) -> Optional[adsk.fusion.CustomGraphicsGroup]:
    """
    Find one root-owned Wire Bundler graphics group.
    """
    groups = design.rootComponent.customGraphicsGroups
    for index in range(groups.count):
        group = groups.item(index)
        if group is not None and group.id == group_id:
            return group
    return None


def _clear_group(design: adsk.fusion.Design, group_id: str) -> None:
    """
    Explicitly delete one root-owned graphics group and its contents.
    """
    groups = design.rootComponent.customGraphicsGroups
    for index in range(groups.count - 1, -1, -1):
        group = groups.item(index)
        if group is None or group.id != group_id:
            continue
        group.isVisible = False
        for child_index in range(group.count - 1, -1, -1):
            child = group.item(child_index)
            if child is not None:
                child.deleteMe()
        group.deleteMe()
