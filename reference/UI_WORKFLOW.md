# Harness Builder User Interaction Workflow

> **Document status:** Broad UX vision and illustrative future workflow. It contains
> concepts from several milestones and is not a statement of current implementation.
> Use `../README.md` for current status and delivery order, and
> `UI_AND_DATA_MODEL.md` for authoritative data and interaction contracts when an older
> illustration or label differs.

The Harness Builder workflow should guide the user through creation of a complete wire or ribbon harness without requiring direct manipulation of spline mathematics. The user defines the physical connections, conductor properties, control structures, terminators, routing relationships, and optional overrides; the add-in then generates and previews the resulting paths before committing editable Fusion 360 geometry. Every conductor remains uniquely mapped from its starting connection to its destination throughout the workflow, and all generated wires retain their individual paths, profiles, sweeps or lofts, bodies, and metadata after creation.

---

# 1. Launch Harness Builder

The add-in should be available from a dedicated Fusion toolbar command:

```text
ASSEMBLE
└── Harness Builder
```

Selecting the command opens the Harness Builder palette.

```text
┌─────────────────────────────────────────────┐
│ HARNESS BUILDER                             │
├─────────────────────────────────────────────┤
│                                             │
│  [ Create New Harness ]                     │
│                                             │
│  Existing Harnesses                         │
│                                             │
│  Harness_001                                │
│  Harness_002                                │
│                                             │
└─────────────────────────────────────────────┘
```

The user may either:

* Create a new harness
* Open an existing procedural harness
* Create a child harness inside an existing harness
* Inspect a previously generated harness

Harness discovery is attribute-driven across the active design. A malformed or
unsupported stored definition remains visible as a damaged entry with its component
name and load error; it must not prevent other harnesses from loading. Creating a
harness from the palette uses a native Fusion command for document-changing inputs,
then refreshes the persistent palette after the transaction succeeds.

---

# 2. Select Parent Assembly

When creating a new harness, the first operation is selecting the Fusion component under which the harness will be created.

```text
CREATE HARNESS

Parent Component:

[ Electronics Assembly                  ] [Select]

Harness Name:

[ Harness_003                           ]

                       [Continue]
```

The selected parent determines the assembly hierarchy.

Harnesses and branches require a Hybrid design because they create nested internal
components. If creation begins in a Part design, Harness Builder converts the document
to Hybrid intent before adding the harness component. A standalone single-wire workflow
keeps Part intent and creates each wire as a body in the part rather than as a child
component. Assembly-only documents create the harness as an external component in the
active Fusion cloud folder; saving the parent assembly persists that new component.
Before serialization and creation, Harness Builder increments a conflicting requested
name until it is unique among sibling occurrences and, for external components, files
in the target cloud folder.

```text
Main Assembly
│
├── Mechanical
├── Electronics
│   │
│   └── Harness_003
│
└── Other Components
```

If an existing harness is selected as the parent:

```text
Harness_001
│
├── Wire Components
│
└── Branch_001
```

the resulting harness becomes a nested child or branch assembly.

---

# 3. Select Harness Routing Mode

The user chooses the primary routing-control method.

```text
ROUTING MODE

○ Routing Gates
  Closed control structures used to route
  independent wires through constrained passages.

○ Profile Gates
  Open sketched profiles used to shape and orient
  ribbon-like arrays of adjacent wires.
```

This selection determines which control-structure tools appear later.

The terminator system remains identical in both modes.

---

# 4. Define Starting Connections

The next step establishes the physical origin of each conductor.

```text
START CONNECTIONS

[ Select Connection Profiles ]

Selected: 6

01   Profile      ✓
02   Profile      ✓
03   Profile      ✓
04   Profile      ✓
05   Profile      ✓
06   Profile      ✓
```

The selected geometry may represent:

* connector pins
* circular wire profiles
* terminal faces
* solder pads
* rectangular contacts
* custom sweep profiles
* existing cable cross sections

