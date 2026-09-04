# Fusion 360 Wire Bundler

Wire Bundler is an Autodesk Fusion add-in for creating editable wire, ribbon, and harness assemblies. The project is in its foundation stage; the current command creates an empty harness child component and stores its versioned draft definition in Fusion attributes. Creating a harness converts an active Part design to Hybrid intent; in an Assembly design it creates an external component in Fusion's active cloud folder.

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

The detailed product behavior is defined in `reference/`. Persistent conductor identity, explicit control-structure ordering, editable geometry, and stored procedural metadata are core requirements.

## Install and smoke test

This repository directory is already located under Fusion's `API/AddIns` directory.

1. Open Fusion and choose **Utilities > Add-Ins > Scripts and Add-Ins**.
2. On the **Add-Ins** tab, select `Fusion360_wire_bundler` and choose **Run**.
3. In the **Solid** workspace, choose the visible **Harness Builder** button in the **Utilities > Add-Ins** panel.
4. Confirm the dialog suggests the next available harness name, choose a routing mode, and select **OK**.
5. Confirm that Fusion creates exactly one empty child component beneath the active component and displays a success message. If the document began as a Part design, also confirm that Fusion changed it to Hybrid intent.
6. Re-run the command with `Harness_001` and confirm the new child is named `Harness_002` without changing the existing harness.
7. In an Assembly design, choose the visible **Harness Builder** button in the **Assembly** tab's **Insert** panel. Confirm it creates an external harness in the active cloud folder; save the parent assembly to persist the new external component.
8. Stop the add-in in **Scripts and Add-Ins** and confirm that the command is removed from both panels.

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

`wire_bundler/domain/` and `wire_bundler/application/` have no Fusion dependency. They define and transactionally persist the empty draft that starts a harness, including deterministic conflict-free naming. `wire_bundler/fusion/` converts a Part design to Hybrid intent when necessary, creates internal children in Hybrid designs or external children in Assembly designs, and stores deterministic schema-versioned JSON in the component attribute group `kev0.wire_bundler` under `harness_definition`. Names are checked against every component in the active design and, for external components, files in the active cloud folder. Standalone wires belong as bodies in Part designs. Fusion geometry inspection, loading and editing existing definitions, non-circular profiles, terminators, and route generation remain future milestones.
