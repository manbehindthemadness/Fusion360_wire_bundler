const RELATIONSHIP_DIAGRAM_CONTRACT_VERSION = "1";
const RELATIONSHIP_DIAGRAM_LAYOUT = "measured-pathway-stack";

function relationshipEndGroups(harness, pathwayId, endpoint, connections) {
  const connectionField = endpoint === "start" ? "startConnectionId" : "endConnectionId";
  const endpointNameField = endpoint === "start" ? "startEndName" : "endEndName";
  const groups = new Map();
  harness.wires
    .filter((wire) => {
      const pathwayIndex = endpoint === "start" ? 0 : wire.orderedPathwayIds.length - 1;
      return wire.orderedPathwayIds[pathwayIndex] === pathwayId;
    })
    .forEach((wire) => {
      const connectionId = wire[connectionField] || "";
      const groupKey = connectionId || `missing:${wire.wireId}`;
      if (!groups.has(groupKey)) {
        groups.set(groupKey, {
          connectionId,
          connectionName: connections.get(connectionId)?.name || "",
          endpointNames: new Set(),
          wires: [],
        });
      }
      const group = groups.get(groupKey);
      if (wire[endpointNameField]) group.endpointNames.add(wire[endpointNameField]);
      group.wires.push(wire);
    });
  return [...groups.values()].map((group) => {
    const endpointNames = [...group.endpointNames];
    const label = endpointNames.length === 1
      ? endpointNames[0]
      : group.connectionName || `Missing End ${endpoint === "start" ? "A" : "B"}`;
    const wireSearch = group.wires.map((wire) => (
      `${wireLabel(wire)} ${wire.wireNumber} ${wire.materials?.insulationMaterial || ""} ${wire.materials?.mainColor?.name || ""}`
    )).join(" ");
    return {
      ...group,
      label,
      searchable: `${label} ${group.connectionName} ${endpointNames.join(" ")} ${wireSearch}`
        .toLocaleLowerCase(),
    };
  });
}

function relationshipPathwayWires(harness, pathwayId) {
  return harness.wires.filter((wire) => wire.orderedPathwayIds.includes(pathwayId));
}

function relationshipJunctionWires(harness, junction) {
  return harness.wires.filter((wire) => wire.orderedPathwayIds.some((pathwayId, index) => (
    pathwayId === junction.precedingPathwayId
      && wire.orderedPathwayIds[index + 1] === junction.followingPathwayId
  )));
}

function relationshipPathwayChains(harness) {
  const pathways = new Map(harness.pathways.map((pathway) => [pathway.pathwayId, pathway]));
  const outgoing = new Map();
  const incoming = new Set();
  (harness.junctions || []).forEach((junction) => {
    if (!outgoing.has(junction.precedingPathwayId)) {
      outgoing.set(junction.precedingPathwayId, junction);
    }
    incoming.add(junction.followingPathwayId);
  });
  const visited = new Set();
  const walk = (root) => {
    const nodes = [];
    let pathway = root;
    while (pathway && !visited.has(pathway.pathwayId)) {
      visited.add(pathway.pathwayId);
      nodes.push({ kind: "pathway", item: pathway });
      const junction = outgoing.get(pathway.pathwayId);
      if (!junction || !pathways.has(junction.followingPathwayId)) break;
      nodes.push({ kind: "junction", item: junction });
      pathway = pathways.get(junction.followingPathwayId);
    }
    return nodes;
  };
  const roots = harness.pathways.filter((pathway) => !incoming.has(pathway.pathwayId));
  const chains = roots.map(walk).filter((nodes) => nodes.length);
  harness.pathways.forEach((pathway) => {
    if (!visited.has(pathway.pathwayId)) chains.push(walk(pathway));
  });
  return chains;
}

