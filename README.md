# Fusion 360 Wire Bundler

Wire Bundler is an Autodesk Fusion add-in for creating editable wire, ribbon, and harness assemblies. The current milestone records reusable pathways, pairs ordered End A and End B profiles into stable logical wires, previews smooth, oriented wire centerlines through circular routing gates, and generates circular solid wire sweeps. Creating a harness stores a versioned draft definition, converts an active Part design to Hybrid intent, or creates an external component in Fusion's active cloud folder when working in an Assembly design.

## Current milestone

- Fusion add-in manifest and entry point
- Promoted Harness Builder button in the Solid Add-Ins and Assembly Insert panels
- Symmetric command registration and teardown
- Immutable, versioned harness domain model
- Strict JSON parsing and deterministic pre-generation validation
- Focused unit tests that run without Fusion
- Transactional empty-harness creation with rollback on metadata failure
- Fusion component and attribute persistence adapter
- Conflict-free harness names shared by the component and stored definition
- Persistent Harness Builder palette with filtering and in-place harness inspection
- Palette entry markup, styling, editor logic, materials, relationship graphics, and Fusion host actions are separated into local packaged resources under `palette/`.
- The floating palette initially opens at 840 × 760 pixels so the relationship graphic and editor controls fit comfortably while remaining user-resizable.
- Reusable routing- or profile-gate pathways captured in explicit selection order
- Ordered End A-to-End B profile pairing through a selected pathway
- Editable pathway-gate and symmetric End A/End B connection ordering
- Optional per-wire end names, editable wire and pathway names, and named traversal ends above/below the gates list; route nodes show custom labels with generated fallbacks.
- Editable connection members with native Add/Replace profile selection and Remove; deleting the last member warns and leaves a repairable missing end.
- End-node menus remember their open/closed state across member edits, palette refreshes, and palette reloads.
- End members display stable short identifiers that survive reordering, replacement, and reload. Routing follows stored stack order, never proximity to the pathway.
- Drag a member row to a blue insertion line and release to reorder. Releasing outside its stack cancels the move.
- Gate traversal uses the same drag-and-drop interaction. Both stacks show a separate far-left position number; stable gate names/IDs and end-member IDs follow their members.
- Section counts align at the right, immediately before the disclosure arrow, independently of heading length.
- Palette edits and Preview/Clear Preview execute as named Fusion commands, grouping definition and graphics changes into one undo transaction. Command completion reloads the palette and reconciles saved preview caches without creating a new edit. Live Fusion Undo/Redo verification is still required.
- End-member rows drag and drop within their own stack and provide add-after, replace, and remove controls. Every profile center guides the preview; both stacks are ordered from terminal toward pathway. Edits refresh the active preview as needed.
- Synchronized end-to-end wire-route and pathway-occupancy representations
- Read-only Master Relationship Graphic below Validation, with one searchable card per pathway, curved connection-to-pathway links, and collapsible End A/End B connection lists centered around the pathway. Lists with seven or fewer connections open by default, and the retained per-harness threshold is editable. Each wire has one detailed colored and striped route graphic: its End A/End B nodes open their ordering editors, pathway nodes navigate to pathway configuration, and the wire specification and material controls remain beneath it. Diagram hover highlighting and click-through navigation remain connected to Fusion geometry. An independent projection audit cross-checks routes, pathway occupancy, and connection usage in both the application layer and palette.
- Click-to-highlight Fusion profiles for gates, connections, and wire endpoint pairs
- Stable wire, connection, profile, pathway, and routing-control identities
- Deterministic hexagonal wire packing with circular-gate capacity checks
- Smooth cubic transitions perpendicular to gate and end-profile planes, preserving ordered crossings and straight middle spans. Auto starts at one quarter of the adjacent span and expands when the wire diameter requires a larger bend.
- Each gate row and end-member row has an **Options** popup for individual interpolation distances (millimeters or Auto). **Defaults** supplies the baseline; saving updates existing controls using defaults unless unchecked. Individual overrides are preserved, and **Use harness defaults** restores inheritance.
- **Generate/Rebuild Solids** creates one marked component per wire with an editable centerline sketch, circular diameter profile, sweep, and measured centerline length. Rebuilding requires confirmation and replaces only marked generated wire components after all new sweeps succeed.
- Harness-level wire-material defaults and field-level per-wire overrides for insulation, main color or an installed Fusion library appearance, ordered procedural stripe specifications, conductor, manufacturer, part number, and notes. Controlled autocomplete fields provide bundled suggestions while accepting custom values. Resolved visuals drive route previews and generated solid appearances.
- Lightweight, selectable Custom Graphics centerline previews with explicit clearing
- Save-time graphics-cache protection prevents active previews from being baked into reopened designs
- Active previews refresh affected routing groups after member edits and redraw only changed paths, preserving unrelated graphics.
- Persistent Fusion entity tokens with reload-time linked-geometry health reporting
- Schema version 4 persistence with automatic in-memory reading of versions 1 through 3
- Isolated reporting of malformed stored definitions without hiding healthy harnesses