Each selected profile establishes:

```text
Connection Position
Connection Orientation
Wire Sweep/Loft Profile
Initial Departure Normal
```

The wire leaves the connection perpendicular to this profile.

---

# 5. Define Destination Connections

The destination profiles are then selected.

```text
DESTINATION CONNECTIONS

[ Select Connection Profiles ]

Selected: 6

01   Profile      ✓
02   Profile      ✓
03   Profile      ✓
04   Profile      ✓
05   Profile      ✓
06   Profile      ✓
```

At this stage the system knows the possible starts and destinations but should not yet assume their correspondence unless the user explicitly requests automatic pairing.

---

# 6. Establish Wire Mapping

The next view becomes the primary **Wire Mapping Table**.

```text
┌──────┬────────────┬────────────┬──────────┬──────────┐
│ Wire │ Start      │ End        │ Profile  │ Status   │
├──────┼────────────┼────────────┼──────────┼──────────┤
│ 001  │ Start 01   │ End 01     │ Ø1.20    │ ✓        │
│ 002  │ Start 02   │ End 02     │ Ø1.20    │ ✓        │
│ 003  │ Start 03   │ End 03     │ Ø1.20    │ ✓        │
│ 004  │ Start 04   │ End 04     │ Ø1.00    │ ✓        │
│ 005  │ Start 05   │ End 05     │ Ø1.00    │ ✓        │
│ 006  │ Start 06   │ End 06     │ Ø1.50    │ ✓        │
└──────┴────────────┴────────────┴──────────┴──────────┘
```

Available operations:

```text
[Auto Pair]
[Reverse Pairing]
[Edit Mapping]
[Add Wire]
[Remove Wire]
```

The add-in must always preserve explicit conductor identity.

For example:

```text
START                           DESTINATION

01 o ---------------------------- o 04
02 o ---------------------------- o 01
03 o ---------------------------- o 06
04 o ---------------------------- o 03
05 o ---------------------------- o 02
06 o ---------------------------- o 05
```

The correspondence should be displayed visually in the viewport before routing begins.

---

# 7. Assign Wire Properties

Each conductor receives a sweep or loft definition.

Common values may be assigned to the entire group:

```text
DEFAULT WIRE

Profile:       Circular
Diameter:      1.20 mm
Clearance:     0.50 mm

[Apply to All]
```

Individual overrides may then be entered:

```text
Wire 001     Ø1.20
Wire 002     Ø1.20
Wire 003     Ø1.50
Wire 004     Ø1.00
Wire 005     Ø1.00
Wire 006     Ø2.00
```

The selected start and destination profiles remain authoritative when custom geometry is required.

---

# 8. Display Initial Connection Preview

As soon as the mapping is valid, the viewport should show lightweight connection indicators.

```text
START                                  END

o  - - - - - - - - - - - - - - - -  o
o  - - - - - - - - - - - - - - - -  o
o  - - - - - - - - - - - - - - - -  o
o  - - - - - - - - - - - - - - - -  o
```

These should not yet represent actual routes.

They simply show:

* conductor identity
* start/end correspondence
* start profile orientation
* destination profile orientation

This gives the user a chance to catch an incorrect mapping before any routing work is performed.

---

# 9. Define Start Terminators

The user can now edit the region between the connection profiles and the first control structure.

```text
START TERMINATOR

Wire 001       [Edit]
Wire 002       [Edit]
Wire 003       [Edit]
Wire 004       [Edit]
Wire 005       [Edit]
Wire 006       [Edit]

[Add Common Guide]
```

By default:

```text
Connection Profile
        │
        │ perpendicular departure
        ▼
First Control Structure
```

For wires requiring additional control:

```text
Connection Profile
        │
        ▼
Guide Profile 01
        │
        ▼
Guide Profile 02
        │
        ▼
First Control Structure
```

Guide profiles are assigned independently per wire.

---

# 10. Add Control Structures

The user begins constructing the main routing corridor.

