# Fusion 360 Harness UI and Data Model

> **Document status:** Authoritative product data, identity, validation, persistence,
> and UI interaction contract. The current implementation and dependency-ordered
> roadmap are recorded in `../README.md`. Sections explicitly marked **Planned** define
> future requirements. Other sections may describe enduring target behavior across
> several milestones; no statement here by itself establishes implementation status.

The Fusion 360 add-in stores each harness as a versioned definition associated with a
dedicated child assembly in the active design hierarchy. Each generated top-level wire
owns its output component, editable route, sweep or loft features, presentation, and
generation metadata. Connection profiles, gates, and guides remain persistent linked
source references and do not need to be copied into every generated component. Future
enclosed composite children may remain logically complete without full-length bodies,
as specified in the planned recursive-composite section. The UI exposes connection
mapping, containment, terminators, control structures, ordering, dimensions, materials,
and validation while keeping transient preview separate from explicit generated output.

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

This provides organizational assembly nesting. Physical branching, recombination,
loops, and per-span membership use the explicit pathway topology planned in M2;
nested harness components do not substitute for those route relationships.

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
definitions derive deterministic IDs until an edit saves them explicitly. Each
wire has one clearly labeled Wire options button beneath its relationship graphic.
The shared dialog edits the finished circular diameter in millimeters together with
the wire's inherited or overridden material fields. Apply renders the current valid
diameter and material settings while keeping the dialog open. Save commits the current
settings and closes it; Cancel or Escape restores the values from when the dialog opened,
including any diameter, body appearance, and stripe changes rendered by Apply. Diameter
edits copy any shared profile first so other wires retain their sizes. Invalid diameters
are rejected; diameter changes refresh affected routing groups in an active preview.

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

The Wire Routes and Pathways & Occupancy presentations should not depend on a
strictly tree-shaped screen layout. Reserve a compact cross-link or loop indicator
so a future relationship model can display an intentional cycle without redesigning
both views. This is a presentation allowance only; it does not change the current
route schema, generation behavior, or initial cycle validation.

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
patterns are represented procedurally so generated presentation and future
diagrams consume the same source data.

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
textures to persist with that document. Route previews contain colored centerlines
without stripe geometry. Longitudinal, dashed, and helical stripe bands are owned by
the corresponding generated wire component and use its component-local exact route,
so occurrence transforms and solid deletion carry the pattern with the wire. Apply
renders without closing the material dialog; Save commits the current settings and
closes it. Cancel or Escape restores the opening settings after any number of Apply
operations. Apply and Save recolor existing generated bodies and refresh
their component-owned stripes without rebuilding the solid. Generated wires created
before component-local route metadata was introduced require one rebuild before a
stripe pattern can be applied. Stripe graphics are two-sided model-space surface
meshes whose width is measured in millimeters. A small
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
Diagram output and persistent stripe face appearances on generated solids remain
subsequent consumers. Those face
appearances can carry stripes into Fusion rendering without relying on transient graphics.
The conformal component-owned mesh may also serve as the front surface of optional render
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

### Master relationship graphic

The selected-harness editor presents a top-level Master Relationship Graphic as
the final section in its vertical stack, immediately below the Validation section.
It is not placed beside the event console and is not nested inside Wire Routes or
Pathways & Occupancy. Its expansion state follows the same retained section-state
behavior as the other top-level editor sections. The resizable floating palette
initially opens at 840 by 760 pixels, giving the standard graphic width room while
allowing users to resize or dock it afterward.

The initial graphic derives only relationships supported by the current model:
stable connections, physical wires, and their ordered pathway memberships. Each
wire's expanded Wire Routes entry contains its detailed SVG from its assigned End
A name, through the named ordered pathways, to its assigned End B name. It uses
the wire's resolved material color and stripe cues, and hover highlights that
wire's available preview/generated geometry. Pathway names sit inside wide opaque
rounded nodes so the colored route cannot obscure their text. This SVG is also the
wire's route-configuration surface; no duplicate route-node strip is shown. End A
and End B nodes toggle their existing ordering editors, or start native profile
selection when their connection is missing. Pathway nodes expand and navigate to
the matching Pathways & Occupancy configuration. The colored wire line and each
typed node retain their scoped Fusion highlighting. Mouse clicks plus Enter and
Space activate the nodes, while one labeled Wire options control remains beneath
the graphic. Stripe cues are centered as a group within the base trace: a single
stripe occupies its centerline and two or three stripes use symmetric offsets.