The detailed product behavior is defined in `reference/`. Persistent conductor identity, explicit control-structure ordering, editable geometry, and stored procedural metadata are core requirements.

## Install and smoke test

This repository directory is already located under Fusion's `API/AddIns` directory.

1. Open Fusion and choose **Utilities > Add-Ins > Scripts and Add-Ins**.
2. On the **Add-Ins** tab, select `Fusion360_wire_bundler` and choose **Run**.
3. In the **Solid** workspace, choose the visible **Harness Builder** button in the **Utilities > Add-Ins** panel and confirm the persistent palette opens.
4. Select **Create New Harness**, confirm the native dialog suggests the next available harness name, choose a routing mode, and select **OK**.
5. Confirm Fusion creates exactly one empty child component beneath the active component, the palette reports success, and the new draft appears under **Existing Harnesses**. If the document began as a Part design, also confirm that Fusion changed it to Hybrid intent.
6. Select the harness entry and confirm the in-place editor shows its persistent ID plus expandable Wire Routes, Pathways & Occupancy, Validation, and Master Relationship Graphic sections in that order.
7. Create at least two closed sketch profiles to act as gates. Select **Add Pathway**, confirm the dialog defaults to the harness routing mode, choose routing or profile gates, then select the profiles in traversal order and choose **OK**.
8. Create equal numbers of closed End A and End B sketch profiles. Select **Add Wire Pairs**, choose the pathway and diameter, select End A profiles in wire order, then select matching End B profiles in the same order and choose **OK**.
9. Confirm the palette shows one wire per ordered pair, sequential wire numbers, the shared profile, the selected pathway, and linked end geometry.
10. Confirm Wire Routes shows each conductor from End A through its complete pathway chain to End B. Click the wire header to collapse/expand it, hover the header to emphasize its existing preview centerline, and use the pen to rename it inline (Enter or blur saves; Escape cancels). Click the clearly labeled **Wire options** button, change its diameter and material settings in the same dialog, and confirm Apply and Save update both while other wires retain their sizes. Check dragging by Fusion's title bar and resizing at its native outer edge; the content has an 4-pixel border matching the window background.
11. Select either end node in Wire Routes and confirm its child editor shows only that wire's endpoint profile. Enter independent end names and confirm the nodes show them. Edit Wire Name and Pathway Name; name the start and end above/below the gate traversal list. Confirm the route reads `End A: Data input → lower fuse box path from O2-sensor to CAN_BUS-ctrl → End B: Data output`, persists after refresh, and restores generated fallbacks when optional labels are cleared.
12. Expand Pathways & Occupancy, then expand one pathway and its independent Gates · Traversal Order and Wire Occupancy children. Confirm the occupancy child identifies every wire plus whether it enters at End A, arrives from a previous pathway, continues onward, or exits at End B. Click gate, end, occupancy, and wire rows and confirm Fusion highlights the referenced profile or end pair.
13. Expand a wire and confirm its colored route graphic is the only route representation. Activate End A and End B to open their respective ordering editors, activate a pathway bubble to expand and navigate to that pathway's configuration, and confirm mouse and keyboard activation both work. Hover the colored line, connections, and pathways to confirm the corresponding Fusion geometry highlights. One **Wire options** button remains beneath the graphic. Confirm every one-, two-, or three-stripe cue is centered within the base trace. Expand the Master Relationship Graphic below Validation and confirm its darker viewport clearly separates the pathway cards and collapsible end lists from the backdrop. With three connections per end, both lists should be open in full and each wire trace should use its resolved base color and centered stripe pattern. Hover a pathway hub and confirm only its gates highlight; click it to expand and navigate to its Pathways & Occupancy configuration. Set **Collapse end lists above** to `2` and confirm both lists and their curves collapse into one neutral aggregate relationship per side; restore `7`, search by a wire, connection, pathway, material, or color, and confirm the matching end opens temporarily with a filtered count. Click a master connection entry to return to the expanded Wire Routes entry. Confirm Validation reports a clear relationship cross-check.
14. Use **+ Add Gates** and **+ Add Wire Pairs** inside the appropriate pathway child and confirm the native dialog targets that pathway. Remove a gate and wire pair, confirming each destructive action first; a pathway's last gate must not be removable.
15. Select **Preview Routes** and confirm one colored, selectable centerline appears per wire through every gate without stripe meshes. These are transient smooth centerlines sampled for display; solid bodies and their component-owned stripe patterns are generated together using **Generate/Rebuild Solids**. Check perpendicular entry/exit at gates and end profiles, with straight middle spans. Drag the event console's lower edge to resize it. Confirm routing failures show a concise message until **Verbose diagnostics** is enabled.
16. With a preview active, replace an end member or change a wire diameter; confirm changed centerlines refresh while unaffected paths remain visible. Removing the last end member hides the incomplete wire's path; restoring the end brings it back. Select **Clear Preview**, edit again, and confirm the preview stays off. Preview again, stop the add-in, and confirm teardown removes it.
17. Reduce a circular gate until the packed wire envelopes no longer fit, then preview and confirm the error identifies that gate instead of drawing partial results.
18. With a preview active, save the design, close it, and reopen it; confirm the preview was not cached into the reopened viewport. Then stop and run the add-in and confirm the definitions and linked-geometry status survive while previews remain transient.
19. Delete or invalidate one selected sketch profile, refresh the palette, and confirm the corresponding connection or routing control reports missing linked geometry.
20. Add another pathway with the same proposed name and confirm the suggested and persisted name increments without changing the existing pathway.
21. Create another harness and confirm the suggested and created name increments without changing the existing harness.
22. In an Assembly design, open Harness Builder from the **Assembly** tab's **Insert** panel. Confirm it creates an external harness in the active cloud folder and appears in the palette; save the parent assembly to persist the new external component.
23. Stop the add-in in **Scripts and Add-Ins** and confirm that the command and palette are removed.

