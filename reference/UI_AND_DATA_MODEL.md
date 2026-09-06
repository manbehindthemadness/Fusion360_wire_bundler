# Fusion 360 Harness Assembly and Add-In Workflow

The Fusion 360 add-in should create each harness as a **self-contained child assembly** within the currently active design hierarchy. Every completed wire should exist as its own child component and contain one finished wire body together with its editable routing path, sweep or loft features, connection profiles, guide geometry, and associated metadata. This structure preserves each wire as a complete, independently editable object while allowing the harness itself to be nested inside any existing Fusion assembly. Because harness assemblies may themselves contain additional child harnesses, the same workflow can be re-run inside an existing harness to construct branching Y-, H-, or other multi-leg connection structures. The add-in UI should expose the engineering relationships that define the harness — connection mapping, wire profiles, terminators, routing gates, profile gates, ordering, dimensions, and clearances — while procedurally generating the underlying Fusion geometry and maintaining an interactive preview before final creation.

## End terminology

User-facing workflows treat both sides of a conductor symmetrically as **End A** and
**End B**. Do not label them source and destination: either side may be selected
first, extended, branched, or used to traverse a route in reverse. Legacy
`start_connection_id` and `end_connection_id` fields remain internal persistence
details until a deliberate schema migration replaces them.

## Assembly Hierarchy

A generated harness should be created as a child of the currently selected parent assembly or component.

```text
Main Assembly
│
├── Mechanical Structure
├── Electronics
│
├── Harness_001
│   │
│   ├── 001_842.6mm
│   │   ├── Wire Body
│   │   ├── Routing Path
│   │   ├── Start Profile
│   │   ├── End Profile
│   │   └── Generated Features
│   │
│   ├── 002_917.3mm
│   │   └── ...
│   │
│   ├── 003_901.8mm
│   │   └── ...
│   │
│   └── Control Geometry
│       ├── Routing Gate 01
│       ├── Routing Gate 02
│       ├── Profile Gate 01
│       └── ...
│
└── Other Components
```

Each completed wire is therefore a complete modeling object rather than merely one body inside a large anonymous harness component.

## Nested Harness Assemblies

A harness may itself become the parent of another generated harness.

This allows branching structures to be created procedurally without requiring a special branch-specific assembly system.

```text
Harness_001
│
├── 001_1250.4mm
├── 002_1304.2mm
│
├── Branch_A
│   ├── 001_322.8mm
│   ├── 002_347.1mm
│   └── 003_341.7mm
│
└── Branch_B
    ├── 001_418.6mm
    └── 002_425.2mm
```

This hierarchy supports:

* Y-connections
* H-connections
* Multi-stage breakouts
* Sub-harnesses
* Local connector branches
* Nested ribbon or wire groups

The same harness-generation command can therefore be used recursively at any level of the Fusion assembly tree.

---

## Wire Component Structure

Each wire should be represented as an individual Fusion component.

```text
001_842.6mm
│
├── START_PROFILE
├── START_TERMINATOR
│   ├── Guide 01
│   └── Guide 02
│
├── ROUTING_PATH
│
├── END_TERMINATOR
│   └── Guide 01
│
├── SWEEP_OR_LOFT
│
└── WIRE_BODY
```

The component should retain sufficient parametric geometry to allow the wire to be edited manually after generation.

The procedural system should therefore preserve:

* Start profile
* End profile
* Connection references
* Terminator guide profiles
* Main spline path
* Sweep or loft feature
* Finished body
* Wire metadata
* Routing metadata

The finished body should not be the only surviving result of procedural generation.

---

## Wire Naming

Each wire should receive a numerical wire identifier followed by its finished modeled length in millimeters.

Example:

```text
001_842.6mm
002_917.3mm
003_901.8mm
004_1042.1mm
```

The displayed name should be updated when the modeled wire length changes.

The numerical identifier should remain stable.

Internally, the system should also maintain a persistent unique identifier independent of the display name.

Example metadata:

```text
wire_id      = 5a8f0c...
wire_number  = 001
length_mm    = 842.6
harness_id   = a7132e...
```

This prevents geometry changes or renaming from breaking wire identity.

## Connection Identity and Naming

Each wire's End A Ordering and End B Ordering editor begins with an optional
End A Name or End B Name text field and shows only that connection's ordered profile members.
These labels replace the generated connection designation in its end nodes and
occupancy description; clearing a label restores the generated designation.
Names are independent even when wires share a pathway. New pairs start unnamed.

Pathways support renaming plus optional Start Name and End Name fields above and
below the Gates · Traversal Order list. Route nodes can read
`End A: Data input → lower fuse box path from O2-sensor to CAN_BUS-ctrl → End B: Data output`.
Unnamed traversal ends fall back to A and B. The wire display follows stored order;
there is no reverse-direction control. Clearing a pathway name chooses
an available generated designation. Name collisions receive deterministic suffixes.