function renderRelationshipConnector(
  groups, wires, fromEndList, expanded, showPlaceholder = false,
) {
  const svg = svgElement("svg", {
    class: "relationship-connector",
    viewBox: "0 0 54 100",
    preserveAspectRatio: "none",
    "aria-hidden": "true",
  });
  const curvePath = (listY, hubY) => fromEndList
    ? `M 0 ${listY} C 24 ${listY}, 30 ${hubY}, 54 ${hubY}`
    : `M 0 ${hubY} C 24 ${hubY}, 30 ${listY}, 54 ${listY}`;
  const redraw = (isExpanded) => {
    svg.replaceChildren();
    if (!wires.length && showPlaceholder) {
      svg.append(svgElement("path", {
        class: "placeholder-trace",
        d: curvePath(50, 50),
      }));
      return;
    }
    if (!wires.length) return;
    const groupedWireIds = new Set(
      groups.flatMap((group) => group.wires.map((wire) => wire.wireId)),
    );
    if (!isExpanded && wires.every((wire) => groupedWireIds.has(wire.wireId))) {
      svg.append(svgElement("path", { class: "aggregate-trace", d: curvePath(50, 50) }));
      return;
    }
    const groupPositions = new Map();
    groups.forEach((group, groupIndex) => {
      const groupY = 20 + 75 * ((groupIndex + 0.5) / groups.length);
      const spacing = Math.min(6, 14 / Math.max(1, group.wires.length - 1));
      group.wires.forEach((wire, wireIndex) => {
        groupPositions.set(
          wire.wireId,
          groupY + (wireIndex - (group.wires.length - 1) / 2) * spacing,
        );
      });
    });
    const hubSpacing = Math.min(2.5, 14 / Math.max(1, wires.length - 1));
    wires.forEach((wire, wireIndex) => {
      const hubY = 50 + (wireIndex - (wires.length - 1) / 2) * hubSpacing;
      const listY = groupPositions.get(wire.wireId) ?? hubY;
      const pathData = curvePath(listY, hubY);
      svg.append(svgElement("path", {
        class: "wire-trace",
        d: pathData,
        stroke: wire.materials?.mainColor?.hex || "#1777c8",
        "data-wire-id": wire.wireId,
      }));
      const stripes = (wire.materials?.stripes || []).slice(0, 3);
      stripes.forEach((stripe, stripeIndex) => {
        const stripeOffset = centeredStripeOffset(stripeIndex, stripes.length, 2);
        svg.append(svgElement("path", {
          class: "stripe-trace",
          d: curvePath(listY + stripeOffset, hubY + stripeOffset),
          stroke: stripe.color?.hex || "#fff",
          "stroke-dasharray": stripe.pattern === "solid" ? "none" : "8 5",
          "data-wire-id": wire.wireId,
        }));
      });
    });
  };
  svg.redraw = redraw;
  redraw(expanded);
  return svg;
}

function renderRelationshipBridge(wires) {
  const svg = svgElement("svg", {
    class: "relationship-chain-link",
    viewBox: "0 0 22 100",
    preserveAspectRatio: "none",
    "aria-hidden": "true",
  });
  if (!wires.length) {
    svg.append(svgElement("path", {
      class: "structural-trace",
      d: "M 0 50 L 22 50",
    }));
    return svg;
  }
  const spacing = Math.min(2.5, 14 / Math.max(1, wires.length - 1));
  wires.forEach((wire, wireIndex) => {
    const y = 50 + (wireIndex - (wires.length - 1) / 2) * spacing;
    svg.append(svgElement("path", {
      class: "wire-trace",
      d: `M 0 ${y} L 22 ${y}`,
      stroke: wire.materials?.mainColor?.hex || "#1777c8",
      "data-wire-id": wire.wireId,
    }));
    (wire.materials?.stripes || []).slice(0, 3).forEach((stripe, stripeIndex, stripes) => {
      const stripeOffset = centeredStripeOffset(stripeIndex, stripes.length, 2);
      svg.append(svgElement("path", {
        class: "stripe-trace",
        d: `M 0 ${y + stripeOffset} L 22 ${y + stripeOffset}`,
        stroke: stripe.color?.hex || "#fff",
        "stroke-dasharray": stripe.pattern === "solid" ? "none" : "8 5",
        "data-wire-id": wire.wireId,
      }));
    });
  });
  return svg;
}