During development, stopping the add-in evicts its `wire_bundler` package modules. Running it again therefore loads current source without restarting Fusion. Changes to the bootstrap file `Fusion360_wire_bundler.py` itself still require one Fusion restart before this reload behavior changes.

There is no standalone launch or type-check command yet. Fusion supplies the `adsk` API at runtime; it is not a package dependency to install from this repository.

## Development environment

The local development environment uses `uv` and Python 3.9 or newer. It is separate from the Python runtime embedded in Fusion.

```bash
uv sync
uv run pytest
uv run ruff check Fusion360_wire_bundler.py wire_bundler tests experiments
uv run ruff format --check Fusion360_wire_bundler.py wire_bundler tests experiments
```

Run the palette rendering regressions with `node tests/test_palette.cjs` (Node 16+
required). These use a mocked DOM/Fusion boundary and do not replace live Fusion
smoke testing.

PyCharm should use `.venv/bin/python` as the project interpreter. Do not install an unrelated `adsk` package from PyPI; Fusion provides its API modules to add-ins inside the host process. Pure application logic should remain importable without `adsk` so it can be covered by local unit tests later.

## Reference verification scenario

`experiments/experiment_reference_harness.py` is a live Fusion integration scenario, not a
normal pytest test. In **Utilities > Scripts and Add-Ins**, select the **Scripts** tab, use the
green **+** button to register `experiments/experiment_reference_harness_runner/`, then run
`experiment_reference_harness_runner` while no command transaction is active.