The wire header collapses/expands its details on click and emphasizes its existing preview centerline on hover. Its pen control temporarily replaces the header with an inline
name input (Enter or blur saves; Escape cancels), with no permanent Wire Name field.
The editable name replaces the default Wire #xxx display designation;
clearing it restores that designation. Internal wire numbers and UUIDs remain
unchanged. All optional names default to blank in older definitions and do not
affect geometry. Future automatic naming may use this metadata.

Endpoint sequence members display a stable shortened UUID, with the full identity
in the row tooltip. IDs follow members through reorder and replacement; legacy
definitions derive deterministic IDs until an edit saves them explicitly. The wire-profile node
opens a Wire Options popup, currently editing the finished circular diameter in
millimeters. Saving applies across that wire and copies any shared profile first,
so other wires retain their sizes. Invalid diameters are rejected; Cancel discards
the popup edit. Diameter changes refresh affected routing groups in an active preview.

End sequences provide per-member Add, Replace, and Remove controls. Dragging a row
onto another reorders it within the same end, with a visible drop indicator. Add
uses a per-row control. Reordering uses captured pointer movement and commits on
release at the blue insertion line; release outside the stack cancels. Add
and Replace open Fusion's native profile picker; Replace keeps the member's list
position. Removing the last member warns that the end sequence will be deleted.
The wire and its other end are preserved, validation reports the missing connection,
and an Add End A/B control restores the end. Hovering an end highlights all members;
hovering a numbered member highlights only that profile. Member order persists in
connection metadata. Both stacks run from terminal toward pathway: the centerline
follows all A members in order, pathway crossings, then B members in reverse.
Additional members guide the same wire rather than creating branches.

An active preview automatically refreshes after member, wire, gate, or diameter
edits. Only routing groups with changed inputs are recalculated, and only changed
centerlines are redrawn. Unaffected paths retain their graphics objects and colors.
All connection-member edits and reorderings invalidate affected routing inputs;
display labels do not trigger routing work.
Incomplete wires have no preview until repaired. A failed group loses its stale
paths and reports a warning while unrelated groups remain visible. Clear Preview
disables automatic refresh until Preview Routes is invoked again. This applies to
edits made through Harness Builder; arbitrary external sketch edits are not watched.

Palette mutations and Preview/Clear Preview execute through named, input-free
Fusion commands. Definition changes and associated preview graphics belong to
the same command transaction. Command completion, including Undo/Redo, reloads
the persisted definition and adopts the cache for graphics restored by Fusion.
History synchronization must not write document data or recreate graphics: a
new edit could invalidate Redo. Session preview snapshots are released on stop.

Deletion uses one concise confirmation describing the affected scope. Harness
deletion does not require a second dialog, checkbox, or typed name. The planned
cascade must be one undoable operation and preserve original sketch/shape
geometry. Full end/pathway/harness deletion cascades remain future implementation.

Every physical, derived-exit, junction, and termination connection must have a
stable internal UUID independent of its user-facing name. Names must be readable,
unique within their configured scope, and generated consistently from a
user-configurable naming convention. A convention may include connector or group
name, connection kind, sequence number, zero padding, and separators; changing a
display convention must not change connection identity or wire mapping.

The UI must show the same resolved connection name in selection prompts, exit
interfaces, wire mapping, validation findings, and generated metadata. Automatic
names remain editable, and collisions are resolved deterministically. The exact
default templates and configuration surface remain to be established rather than
being inferred from temporary development names.

---

## Persistent Wire Identity

A wire's actual identity should never depend solely on:

* Component name
* Body name
* Position in the browser tree
* Current length
* Gate position
* Sweep feature name

Instead, each conductor should be assigned an immutable internal ID.

```text
Wire 001
│
├── UUID
├── Start Connection ID
├── Destination Connection ID
├── Profile ID
├── Route Definition
└── Generated Geometry
```

The add-in can then reliably determine whether a generated wire is:

* unchanged
* regenerated
* modified manually
* missing
* duplicated
* disconnected from its original definition

---

# Harness Builder UI

The add-in should provide a persistent **Harness Builder** interface that manages the complete routing definition.

A conceptual layout:

```text
┌──────────────────────────────────────────────┐
│ HARNESS BUILDER                              │
├──────────────────────────────────────────────┤
│ Harness: Harness_001                         │
│ Parent: Electronics                          │
│ Routing Mode: Routing Gates ▼                │
├──────────────────────────────────────────────┤
│ CONNECTIONS                                  │
│                                              │
│ Wire   Start       End        Profile        │
│ 001    J1-01       J2-04       Ø1.20         │
│ 002    J1-02       J2-05       Ø1.20         │
│ 003    J1-03       J2-06       Ø1.00         │
│                                              │
│ [Add] [Auto Pair] [Remove] [Edit Mapping]   │
├──────────────────────────────────────────────┤
│ CONTROL STRUCTURES                           │
│                                              │
│ 01   Routing Gate      ✓                     │
│ 02   Routing Gate      ✓                     │
│ 03   Routing Gate      ✓                     │
│                                              │
│ [Add Gate] [Reorder] [Remove]               │
├──────────────────────────────────────────────┤
│ TERMINATORS                                  │
│ Start Guides    [Edit]                       │
│ End Guides      [Edit]                       │
├──────────────────────────────────────────────┤
│ STATUS                                       │
│ ✓ 3 valid wires                              │
│ ✓ Endpoints unique                           │
│ ✓ Routing valid                              │
│ ✓ Preview valid                              │
├──────────────────────────────────────────────┤
│ [PREVIEW]                     [BUILD HARNESS] │
└──────────────────────────────────────────────┘
```

The interface should expose engineering concepts rather than spline control mathematics.

---

## Primary UI Responsibilities

The Harness Builder should allow the user to define:

* Harness parent assembly
* Harness name
* Wire count
* Start connections
* Destination connections
* Wire profiles
* Wire dimensions
* Routing mode
* Routing gates
* Profile gates
* Gate ordering
* Gate parameters
* Terminator guide profiles
* Wire-specific overrides
* Clearance requirements
* Sweep or loft settings
* Preview behavior
* Final generation

---

# Wire Connection Table

The central data structure of the UI should be a **wire connection table**.

Every row represents one complete conductor from its physical starting connection to its final destination.

```text
┌──────┬────────────┬────────────┬──────────┬──────────┐
│ Wire │ Start      │ End        │ Profile  │ Status   │
├──────┼────────────┼────────────┼──────────┼──────────┤
│ 001  │ J1 / Pin 1 │ J3 / Pin 4 │ Ø1.20    │ ✓ Valid  │
│ 002  │ J1 / Pin 2 │ J3 / Pin 5 │ Ø1.20    │ ✓ Valid  │
│ 003  │ J1 / Pin 3 │ J4 / Pin 1 │ Ø1.00    │ ✓ Valid  │
│ 004  │ J2 / Pin 7 │ J4 / Pin 2 │ Ø1.50    │ ⚠ Route  │
└──────┴────────────┴────────────┴──────────┴──────────┘
```

This row becomes the authoritative definition of that wire.

Internally:

```text
Wire 003
│
├── Start Connection
├── Start Profile
├── Start Terminator Guides[]
├── Ordered Control Structures[]
├── End Terminator Guides[]
├── End Profile
└── Destination Connection
```

---

## Connection Mapping

The system should support multiple methods of assigning start and destination connections.

### Individual Pairing

The user explicitly selects:

```text
Start Profile → Destination Profile
```

for each wire.

### Array Pairing

Two ordered groups may be paired automatically.

```text
START                   DESTINATION

1  o ---------------------- o  1
2  o ---------------------- o  2
3  o ---------------------- o  3
4  o ---------------------- o  4
```

### Manual Mapping

Nonlinear connector pin relationships can be assigned explicitly.

```text
START                   DESTINATION

1  o ---------------------- o  4
2  o ---------------------- o  1
3  o ---------------------- o  3
4  o ---------------------- o  2
```

The mapping should always be visible before the harness is generated.

The add-in should never silently infer a final conductor correspondence when the mapping is ambiguous.

---

# Routing Sequence

Control structures should be stored as an explicit ordered sequence.

For routing-gate mode:

```text
START
  │
  ▼
[ Routing Gate 01 ]
  │
  ▼
[ Routing Gate 02 ]
  │
  ▼
[ Routing Gate 03 ]
  │
  ▼
END
```

For profile-gate mode:

```text
START
  │
  ▼
[ Profile Gate 01 ]
  │
  ▼
[ Profile Gate 02 ]
  │
  ▼
[ Profile Gate 03 ]
  │
  ▼
END
```

The order should be editable directly in the UI.

```text
☰ Routing Gate 01
☰ Routing Gate 02
☰ Routing Gate 03
```

Route order should be treated as explicit semantic information rather than inferred from spatial proximity.

---

# Terminator Editing

The start and end terminators should be represented as expandable control groups.

```text
START TERMINATOR
│
├── Wire 001
│   ├── Connection Profile
│   ├── Guide Profile 01
│   └── Guide Profile 02
│
├── Wire 002
│   └── Connection Profile
│
└── Wire 003
    ├── Connection Profile
    └── Guide Profile 01
```