For routing-gate mode:

```text
CONTROL STRUCTURES

[ + Add Routing Gate ]

01   Routing Gate
02   Routing Gate
03   Routing Gate
```

For profile-gate mode:

```text
CONTROL STRUCTURES

[ + Add Profile Gate ]

01   Profile Gate
02   Profile Gate
03   Profile Gate
```

Selecting **Add Gate** switches Fusion into geometry-selection mode.

The user selects the existing sketch geometry that defines the gate.

---

# 11. Establish Gate Order

The order of the control structures is explicitly shown.

```text
ROUTE SEQUENCE

START
  │
  ▼
☰ Routing Gate 01
  │
  ▼
☰ Routing Gate 02
  │
  ▼
☰ Routing Gate 03
  │
  ▼
END
```

The user may reorder gates by dragging.

```text
☰ Gate 01
☰ Gate 03
☰ Gate 02
```

The resulting order is immediately reflected in the route preview.

Spatial proximity should never silently redefine gate order.

---

# 12. Configure Routing Gates

For routing-gate mode, selecting a gate opens its property panel.

```text
ROUTING GATE 02

Geometry
[ Selected Sketch Profile ✓ ]

Side A Transition
[ 40.0 mm ]

Side B Transition
[ 65.0 mm ]

Minimum Wire Clearance
[ 0.50 mm ]

Affected Wires
☑ 001
☑ 002
☑ 003
☑ 004
☑ 005
☑ 006
```

The user controls:

* Gate geometry
* Gate orientation
* Side A transition distance
* Side B transition distance
* Applicable wires
* Packing behavior
* Clearance

The wire paths cross the gate perpendicular to its plane.

```text
                    Gate
                     |
---------------------o---------------------
                     |
                  normal
```

Transition distances control where curvature is allowed to occur.

```text
Gate A                                  Gate B

  |                                        /
  O---curve---________________---curve----O
             mostly straight
```

---

# 13. Configure Profile Gates

For profile-gate mode, the selected sketch geometry represents an open-ended transverse profile.

```text
PROFILE GATE 02

Geometry
[ Selected Open Sketch ✓ ]

Sampling
[ Arc Length ]

Centering
[ Automatic ]

Affected Wires
[ 001 through 012 ]

Continuity
[ Smooth ▼ ]
```

The profile gate may be:

```text
Straight

-------------------------


C-Shaped

      _________
   __/         \__


S-Shaped

____
    \____
         \____
```

The conductors are sampled along the gate and corresponding samples are interpolated longitudinally.

```text
Gate 01              Gate 02              Gate 03

o-o-o-o-o            o---o                  o
                    o     o               o   o
                                           o
```

---

# 14. Live Centerline Preview

Once sufficient information exists, the system begins generating a live centerline preview.

```text
PREVIEW MODE

● Centerlines
○ Wire Envelopes
○ Final Geometry
```

The default preview should use lightweight transient geometry.

Example:

```text
Start      Gate 1       Gate 2       Gate 3       End

o-----------o------------o------------o------------o
 o-----------o------------o------------o------------o
  o-----------o------------o------------o------------o
```

Updating any control parameter should refresh the affected paths.

Examples include:

* moving a gate
* rotating a gate
* changing transition distance
* reshaping a profile gate
* reordering gates
* editing a terminator guide
* changing a wire diameter

---

# 15. Selection Highlighting

Selecting any wire in the UI should highlight the complete conductor path.

```text
WIRE 003

Start
  ↓
Terminator
  ↓
Gate 01
  ↓
Gate 02
  ↓
Gate 03
  ↓
End Terminator
  ↓
Destination
```

Selecting a control structure should highlight every affected conductor.

This makes the relationship between table data and viewport geometry immediately visible.

---

# 16. Define End Terminators

The same workflow used for the start terminator is applied after the final control structure.

```text
Last Control Structure
        │
        ▼
Guide Profile 02
        │
        ▼
Guide Profile 01
        │
        ▼
Destination Profile
```

