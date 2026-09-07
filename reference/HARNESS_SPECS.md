# Constraint-Driven Routing-Gate Spline Generation

> **Document status:** Geometry and solver design reference. The implemented subset and
> current milestone are recorded in `../README.md`; persistent data and UI contracts are
> recorded in `UI_AND_DATA_MODEL.md`. Examples in this document do not by themselves
> mark a feature implemented or scheduled.

This spline-generation method uses a sequence of **oriented routing gates** to procedurally define one or more wire, cable, hose, or conduit paths through an engineered routing corridor. Each routing gate acts as both a **passage constraint** and a **directional constraint**: each spline must pass through the usable aperture of the gate while crossing its surface plane perpendicularly. Independent transition-length values are assigned to the **A and B sides** of each gate, controlling how far the gate's orientation influences the spline into the adjacent routing spans. Between these transition regions, the generated paths remain straight or nearly straight. If transition regions from neighboring gates would overlap, their lengths are clamped to the available span.

The result is a procedural routing system in which the designer controls the path primarily by positioning, orienting, and shaping routing gates rather than by manually manipulating spline control points or Bézier handles.

## Core Concept

A routing corridor consists of an ordered sequence of gates:

```text
        Gate 1                  Gate 2                  Gate 3
          |                       /                       |
          |                      /                        |
----------O---------------------O-------------------------O----------
```

Each gate defines:

* A position in 3D space
* A surface plane
* A surface normal
* A usable routing aperture
* A transition distance on Side A
* A transition distance on Side B
* Optional wire-spacing and clearance constraints

The gate normal determines the tangent direction of every spline as it passes through that gate.

```text
                         Gate plane
                             |
                             |
Spline ----------------------O---------------------- Spline
                             |
                             |
                             ^ Gate normal
```

Mathematically, for spline \(C_j\) passing through gate \(i\):

$$
C_j(u_i) \in H_i
$$

where \(H_i\) is the usable aperture of the gate, and

$$
C'_j(u_i) \parallel N_i
$$

where \(N_i\) is the gate-plane normal.

## Gate Orientation Controls Passage Angle

Rotating a routing gate changes the required direction of the spline as it crosses the gate.

```text
Unrotated gate:

                         |
-------------------------O-------------------------
                         |
                         ^ normal


Rotated gate:

                              /
                             /
----------------------------O
                          _/
                       __/
                    __/
```

This allows routing gates to be incorporated directly into engineered structures such as:

* Bulkhead penetrations
* Cable trays
* Conduit openings
* Grommets
* Connector backshells
* Wiring channels
* Structural ribs
* Harness guides
* Equipment enclosures

The geometry of the structure therefore controls both **where the wiring may pass** and **the direction in which it must pass**.

## A/B Transition Regions

Each routing gate contains two independent transition-length values:

```text
                         Routing Gate
                              |
                              |
          Side A              |              Side B
<-------------------->        |        <-------------------->
                              O
```

These values define how far the directional influence of the gate extends into the neighboring routing spans.

For gate \(i\):

$$
L_i^A
$$

defines the transition distance on Side A, and

$$
L_i^B
$$

defines the transition distance on Side B.

A typical gate-to-gate span therefore consists of:

```text
Gate 1                                                   Gate 2

  |                                                         /
  |                                                        /
  O---- transition ----________________---- transition ----O
                      straight routing span
```

The preferred path structure is therefore:

```text
[ Gate ]
    |
    +-- Curved transition
    |
    +-- Straight or nearly straight span
    |
    +-- Curved transition
    |
[ Gate ]
```

This keeps most of the wiring path geometrically simple while concentrating curvature where directional changes are actually required.

## Independent Transition Control

The A and B values do not need to be symmetrical.

For example, a gate might require a short approach but a long departure:

```text
                    Gate
                     |
                     |
-------- short ------O---------------- long transition ----------------
```

This can represent real mechanical conditions such as:

* A connector requiring a long strain-relief exit
* A bulkhead with limited clearance on one side
* A cable channel that immediately opens into a large cavity
* A wiring passage adjacent to a rigid component
* A controlled fan-out region near a connector

## Transition Clamping

If transition regions from neighboring gates would occupy more space than is physically available, the requested transition lengths are clamped.

```text
Requested:

Gate A                                      Gate B

  O--------------------------O
  <----------->      <------------->
   Transition A       Transition B

Requested transition regions overlap.
```

The solver reduces the effective transition distances so they fit within the available gate-to-gate span:

```text
Clamped:

Gate A                                      Gate B

  O--------------------------O
  <---------><-------------->
    Curve        Curve
```

The result remains deterministic and geometrically valid without allowing one transition region to extend through or beyond the neighboring gate.

When the safe localized regions still overlap, the solver may use the complete span
as one profile-to-profile cubic. It optimizes the two endpoint handles independently
so asymmetric profile orientations can retain their ordered crossing tangents and the
diameter-derived minimum bend radius.

If laterally offset profiles have equal tangents and one cubic cannot retain that
radius, the solver uses two opposing circular-arc cubic approximations. They meet at
the chord midpoint with a shared tangent, creating a smooth S-bend while preserving
the exact ordered profile crossings and endpoint directions.

Procedurally derived transition, center-drift, and profile-deformation values are
projected to the closest feasible result within the wire's physical limits and the
allowed routing corridor. User-facing controls expose the corresponding feasible
range and clamp entries to it. A generated value does not become a user-facing
failure while a valid routed shape remains inside those constraints. Validation
reports an impossible route only when the permitted corridor and physical limits
contain no feasible result.

The available distance may be represented approximately as:

$$
D_{available}
$$