Most wires may require no additional guide profiles, so these controls can remain collapsed by default.

A wire that requires special termination geometry can be edited independently.

---

# Routing Gate Editor

Selecting a routing gate should expose the parameters associated with that structure.

```text
ROUTING GATE 02

Geometry              [Selected ✓]

Side A Transition       35.0 mm
Side B Transition       50.0 mm

Wire Clearance           1.0 mm

Affected Wires
☑ 001
☑ 002
☑ 003
☑ 004
```

The gate editor may also expose:

* Aperture geometry
* Packing method
* Minimum spacing
* Transition clamping
* Gate orientation
* Allowed wires
* Excluded wires
* Local routing overrides

---

# Profile Gate Editor

Selecting a profile gate should expose ribbon-specific parameters.

```text
PROFILE GATE 03

Profile Geometry       [Selected ✓]

Sampling               Arc Length
Centering               Automatic
Wire Spacing            1.50 mm

Affected Wires
001–012
```

Additional parameters may include:

* Profile orientation
* Profile interpolation tension
* Profile centering
* Implied extension behavior
* Fold behavior
* Continuity mode
* Wire ordering
* Local spacing

---

# Preview System

The add-in should provide a continuous procedural preview before final geometry is committed.

Two preview levels are recommended.

## Centerline Preview

The default preview should display spline centerlines only.

```text
Wire 001  -------------------------------
Wire 002  -------------------------------
Wire 003  -------------------------------
```

This mode should update quickly while:

* gates are moved
* gates are rotated
* transition distances are changed
* profile shapes are modified
* terminator guides are edited

## Sweep-Envelope Preview

An optional preview mode should display approximate wire diameters or ribbon envelopes.

```text
☑ Show Wire Diameter
☑ Show Clearance Envelope
☑ Show Collision Indicators
```

This mode may update more slowly but provides better validation of physical interference.

## Preview Performance and Level of Detail

Preview must scale to complex harnesses with at least hundreds of connections
without continuously creating finished Fusion features or bodies. Use the
lightest representation that answers the current question:

```text
Level 0   Connection, gate, junction, and exit-interface markers
Level 1   Lightweight centerlines and wire-identity correspondence
Level 2   Diameter and clearance envelopes for selected or affected wires
Commit    One finished Fusion body per wire
```

Interactive edits should update only dirty pathway spans and affected wires,
reuse unchanged packing and route results, coalesce rapid manipulator changes,
and defer precise recalculation until interaction settles. Large-harness views
may show selected, failing, or locally affected wires while retaining full
mapping and validation status in the palette. Collision checks should reject
distant wire pairs through a spatial broad phase before performing detailed
curve-separation work.

Preview centerlines and envelopes are disposable visualization data, not
temporary finished sweeps. Final body generation occurs only on explicit build or
regeneration, reports progress, and must avoid leaving a partially generated
harness after cancellation or failure. Concrete performance thresholds require
measurement in Fusion and must not be invented before representative 100-plus
connection experiments exist.

When a reachable route preview exists at save time, the add-in temporarily disables
Fusion's document graphics cache for that save and restores the user's preference
afterward. This prevents transient Custom Graphics from becoming an OGS scene-cache
artifact that remains visible after reload without a corresponding API object.

---

# Preview Status

The viewport and UI should provide immediate route feedback.

Conceptually:

```text
Valid wire          ✓
Collision           ✗
Missing route       !
Unresolved mapping  ?
Clamped transition  C
```

The user should be able to click an error or warning and have the relevant wire or gate highlighted in the Fusion viewport.

---

# Validation Before Generation

The **Build Harness** action should require every wire to have a complete valid route.

Each conductor should contain:

```text
Start Profile
      ↓
Start Terminator
      ↓
First Control Structure
      ↓
Intermediate Control Structures
      ↓
Last Control Structure
      ↓
End Terminator
      ↓
Destination Profile
```

Example validation display:

```text
Wire 006

Start Connection     ✓
End Connection       ✓
Wire Profile         ✓
Gate 01              ✓
Gate 02              ✗ No legal passage
Gate 03              ✓
Clearance            ✗ Intersects Wire 008
```

Validation should detect:

* Missing start connections
* Missing destination connections
* Duplicate endpoints
* Duplicate wire IDs
* Invalid profiles
* Missing gate geometry
* Impossible routing
* Wire-to-wire intersection
* Wire-to-structure intersection
* Invalid profile-gate sampling
* Excessive curvature
* Terminator failures
* Unresolved gate order
* Invalid sweep or loft construction

---

# Generated Wire Geometry

Each completed conductor should preserve its editable construction geometry.

