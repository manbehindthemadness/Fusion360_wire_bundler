# Terminator Sections

> **Document status:** Future M1/M2 geometry reference. The current implementation has
> symmetric End A/End B profiles and smooth end transitions, but the complete terminator
> and per-member guide system described here is not implemented. Milestone status is in
> `../README.md`; persistent contracts belong in `UI_AND_DATA_MODEL.md`.

A **terminator section** is the procedural transition region between the first or last control structure in a routing system and the actual modeled connection points of the wires, conductors, pins, terminals, or cable interfaces. Terminator sections are shared across all routing modes and are independent of whether the internal cable is modeled as loose wires, a structured ribbon, a frayed ribbon, or another grouped arrangement. Each wire begins or ends at its own physical connection profile, extends initially perpendicular to that profile, and then transitions through zero or more optional per-wire guide profiles before converging into the first routing or profile gate. The same process occurs in reverse at the opposite end of the routed structure.

## Core Concept

A complete routed assembly can be divided into three major regions:

```text
Connection Geometry
       |
       v

[ Start Profiles ]
       |
       |  Terminator Section
       v
[ First Control Gate ]
       |
       |  Main Routing Corridor
       |
[ Last Control Gate ]
       |
       |  Terminator Section
       v
[ End Profiles ]
```

The terminator section therefore acts as the interface between:

* fixed physical connection geometry
* procedural cable routing geometry

It absorbs the geometric transition between the two.

---

## Connection Profiles

Each wire begins or ends at a **connection profile** that defines the local shape and size of its sweep or loft.

Examples may include:

```text
Round wire:

    ( )


Rectangular conductor:

   +----+
   |    |
   +----+


Flat contact:

   --------


Custom terminal profile:

    /----\
   |      |
    \____/
```

The connection profile determines the actual terminal geometry of the routed element.

The spline leaving the connection profile initially follows the profile normal:

```text
Connection Profile

       +------+
       |      |
       +------+
           |
           |
           |  initial spline direction
           |
           v
```

This ensures that the modeled conductor exits the connector, pin, pad, terminal, or attachment surface in a controlled and mechanically meaningful direction.

---

## Initial Perpendicular Departure

For each connection profile \(P_j\), the corresponding wire centerline begins perpendicular to the profile plane.

If:

$$
N_j
$$

is the connection-profile normal, then the initial spline tangent satisfies:

$$
C'_j(0) \parallel N_j
$$

Conceptually:

```text
Terminal face

+----------------------+
|   o    o    o    o   |
+----------------------+
    |    |    |    |
    |    |    |    |
    v    v    v    v

Initial conductor departure
```

The wire paths may then begin collecting toward the first control gate.

---

## Collecting Into the First Gate

The terminator section allows a dispersed set of connection points to transition into the organized arrangement required by the first control structure.

For example:

```text
Connector Pins                         First Routing Gate

o     o     o     o
 \     \   /     /
  \     \ /     /
   \     |     /
    \    |    /
     o---o---o
```

Or for a ribbon-like termination:

```text
Connector

o-o-o-o-o-o
||||||||||||
 \ \ \ \ \ \
  \ \ \ \ \ \
   o-o-o-o-o-o      First Profile Gate
```

The connection geometry may be regular or irregular.

---

## Arbitrary Connection Arrangements

The terminator section does not assume that the connection points form a clean row or grid.

The attachment geometry may be:

### Structured

```text
o   o   o   o
o   o   o   o
```

### Ribbon-like

```text
o-o-o-o-o-o-o
```

### Frayed ribbon

```text
o-o-o-o-o-o
 \ \  |  /
  \ \ | /
   \ \|/
```

### Arbitrary

```text
      o

o             o

       o

   o               o
```

All of these can collect into the same downstream control structure.

---

## Per-Wire Guide Profiles

Each wire may optionally pass through one or more **guide profiles** inside the terminator section before reaching the first control gate.

```text
Connection       Guide 1       Guide 2       First Gate

    o---------------o-------------o--------------o
```

Different wires may have different guide-profile sequences:

```text
Wire A:

o---------o-----------------------------o


Wire B:

o----o---------o------------------------o


Wire C:

o------------------o------o-------------o
```

Guide profiles provide local control over the conductor path without requiring the entire terminator region to be controlled by a single shared gate.

They can be used to:

* control connector breakout
* avoid nearby mechanical geometry
* establish temporary spacing
* create intentional fan-out
* guide conductors around obstacles
* maintain local alignment
* control entry into the first routing gate
* produce asymmetrical termination geometry

---

## Terminator Collection Behavior

The terminator section can be viewed as a procedural **collection region**.

Individual conductors begin from their physical attachment geometry:

```text
o       o        o      o
|       |        |      |
|       |        |      |
```

and progressively organize into the arrangement defined by the first control gate:

```text
o       o        o      o
 \       \      /      /
  \       \    /      /
   \       \  /      /
    \       \/      /
     o---o---o---o
```

The opposite terminator performs the inverse operation:

```text
Last Gate                         Connection Points

o---o---o---o
 \   \   \   \
  \   \   \   \
   o   o      o     o
```

---

## Shared Across Routing Modes

Terminator sections operate independently of the routing method used between the first and last control structures.

### Loose-wire routing