with the requirement:

$$
L_{effective}^{B_i} + L_{effective}^{A_{i+1}}
\leq
D_{available}
$$

## Localized Curvature

The routing system intentionally avoids distributing curvature across the entire corridor.

A globally smoothed spline might produce:

```text
Gate A                                            Gate B

  |                                                  /
  O_______________________________________________--
```

Although mathematically smooth, this causes the entire span to participate in the directional change.

The preferred routing behavior is:

```text
Gate A                                            Gate B

  |                                                  /
  O---- curved ----____________________---- curved --O
                  mostly straight
```

This produces wiring geometry that is easier to understand, manufacture, inspect, and modify.

## Multi-Wire Routing

A routing gate may carry one or more splines through the same aperture.

Front view of a routing gate:

```text
+--------------------------------------+
|                                      |
|        o          o          o       |
|                                      |
|             o          o             |
|                                      |
|        o          o          o       |
|                                      |
+--------------------------------------+
```

Each `o` represents the centerline crossing of an individual wire.

All splines crossing the same gate share the gate's normal direction:

```text
Side view:

                    Gate plane
                        |
Wire 1 ----------------o----------------
                        |
Wire 2 ----------------o----------------
                        |
Wire 3 ----------------o----------------
                        |
Wire 4 ----------------o----------------
```

The crossing locations are distributed across the gate aperture so that the swept wire volumes do not intersect.

For wires \(a\) and \(b\), a clearance condition can be expressed as:

$$
d(C_a,C_b)
\geq
r_a+r_b+c
$$

where:

* \(r_a\) is the radius of Wire A
* \(r_b\) is the radius of Wire B
* \(c\) is the required additional clearance

## Routing-Gate Coordinate Frame

Each gate can be represented by a local coordinate frame:

```text
                     N
                     ^
                     |
                     |
             V       O------> U
             ^
            /
           /
```

Where:

* \(O\) is the gate origin
* \(U\) and \(V\) describe the gate surface plane
* \(N\) is the gate normal

A wire crossing location within the gate can therefore be described in local 2D gate coordinates:

$$
P_{ij}
=
O_i
+
u_{ij}U_i
+
v_{ij}V_i
$$

This makes placement and packing of multiple wires largely a two-dimensional problem within each gate.

The resulting 3D spline then connects corresponding crossing locations between successive routing gates.

## Example Routing Corridor

A corridor containing three gates might appear as follows:

```text
Gate 1                     Gate 2                       Gate 3

   |                           /                           |
   |                          /                            |
   O----\____________________O                            |
         \                  / \                           O
          \________________/   \_________________________/
           mostly straight       mostly straight
```

The routing gates determine the required local passage direction, while the spline solver determines the transition geometry between them.

A more structured representation is:

```text
       Gate 1                  Gate 2                  Gate 3

         |                        /                       |
         |                       /                        |
---------O----------------------O-------------------------O---------
       A | B                  A | B                   A | B
         |                      |
         |                      |
     transition             transition
       control                control
```

## Procedural Generation Workflow

A typical procedural routing operation can follow this sequence:

1. Place routing gates through the mechanical structure.
2. Orient each gate to define the required passage direction.
3. Shape each gate aperture to represent the usable wiring passage.
4. Assign Side A and Side B transition distances.
5. Assign the wires or splines that must pass through each gate.
6. Determine legal crossing locations within each gate aperture.
7. Enforce wire diameter and clearance requirements.
8. Derive minimum transition lengths from each wire diameter and local profile orientation.
9. Project requested transition lengths into the available span while preserving those minima.
10. Generate localized transition curves near each gate.
11. Connect the transition regions with straight or nearly straight spline spans.
12. Sweep the desired wire profiles along the generated centerlines.
13. Verify that resulting swept volumes do not intersect each other or surrounding restricted geometry.

## Design Characteristics

* **Constraint-driven**
  Routing geometry is generated from engineering constraints rather than manually placed spline handles.

* **Gate-controlled direction**
  The surface normal of each routing gate determines the spline tangent as the spline crosses the gate.

* **A/B transition control**
  Each side of every gate independently controls the distance over which directional transition occurs.

* **Localized curvature**
  Curvature is intentionally concentrated near routing gates.

* **Predominantly straight routing**
  Gate-to-gate spans remain straight or nearly straight wherever geometry permits.

* **Diameter-constrained transition regions**
  Transition distances clamp proportionally into the available span without crossing their calculated bend-safe minima.

* **Multi-wire capable**
  Multiple spline centerlines may pass through a single gate.

* **Collision-aware**
  Crossing locations and spline geometry are arranged so that swept wire volumes maintain required separation.

* **Aperture-aware**
  Wires may pass through any valid location within the usable gate region rather than being restricted to the gate center.

* **Procedural**
  Editing the location, orientation, shape, or transition parameters of a routing gate causes the affected wire paths to regenerate automatically.

* **Engineering-oriented**
  Primary controls correspond to physical routing concepts such as passage location, approach direction, transition distance, wire diameter, and clearance.

## Suggested Terminology

A concise technical description for this approach is:

> **Constraint-driven piecewise-faired spline routing using oriented passage gates and bounded transition regions.**

Alternative terminology could include:

* **Routing-gate spline system**
* **Gate-constrained procedural cable routing**
* **Oriented-passage spline routing**
* **Transition-bounded wire routing**
* **Constraint-based harness path generation**
* **Procedural gate-guided spline routing**

The term **routing gate** is particularly useful because each control structure represents more than a conventional spline waypoint: it defines a permitted passage region, passage orientation, local transition behavior, and potentially the packing constraints for multiple routed elements.