```text
001_842.6mm
│
├── Route_Data
│   ├── Start_Profile
│   ├── Start_Guides
│   ├── Main_Path
│   ├── End_Guides
│   └── End_Profile
│
├── Sweep_or_Loft
│
└── Wire_Body
```

The path should remain available after generation so the user may manually adjust a particular wire if required.

The procedural system should therefore generate **editable Fusion features**, not merely final static solids.

---

# Procedural Metadata

Each generated object should carry enough metadata to reconnect it to the harness definition.

Example:

```text
generated_by     = HarnessBuilder
harness_id       = <UUID>
wire_id          = <UUID>
wire_number      = 001
routing_mode     = routing_gate
generation_state = procedural
```

Control structures may similarly contain:

```text
gate_id          = <UUID>
gate_type        = routing_gate
gate_order       = 02
harness_id       = <UUID>
```

This allows the add-in to reopen an existing harness and reconstruct the editing state reliably.

---

# Harness Definition Versus Generated Geometry

The add-in should maintain a logical harness definition separately from the resulting Fusion geometry.

```text
Harness Definition
│
├── Wire Identities
├── Connection Mapping
├── Wire Profiles
├── Terminator Definitions
├── Gate Definitions
├── Gate Ordering
├── Routing Parameters
└── Parent/Child Relationships
        │
        ▼
Generated Fusion Geometry
```

The Fusion geometry represents the current physical realization of the harness definition.

The software should not depend on reverse-engineering the user's intent from geometry alone.

This distinction becomes especially important when supporting:

* Nested harnesses
* Y-branches
* H-branches
* Ribbon breakouts
* Manually edited wires
* Multiple wire diameters
* Shared gates
* Reordered wires
* Regeneration
* Version changes

---

# Manual Editing

A generated wire should be capable of transitioning from fully procedural control to manual Fusion editing.

Conceptually:

```text
Procedurally Managed
        │
        ▼
Manual Path Modification
        │
        ▼
User-Controlled Wire
```

The add-in should record this condition rather than silently overwriting the wire during a later regeneration.

Possible states:

```text
PROCEDURAL
MODIFIED
LOCKED
DETACHED
INVALID
```

A future regeneration operation could then ask the user whether to:

* preserve the manual wire
* regenerate it
* duplicate it
* detach it from the harness definition

---

# Pathway Junction Wire Disposition

A Y junction attaches a branch pathway to a movable slice plane on its parent
pathway. Each parent wire must have an explicit disposition at that junction:

```text
EXCLUDE_BRANCH    Present on Pathway A after the slice; absent from Pathway B
BRANCH            Continues on Pathway A and creates a branch leg on Pathway B
REDIRECT_BRANCH   Present on Pathway A only up to the slice, then on Pathway B
```

The UI may present `EXCLUDE_BRANCH` as a per-wire exclusion and
`REDIRECT_BRANCH` as a Redirect option. Persist the disposition against the
stable incoming wire UUID rather than relying on list position or a changing
default.

A redirected wire is removed from every downstream routing-gate packing and
generated span on Pathway A. Its route consists of the parent-pathway prefix, a
generated junction transition, Pathway B, and the branch exit termination. This
supports controlled partial exits such as individual ground straps. Moving the
slice plane regenerates the transition while preserving wire identity.

`BRANCH` represents a true Y connection: the parent route continues after the
slice and an additional branch leg enters Pathway B. The branch leg must receive
its own stable physical-wire identity and an explicit electrical relationship to
the incoming wire; one wire UUID must never silently identify two generated
bodies. The detailed splice and electrical-net representation remains a separate
data-model decision within Y-junction implementation.

Gate-capacity and wire-to-wire collision validation must use the resulting
per-span membership: all incoming wires before the slice; excluded and branched
parent wires after the slice on Pathway A; and redirected wires plus new branch
legs on Pathway B.

---

# Pathway Extensions and Open Exits

An extension attaches Pathway B directly to Pathway A's exit interface. Unlike a
Y junction, it has no mid-path slice, split, or duplicated branch leg. Every wire
that has not been terminated at Pathway A's exit continues through Pathway B with
the same stable wire identity.

```text
Pathway A → Exit A → Pathway B → Exit B → optional further extension
                         │
                         └── locally terminated wires leave the route here
```

At each exit interface, every arriving wire has an explicit lifecycle state:

```text
OPEN          Available for termination or extension
TERMINATED    Connected locally and absent from later pathway segments
EXTENDED      Continues through the attached extension pathway
```

Creating an extension initially assigns all `OPEN` wires to the new pathway.
Users may terminate selected wires at the current exit; only the remaining wires
continue. The new pathway derives its entry positions, orientations, profiles,
and conductor identities from the previous exit interface rather than requiring
the source connections to be selected again. Its generated exit interface can be
terminated normally or extended again.