The master graphic aggregates the same data into one card per pathway. Its End A
and End B columns group wires by connection, show assigned endpoint and connection
names, and navigate to a participating wire when clicked. A search filters pathway,
connection, endpoint, wire, and material labels. Matching end lists open while a
search is active and show filtered and total counts. Each end list starts open when
its connection count is at or below a retained per-harness threshold and collapsed
when its count is above that threshold. The numeric setting is clamped from 1 to
999 and defaults to 7, allowing simple harnesses to appear in full without letting
large connector lists dominate the palette. A manual disclosure choice lasts for
the current palette session until the threshold changes. Hovering a pathway hub
highlights only its gates, while an end-list heading highlights the occupying wires
and a connection entry highlights that connection. Activating a pathway hub expands
and scrolls to its matching Pathways & Occupancy configuration. The viewport uses a
darker neutral backdrop to distinguish its light pathway cards and end-list buckets,
and scrolls so large relationship sets do not compress their labels. The pathway hub
is vertically centered against the full height of both end columns. Smooth SVG
curves join each visible connection to that hub. Expanding an end fans one trace
per participating wire, using the wire's resolved base color and up to three solid
or dashed stripe cues centered within the base trace; wires sharing one connection
remain parallel at that entry. Collapsing the end replaces the hidden material
traces with one neutral aggregate curve. Open end columns distribute their entries
across the available card height so unequal End A and End B counts remain visually
aligned with the centered hub.

The palette is delivered as a small `palette.html` entry shell plus local packaged
resources under `palette/`: `styles.css`, `foundation.js`, `route-editors.js`,
`materials.js`, `relationship-audit.js`, `wire-graphic.js`, `master-graphic.js`,
`editor.js`, and `host.js`. Scripts load in that explicit order so shared state and
utilities exist before the final host bridge initializes. Fusion palette creation
validates the complete resource set before opening.

The application builds stable typed nodes, ordered segments, wire routes,
pathway-occupancy indexes, and connection-usage indexes without Fusion API
dependencies. A separate audit reconstructs all five projections from the harness
definition and reports mismatches in Validation. The palette repeats route,
occupancy, and connection-use checks at the display boundary so a stale or
malformed payload is visible rather than silently diagrammed. Missing references
remain explicit typed nodes for diagnosis. The graphic does not infer Y-junction,
ribbon, shielding, or extended-branch behavior before those concepts have defined
domain semantics; later milestones can add node and edge kinds without replacing
existing identities.

### Planned recursive composite-wire and shielding milestone

Recursive multi-conductor cables and shields are a planned domain extension rather
than an inferred diagram feature. This milestone does not change the current
round-wire schema or generation behavior.

A complex wire is a rooted containment hierarchy. Every member has a stable UUID,
an explicit parent, an ordered child list, and a physical outer envelope. A member
may be a current single conductor, a shield surrounding other members, or a composite
group containing any number of conductors, shields, and further composite members.
The schema must not impose a fixed nesting depth or assume a pair, coaxial cable, or
one-level construction.

Containment and electrical connectivity are independent. Nesting records which
physical envelope surrounds a member; it does not imply that a shield is electrically
connected to a child or that children share a net. Shield terminations, bonds,
grounds, drain-wire relationships, intermediate connections, and loops belong to the
any-to-any connection graph.

Every conductor stores its own technical record, including material, size,
manufacturer, part number, notes, and future electrical ratings. Each conductor or
composite child may have optional insulation using the existing material, appearance,
color, stripe, manufacturer, part-number, and notes concepts. The schema represents a
bare conductor explicitly. Each optional shield also has stable identity and its own
construction, material, dimensions, coverage, manufacturer, part number, and notes;
the exact braid, foil, served-shield, and drain-wire fields remain a design decision.

Fit is checked recursively at every parent before preview or generation. Validation
uses each child's complete outer envelope, including insulation, shield thickness,
clearance, and the applicable packing rule, and verifies that the children fit inside
their immediate parent's usable region without overlap. It identifies the failing
hierarchy level, required and available envelopes, and controlling clearance or
thickness. Circular children may reuse deterministic packing, while non-circular
members require shape-aware containment. A valid root does not excuse an invalid
nested child, and routing gates validate the complete outer envelope of the members
that traverse each span.

Nested members are logically continuous through their parent without requiring
full-length Fusion bodies. By default, an enclosed child inherits its parent's route
and is represented by identity, connectivity, cross-sectional placement, and
technical metadata. Child geometry is realized only at entries, exits, terminations,
breakouts, recombination regions, exposed sections, child-guided spans, and spans the
user explicitly selects for internal detail. Optional cutaway, exploded, inspection,
or manufacturing modes may realize selected children or their complete lengths.
Validation and diagrams remain complete when no corresponding child body exists.
Length reporting must distinguish inherited parent length, offset-path estimates,
and explicitly realized geometry.