Each conductor may have:

```text
0 guides
1 guide
2 guides
...
N guides
```

This supports:

* connector fan-out
* ribbon fraying
* local path correction
* staggered contacts
* unusual terminal geometry

---

# 17. Preview Wire Envelopes

Once the centerline solution is valid, the user can enable an envelope preview.

```text
PREVIEW

☑ Show Centerlines
☑ Show Wire Diameters
☑ Show Clearance
☑ Show Control Structures
```

Example:

```text
Centerline:

---------------------------


Wire envelope:

===========================


Clearance envelope:

((=========================))
```

For large harnesses, this preview may use simplified geometry rather than final B-Rep sweeps.

---

# 18. Collision and Clearance Analysis

The system evaluates:

```text
Wire ↔ Wire
Wire ↔ Control Geometry
Wire ↔ Restricted Geometry
```

A problem should be identified both in the UI and in the viewport.

Example:

```text
WIRE 008

⚠ Clearance violation
   with Wire 009

Location:
Gate 03 → Gate 04
```

The affected area should be highlighted.

The system should distinguish between:

```text
ERROR
Cannot generate valid geometry.

WARNING
Geometry can be generated but violates
a user-defined engineering preference.

INFO
Transition length was automatically clamped.
```

---

# 19. Per-Wire Inspection

Before final generation, the user should be able to inspect any conductor individually.

```text
WIRE 003

Start Connection     J1 / Pin 03
End Connection       J4 / Pin 07

Profile              Ø1.20 mm

Start Guides         1
Control Structures   4
End Guides           0

Calculated Length    917.28 mm

Minimum Radius       14.2 mm
Minimum Clearance     0.8 mm

Status               VALID
```

This provides a final engineering check before solid generation.

---

# 20. Harness Validation

The add-in performs a complete validation pass.

```text
HARNESS VALIDATION

Connections
✓ 12 unique starts
✓ 12 unique destinations
✓ 12 complete mappings

Routing
✓ All required gates valid
✓ Gate order valid
✓ All wires routable

Geometry
✓ Sweep profiles valid
✓ No illegal self-intersections
✓ Clearance requirements satisfied

Terminators
✓ All start paths valid
✓ All end paths valid

Assembly
✓ Parent component valid
✓ Wire IDs unique
```

Only valid geometry should proceed directly to final construction.

---

# 21. Build Harness

The user presses:

```text
[ BUILD HARNESS ]
```

The add-in creates:

```text
Harness_001
│
├── 001_<length>mm
├── 002_<length>mm
├── 003_<length>mm
│
├── Control Geometry
│
└── Harness Metadata
```

Each wire component receives:

```text
Start Profile
Start Terminator Geometry
Main Routing Path
End Terminator Geometry
End Profile
Sweep/Loft Feature
Finished Body
Metadata
```

---

# 22. Measure Final Wire Lengths

The final length should be measured from the actual generated conductor centerline.

For example:

```text
Wire 001 = 842.58 mm
Wire 002 = 917.31 mm
Wire 003 = 901.76 mm
```

The display names become:

```text
001_842.6mm
002_917.3mm
003_901.8mm
```

Length should be calculated after the final geometry is generated so the displayed value represents the actual modeled route.

---

# 23. Final Assembly Result

The Fusion browser should show a clean structure.

```text
Harness_001
│
├── 001_842.6mm
│   ├── Path
│   ├── Profiles
│   ├── Sweep
│   └── Body
│
├── 002_917.3mm
│   ├── Path
│   ├── Profiles
│   ├── Sweep
│   └── Body
│
├── 003_901.8mm
│   └── ...
│
├── Control_Geometry
│   ├── Gate_01
│   ├── Gate_02
│   └── Gate_03
│
└── Harness_Data
```

The assembly may now be treated as ordinary Fusion geometry.

---

# 24. Reopen Existing Harness

Selecting a generated harness and choosing:

```text
Harness Builder
→ Edit Harness
```

should reload the saved harness definition.

```text
HARNESS_001

12 Wires
4 Routing Gates
2 Terminators
Status: Procedural
```

The user may then:

* add wires
* remove wires
* change connections
* move gates
* reshape profile gates
* reorder gates
* edit transition lengths
* edit terminator guides
* regenerate selected wires
* regenerate the entire harness

---

# 25. Detect Manual Wire Editing

If a generated path has been edited manually, the add-in should detect that the current geometry no longer matches the saved procedural state.

```text
WIRE 006

Status: MODIFIED

The routing path has been manually changed.
```

The wire should not be silently overwritten.

Possible actions:

```text
[ Preserve Manual Wire ]
[ Regenerate Wire ]
[ Detach From Harness ]
[ Duplicate Before Regeneration ]
```

---

# 26. Selective Regeneration

The user should not need to rebuild an entire harness after every change.

The add-in should support:

```text
[ Regenerate Selected Wire ]
[ Regenerate Affected Wires ]
[ Regenerate Entire Harness ]
```

For example, moving Gate 03 may affect only:

```text
Wire 001
Wire 002
Wire 005
Wire 006
```

Other wire components remain untouched.

---

# 27. Branch Creation

A branch can be created by selecting an existing harness or branch as the parent and launching Harness Builder again.

```text
Harness_Main
│
├── Wires
│
└── Harness_Branch_A
    │
    ├── Wires
    │
    └── Harness_Branch_B
```

This provides a general-purpose solution for:

* Y harnesses
* H harnesses
* breakout branches
* connector subgroups
* local ribbon separations

without requiring a separate branching workflow.

---

# Recommended Main Interface

The persistent palette could ultimately be organized into the following sections:

```text
┌─────────────────────────────────────────────┐
│ HARNESS BUILDER                             │
├─────────────────────────────────────────────┤
│ HARNESS                                     │
│ Parent / Name / Mode                        │
├─────────────────────────────────────────────┤
│ WIRES                                       │
│ Connection Mapping / Profiles               │
├─────────────────────────────────────────────┤
│ START TERMINATOR                            │
│ Connection / Guide Profiles                 │
├─────────────────────────────────────────────┤
│ ROUTE                                       │
│ Ordered Routing or Profile Gates            │
├─────────────────────────────────────────────┤
│ END TERMINATOR                              │
│ Guide Profiles / Connections                │
├─────────────────────────────────────────────┤
│ VALIDATION                                  │
│ Errors / Warnings / Lengths                 │
├─────────────────────────────────────────────┤
│ PREVIEW                                     │
│ Centerline / Envelope / Clearance           │
├─────────────────────────────────────────────┤
│                                             │
│ [ UPDATE PREVIEW ]                          │
│                                             │
│ [ BUILD / REGENERATE HARNESS ]              │
└─────────────────────────────────────────────┘
```

The palette begins as a searchable harness library. Selecting one harness replaces
the library in place with its editor; it must not open another palette or dialog.
Returning to the library is one action. Data refreshes preserve the selected
harness, expanded sections, active filters, and scroll position whenever those
items still exist. Native Fusion dialogs are reserved for operations that require
viewport selection, transactional document changes, or destructive confirmation.

---

# Interaction Philosophy

The UI should follow several core principles:

* **Engineering controls instead of spline controls**
  Users manipulate connections, gates, profiles, transition distances, and clearances rather than Bézier handles.

* **Wire identity is always visible**
  Every conductor has a persistent start-to-destination identity.

* **Geometry selection occurs in the Fusion viewport**
  The palette manages relationships and parameters while Fusion remains the primary geometric workspace.

* **Preview before generation**
  The user should be able to understand the complete route before final B-Rep geometry is constructed.

* **Incremental complexity**
  Simple harnesses require very little configuration, while terminator guides and wire-specific overrides remain available when required.

* **Explicit ordering**
  Control-structure order is stored deliberately rather than inferred.