The scenario creates a new unsaved Hybrid design, builds three End A profiles, three ordered
routing gates, and three End B profiles, then exercises harness creation, pathway
persistence, ordered wire assignment, route solving and preview, validation, entity-token resolution,
and metadata rediscovery. The design remains open after either outcome for inspection. Timestamped `.log`
and `.json` reports are written beneath the ignored `artifacts/verification/` directory and key
messages are also mirrored into Fusion's application log. Extend this same scenario with spline
fairing and body-generation assertions as those production services are implemented.

## Layout

```text
Fusion360_wire_bundler.manifest  Fusion add-in metadata
Fusion360_wire_bundler.py        Fusion run/stop entry point
pyproject.toml                    Python and uv project metadata
wire_bundler/                    Fusion lifecycle, host adapters, domain, and application services
tests/                           Application-owned unit tests
experiments/                     Live Fusion integration scenarios and reporting support
artifacts/verification/          Ignored generated scenario logs and JSON reports
resources/originals/             Full-resolution source artwork for all commands
resources/                       Fusion standard and high-DPI command icon sets
reference/                       Product and engineering specifications
F360WireGenerator/               Unrelated third-party example repository
```

`F360WireGenerator/` is retained only as an example of a loadable Fusion add-in. Its code and design conventions are not part of Wire Bundler.

## Domain boundary

`wire_bundler/domain/`, `wire_bundler/application/`, and `wire_bundler/routing/` have no Fusion dependency. They define and transactionally persist harness drafts and solve deterministic parallel-wire crossings independently of the host. `wire_bundler/fusion/` owns Fusion persistence, profile/frame translation, linked-geometry health checks, viewport selection, and transient centerline graphics. Current routing supports circular routing gates, zero additional clearance by default, and tangent-continuous cubic transitions. Exact cubic geometry is retained separately from ordered crossings and adaptively sampled to a 0.05 mm chord tolerance for display. The host-independent fairing API supports independent approach/departure lengths with diameter-derived safety floors. Crowded spans use the full available chord: a direct profile-to-profile cubic is preferred, while equal-tangent lateral offsets use a tangent-continuous two-arc S-bend when one cubic cannot preserve the sweep radius. Preview and solid generation report adjustments in the palette's vertically resizable event console. Failures remain concise unless session-persistent verbose diagnostics are enabled. The Fusion adapter applies this diameter-aware fairing across pathway controls and every connection-owned end profile. Wire-envelope fit checks apply only to pathway apertures. Ordered gate and endpoint-pairing edits update the versioned definition transactionally and invalidate stale previews. Configurable clearance, profile-gate/ribbon routing, selective solid regeneration, center drift, ovalization, and full-span collision analysis remain future milestones.

Wire materials use complete harness defaults with nullable overrides on each persistent
wire. An unset override inherits its parent field; an explicit empty stripe list removes
inherited stripes. The catalog under `resources/catalogs/` supplies searchable suggestions
and remains deployable with the add-in as a relative resource. The base visual can
instead reference an appearance from an installed Fusion library; the selected
appearance is copied into the design before assignment to generated bodies. Route
previews remain lightweight colored centerlines. Longitudinal, dashed, and helical
model-space stripe bands belong to each generated wire component, so they move and
are deleted with their solid. Generated metadata retains the exact component-local
curve controls so Apply and Save can refresh stripe patterns without following a
newer, unreconstructed preview route. Existing generated wires from before this
metadata require one rebuild before stripes can be applied. Apply keeps Wire options
open for visual inspection; Save commits the displayed settings, while Cancel or Escape
restores the diameter, materials, and solid-owned stripes present when the dialog opened.