Every routable child can own ordered guide-face references for local collection,
breakout, and termination control. These references use persistent Fusion entity
tokens and the current repairable linked-geometry health behavior. A child guide
makes its affected local span eligible for geometry realization without forcing a
full-length body. Parent motion propagates to descendants; deleting a guide never
silently reassigns the child to nearby geometry.

A parent may break out into any number of child conductors or composite members.
Children keep their stable identities through guides, branches, ends, validation,
generation, and diagrams. Repeated breakouts and later recombination must not assume
a strict Y shape or silently reuse one physical-wire UUID for multiple bodies. The
containment tree describes what is inside a cable, while the route graph independently
describes where every member travels and connects.

The milestone includes reusable, versioned complex-wire configurations containing
the recursive order, relative dimensions, materials, insulation, shields, technical
fields, and default naming. Harness-specific endpoint connections, pathway assignments,
guide faces, and Fusion entity tokens remain instance data. Document-local presets,
packaged catalogs, and a user-managed library remain storage candidates. Versioning,
migration, duplicate handling, template updates versus instance overrides, and copy
versus linked-instance behavior must be decided before persistence is implemented.
Fusion document history continues to version placed instances.

M2 establishes target-derived naming for top-level connections. This milestone extends
the same rule to nested members: Harness Builder offers a name from the most specific
stable metadata available, including explicit connection or pin metadata, a user-named
target face, its owning body/component/occurrence, and finally the existing generated
fallback. The stored connection records the target reference and naming provenance.
An explicit Harness Builder name always wins. The schema must decide whether inherited
names track later Fusion renames or are copied at connection time; refresh must never
overwrite a custom name.

The per-wire graphic can expand a composite recursively and navigate to each member's
configuration. The master graphic collapses it to external connections and pathways
until the user drills in. Search includes nested names, target-derived names, technical
fields, and part numbers. Logical continuity remains visible independently of realized
geometry. Cross-checking treats containment, route membership, electrical connections,
guide references, and generated identities as separate projections.

Before implementation, settle Y-junction/breakout route semantics and the profile-gate
behavior required for non-circular envelopes. Implement and migrate the recursive
host-independent model and deterministic fit validation before adding Fusion guide
selection, preview, or generation. Sparse realization ensures that connection
complexity scales primarily with data and diagrams rather than with full-length Fusion
bodies for every enclosed member.

### Planned routed-member flexibility and kink diagnostics milestone

The domain must generalize the physical items routed through a harness. An electrical
conductor remains one routed-member kind; optical fiber, liquid-cooling tubing, and
future service lines are non-conductor kinds. All routed members share stable identity,
parent containment, outer-envelope geometry, guide faces, route membership, technical
notes, manufacturer and part-number provenance, and optional flexibility data. Each
kind may add relevant fields without pretending that conductor material, electrical
ratings, optical properties, and fluid properties are interchangeable.

Every routed member may store a manufacturer-specified flex or kink rating. The
application uses a normalized representation capable of expressing at least a minimum
bend radius or an outer-diameter multiplier while preserving the manufacturer's
original value, units, source, and applicable conditions. Static installation,
dynamic/flexing service, temperature, pressure, cycle count, and bend-direction limits
may require distinct ratings. The schema must not collapse materially different test
conditions into one unexplained number. The default is an explicit **Not specified**
state. It imposes no advisory bend limit, is treated as infinitely flexible within
the geometry solver's independent feasibility constraints, and is skipped by
rating-based routing and kink analysis to avoid unnecessary computation.

A composite wire's effective bend target is set by its least-flexible active rated
member on the span being evaluated. For minimum bend radius, this is the largest
applicable required radius after normalizing every rated descendant and any rated
parent jacket or shield. Members that have already branched away do not constrain
later parent spans. Not-specified members are excluded from this calculation. If no
active member has a rating, the span has no advisory bend target and bypasses all
rating-driven fairing and kink checks.

The harness supports two flexibility modes:

- **Constrained** routing asks transition allocation and fairing to satisfy the
  effective manufacturer bend target wherever the available route permits. If the
  requested target cannot fit, the solver clamps the influence of that rating to the
  best feasible geometry, completes the route, and emits a violation. Repeated or
  severe over-bending may produce multiple warnings, but the manufacturer rating never
  converts the result into a geometry-generation failure.
- **Unconstrained** routing follows the user's geometric controls without using the
  manufacturer rating to shape the route. Kink analysis still evaluates the result and
  reports applicable violations so the user can inspect the design.