A wire route is therefore an ordered chain of pathway legs, with capacity and
wire-to-wire collision validation calculated from the membership of each leg.
An extension pathway is an ordinary pathway leg and may host one or more movable
Y junctions under the same rules as the initial pathway. Junction dispositions
change membership for the remainder of that leg and for every branch or extension
downstream. The resulting route topology is a directed graph rather than a single
linear chain. Initial implementation should reject cycles so a route cannot
eventually feed back into an earlier pathway.

---

# Recommended Add-In Workflow

A typical creation workflow should be:

1. Select the parent Fusion component.
2. Create a new harness assembly.
3. Define or select start connections.
4. Define or select destination connections.
5. Establish wire-to-wire connection mapping.
6. Assign wire profiles and dimensions.
7. Select routing mode.
8. Add and order routing gates or profile gates.
9. Configure gate parameters.
10. Configure start terminators.
11. Configure end terminators.
12. Generate centerline preview.
13. Validate route topology.
14. Preview sweep or loft envelopes.
15. Resolve collisions or routing failures.
16. Build the final harness.
17. Calculate final wire lengths.
18. Rename wire components with numerical identifier and length.
19. Store harness metadata.
20. Preserve all wire paths and construction features for later editing.

---

# Wire Materials

Every harness owns complete wire-material defaults. Every persistent wire owns
nullable, field-level overrides. A null wire field inherits the corresponding
harness field, while an explicit value takes precedence. For ordered stripes,
null means inherit and an explicit empty list means no stripes.

The material definition includes insulation material, main insulation color,
zero or more ordered stripes, conductor material, manufacturer, part number,
and notes. Each stripe stores its color, width, starting angular position,
pattern, and optional repeat distance. Longitudinal, dashed, and helical
patterns are represented procedurally so previews, generated geometry, and
future diagrams consume the same source data.

Insulation and conductor inputs offer searchable bundled suggestions but permit
custom text. Their controlled autocomplete menus avoid host-native datalist layout
differences. The main insulation visual may use a named RGB color or an appearance
selected from any installed Fusion material library. Library and appearance IDs are
stored with their display names; a per-wire main-color override also owns whether
that wire uses its own library appearance or plain color. Palette edits use the
existing native Fusion transaction and document change tracking. The bundled catalog
is an add-in-relative resource that must be included when the finished add-in is packaged.

The current rendering slice applies resolved main colors to route previews and
generated wire bodies. A selected library appearance is copied into the active
document before it is assigned to a body, allowing its renderer properties and
textures to persist with that document. It renders longitudinal, dashed, and helical
stripe bands at the wire radius in route previews using a parallel-transported local frame.
Apply persists and renders without closing the material dialog; Save performs the
same operation and closes it. Both actions update active previews and recolor
existing generated bodies without rebuilding their geometry. If stripes exist and
no preview is active, either action creates the material preview. Stripe graphics are
two-sided model-space surface meshes whose width is measured in millimeters. A small
physical surface offset prevents depth conflict with the wire body while ordinary
depth testing hides the rear surface, so angle remains visible and the band scales
with model geometry during viewport zoom. The bands sample exact centerline cubics
at a tighter chord tolerance than the lightweight centerline graphic, and helical
bands use at least 32 angular steps per repeat to remain conformal through bends.
Their width is tessellated at no more than ten degrees per face so a broad band's
flat mesh faces remain outside the circular insulation surface instead of cutting
through it. Material-dialog grids and native selects are constrained to the dialog's
content width; only vertical overflow scrolls when the available palette height is
smaller than the complete form.
Diagram output and persistent
stripe face appearances on generated solids remain subsequent consumers. Those face
appearances can carry stripes into Fusion rendering without relying on transient graphics.
The conformal preview mesh may also serve as the front surface of optional render
geometry after adding an underside and end caps. Before implementing that path, verify
whether Fusion exposes a dependable pre-render event; otherwise expose render preparation
as an explicit command and keep the resulting bodies clearly application-owned.

---

# Deferred Presentation and Routing Research

The following ideas are explicitly deferred and must not expand the scope or
acceptance criteria of the core connection, pathway, wire-generation, and
validation milestones:

* **Pathway coverings**
  Investigate optional procedural sheath, harness tape, and heat-shrink geometry
  placed along a completed pathway at user-controlled intervals. This is a
  late-game aesthetic layer derived from generated bundle geometry, not part of
  the authoritative wire definition or a prerequisite for a valid harness.

* **Twisted bundles**
  Investigate low-priority support for conductors that rotate around a shared
  bundle axis. Any future design must account for pitch, phase, conductor length,
  bend behavior, and wire-to-wire clearance without changing conductor identity.

