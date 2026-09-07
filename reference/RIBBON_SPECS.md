# Profile-Gate Ribbon Routing

> **Document status:** Future M2 geometry reference. Profile-gate and ribbon behavior is
> not part of the current round-wire implementation. Milestone order and exit criteria
> are recorded in `../README.md`; persistent contracts belong in
> `UI_AND_DATA_MODEL.md` before implementation.

This routing method uses a sequence of **profile gates** to procedurally define ribbon cables made from an array of closely spaced wire splines. Unlike closed routing gates, profile gates are **open-ended sketched curves** that define the local transverse shape of the ribbon at each control station. A profile gate may be straight, curved, C-shaped, S-shaped, or any other open sketch profile. Its position, 3D orientation, and curvature control the local position, bank, twist, curl, and cross-sectional deformation of the ribbon, while corresponding wire positions are interpolated between successive gates to create the final ribbon geometry.

Round-wire center drift, diameter-driven ovalization, and closed-aperture packing
do not define ribbon behavior. Ribbon geometry and validation use the profile-gate
model in this document and are implemented after parallel-wire routing is complete.

## Core Concept

A ribbon is treated as an ordered array of adjacent wire centerlines:

```text
Wire 1  =========================================
Wire 2  =========================================
Wire 3  =========================================
Wire 4  =========================================
Wire 5  =========================================
Wire 6  =========================================
```

Each profile gate defines where those wires should lie across the width of the ribbon at a particular station.

A flat profile gate might look like:

```text
Profile Gate A

o---o---o---o---o---o
```

while a curved profile gate might look like:

```text
Profile Gate B

      o---o---o
    o         o
  o             o
```

or:

```text
Profile Gate C

o---o
    \
     o---o
         \
          o---o
```

Each `o` represents the location of one ribbon conductor at that gate.

## Open-Ended Profile Geometry

A profile gate is not limited to a straight line. It may consist of any open-ended sketched shape, including:

* Straight segments
* Circular or elliptical arcs
* C-shaped curves
* S-shaped curves
* Compound sketch geometry
* Freeform splines
* Piecewise-connected open curves

Examples:

```text
Straight:

--------------------------


C-shaped:

       __________
    __/          \__


S-shaped:

   _____
__/     \____
            \___


Compound:

---------\
          \____
               \------
```

The gate shape directly defines the local cross-sectional deformation of the ribbon.

## Ribbon Sampling

If the ribbon contains \(n\) wires, the profile gate is sampled at \(n\) transverse locations.

For profile gate \(i\):

$$
G_i(s)
$$

represents the open profile curve.

Each wire \(j\) is assigned a normalized transverse coordinate:

$$
q_j \in [0,1]
$$

and its position on the profile gate is:

$$
P_{ij}=G_i(q_j)
$$

In practice, sampling should be based on **arc length** rather than raw spline parameterization so that adjacent wires remain evenly spaced across curved profile gates.

```text
Uneven spline parameterization:

o-o-----o--o----------o

Preferred arc-length spacing:

o---o---o---o---o
```

## Implied Profile Extensions

The drawn length of a profile gate does not determine the ribbon width.

If the sketched profile is shorter than the ribbon requires, the gate is treated as having an implied continuation beyond its visible endpoints.

```text
Drawn profile:

        --------

Required ribbon width:

<------------------------>

Effective interpretation:

---------[--------]---------
          used
```

If the profile gate is longer than the ribbon width, the ribbon is centered on the profile and the excess geometry is ignored.

```text
Profile gate:

----------------------------------------

Ribbon width:

          <---------------->

Used section:

----------[----------------]----------
```

This allows the designer to focus on the desired profile shape rather than manually matching every profile gate to an exact cable width.

## Flat Ribbon Routing

When all profile gates are straight, the system behaves like a conventional flat ribbon router.

```text
Gate A                 Gate B                 Gate C

o-o-o-o-o-o            o-o-o-o-o-o            o-o-o-o-o-o
```

The resulting wire paths remain parallel or nearly parallel:

```text
================================================
================================================
================================================
================================================
================================================
================================================
```

## Curving the Ribbon

Moving the center of successive profile gates causes the entire ribbon to bend through space.

```text
Gate A              Gate B              Gate C

--------               --------
                          --------
                                      --------
```

Result:

```text
==================
                  \
                   \================
                                    \
                                     ==========
```

The ribbon remains locally shaped by each profile while its overall path curves through the routing corridor.

## Banking and Twisting

Rotating a profile gate changes the orientation of the ribbon cross section.

```text
Gate A              Gate B              Gate C

----------              /                  |
                       /                   |
                      /                    |
```

Interpolating between these profile orientations creates ribbon bank or twist:

```text
Flat              Twisting              Vertical

==========        ========\              ||
                   ========\             ||
                    ========\            ||
```

The profile geometry therefore provides an explicit orientation constraint that a center spline alone cannot provide.

## Curling the Ribbon

A curved profile gate deforms the wire array across its width.

Flat profile:

```text
o---o---o---o---o---o
```

C-shaped profile:

```text
      o---o
    o     o
   o       o
  o         o
```

S-shaped profile:

```text
o---o
    \
     o---o
         \
          o---o
```

By interpolating between flat and curved profile gates, the ribbon can gradually curl:

```text
Gate A            Gate B             Gate C

o-o-o-o-o          o-o-o             o---o
                  o     o           o     o
                                    o     o
```

Resulting behavior:

```text
Flat ribbon
======================

              gradually curling
====================\____
                         \__
                            )
                           )
```

## Profile-Gate Interpolation

Unlike bounded-transition routing gates, profile gates operate more like **interpolated spline stations**.