Manufacturer flexibility is therefore an advisory engineering constraint. Independent
hard failures remain possible for malformed inputs, missing required route geometry,
impossible topology, gate-capacity violations, or a curve the Fusion kernel cannot
construct. A flex or kink rating alone must never raise such a failure. The system must
fall back to the same unrated best-effort geometry if rating-aware fairing cannot find
a compliant result.

Kink detection evaluates the finished exact route, including inherited parent spans
for sparsely realized children and explicit child geometry around guides and breakouts.
It compares local curvature and tangent continuity against every applicable normalized
rating. Adaptive evaluation must retain the location of the tightest bend rather than
depending on a display tessellation. Each finding records the affected member and
ancestor composite, route span and parameter, actual bend radius, required rating,
clamp or fallback applied, and manufacturer-rating provenance.

In constrained mode, successful geometry generation also records a reference-length
baseline for every conductor and routed member. The record includes stable member
identity, total length, per-span lengths where available, the generated definition or
route revision, and measurement provenance. Explicitly realized members use their
exact generated paths. Sparse enclosed members record whether their value comes from
inherited parent length or an offset-path estimate, so an estimate is never presented
as exact realized geometry.

Animation and test inspection recomputes current lengths and compares them with the
stored baseline. Per member and span it reports positive length growth, percentage
extension, and the location contributing the largest increase. This provides an
informational indication of pull and possible tearing as parts move. A current length
at or below its baseline produces no pull finding.

The planned mechanical monitoring scope is deliberately limited to pull from length
growth and flex from bend-radius/kink analysis. It does not attempt compression,
buckling, force, stress, fatigue, pressure, thermal, or general material-failure
analysis.

All routed members are treated as inextensible. Flex permits a member to change shape
through bending but does not give it elastic length. Consequently the two monitoring
measurements are sufficient: local bend radius against the specified flex rating, and
current routed length against the generated reference length. Any positive length
growth beyond a small deterministic numerical tolerance is a pull finding because the
member cannot stretch to supply it. That tolerance exists only to suppress floating
point and curve-evaluation noise; it is not an elastic allowance. No spring, modulus,
or stretch solver is planned.

Reference lengths are observational data. They never alter transition allocation,
fairing, packing, collision checks, or generated geometry, and no length-monitoring
finding may fail a solver or block generation. Animation sampling reads the baseline
without rewriting it. A successful explicit Generate/Rebuild or future Rebaseline
action may establish a new reference state; ordinary animation frames and tests may
not silently move that baseline.

Warnings highlight the relevant route segment, controls or guide faces that bound it,
and the member rows in Wire Routes, the recursive member editor, Validation, and the
relationship graphics. Activating a finding navigates to the affected member and
controls. The UI distinguishes Not specified, a compliant route, a constrained
route that was adjusted successfully, a clamped non-compliant route, and an
unconstrained violation. Users may acknowledge a warning for a deliberate design, but
the stored rating and measured violation remain visible and auditable.

Fit validation and bend validation remain separate. A coolant line or fiber may fit
inside its parent while violating its bend rating, or comply with its bend rating while
the complete bundle fails an aperture. Cross-checking reconstructs routed-member kinds,
effective composite ratings, per-span membership, kink findings, reference lengths,
positive animation/test pull deltas, and UI projections from the same persistent
identities.

### Planned wrappings, ties, and custom restraints milestone

Wrappings and ties are physical restraint definitions associated with a selected set
of routed members. They are not conductors, routed-member children, or electrical
connections. Each restraint has stable identity, a placement rule, an ordered target
member set, generated-geometry ownership, material settings, and optional naming,
manufacturer, part number, and notes.

The placement rule supports three initial methods:

- **Slice plane** places one restraint at a user-selected station and orientation
  through the routed member envelope. The plane remains a persistent linked-geometry
  reference and follows the current repairable missing-reference behavior.
- **Guide body** derives placement and local orientation from selected guide geometry.
  The definition records the source body or faces needed to reproduce the placement
  rather than relying on viewport proximity.
- **Incremental** repeats a restraint at an explicit spacing along a selected parent or
  pathway span. It records the start reference or offset, spacing, direction, extent or
  count, and end handling so regeneration is deterministic.

Built-in prefabs initially include **Heat shrink** and **Tape**. Each prefab owns the
parameters required by its construction, such as axial coverage, thickness, overlap,
or repeat where applicable. Every prefab and placed instance has the same material
control principles as wire insulation: a catalog or custom material description,
plain color or Fusion library appearance, manufacturer, part number, and notes, with
clear instance override and inheritance behavior. These materials are independent of
the materials on the restrained members.

