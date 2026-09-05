# Fusion 360 Wire Bundler

Wire Bundler is an Autodesk Fusion add-in for creating editable wire, ribbon, and harness assemblies. The current milestone records reusable pathways, pairs ordered source and destination profiles into stable logical wires, and previews parallel-wire centerlines through circular routing gates. Creating a harness stores a versioned draft definition, converts an active Part design to Hybrid intent, or creates an external component in Fusion's active cloud folder when working in an Assembly design.

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
- Ordered source-to-destination profile pairing through a selected pathway
- Stable wire, connection, profile, pathway, and routing-control identities
- Deterministic hexagonal wire packing with circular-gate capacity checks
- Lightweight, selectable Custom Graphics centerline previews with explicit clearing
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
6. Select the harness entry and confirm the in-place editor shows its persistent ID plus expandable Pathways, Wires, Connections, Routing, and Validation sections.
7. Create at least two closed sketch profiles to act as gates. Select **Add Pathway**, confirm the dialog defaults to the harness routing mode, choose routing or profile gates, then select the profiles in traversal order and choose **OK**.
8. Create equal numbers of closed source and destination sketch profiles. Select **Add Wires**, choose the pathway and diameter, select source profiles in wire order, then select matching destination profiles in the same order and choose **OK**.
9. Confirm the palette shows one wire per ordered pair, sequential wire numbers, the shared profile, the selected pathway, and linked source/destination geometry.
10. Select **Preview Routes** and confirm one colored, selectable centerline appears per wire through every gate. These are transient piecewise-linear previews; no solid wire bodies are generated yet.
11. Select **Clear Preview** and confirm the centerlines disappear. Preview again, stop the add-in, and confirm teardown also removes them.
12. Reduce a circular gate until the packed wire envelopes no longer fit, then preview and confirm the error identifies that gate instead of drawing partial results.
13. Refresh, close and reopen the palette, then stop and run the add-in; confirm the definitions and linked-geometry status survive while previews remain transient.
14. Delete or invalidate one selected sketch profile, refresh the palette, and confirm the corresponding connection or routing control reports missing linked geometry.
15. Add another pathway with the same proposed name and confirm the suggested and persisted name increments without changing the existing pathway.
16. Create another harness and confirm the suggested and created name increments without changing the existing harness.
17. In an Assembly design, open Harness Builder from the **Assembly** tab's **Insert** panel. Confirm it creates an external harness in the active cloud folder and appears in the palette; save the parent assembly to persist the new external component.
18. Stop the add-in in **Scripts and Add-Ins** and confirm that the command and palette are removed.

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

PyCharm should use `.venv/bin/python` as the project interpreter. Do not install an unrelated `adsk` package from PyPI; Fusion provides its API modules to add-ins inside the host process. Pure application logic should remain importable without `adsk` so it can be covered by local unit tests later.

## Reference verification scenario

`experiments/experiment_reference_harness.py` is a live Fusion integration scenario, not a
normal pytest test. In **Utilities > Scripts and Add-Ins**, select the **Scripts** tab, use the
green **+** button to register `experiments/experiment_reference_harness_runner/`, then run
`experiment_reference_harness_runner` while no command transaction is active.

The scenario creates a new unsaved Hybrid design, builds three source profiles, three ordered
routing gates, and three destination profiles, then exercises harness creation, pathway
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

`wire_bundler/domain/`, `wire_bundler/application/`, and `wire_bundler/routing/` have no Fusion dependency. They define and transactionally persist harness drafts and solve deterministic parallel-wire crossings independently of the host. `wire_bundler/fusion/` owns Fusion persistence, profile/frame translation, linked-geometry health checks, and transient centerline graphics. Current routing supports circular routing gates, zero additional clearance by default, and piecewise-linear previews. Spline fairing, configurable clearance, profile-gate/ribbon routing, pathway/wire editing, final swept bodies, terminators, and full span collision analysis remain future milestones.