* **Wire tips**
  Investigate optional start and end tip bodies that extend outward from their
  connection profiles. Tip length is user-defined and stored canonically in
  millimeters while the UI may display the active Fusion document units. For a
  circular parent wire, tip diameter defaults to 60 percent of the parent-wire
  diameter and remains adjustable. Tip material defaults to copper and remains
  adjustable. Common tip defaults may be shared by both ends while permitting
  independent start and end overrides. Tip and insulation regions must be created
  as editable features and joined into one finished wire body. Region-specific
  material or appearance assignments must remain represented in metadata and on
  suitable faces without leaving multiple final wire bodies. Future design work
  must define endpoint direction, regeneration behavior, Fusion material-library
  versus per-face appearance support, and whether tip extensions contribute to
  reported conductor or cut length.

* **Fusion Electrical design integration**
  Investigate late-stage interoperability with Fusion Electrical designs. If the
  supported Fusion APIs expose stable markers for connectors, pins, nets, signal
  names, or other electrical intent, those markers may seed connection identity,
  propose wire-to-wire mappings, and drive an assisted auto-wiring workflow through
  the mechanical pathway graph. Electrical metadata must be treated as imported
  intent rather than generated geometry: mappings remain previewable, editable,
  validated, and explicitly accepted before harness creation. The integration must
  tolerate incomplete, duplicated, renamed, or unavailable markers and must not
  become a runtime requirement for manually defined harnesses. Exact API access,
  marker semantics, synchronization direction, and change-detection behavior remain
  research questions; do not infer them until verified against the then-current
  Fusion Electrical API and representative designs.

Generated coverings, tips, and twist settings should remain
optional, regenerable, and separable from the underlying connection mapping and
pathway definition.

---

# Design Characteristics

* **Assembly-native**
  Each harness is generated as a Fusion child assembly.

* **Wire-native**
  Each complete conductor exists as its own child component.

* **Editable**
  Generated paths, profiles, sweeps, and lofts remain available after creation.

* **Nested**
  Harnesses may contain additional child harnesses.

* **Branch-capable**
  Y-, H-, and multi-leg structures can be produced through recursive harness creation.

* **Persistent identity**
  Every wire has an internal unique identifier independent of its display name.

* **Length-aware naming**
  Finished wire length is included in the wire component name.

* **Connection-driven**
  Every wire is explicitly mapped from one physical connection to another.

* **Order-aware**
  Routing and profile gate sequences are explicitly defined.

* **Terminator-aware**
  Per-wire guide profiles may be defined before the first and after the last control structure.

* **Preview-driven**
  The user can inspect generated centerlines before committing solid geometry.

* **Validation-driven**
  Invalid or ambiguous routes are identified before final creation.

* **Collision-aware**
  Wire and sweep intersections can be detected before generation.

* **Metadata-backed**
  Logical harness definitions are preserved independently from physical Fusion geometry.

* **Manual-edit compatible**
  Individual wires may be edited directly after creation without requiring the entire harness to be rebuilt.

---

## Overall Architecture

The complete system can be represented as:

```text
Fusion Parent Assembly
        │
        ▼
Harness Assembly
        │
        ├────────────── Harness Definition
        │                    │
        │                    ├── Connections
        │                    ├── Profiles
        │                    ├── Terminators
        │                    ├── Gates
        │                    ├── Parameters
        │                    └── Wire Mapping
        │
        ├── Wire 001
        │    ├── Path
        │    ├── Profiles
        │    ├── Sweep/Loft
        │    └── Body
        │
        ├── Wire 002
        │    └── ...
        │
        ├── Wire 003
        │    └── ...
        │
        └── Child Harnesses
             ├── Branch A
             └── Branch B
```

The overall design objective is therefore:

> **Provide a constraint-driven Fusion 360 harness-design environment in which users define physical connections, routing controls, and conductor properties while the add-in procedurally creates a fully editable, nested assembly of uniquely identified wire components.**

### Hover targeting

Wire Routes and its wire rows default to collapsed and retain saved expansion.
End-node ordering menus also retain their open/closed state across member edits,
palette refreshes, and palette reloads. Selecting the opposite end explicitly
switches the open ordering menu.
Each end-member row has + (insert after), replace, and × controls and supports
drag-and-drop reordering within its own stack. All edits refresh active preview
state, and every member center contributes to the smooth, ordered route.
Gate traversal rows use the same captured-pointer reordering and insertion marker.
Both stacks have a far-left position column numbered from one; position numbers
describe the current slots while stable names and IDs move with their members.
Gate drops insert across any number of rows, synchronize dependent wire-control
order, and refresh affected active previews.
Hovering a wire header or occupancy member emphasizes its existing preview. A
pathway node within a wire route highlights only its gates. A pathway heading in
Pathways & Occupancy highlights its gates and all occupying wire previews; its
Gates heading highlights all gates, and its Wire Occupancy heading highlights all
occupying previews. Individual gate and endpoint members highlight only their own
profiles. Mouse-out clears both sketch selection and preview emphasis. End nodes
highlight their connection profiles. Intersection slice highlighting remains a
future extension once intersection geometry exists.