Tie, strap, and zip-tie style restraints may reference a custom buckle model. Before
use, the model must expose two manually assigned and uniquely identifiable interface
faces: **Band Start** and **Band End**. Harness Builder places and orients the buckle,
constructs a band leaving Band Start, wraps that band around the outer envelope of the
selected target members, and joins it into Band End. The generated band and buckle
occurrence share one restraint identity while remaining distinguishable generated
children for selection and regeneration.

Custom buckle placement supports an explicit scale needed to suit the selected bundle.
The stored definition retains the source-model reference, original dimensions,
applied scale, transform, and both interface-face identities. Scaling must preserve
the two interfaces and is applied before the band path is solved. Uniform scaling is
the safe baseline; axis-specific scaling requires separate validation because it may
distort the interfaces or the functional buckle geometry.

Band construction uses the evaluated outer envelope of the selected routed members at
the placement station, including insulation, shields, and nested composite jackets.
It must not route through the selected members or the buckle. A restraint around a
subset uses that subset's envelope rather than automatically capturing every member in
the parent. The chosen wrap direction, clearance, band width, thickness, and any user
rotation are persistent inputs, not results inferred again from incidental geometry.

Wrappings and restraints contribute their finished outer geometry to clearance,
aperture, and collision validation. They do not alter electrical connectivity, flex
ratings, pull baselines, or the routing solver. If the target envelope changes,
regeneration updates the wrap and incremental placements while preserving restraint
identity and custom buckle source. Invalid buckle interfaces, lost placement references,
or an unsolvable band path produce repairable restraint findings and do not corrupt
the routed members they surround.

The palette provides prefab selection, material controls, placement method and
parameters, target-member selection, buckle source and scale, preview, and explicit
generation. Hover and findings highlight the restraint, its targets, placement
reference, buckle interfaces, and generated band. Relationship diagrams may show a
compact physical-restraint annotation where useful, but restraints do not become
nodes or edges in the connection relationship graph.

Before implementation, define the persistent naming mechanism for Band Start and Band
End faces, confirm how external custom buckle models are referenced and packaged, and
prototype the band-around-envelope solver for circular and non-circular target sets.
Incremental placement must be evaluated from stable route distance so edits do not
accumulate positional drift.

Cross-check comparisons operate on endpoint field values rather than serialized
object-key order. Fusion state payloads use sorted JSON keys, which must not create
findings when `{end, wireId}` and `{wireId, end}` carry identical values.

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

Metadata introduced in schema version 3 and retained in version 4 stores per-gate
override flags and per-end-member settings (null entries inherit the section baseline).
Legacy section settings remain a fallback for older definitions. Saves use one native
Fusion transaction, refresh affected active previews, and preserve editor expansion
state. Original sketch geometry is untouched.

### Initial persistent solid generation

Generate/Rebuild Solids is an explicit native Fusion command separate from
transient previews. It creates one child component per conductor with editable
cubic control-point splines and straight segments, a diameter-sized circular
profile normal to the path, and one solid sweep. UUID, number, diameter, and
measured centerline length are stored on the generated component. The exact
component-local cubic controls are retained for material-only stripe refreshes.
Component names use the wire label, or its number and centerline length when no
label is supplied.

This first slice rebuilds all wires after one confirmation that includes manual
edits inside generated components. Every replacement is built before any previous
marked component is deleted. Original sketches and unmarked components are not
modified. Native command rollback covers failures during final replacement.
Preview edits do not implicitly replace solid bodies; explicit rebuilding is
required. Selective regeneration and automatic manual-edit detection are later
work. Clear Solids deletes only marked generated wire components in a native
transaction, leaving original sketches and unrelated components untouched. Stripe
graphics are children of each marked generated component, so clearing or
moving that component clears or moves its pattern as one unit. Preview and Clear
Preview never create, refresh, or delete these solid-owned stripe groups. Solid
geometry persists independently of preview visibility and add-in state. The upper
palette status area retains informational and failure events in a vertically
scrollable console using the same surface and text colors as the rest of the palette.
The top-level Developer mode checkbox defaults off. Enabling it first presents a
versioned disclosure explaining that development-only tools may capture visible Fusion
content or simulate input, may require operating-system Screen Recording or
Accessibility permission, and must be used with suitable test data. The user must
explicitly affirm that the disclosure was read and understood before Developer mode is
enabled for the palette session. Cancel, Escape, or disabling the checkbox leaves
Developer mode off and hides full routing diagnostics. Enabling Developer mode does not
grant operating-system permission or start external capture or input automation; every
external QA invocation remains separately opt-in. This session preference is UI state
and is never stored in a harness definition.
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