* **Safe regeneration**
  Manual modifications are identified and preserved unless explicitly replaced.

* **Selective rebuilding**
  Only affected wires should need regeneration after localized changes.

* **Recursive assembly structure**
  The exact same workflow can be executed within an existing harness to create child branches.

---

## Complete User Flow

The full workflow can be summarized as:

```text
Launch Harness Builder
        │
        ▼
Select Parent Assembly
        │
        ▼
Select Routing Mode
        │
        ▼
Select Start Connections
        │
        ▼
Select Destination Connections
        │
        ▼
Map Individual Wires
        │
        ▼
Assign Wire Profiles
        │
        ▼
Configure Start Terminator
        │
        ▼
Add and Order Control Structures
        │
        ▼
Configure Gate Parameters
        │
        ▼
Configure End Terminator
        │
        ▼
Generate Centerline Preview
        │
        ▼
Inspect Wire Mapping
        │
        ▼
Preview Wire Envelopes
        │
        ▼
Validate Clearance and Geometry
        │
        ▼
Build Harness
        │
        ▼
Measure Final Wire Lengths
        │
        ▼
Name Wire Components
        │
        ▼
Store Procedural Metadata
        │
        ▼
Editable Fusion Harness Assembly
```

The primary objective of the workflow is:

> **Allow a designer to construct a complete, geometrically accurate wire or ribbon harness by defining physical connections and engineering routing constraints, while the add-in maintains conductor identity, generates the required paths, previews the resulting geometry, validates the design, and produces a fully editable Fusion 360 assembly.**

# Viewport Wire Correspondence Mode

The Harness Builder should include a dedicated **Wire Correspondence Mode** for visually verifying conductor identity throughout the complete routed assembly. When enabled, the Fusion 360 viewport temporarily displays wire-number labels at each important routing station, including the starting connection, terminator guides, routing-gate or profile-gate crossings, and final destination. The purpose of this mode is to make conductor correspondence immediately visible during complex routing, ribbon deformation, fan-out, gate packing, and connector remapping, ensuring that each wire maintains its unique start-to-destination identity throughout the procedural model.

## Core Concept

Each wire has a persistent numerical identity:

```text id="xqf8w1"
001
002
003
004
005
006
```

Wire Correspondence Mode overlays those identifiers directly onto the generated route.

For example:

```text id="v3d1jt"
START              GATE 01             GATE 02              END

001 o---------------o 001---------------o 001---------------o 001
002 o---------------o 002---------------o 002---------------o 002
003 o---------------o 003---------------o 003---------------o 003
004 o---------------o 004---------------o 004---------------o 004
```

The labels are temporary viewport graphics and should not become permanent modeling geometry.

---

## Complex Mapping Verification

The mode becomes especially useful when connection order changes.

```text id="bo4t77"
START                                                  END

001 o ----------------------------------------------- o 004
002 o ----------------------------------------------- o 001
003 o ----------------------------------------------- o 006
004 o ----------------------------------------------- o 003
005 o ----------------------------------------------- o 002
006 o ----------------------------------------------- o 005
```

The actual conductor identity remains tied to the wire itself rather than to its physical position within a connector, gate, ribbon, or bundle.

Wire Correspondence Mode should therefore display:

```text id="zpcvbe"
Wire identity:       001
Start connection:    J1 / Pin 01
End connection:      J2 / Pin 04
```

rather than renumbering conductors based on their current ordering.

---

# Gate Crossing Labels

At routing gates, each crossing location can be labeled with the wire number.

Front view:

```text id="kr7x19"
        ROUTING GATE 02

+----------------------------------+
|                                  |
|     001           002            |
|      o             o             |
|                                  |
| 003       004          005       |
|  o         o            o        |
|                                  |
|            006                   |
|             o                    |
|                                  |
+----------------------------------+
```

This allows the designer to verify packing and conductor ordering directly at the passage.

---

# Profile Gate Correspondence