Diameter-aware center drift, bounded oval deformation, and circular-envelope
packing are parallel round-wire behavior. Ribbon routing remains a separate
profile-gate system and follows completion of parallel-wire routing.

Undo/Redo host verification (pending): with an active preview, rename a wire,
drag an end member, reorder gates, change diameter, and remove a wire. For each,
confirm Fusion lists one named undo action, Undo restores definition/order/IDs
and preview geometry, and Redo restores the edit. Repeat with Preview/Clear
Preview, several consecutive Undos/Redos, and an edit after Undo. Confirm the
palette expansion stays intact and hovering does not invalidate Redo. Verify a
failed edit leaves no partial definition or graphics, and stop/start removes and
re-registers the command-completion handler. Use an unsaved test design; the local
Fusion MCP endpoint was unavailable during automated verification.

Deferred UI follow-up: match Fusion’s light/dark color scheme, including automatic host/OS theme changes. The current palette remains light when the host switches to dark.

## Solid wire generation smoke test

Stop/run the add-in, open a complete harness, and select **Generate/Rebuild Solids**.
Confirm one child component per wire appears beneath the harness, each containing
one solid body, Wire Centerline and Wire Diameter sketches, and a Wire Sweep.
Unnamed wires use their stable number and measured centerline length in the
component name. Successful generation clears the transient route preview after
the modeling command closes. Hovering related palette items selects generated
wire bodies along with their linked profiles and preview centerlines. Generated
geometry remains after Clear Preview and add-in stop.

Edits continue to refresh lightweight previews; solids update only when explicitly
rebuilt. Rebuild replaces all marked wire components, including manual edits inside
them, after one confirmation. Unmarked components and original sketches are left
untouched. **Clear Solids** removes only marked generated wire components after
confirmation. Verify Undo restores cleared or rebuilt solids and Redo reapplies the
operation. Clear Preview runs synchronously as transient palette cleanup outside the
model-edit command transaction. It hides and empties nested graphics before deleting
the parent, scans the root and every design component, verifies deletion, refreshes
the viewport, and reports the removed count.
A failed sweep should identify its wire and leave the previous output intact.
Repeated harness placements are rejected because a unique coordinate context is
required. Profile-gate/ribbon solids, center drift, ovalization, and full-span
collision checks remain future work. The original five-case diameter-aware Sweep
matrix, three-stroke 180-degree zig-zag, adjacent pinch turns, and explicit-value
clamping all pass in Fusion's native Sweep kernel.

The adapter uses Autodesk’s [control-point spline API](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/SketchControlPointSplines_add.htm)
and [sweep API](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/SweepFeatures_createInput.htm).

Generation diagnostics: failed command messages remain in the palette's scrollable,
theme-matched event panel after refresh,
and Fusion's application log includes the full traceback and the failed generation
operation (for example, creating the cross-section plane or creating the sweep). If
the Fusion kernel rejects a sweep, the message also reports the centerline's tightest
sampled local bend radius, curve number, curve parameter, and wire radius. This
diagnostic locates local curvature; it does not certify clearance between distant
parts of the swept tube.

For repeatable kernel verification, register
`experiments/experiment_sweep_matrix_runner/` with the green **+** button on
Fusion's Scripts tab, then run `experiment_sweep_matrix_runner` while no command
transaction is active. It creates an unsaved design, generates the shared straight,
spatial, three-stroke 180-degree zig-zag, three-adjacent-pinch, asymmetric crowded-span,
equal-tangent offset S-bend, diameter-expanded,
undersized-explicit-clamp, and impossible-span cases, invokes Sweep only for routes
that pass preflight, and writes reports under `artifacts/verification/`.