### Smooth centerline milestone

Packing still determines the exact ordered crossings. A separate fairing stage
uses each gate/profile plane normal as the local tangent and joins crossings
with cubic transitions plus a straight middle span. Auto initially assigns one
quarter of each span to each transition, then expands to the diameter-derived bend
minimum or contracts toward that minimum when the span is crowded. Independent
explicit approach/departure lengths are preserved when feasible and clamped to the
nearest proportional fit. When two localized bend-safe transitions cannot share a
span, the fairer dynamically reduces that wire's effective transition to the full
available span and uses one direct profile-to-profile cubic if that curve preserves
the same sweep radius. The geometry-specific correction does not rewrite a shared
gate or end-member setting. Preview and solid generation report the required
distance, applied distance, and preserved radius as an informational event. Exact curves
are retained while Custom Graphics uses adaptive sampling at 0.05 mm chord error.
Normal signs follow the stored traversal; points are never sorted by proximity.
Coincident consecutive profiles and unavoidable collinear reversals are rejected.
Aperture packing is validated only at pathway routing gates. Diameter-aware
fairing and guarded local circular-wire bend radii apply across the complete
route, including every connection-owned end profile. Whole-span
collision/clearance, center drift, and ovalization remain pending.

Deferred UI work: follow Fusion’s light/dark theme and automatic host theme changes.

### Interpolation options and defaults

Each routing-gate row and each individual end-member row has an Options popup.
Gate labels also open options on click or keyboard activation; dragging still
reorders without opening a popup. End section headings retain ordering/name
controls, while interpolation belongs to the individual profiles in their stack.

Gate distances follow approach/departure traversal order. End-member distances
use terminal-side/pathway-side directions; the adapter swaps these for End B's
reversed traversal. The terminal profile (first member) only uses its pathway-side
value. Blank values mean Auto; explicit values are finite nonnegative millimeters.
Auto respects the bend-safe floor calculated for each wire and profile side.
Explicit values below that floor expand to it. Combined values beyond the span
contract proportionally without crossing either physical floor.

Defaults supplies separate gate and end-member baselines. The checked-by-default
“Update existing controls using defaults” option applies new baselines to current
previews while preserving individual overrides. Unchecking it only changes
creation presets. New gates and members start with defaults. Individual popups
show whether a control uses defaults or custom settings; “Use harness defaults”
restores inheritance when saved. Member overrides follow stable member IDs across
reorder and replacement; adding/removing members maintains aligned settings.

Optional schema-v3 metadata stores per-gate override flags and per-end-member
settings (null entries inherit the section baseline). Legacy section settings
remain a fallback for older definitions. Saves use one native Fusion transaction,
refresh affected active previews, and preserve editor expansion state. Original
sketch geometry is untouched.

### Initial persistent solid generation

Generate/Rebuild Solids is an explicit native Fusion command separate from
transient previews. It creates one child component per conductor with editable
cubic control-point splines and straight segments, a diameter-sized circular
profile normal to the path, and one solid sweep. UUID, number, diameter, and
measured centerline length are stored on the generated component. Component names
use the wire label, or its number and centerline length when no label is supplied.

This first slice rebuilds all wires after one confirmation that includes manual
edits inside generated components. Every replacement is built before any previous
marked component is deleted. Original sketches and unmarked components are not
modified. Native command rollback covers failures during final replacement.
Preview edits do not implicitly replace solid bodies; explicit rebuilding is
required. Selective regeneration and automatic manual-edit detection are later
work. Clear Solids deletes only marked generated wire components in a native
transaction, leaving original sketches and unrelated components untouched. Solid
geometry persists independently of preview visibility and add-in state. The upper
palette status area retains informational and failure events in a vertically
scrollable console using the same surface and text colors as the rest of the palette.
After successful solid generation, the short-lived command's destroy event clears
the transient route preview outside the completed modeling transaction. Failed
generation retains the preview for inspection. Palette hover targets emphasize
generated wire bodies by persistent wire identity in addition to their linked
profiles and any active preview centerlines; leaving the target clears all emphasis.
Clear Preview runs synchronously from the palette outside the model-edit command
transaction. It hides each preview, explicitly deletes nested wire graphics, deletes
the parent group, scans Custom Graphics collections on the root and every design
component, verifies each deletion, refreshes the viewport, and reports the number
of removed groups.
