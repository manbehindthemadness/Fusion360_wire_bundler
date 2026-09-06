# Fusion 360 Wire Bundler

Wire Bundler is an Autodesk Fusion add-in for creating editable wire, ribbon, and harness assemblies. The current milestone records reusable pathways, pairs ordered End A and End B profiles into stable logical wires, and previews parallel-wire centerlines through circular routing gates. Creating a harness stores a versioned draft definition, converts an active Part design to Hybrid intent, or creates an external component in Fusion's active cloud folder when working in an Assembly design.

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
- End-member rows drag and drop within their own stack and provide add-after, replace, and remove controls. Every profile center guides the preview; both stacks are ordered from terminal toward pathway. Edits refresh the active preview as needed.
- Synchronized end-to-end wire-route and pathway-occupancy representations
- Click-to-highlight Fusion profiles for gates, connections, and wire endpoint pairs
- Stable wire, connection, profile, pathway, and routing-control identities
- Deterministic hexagonal wire packing with circular-gate capacity checks
- Lightweight, selectable Custom Graphics centerline previews with explicit clearing
- Active previews refresh affected routing groups after member edits and redraw only changed paths, preserving unrelated graphics.
- Persistent Fusion entity tokens with reload-time linked-geometry health reporting
- Schema version 3 persistence with automatic in-memory reading of versions 1 and 2
- Isolated reporting of malformed stored definitions without hiding healthy harnesses

The detailed product behavior is defined in `reference/`. Persistent conductor identity, explicit control-structure ordering, editable geometry, and stored procedural metadata are core requirements.

## Install and smoke test

This repository directory is already located under Fusion's `API/AddIns` directory.

1. Open Fusion and choose **Utilities > Add-Ins > Scripts and Add-Ins**.
2. On the **Add-Ins** tab, select `Fusion360_wire_bundler` and choose **Run**.
3. In the **Solid** workspace, choose the visible **Harness Builder** button in the **Utilities > Add-Ins** panel and confirm the persistent palette opens.
4. Select **Create New Harness**, confirm the native dialog suggests the next available harness name, choose a routing mode, and select **OK**.
5. Confirm Fusion creates exactly one empty child component beneath the active component, the palette reports success, and the new draft appears under **Existing Harnesses**. If the document began as a Part design, also confirm that Fusion changed it to Hybrid intent.
6. Select the harness entry and confirm the in-place editor shows its persistent ID plus expandable Wire Routes, Pathways & Occupancy, and Validation sections.
7. Create at least two closed sketch profiles to act as gates. Select **Add Pathway**, confirm the dialog defaults to the harness routing mode, choose routing or profile gates, then select the profiles in traversal order and choose **OK**.
8. Create equal numbers of closed End A and End B sketch profiles. Select **Add Wire Pairs**, choose the pathway and diameter, select End A profiles in wire order, then select matching End B profiles in the same order and choose **OK**.
9. Confirm the palette shows one wire per ordered pair, sequential wire numbers, the shared profile, the selected pathway, and linked end geometry.
10. Confirm Wire Routes shows each conductor from End A through its complete pathway chain to End B. Click the wire header to collapse/expand it, hover the header to emphasize its existing preview centerline, and use the pen to rename it inline (Enter or blur saves; Escape cancels). Click its profile node to open Wire Options and save a positive diameter in millimeters; other wires must retain their sizes. Check dragging by Fusion's title bar and resizing at its native outer edge; the content has an 4-pixel border matching the window background.
11. Select either end node in Wire Routes and confirm its child editor shows only that wire's endpoint profile. Enter independent end names and confirm the nodes show them. Edit Wire Name and Pathway Name; name the start and end above/below the gate traversal list. Confirm the route reads `End A: Data input → lower fuse box path from O2-sensor to CAN_BUS-ctrl → End B: Data output`, persists after refresh, and restores generated fallbacks when optional labels are cleared.
12. Expand Pathways & Occupancy, then expand one pathway and its independent Gates · Traversal Order and Wire Occupancy children. Confirm the occupancy child identifies every wire plus whether it enters at End A, arrives from a previous pathway, continues onward, or exits at End B. Click gate, end, occupancy, and wire rows and confirm Fusion highlights the referenced profile or end pair.
13. Use **+ Add Gates** and **+ Add Wire Pairs** inside the appropriate pathway child and confirm the native dialog targets that pathway. Remove a gate and wire pair, confirming each destructive action first; a pathway's last gate must not be removable.
14. Select **Preview Routes** and confirm one colored, selectable centerline appears per wire through every gate. These are transient piecewise-linear previews; no solid wire bodies are generated yet.
15. With a preview active, replace an end member or change a wire diameter; confirm changed centerlines refresh while unaffected paths remain visible. Removing the last end member hides the incomplete wire's path; restoring the end brings it back. Select **Clear Preview**, edit again, and confirm the preview stays off. Preview again, stop the add-in, and confirm teardown removes it.
16. Reduce a circular gate until the packed wire envelopes no longer fit, then preview and confirm the error identifies that gate instead of drawing partial results.
17. Refresh, close and reopen the palette, then stop and run the add-in; confirm the definitions and linked-geometry status survive while previews remain transient.
18. Delete or invalidate one selected sketch profile, refresh the palette, and confirm the corresponding connection or routing control reports missing linked geometry.
19. Add another pathway with the same proposed name and confirm the suggested and persisted name increments without changing the existing pathway.
20. Create another harness and confirm the suggested and created name increments without changing the existing harness.
21. In an Assembly design, open Harness Builder from the **Assembly** tab's **Insert** panel. Confirm it creates an external harness in the active cloud folder and appears in the palette; save the parent assembly to persist the new external component.
22. Stop the add-in in **Scripts and Add-Ins** and confirm that the command and palette are removed.

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

`wire_bundler/domain/`, `wire_bundler/application/`, and `wire_bundler/routing/` have no Fusion dependency. They define and transactionally persist harness drafts and solve deterministic parallel-wire crossings independently of the host. `wire_bundler/fusion/` owns Fusion persistence, profile/frame translation, linked-geometry health checks, viewport selection, and transient centerline graphics. Current routing supports circular routing gates, zero additional clearance by default, and piecewise-linear previews. Ordered gate and endpoint-pairing edits update the versioned definition transactionally and invalidate stale previews. Spline fairing, configurable clearance, profile-gate/ribbon routing, connection renaming, final swept bodies, terminators, and full span collision analysis remain future milestones.
