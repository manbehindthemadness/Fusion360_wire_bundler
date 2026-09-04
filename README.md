# Fusion 360 Wire Bundler

Wire Bundler is an Autodesk Fusion add-in for creating editable wire, ribbon, and harness assemblies. The current milestone provides a persistent Harness Builder palette that discovers and inspects stored procedural harnesses and opens the native creation workflow. Creating a harness stores a versioned draft definition, converts an active Part design to Hybrid intent, or creates an external component in Fusion's active cloud folder when working in an Assembly design.

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
- Persistent Harness Builder palette with create, refresh, discovery, and summary inspection
- Isolated reporting of malformed stored definitions without hiding healthy harnesses

The detailed product behavior is defined in `reference/`. Persistent conductor identity, explicit control-structure ordering, editable geometry, and stored procedural metadata are core requirements.

## Install and smoke test

This repository directory is already located under Fusion's `API/AddIns` directory.

1. Open Fusion and choose **Utilities > Add-Ins > Scripts and Add-Ins**.
2. On the **Add-Ins** tab, select `Fusion360_wire_bundler` and choose **Run**.
3. In the **Solid** workspace, choose the visible **Harness Builder** button in the **Utilities > Add-Ins** panel and confirm the persistent palette opens.
4. Select **Create New Harness**, confirm the native dialog suggests the next available harness name, choose a routing mode, and select **OK**.
5. Confirm Fusion creates exactly one empty child component beneath the active component, the palette reports success, and the new draft appears under **Existing Harnesses**. If the document began as a Part design, also confirm that Fusion changed it to Hybrid intent.
6. Select the harness entry and confirm its component name, definition name, routing mode, counts, persistent ID, and draft status appear without closing the palette.
7. Create another harness and confirm the suggested and created name increments without changing the existing harness.
8. In an Assembly design, open Harness Builder from the **Assembly** tab's **Insert** panel. Confirm it creates an external harness in the active cloud folder and appears in the palette; save the parent assembly to persist the new external component.
9. Close and reopen the palette, then stop and run the add-in. Confirm the existing definitions are rediscovered after each operation.
10. Stop the add-in in **Scripts and Add-Ins** and confirm that the command and palette are removed.

During development, stopping the add-in evicts its `wire_bundler` package modules. Running it again therefore loads current source without restarting Fusion. Changes to the bootstrap file `Fusion360_wire_bundler.py` itself still require one Fusion restart before this reload behavior changes.

There is no standalone launch or type-check command yet. Fusion supplies the `adsk` API at runtime; it is not a package dependency to install from this repository.

## Development environment

The local development environment uses `uv` and Python 3.9 or newer. It is separate from the Python runtime embedded in Fusion.

```bash
uv sync
uv run pytest
uv run ruff check Fusion360_wire_bundler.py wire_bundler tests
uv run ruff format --check Fusion360_wire_bundler.py wire_bundler tests
```

PyCharm should use `.venv/bin/python` as the project interpreter. Do not install an unrelated `adsk` package from PyPI; Fusion provides its API modules to add-ins inside the host process. Pure application logic should remain importable without `adsk` so it can be covered by local unit tests later.

## Layout

```text
Fusion360_wire_bundler.manifest  Fusion add-in metadata
Fusion360_wire_bundler.py        Fusion run/stop entry point
pyproject.toml                    Python and uv project metadata
wire_bundler/                    Fusion lifecycle, host adapters, domain, and application services
tests/                           Application-owned unit tests
resources/originals/             Full-resolution source artwork for all commands
resources/                       Fusion standard and high-DPI command icon sets
reference/                       Product and engineering specifications
F360WireGenerator/               Unrelated third-party example repository
```

`F360WireGenerator/` is retained only as an example of a loadable Fusion add-in. Its code and design conventions are not part of Wire Bundler.

## Domain boundary

`wire_bundler/domain/` and `wire_bundler/application/` have no Fusion dependency. They define and transactionally persist the empty draft that starts a harness, including deterministic conflict-free naming, and decode discovered definitions without allowing one damaged component to hide healthy neighbors. `wire_bundler/fusion/` converts a Part design to Hybrid intent when necessary, creates internal children in Hybrid designs or external children in Assembly designs, stores deterministic schema-versioned JSON in the component attribute group `kev0.wire_bundler` under `harness_definition`, and discovers marked components across the active design. Names are checked against every component in the active design and, for external components, files in the active cloud folder. Standalone wires belong as bodies in Part designs. Editing definitions, Fusion geometry inspection, non-circular profiles, terminators, and route generation remain future milestones.