function renderRelationshipEndList(
  harness, pathway, endpoint, groups, visibleGroups, query, collapseLimit,
) {
  const side = endpoint === "start" ? "A" : "B";
  const details = document.createElement("details");
  const summary = document.createElement("summary");
  const label = document.createElement("span");
  const count = document.createElement("span");
  const items = document.createElement("div");
  const overrideKey = `${harnessKey(harness)}:${pathway.pathwayId}:${endpoint}`;
  const override = relationshipEndListOverrides.get(overrideKey);
  details.className = `relationship-end-list${groups.length ? "" : " empty"}`;
  details.dataset.pathwayId = pathway.pathwayId;
  details.dataset.endpoint = endpoint;
  details.open = query
    ? visibleGroups.length > 0
    : override ?? groups.length <= collapseLimit;
  label.textContent = `End ${side}`;
  count.textContent = query && visibleGroups.length !== groups.length
    ? `${visibleGroups.length} of ${groups.length}`
    : `${groups.length}`;
  hoverHighlight(summary, () => highlightMember(harness, "pathway_wires", pathway.pathwayId));
  if (!groups.length) {
    details.open = false;
    summary.append(label);
    summary.addEventListener("click", (event) => {
      event.preventDefault();
      navigateToPathway(pathway.pathwayId);
    });
    details.append(summary);
    return details;
  }
  summary.append(label, count);
  items.className = "relationship-end-items";
  visibleGroups.forEach((group) => {
    const button = document.createElement("button");
    const name = document.createElement("strong");
    const meta = document.createElement("small");
    button.type = "button";
    button.className = "relationship-end-entry";
    button.dataset.connectionId = group.connectionId;
    name.textContent = group.label;
    const connectionContext = group.connectionName && group.connectionName !== group.label
      ? `${group.connectionName} · ` : "";
    meta.textContent = `${connectionContext}${group.wires.length} ${group.wires.length === 1 ? "wire" : "wires"}`;
    button.append(name, meta);
    hoverHighlight(button, () => group.connectionId
      ? highlightMember(harness, "connection", group.connectionId)
      : highlightMember(harness, "preview_wire", group.wires[0].wireId));
    button.addEventListener("click", () => navigateToWire(group.wires[0].wireId));
    items.append(button);
  });
  if (!visibleGroups.length) items.append(emptyMessage(`No matching End ${side} connections.`));
  details.addEventListener("toggle", () => {
    if (!query) relationshipEndListOverrides.set(overrideKey, details.open);
    if (details.redrawConnector) details.redrawConnector(details.open);
  });
  details.append(summary, items);
  return details;
}

/**
 * Position pathway groups on a measured vertical diagram canvas.
 */
function layoutRelationshipGraph(stack, pathwayGroups) {
  const padding = 30;
  const verticalGap = 30;
  const measured = [...pathwayGroups.values()].map((group) => ({
    group,
    width: Math.max(760, group.scrollWidth),
    height: Math.max(92, group.scrollHeight),
  }));
  const canvasWidth = Math.max(760, ...measured.map((item) => item.width)) + padding * 2;
  let nextY = padding;
  measured.forEach((item) => {
    item.group.style.left = `${(canvasWidth - item.width) / 2}px`;
    item.group.style.top = `${nextY}px`;
    nextY += item.height + verticalGap;
  });
  stack.style.width = `${canvasWidth}px`;
  stack.style.height = `${Math.max(nextY - verticalGap + padding, 260)}px`;
}

function addRelationshipMapContextMenu(workspace) {
  const menu = document.createElement("div");
  const close = () => {
    menu.hidden = true;
    document.removeEventListener("mousedown", dismissOnOutsideMouseDown, true);
  };
  const dismissOnOutsideMouseDown = (event) => {
    if (!menu.contains(event.target)) close();
  };
  menu.className = "relationship-map-context-menu";
  menu.hidden = true;
  menu.setAttribute("role", "menu");
  menu.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      close();
      workspace.viewport.focus();
    }
  });
  const show = (event, items) => {
    event.preventDefault();
    const bounds = workspace.root.getBoundingClientRect();
    const left = Math.min(
      Math.max(4, event.clientX - bounds.left),
      Math.max(4, workspace.root.clientWidth - 160),
    );
    const top = Math.min(
      Math.max(4, event.clientY - bounds.top),
      Math.max(4, workspace.root.clientHeight - 44 * items.length),
    );
    menu.style.left = `${left}px`;
    menu.style.top = `${top}px`;
    menu.replaceChildren();
    items.forEach(({ label, action, disabled = false, title = "" }) => {
      const button = document.createElement("button");
      button.type = "button";
      button.setAttribute("role", "menuitem");
      button.textContent = label;
      button.disabled = disabled;
      button.title = title;
      button.addEventListener("click", () => {
        close();
        void action();
      });
      menu.append(button);
    });
    menu.hidden = false;
    document.addEventListener("mousedown", dismissOnOutsideMouseDown, true);
    const firstEnabled = Array.from(menu.children).find((button) => !button.disabled);
    if (firstEnabled) firstEnabled.focus();
  };
  workspace.viewport.addEventListener("contextmenu", (event) => {
    show(event, [{ label: "Add pathway", action: addPathway }]);
  });
  workspace.root.append(menu);
  return show;
}