Each gate defines the transverse state that the ribbon should assume at that location:

```text
Gate A               Gate B               Gate C

----------              /                    (
                       /                    (
                      /                      (
```

The wire splines interpolate smoothly through the corresponding locations on each gate.

For wire \(j\):

$$
C_j(u_i)=P_{ij}
$$

where:

$$
P_{ij}=G_i(q_j)
$$

The longitudinal spline therefore passes through the corresponding sampled positions of all profile gates:

```text
Wire j:

Gate A          Gate B          Gate C

   o--------------o--------------o
```

The same process is repeated for every wire in the ribbon.

## Ribbon as a Parametric Surface

The entire ribbon may also be interpreted as a continuous parametric surface:

$$
S(u,v)
$$

where:

* \(u\) represents position along the routing corridor
* \(v\) represents position across the ribbon width

Each profile gate defines a transverse section:

$$
S(u_i,v)=G_i(v)
$$

and each wire path is simply a constant-\(v\) curve:

$$
C_j(u)=S(u,v_j)
$$

Conceptually:

```text
Profile Gate A        Profile Gate B        Profile Gate C

o---o---o---o         o---o---o            o
                                            \
 o---o---o---o          o---o---o            o
                                              \
  o---o---o---o           o---o---o            o
```

Longitudinal correspondence between the sampled positions creates the individual wire splines.

## Compound Shape Control

A profile gate can simultaneously control several aspects of ribbon behavior.

Its:

* **Position** controls where the ribbon passes.
* **Orientation** controls ribbon bank and roll.
* **Open-profile geometry** controls cross-sectional curl or deformation.
* **Relationship to neighboring gates** controls longitudinal curvature and twist.

For example:

```text
Gate A                 Gate B                 Gate C

----------------       _____                   )
                     _/     \_                (
                                              )
```

could produce a ribbon that:

1. Starts flat
2. Begins curving
3. Develops a bowed cross section
4. Rotates in space
5. Ends in a curled configuration

## Folding Behavior

Profile gates can also be used to create deliberate ribbon folds.

A smooth routing sequence might interpolate continuously:

```text
----------      --------      ------      ----
```

while a designated fold station could intentionally create a sharp orientation change:

```text
Before fold

------------------+
                  |
                  |
                  |
                  |

After fold
```

Depending on the implementation, folds may be represented by:

* Reduced continuity at the fold gate
* Explicit crease constraints
* Very short interpolation spans
* Dedicated fold-angle parameters

This allows the same profile-gate system to support both smooth ribbon routing and deliberate mechanical folds.

## Multi-Wire Construction

Although the result behaves visually like a ribbon, the underlying geometry remains an array of independent wire sweeps.

```text
Profile gate:

o---o---o---o---o---o
|   |   |   |   |   |
|   |   |   |   |   |
v   v   v   v   v   v

Individual longitudinal splines
```

Each wire:

* Maintains its corresponding transverse position
* Interpolates through every applicable profile gate
* Can be swept independently
* Can retain its own diameter or section
* Can be checked independently for collision or clearance

This allows ribbon-cable behavior without requiring the cable to be represented as a single monolithic surface or solid.

## Example Profile-Gate Corridor

A simple profile-gate routing sequence might look like:

```text
Gate 1                  Gate 2                  Gate 3

o-o-o-o-o-o             o-o-o                   o
                       o     o                o     o
                                              o   o
```

The generated wire array interpolates between these transverse states:

```text
Wire 1  =====================\______________
Wire 2  ======================\_____________
Wire 3  =======================\____________
Wire 4  ========================\___________
Wire 5  =========================\__________
Wire 6  ==========================\_________
```

while also following the 3D placement and orientation of the profile gates.

## Design Characteristics

* **Open-profile controlled**
  Each gate is an open-ended sketched curve rather than a closed aperture.

* **Arbitrary profile geometry**
  Gates may be straight, curved, C-shaped, S-shaped, freeform, or compound.

* **Cross-sectional deformation**
  Gate curvature directly controls the local shape of the wire array.

* **Orientation-aware**
  Rotating a profile gate controls ribbon bank, roll, and twist.

* **Position-aware**
  Translating profile gates controls the overall routing path.

* **Interpolated behavior**
  Wire paths interpolate corresponding positions across successive profile gates.

* **Arc-length sampled**
  Conductors are preferably distributed using physical arc length to preserve consistent spacing.

* **Width-independent control geometry**
  The sketched length of a profile gate does not need to equal the ribbon width.

* **Implied extension**
  Profiles shorter than the ribbon are conceptually extended as needed.

* **Centered trimming**
  Profiles longer than the ribbon are sampled only over the centered region required by the ribbon width.

* **Procedural multi-wire generation**
  A single profile-gate sequence controls an entire array of wire splines.

* **Supports smooth deformation**
  The system can produce gradual bending, banking, twisting, curling, and compound deformation.

* **Supports intentional folds**
  Local continuity rules may be altered to create deliberate crease or fold behavior.

* **Editable as a unified ribbon**
  Designers manipulate profile gates rather than adjusting the individual wire splines.

## Suggested Terminology

A concise description for the method is:

> **Profile-gate ribbon routing uses interpolated open sketch profiles to procedurally control the position, orientation, and transverse deformation of an array of adjacent wire splines.**

A more technical description is:

> **Constraint-driven ribbon routing using interpolated open-profile stations and arc-length-corresponded longitudinal splines.**

This distinguishes the two routing systems clearly:

* **Routing gates** constrain independent wire paths through closed engineered passages.
* **Profile gates** define the transverse shape and orientation of ribbon-like arrays using open-ended sketch profiles.
