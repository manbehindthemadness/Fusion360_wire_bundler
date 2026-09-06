"""
Host-independent application services for Wire Bundler workflows.
"""

from .add_pathway import (
    PathwayGateway,
    PathwayUpdateError,
    add_pathway,
    suggest_pathway_name,
)
from .add_wire_batch import (
    WireBatchGateway,
    WireBatchResult,
    WireBatchUpdateError,
    add_wire_batch,
)
from .create_harness import (
    HarnessCreationError,
    HarnessGateway,
    create_empty_harness,
    suggest_harness_name,
)
from .edit_harness import (
    HarnessEditError,
    HarnessEditGateway,
    append_pathway_gates,
    move_pathway_gate,
    move_wire_endpoint,
    remove_pathway_gate,
    remove_wire,
    rename_pathway,
    rename_route_end,
    rename_wire,
    set_harness_material_defaults,
    set_wire_diameter,
    set_wire_material_overrides,
)
from .load_harnesses import (
    HarnessLibraryGateway,
    HarnessLoadResult,
    StoredHarness,
    load_harnesses,
)
from .material_catalog import WireMaterialCatalog, load_wire_material_catalog

__all__ = [
    "HarnessCreationError",
    "HarnessEditError",
    "HarnessEditGateway",
    "HarnessGateway",
    "HarnessLibraryGateway",
    "HarnessLoadResult",
    "StoredHarness",
    "WireBatchGateway",
    "WireBatchResult",
    "WireBatchUpdateError",
    "WireMaterialCatalog",
    "PathwayGateway",
    "PathwayUpdateError",
    "add_pathway",
    "add_wire_batch",
    "append_pathway_gates",
    "create_empty_harness",
    "load_harnesses",
    "move_pathway_gate",
    "move_wire_endpoint",
    "remove_pathway_gate",
    "remove_wire",
    "rename_route_end",
    "rename_pathway",
    "rename_wire",
    "set_harness_material_defaults",
    "set_wire_diameter",
    "set_wire_material_overrides",
    "load_wire_material_catalog",
    "suggest_harness_name",
    "suggest_pathway_name",
]