For profile-gate ribbon routing, conductor numbers should be displayed along the sampled profile.

Flat profile:

```text id="thjjpq"
001     002     003     004     005     006
 o-------o-------o-------o-------o-------o
```

Curved profile:

```text id="nq465e"
             003     004
              o-------o
          002           005
           o             o
       001                 006
        o                   o
```

The displayed sequence makes it possible to immediately detect an unintended reversal, crossing, or incorrect correspondence between successive profile gates.

---

# Ribbon Twist Verification

A twisted ribbon can be difficult to inspect visually without explicit conductor labels.

```text id="0fmv66"
PROFILE GATE 01          PROFILE GATE 02          PROFILE GATE 03

001                       006                      006
002                       005                      005
003          --->         004         --->         004
004                       003                      003
005                       002                      002
006                       001                      001
```

If the transformation is intentional, the user can verify it.

If not, the correspondence display makes the error immediately obvious.

---

# Terminator Correspondence

Labels should also be available throughout terminator sections.

```text id="qrxx4z"
Connector                                      First Gate

001 o-----------------------------\------------o 001
002 o------------------------\-----\-----------o 002
003 o-----------o-------------\-----\----------o 003
004 o--------------------------\---------------o 004
```

This is particularly useful for:

* Connector fan-out
* Frayed ribbons
* Staggered terminals
* Random terminal layouts
* Per-wire guide profiles
* Dense branch transitions

---

# Selective Display

The correspondence overlay should support multiple display scopes.

```text id="i0aoxg"
WIRE CORRESPONDENCE

☑ Connection Points
☑ Terminator Guides
☑ Control Structures
☑ Final Destinations

Label Scope:

○ All Wires
● Selected Wires
○ Current Gate Only
```

For large harnesses, displaying every wire number at every gate may become visually overwhelming.

Selective display therefore becomes important.

---

# Highlight Selected Wire

Selecting a wire in the connection table should emphasize that conductor throughout the viewport.

Example:

```text id="p1pa9v"
Selected: WIRE 017

START        GATE 01        GATE 02        GATE 03        END

017 o----------o--------------o--------------o-------------o 017
```

Other wires may remain visible but visually de-emphasized.

The corresponding table row should remain selected at the same time.

---

# Highlight Selected Gate

Selecting a gate should display the conductor identities at that station.

```text id="r3gqe2"
ROUTING GATE 04

003      009      011
 o        o        o

001      017      021
 o        o        o
```

This provides a quick inspection method for local packing and ordering.

---

# Hover and Selection Information

Hovering over a wire label or centerline should expose basic conductor data.

Example:

```text id="vddjlb"
WIRE 017

Start:      J1 / Pin 14
End:        J4 / Pin 03
Diameter:   1.20 mm
Length:     842.6 mm
Status:     Valid
```

Selecting the label should select the corresponding wire component and row in the Harness Builder table.

---

# Crossing Detection

Wire Correspondence Mode can also help visualize topology changes.

If two conductors exchange position:

```text id="9dhlk8"
Gate 01                  Gate 02

001 o-----------------\ /----------------o 002
                      X
002 o-----------------/ \----------------o 001
```

the system should distinguish between:

* An intentional positional swap
* A legal ribbon twist
* An unintended spline crossing
* A physical sweep collision

The wire numbers make the topology visually understandable even before full collision geometry is shown.

---

# Persistent Identity Through Reordering

Wire position inside a gate should never determine wire number.

For example:

```text id="3m92pb"
Gate 01:

001   002   003   004


Gate 02:

003   001   004   002
```

The conductors retain their original identities:

```text id="uf90vh"
001 remains 001
002 remains 002
003 remains 003
004 remains 004
```

regardless of the arrangement at any subsequent gate.

---

# Correspondence Warnings

The system should automatically flag suspicious routing conditions.

Example:

