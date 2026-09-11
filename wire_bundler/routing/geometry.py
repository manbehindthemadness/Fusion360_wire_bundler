"""
Host-independent vectors and cubic centerline geometry in millimeters.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Vector3:
    """
    Store one point or direction in millimeters.
    """

    x: float
    y: float
    z: float

    def translated(self, direction: Vector3, distance: float) -> Vector3:
        """
        Return this point translated along a direction.
        """
        return Vector3(
            self.x + direction.x * distance,
            self.y + direction.y * distance,
            self.z + direction.z * distance,
        )


@dataclass(frozen=True)
class CubicBezier:
    """
    Retain exact cubic control points independently of preview tessellation.
    """

    start: Vector3
    control_a: Vector3
    control_b: Vector3
    end: Vector3

    def point(self, parameter: float) -> Vector3:
        """
        Evaluate the curve on its unit parameter interval.
        """
        if not math.isfinite(parameter) or not 0.0 <= parameter <= 1.0:
            raise ValueError("Curve parameter must be between zero and one.")
        first = lerp(self.start, self.control_a, parameter)
        middle = lerp(self.control_a, self.control_b, parameter)
        last = lerp(self.control_b, self.end, parameter)
        return lerp(lerp(first, middle, parameter), lerp(middle, last, parameter), parameter)

    def derivative(self, parameter: float) -> Vector3:
        """
        Evaluate the tangent vector without normalizing away its magnitude.
        """
        if not math.isfinite(parameter) or not 0.0 <= parameter <= 1.0:
            raise ValueError("Curve parameter must be between zero and one.")
        first = difference(self.control_a, self.start)
        middle = difference(self.control_b, self.control_a)
        last = difference(self.end, self.control_b)
        tangent = lerp(lerp(first, middle, parameter), lerp(middle, last, parameter), parameter)
        return Vector3(tangent.x * 3.0, tangent.y * 3.0, tangent.z * 3.0)

    def second_derivative(self, parameter: float) -> Vector3:
        """
        Evaluate the curve acceleration used for spatial curvature.
        """
        if not math.isfinite(parameter) or not 0.0 <= parameter <= 1.0:
            raise ValueError("Curve parameter must be between zero and one.")
        first = Vector3(
            self.control_b.x - 2.0 * self.control_a.x + self.start.x,
            self.control_b.y - 2.0 * self.control_a.y + self.start.y,
            self.control_b.z - 2.0 * self.control_a.z + self.start.z,
        )
        last = Vector3(
            self.end.x - 2.0 * self.control_b.x + self.control_a.x,
            self.end.y - 2.0 * self.control_b.y + self.control_a.y,
            self.end.z - 2.0 * self.control_b.z + self.control_a.z,
        )
        acceleration = lerp(first, last, parameter)
        return Vector3(
            acceleration.x * 6.0,
            acceleration.y * 6.0,
            acceleration.z * 6.0,
        )


def difference(left: Vector3, right: Vector3) -> Vector3:
    """
    Subtract two points or directions componentwise.
    """
    return Vector3(left.x - right.x, left.y - right.y, left.z - right.z)


def dot(left: Vector3, right: Vector3) -> float:
    """
    Return the scalar product of two directions.
    """
    return left.x * right.x + left.y * right.y + left.z * right.z


def cross(left: Vector3, right: Vector3) -> Vector3:
    """
    Return a perpendicular direction using the right-hand rule.
    """
    return Vector3(
        left.y * right.z - left.z * right.y,
        left.z * right.x - left.x * right.z,
        left.x * right.y - left.y * right.x,
    )


def magnitude(vector: Vector3) -> float:
    """
    Compute vector length without squaring large coordinates.
    """
    return math.hypot(vector.x, vector.y, vector.z)


def unit(vector: Vector3) -> Vector3:
    """
    Normalize a finite nonzero direction.
    """
    length = magnitude(vector)
    if not math.isfinite(length) or length <= 1e-12:
        raise ValueError("Routing normals must be finite nonzero vectors.")
    return Vector3(vector.x / length, vector.y / length, vector.z / length)


def lerp(left: Vector3, right: Vector3, fraction: float) -> Vector3:
    """
    Interpolate between points or directions.
    """
    return Vector3(
        left.x * (1.0 - fraction) + right.x * fraction,
        left.y * (1.0 - fraction) + right.y * fraction,
        left.z * (1.0 - fraction) + right.z * fraction,
    )


def linear_combination(
    left: Vector3,
    left_scale: float,
    right: Vector3,
    right_scale: float,
) -> Vector3:
    """
    Combine two vectors with independent scalar weights.
    """
    return Vector3(
        left.x * left_scale + right.x * right_scale,
        left.y * left_scale + right.y * right_scale,
        left.z * left_scale + right.z * right_scale,
    )