```text
Connector    Terminator     Routing Gates

o   o
 \ /
  o----------O----------O
```

### Ribbon routing

```text
Connector    Terminator     Profile Gates

o-o-o-o
 \ \ \ \
  o-o-o-o------~~~~------~~~~
```

### Frayed ribbon

```text
Connector                   Ribbon Region

o   o   o   o
 \  |  /  /
  \ | /  /
   o-o-o-o================
```

This provides one consistent termination system regardless of the cable topology used in the main routing corridor.

---

## Guide-Profile Hierarchy

A terminator path for a single conductor may be described as:

```text
Connection Profile
       |
       v
Guide Profile 1
       |
       v
Guide Profile 2
       |
       v
Guide Profile N
       |
       v
First Control Gate
```

or, on the opposite side:

```text
Last Control Gate
       |
       v
Guide Profile N
       |
       v
Guide Profile 2
       |
       v
Guide Profile 1
       |
       v
Connection Profile
```

Guide profiles are optional.

A simple termination may contain none:

```text
Connection Profile ---------------- First Gate
```

while a complex termination may contain several:

```text
Connection --> Guide --> Guide --> Guide --> Gate
```

---

## Relationship to the Main Control Gate

The final portion of the terminator section must transition cleanly into the geometry expected by the first or last control structure.

For a routing gate:

```text
Connection side              Routing Gate

o
 \
  \
   \___________
               \______O
                      |
                      |
```

For a profile gate:

```text
Connection side              Profile Gate

o       o       o
 \      |      /
  \     |     /
   \    |    /
    o---o---o---o
```

The gate defines the organized state of the cable at the beginning of the main corridor.

The terminator section determines how the real connection geometry reaches that state.

---

## Independent Wire Control

Because guide profiles are assigned per wire, individual conductors can take different paths before joining the common routed structure.

```text
Connection Geometry

o------\
        \____________
                     \
o---------o-----------\------ Gate
                       \
o----o------------------\
```

This is especially useful where:

* connector pins have different depths
* terminals are staggered
* wires must avoid connector hardware
* bundle members enter from different directions
* ribbon conductors separate before termination
* some wires require additional strain-relief geometry

---

## Example: Ribbon to Individual Terminals

A structured ribbon can gradually separate into individual conductors:

```text
Ribbon                        Terminator                  Pins

====================o
=====================\____________o
======================\________________o
=======================\_____________________o
```

Or the reverse:

```text
Pins                          Terminator                  Ribbon

o________________
                 \
        o_________\________________
                   \
              o_____\====================
                     ====================
                     ====================
```

This allows the same routed object to behave like a ribbon internally while terminating into discrete physical contacts.

---

## Example: Random Terminals to Organized Bundle

```text
Physical Connections                         First Gate

      o
       \
o-------\________
         \       \
    o-----\-------\____
           \           \
             o----------o
                        |
                    o---o---o---o
```

The terminator solver determines a smooth, collision-free collection path from the attachment geometry to the required gate arrangement.

---

## Design Characteristics

* **Common to all routing modes**
  Terminator sections use the same fundamental behavior whether the routed object is a ribbon, loose bundle, frayed ribbon, or parallel wire group.

* **Connection-profile driven**
  Every wire begins and ends from a profile that defines its sweep or loft geometry.

* **Normal initial departure**
  Conductors initially extend perpendicular to their connection profiles.

* **Per-wire routing**
  Each conductor retains an independent centerline through the terminator section.

* **Optional guide profiles**
  Zero or more guide profiles may be assigned independently to each conductor.

* **Procedural collection**
  Dispersed or structured connection points converge into the organization defined by the first control gate.

* **Procedural breakout**
  The final terminator section performs the inverse process, distributing the routed bundle toward its destination connection points.

* **Topology-independent**
  Connection arrangements may be linear, ribbon-like, grid-based, staggered, irregular, or completely arbitrary.

* **Supports fraying and consolidation**
  Ribbon structures can separate into individual conductors near a termination, and loose conductors can consolidate into an organized bundle.

* **Local geometric control**
  Guide profiles provide fine control near mechanical interfaces without affecting the entire routing corridor.

* **Profile-preserving**
  The wire sweep or loft remains associated with the conductor's defined profile throughout the termination geometry.

* **Compatible with both control systems**
  Terminator sections can connect directly to either routing gates or profile gates.

---

## Suggested Terminology

A concise description is:

> **A terminator section is a procedural collection or breakout region that connects physical conductor attachment profiles to the first or last control structure of a routed cable system.**

A more technical description is:

> **Terminator sections interpolate individual conductor paths from profile-normal connection geometry through optional per-wire guide profiles into the organized cross-sectional state defined by the adjacent control gate.**

The complete routing architecture can therefore be described as:

```text
[ Connection Profiles ]
          |
          v
[ Start Terminator ]
          |
          v
[ First Control Structure ]
          |
          v
[ Procedural Routing Corridor ]
          |
          v
[ Last Control Structure ]
          |
          v
[ End Terminator ]
          |
          v
[ Connection Profiles ]
```

This separates the system into three clear responsibilities:

* **Terminators** handle physical connection and breakout geometry.
* **Routing gates** handle constrained routing through engineered passages.
* **Profile gates** handle ribbon-like cross-sectional shaping and deformation.