```text id="nn753s"
⚠ WIRE CORRESPONDENCE WARNING

Wire 014 and Wire 015 exchange positions
between Profile Gate 03 and Profile Gate 04.

Swept envelopes intersect.
```

Other warnings may include:

* Unexpected conductor reversal
* Duplicate gate assignment
* Missing conductor at a gate
* Multiple wires assigned to the same crossing
* Illegal profile ordering
* Unintentional crossing
* Broken endpoint correspondence

---

# Suggested Palette Control

Wire Correspondence Mode can be exposed as part of the Preview section.

```text id="6e2b6n"
PREVIEW

☑ Centerlines
☐ Wire Envelopes
☐ Clearance Envelopes
☑ Wire Correspondence

Correspondence Scope:
[ Selected Wires ▼ ]

Labels:
☑ Start Connections
☑ Terminator Guides
☑ Gates
☑ Destinations
```

A toolbar toggle could also provide quick access:

```text id="0eyq2d"
[ # Show Wire IDs ]
```

---

# Example Complex Harness

Without correspondence labels:

```text id="9hdfch"
Connector            Ribbon                Breakout

o o o o  \==========/========\       o
           \========/         \===== o
o o o o ----\====================== o
```

With correspondence mode enabled:

```text id="pkkxc9"
Connector              Profile Gate            Breakout

001 o ------------------- o 001 -------------------- o 001
002 o ------------------- o 002 -------------\------ o 002
003 o ------------------- o 003 ----------\---\----- o 003
004 o ------------------- o 004 -----------\--------- o 004
```

The user can therefore inspect the entire conductor topology without having to isolate individual bodies manually.

---

# Integration With Validation

Correspondence visualization should share the same internal wire-ID system used for procedural validation.

```text id="zdy9rf"
Wire UUID
    │
    ├── Display Number
    ├── Start Connection
    ├── Gate Crossings
    ├── Terminator Guides
    ├── Destination
    └── Generated Component
```

This ensures that:

* viewport labels
* table rows
* generated geometry
* validation errors
* regeneration operations

all refer to the exact same conductor.

---

# Design Characteristics

* **Persistent identity**
  Wire numbers remain associated with the same conductor from start to destination.

* **Viewport-native inspection**
  Conductor identities are visible directly alongside the modeled geometry.

* **Non-destructive**
  Labels exist only as temporary visualization aids.

* **Gate-aware**
  Wire identity can be shown at every routing or profile gate.

* **Terminator-aware**
  Per-wire guide profiles can also display conductor correspondence.

* **Ribbon-aware**
  Conductor ordering remains visible through curling, banking, twisting, and folding operations.

* **Mapping-aware**
  Complex connector pin remapping can be inspected before final generation.

* **Collision-aware**
  Wire correspondence can be combined with physical envelope and crossing validation.

* **Scalable**
  Labels may be limited to selected wires, selected gates, or selected regions for large harnesses.

* **Bidirectional selection**
  Selecting a wire in the viewport selects it in the UI, and selecting a wire in the UI highlights it in the viewport.

---

## Updated Preview Workflow

The preview stage of the Harness Builder should therefore support four related visualization layers:

```text id="nqiuak"
PREVIEW LAYERS

1. Centerline Geometry
        │
        ▼
2. Wire Correspondence
        │
        ▼
3. Wire/Sweep Envelopes
        │
        ▼
4. Clearance and Collision Results
```

These layers may be enabled independently.

A typical workflow would be:

```text id="08focm"
Generate Centerlines
        │
        ▼
Enable Wire Correspondence
        │
        ▼
Verify Start-to-End Mapping
        │
        ▼
Inspect Gate Ordering
        │
        ▼
Enable Wire Envelopes
        │
        ▼
Check Physical Clearance
        │
        ▼
Build Harness
```

The intent of Wire Correspondence Mode is therefore:

> **Provide an immediate visual audit of conductor identity throughout the complete procedural routing system so that every wire can be verified from its physical starting connection, through all terminators and control structures, to its intended destination before final harness geometry is created.**