function renderRelationshipMap(harness, auditIssues) {
  const connections = new Map(
    harness.connections.map((connection) => [connection.connectionId, connection]),
  );
  const container = document.createElement("div");
  const toolbar = document.createElement("div");
  const filter = document.createElement("input");
  const summary = document.createElement("span");
  const settings = document.createElement("label");
  const collapseInput = document.createElement("input");
  const workspace = createBlockDiagramWorkspace("Zoomable master relationship diagram");
  const showContextMenu = addRelationshipMapContextMenu(workspace);
  container.className = "section-content relationship-map";
  container.dataset.diagramContractVersion = RELATIONSHIP_DIAGRAM_CONTRACT_VERSION;
  container.dataset.diagramLayout = RELATIONSHIP_DIAGRAM_LAYOUT;
  toolbar.className = "relationship-map-toolbar";
  filter.className = "filter";
  filter.type = "search";
  filter.placeholder = "Find a wire, connection, or pathway…";
  filter.setAttribute("aria-label", "Filter master relationship graphic");
  filter.autocomplete = "off";
  filter.value = relationshipFilters.get(harnessKey(harness)) || "";
  summary.className = "relationship-map-summary";
  summary.textContent = auditIssues.length ? `${auditIssues.length} cross-check findings` : "Cross-check clear";
  toolbar.append(filter, summary);
  settings.className = "relationship-map-settings";
  settings.textContent = "Collapse end lists above";
  collapseInput.type = "number";
  collapseInput.min = `${MIN_RELATIONSHIP_COLLAPSE_LIMIT}`;
  collapseInput.max = `${MAX_RELATIONSHIP_COLLAPSE_LIMIT}`;
  collapseInput.step = "1";
  collapseInput.value = `${relationshipCollapseLimit(harness)}`;
  collapseInput.setAttribute("aria-label", "Connections before end lists collapse");
  settings.append(collapseInput, "connections");

  const draw = () => {
    const query = filter.value.trim().toLocaleLowerCase();
    const collapseLimit = clampRelationshipCollapseLimit(collapseInput.value);
    relationshipFilters.set(harnessKey(harness), query);
    workspace.stage.replaceChildren();
    const stack = document.createElement("div");
    const pathwayGroups = new Map();
    let visiblePathways = 0;
    stack.className = "relationship-pathway-stack";
    stack.dataset.diagramContractVersion = RELATIONSHIP_DIAGRAM_CONTRACT_VERSION;
    stack.dataset.diagramLayout = RELATIONSHIP_DIAGRAM_LAYOUT;
    relationshipPathwayChains(harness).forEach((chain, chainIndex) => {
      const pathwayNodes = chain.filter((node) => node.kind === "pathway");
      const pathway = pathwayNodes[0].item;
      const endpointGroups = new Map();
      pathwayNodes.forEach((node) => {
        endpointGroups.set(node.item.pathwayId, {
          start: relationshipEndGroups(harness, node.item.pathwayId, "start", connections),
          end: relationshipEndGroups(harness, node.item.pathwayId, "end", connections),
        });
      });
      const pathwayMatches = chain.map((node) => (
        node.kind === "pathway"
          ? `${node.item.name} ${node.item.startName || ""} ${node.item.endName || ""}`
          : node.item.name
      )).join(" ")
        .toLocaleLowerCase().includes(query);
      const matchingWireIds = new Set();
      endpointGroups.forEach((groups) => {
        [...groups.start, ...groups.end]
          .filter((group) => group.searchable.includes(query))
          .forEach((group) => group.wires.forEach((wire) => matchingWireIds.add(wire.wireId)));
      });
      if (query && !pathwayMatches && !matchingWireIds.size) return;
      const pathwayGroup = document.createElement("div");
      const columns = [];
      pathwayGroup.className = "relationship-pathway-group";
      pathwayGroup.dataset.pathwayId = pathway.pathwayId;
      pathwayGroups.set(`chain-${chainIndex}`, pathwayGroup);
      chain.forEach((node) => {
        if (node.kind === "junction") {
          const junctionWires = relationshipJunctionWires(harness, node.item)
            .filter((wire) => !query || pathwayMatches || matchingWireIds.has(wire.wireId));
          const junction = document.createElement("button");
          const junctionName = document.createElement("strong");
          const junctionKind = document.createElement("small");
          junction.type = "button";
          junction.className = "relationship-junction-hub";
          junction.title = "Junction routing control";
          junctionName.textContent = node.item.name || "Unnamed junction";
          junctionKind.textContent = "Junction";
          hoverHighlight(
            junction,
            () => highlightMember(harness, "junction", node.item.junctionId),
          );
          junction.append(junctionName, junctionKind);
          pathwayGroup.append(
            renderRelationshipBridge(junctionWires),
            junction,
            renderRelationshipBridge(junctionWires),
          );
          columns.push("14px", "154px", "14px");
          return;
        }

        const candidate = node.item;
        const groups = endpointGroups.get(candidate.pathwayId);
        const visibleStart = !query || pathwayMatches
          ? groups.start : groups.start.filter((group) => group.searchable.includes(query));
        const visibleEnd = !query || pathwayMatches
          ? groups.end : groups.end.filter((group) => group.searchable.includes(query));
        const pathwayWires = relationshipPathwayWires(harness, candidate.pathwayId)
          .filter((wire) => !query || pathwayMatches || matchingWireIds.has(wire.wireId));
        const startList = renderRelationshipEndList(
          harness, candidate, "start", groups.start, visibleStart, query, collapseLimit,
        );
        const endList = renderRelationshipEndList(
          harness, candidate, "end", groups.end, visibleEnd, query, collapseLimit,
        );
        const startConnector = renderRelationshipConnector(
          visibleStart, pathwayWires, true, startList.open, pathwayWires.length === 0,
        );
        const endConnector = renderRelationshipConnector(
          visibleEnd, pathwayWires, false, endList.open, pathwayWires.length === 0,
        );
        const hub = document.createElement("button");
        const hubName = document.createElement("strong");
        const hubDirection = document.createElement("small");
        const controls = new Map(harness.controls.map((control) => [control.controlId, control]));
        const canSegment = candidate.orderedControlIds.slice(1, -1).some((controlId) => {
          const control = controls.get(controlId);
          return control && ["routing_gate", "refine"].includes(control.kind);
        });
        hub.type = "button";
        hub.className = "relationship-pathway-hub";
        hub.title = "Open pathway configuration";
        hubName.textContent = candidate.name || "Unnamed pathway";
        hubDirection.textContent = pathwayDirection(candidate);
        hoverHighlight(hub, () => highlightMember(harness, "pathway_gates", candidate.pathwayId));
        hub.addEventListener("click", () => openPathwayPopup(harness, candidate.pathwayId));
        hub.addEventListener("contextmenu", (event) => {
          event.stopPropagation();
          showContextMenu(event, [
            { label: "Add refine point", action: () => addPathwayRefine(harness, candidate) },
            {
              label: "Segment",
              action: () => segmentPathway(harness, candidate),
              disabled: !canSegment,
              title: canSegment ? "" : "Requires an interior routing gate or refine point",
            },
          ]);
        });
        hub.append(hubName, hubDirection);
        startList.redrawConnector = startConnector.redraw;
        endList.redrawConnector = endConnector.redraw;
        pathwayGroup.append(startList, startConnector, hub, endConnector, endList);
        columns.push(
          groups.start.length ? "210px" : "max-content",
          "32px",
          "154px",
          "32px",
          groups.end.length ? "210px" : "max-content",
        );
      });
      pathwayGroup.style.gridTemplateColumns = columns.join(" ");
      stack.append(pathwayGroup);
      visiblePathways += 1;
    });
    if (!visiblePathways) {
      const message = emptyMessage(
        harness.pathways.length
          ? "No relationships match this filter."
          : "No pathways to display yet.",
      );
      message.className = "empty relationship-map-empty";
      workspace.stage.append(message);
      window.requestAnimationFrame(() => workspace.fit());
      return;
    }
    workspace.stage.append(stack);
    window.requestAnimationFrame(() => {
      layoutRelationshipGraph(stack, pathwayGroups);
      workspace.fit();
    });
  };
  filter.addEventListener("input", draw);
  collapseInput.addEventListener("change", () => {
    const limit = clampRelationshipCollapseLimit(collapseInput.value);
    collapseInput.value = `${limit}`;
    writeSession(relationshipCollapseStorageKey(harness), `${limit}`);
    [...relationshipEndListOverrides.keys()]
      .filter((key) => key.startsWith(`${harnessKey(harness)}:`))
      .forEach((key) => relationshipEndListOverrides.delete(key));
    draw();
  });
  container.append(toolbar, settings, workspace.root);
  draw();
  return container;
}
