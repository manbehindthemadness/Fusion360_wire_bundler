const RELATIONSHIP_DIAGRAM_CONTRACT_VERSION = "2";
const RELATIONSHIP_DIAGRAM_LAYOUT = "endpoint-junction-forest";

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
  const relationships = junction.pathwayRelationships || [];
  const preceding = new Set(
    relationships.filter((item) => item.endpoint === "end").map((item) => item.pathwayId),
  );
  const following = new Set(
    relationships.filter((item) => item.endpoint === "start").map((item) => item.pathwayId),
  );
  return harness.wires.filter((wire) => wire.orderedPathwayIds.some((pathwayId, index) => (
    preceding.has(pathwayId) && following.has(wire.orderedPathwayIds[index + 1])
  )));
}

function relationshipTopology(harness) {
  const nodes = new Map();
  const edges = [];
  const addNode = (kind, item, index) => {
    const id = `${kind}:${kind === "pathway" ? item.pathwayId : item.junctionId}`;
    nodes.set(id, { id, kind, item, index, incoming: [], outgoing: [], neighbors: [] });
  };
  harness.pathways.forEach((pathway, index) => addNode("pathway", pathway, index));
  (harness.junctions || []).forEach((junction, index) => (
    addNode("junction", junction, harness.pathways.length + index)
  ));
  (harness.junctions || []).forEach((junction) => {
    const junctionId = `junction:${junction.junctionId}`;
    (junction.pathwayRelationships || []).forEach((relationship) => {
      const pathwayId = `pathway:${relationship.pathwayId}`;
      if (!nodes.has(junctionId) || !nodes.has(pathwayId)) return;
      const sourceId = relationship.endpoint === "end" ? pathwayId : junctionId;
      const targetId = relationship.endpoint === "end" ? junctionId : pathwayId;
      const edge = { junction, relationship, sourceId, targetId };
      edges.push(edge);
      nodes.get(sourceId).outgoing.push(targetId);
      nodes.get(targetId).incoming.push(sourceId);
      nodes.get(junctionId).neighbors.push(pathwayId);
      nodes.get(pathwayId).neighbors.push(junctionId);
    });
  });
  const indegrees = new Map([...nodes].map(([id, node]) => [id, node.incoming.length]));
  const ready = [...nodes.values()].filter((node) => !indegrees.get(node.id))
    .sort((left, right) => left.index - right.index);
  const depths = new Map([...nodes.keys()].map((id) => [id, 0]));
  while (ready.length) {
    const node = ready.shift();
    node.outgoing.forEach((targetId) => {
      depths.set(targetId, Math.max(depths.get(targetId), depths.get(node.id) + 1));
      indegrees.set(targetId, indegrees.get(targetId) - 1);
      if (!indegrees.get(targetId)) {
        ready.push(nodes.get(targetId));
        ready.sort((left, right) => left.index - right.index);
      }
    });
  }
  const visited = new Set();
  const components = [];
  [...nodes.values()].sort((left, right) => left.index - right.index).forEach((root) => {
    if (visited.has(root.id)) return;
    const queue = [root];
    const componentNodes = [];
    visited.add(root.id);
    while (queue.length) {
      const node = queue.shift();
      componentNodes.push({ ...node, depth: depths.get(node.id) || 0 });
      node.neighbors.forEach((neighborId) => {
        if (!visited.has(neighborId)) {
          visited.add(neighborId);
          queue.push(nodes.get(neighborId));
        }
      });
    }
    componentNodes.sort((left, right) => left.depth - right.depth || left.index - right.index);
    const nodeIds = new Set(componentNodes.map((node) => node.id));
    components.push({
      nodes: componentNodes,
      edges: edges.filter((edge) => nodeIds.has(edge.sourceId) && nodeIds.has(edge.targetId)),
    });
  });
  return components;
}

function openJunctionRelationships(harness, junction) {
  closePathwayPopup();
  const prior = document.body.querySelector(".junction-relationships-popup");
  if (prior) {
    prior.remove();
    if (prior.open) prior.close();
  }
  openJunctionPopupId = junction.junctionId;
  const dialog = document.createElement("dialog");
  const content = document.createElement("div");
  const heading = document.createElement("h2");
  const relationships = document.createElement("details");
  const relationshipSummary = document.createElement("summary");
  const relationshipTitle = document.createElement("strong");
  const relationshipCount = document.createElement("span");
  const sequence = document.createElement("div");
  const add = document.createElement("button");
  const actions = document.createElement("div");
  const close = document.createElement("button");
  const pathways = new Map(
    harness.pathways.map((pathway) => [pathway.pathwayId, pathway]),
  );
  const existingRelationships = junction.pathwayRelationships || [];
  dialog.className = "junction-relationships-popup";
  heading.textContent = `Pathway relationships · ${junction.name || "Unnamed junction"}`;
  content.className = "junction-relationships-content";
  relationships.className = "junction-relationship-stack";
  relationshipTitle.textContent = "Pathway Relationships";
  relationshipCount.className = "item-meta";
  relationshipCount.textContent = `${existingRelationships.length}`;
  relationshipSummary.append(relationshipTitle, relationshipCount);
  sequence.className = "sequence";
  existingRelationships.forEach((relationship) => {
    const pathway = pathways.get(relationship.pathwayId);
    const endpointLabel = relationship.endpoint === "start" ? "End A" : "End B";
    const childWires = relationshipEndpointWires(harness, junction, relationship);
    const row = memberRow(
      `${pathway?.name || "Missing pathway"} · ${endpointLabel}`,
      () => highlightMember(harness, "pathway_gates", relationship.pathwayId),
      [actionButton("×", `Remove ${endpointLabel} relationship`, () => {
        if (childWires.length && !window.confirm(
          `${childWires.length} ${childWires.length === 1 ? "wire pathway traverses" : "wire pathways traverse"} this relationship. Remove it?`,
        )) return;
        void mutate("remove_junction_relationship", {
          harnessId: harness.harnessId,
          junctionId: junction.junctionId,
          pathwayId: relationship.pathwayId,
          endpoint: relationship.endpoint,
        }, "Removing junction relationship…");
      }, false, true)],
      !pathway,
    );
    row.dataset.pathwayId = relationship.pathwayId;
    row.dataset.endpoint = relationship.endpoint;
    sequence.append(row);
  });
  if (!existingRelationships.length) {
    sequence.append(emptyMessage("No pathway relationships."));
  }
  relationships.append(relationshipSummary, sequence);
  add.type = "button";
  add.className = "button compact";
  add.textContent = "+ Add Relationship";
  add.addEventListener("click", () => addJunctionRelationship(junction.junctionId));
  close.type = "button";
  close.className = "button";
  close.textContent = "Close";
  close.addEventListener("click", () => dialog.close());
  actions.className = "dialog-actions";
  actions.append(close);
  dialog.addEventListener("close", () => {
    if (document.body.querySelector(".junction-relationships-popup") === dialog) {
      openJunctionPopupId = "";
    }
    dialog.remove();
  });
  content.append(
    heading,
    nameField(
      "Junction Name",
      junction.name,
      "rename_junction",
      { harnessId: harness.harnessId, junctionId: junction.junctionId },
      "Junction name",
      { showLabel: false },
    ),
    relationships,
    add,
    actions,
  );
  dialog.append(content);
  document.body.append(dialog);
  dialog.showModal();
}

function closeJunctionRelationships() {
  const dialog = document.body.querySelector(".junction-relationships-popup");
  openJunctionPopupId = "";
  if (dialog?.open) dialog.close();
  else dialog?.remove();
}

function renderRelationshipJunctionHub(harness, junction) {
  const hub = document.createElement("button");
  const name = document.createElement("strong");
  const kind = document.createElement("small");
  hub.type = "button";
  hub.className = "relationship-junction-hub";
  hub.title = "Junction routing control";
  name.textContent = junction.name || "Unnamed junction";
  const relationshipCount = (junction.pathwayRelationships || []).length;
  kind.textContent = relationshipCount
    ? `${relationshipCount} pathway ${relationshipCount === 1 ? "endpoint" : "endpoints"}`
    : "Unconnected junction";
  hoverHighlight(hub, () => highlightMember(harness, "junction", junction.junctionId));
  hub.addEventListener("click", () => openJunctionRelationships(harness, junction));
  hub.addEventListener("contextmenu", (event) => {
    event.preventDefault();
    event.stopPropagation();
    openJunctionRelationships(harness, junction);
  });
  hub.append(name, kind);
  return hub;
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

function relationshipEndpointWires(harness, junction, relationship) {
  const relationships = junction.pathwayRelationships || [];
  const preceding = new Set(
    relationships.filter((item) => item.endpoint === "end").map((item) => item.pathwayId),
  );
  const following = new Set(
    relationships.filter((item) => item.endpoint === "start").map((item) => item.pathwayId),
  );
  return harness.wires.filter((wire) => wire.orderedPathwayIds.some((pathwayId, index) => {
    const nextPathwayId = wire.orderedPathwayIds[index + 1];
    if (!preceding.has(pathwayId) || !following.has(nextPathwayId)) return false;
    return relationship.endpoint === "end"
      ? relationship.pathwayId === pathwayId
      : relationship.pathwayId === nextPathwayId;
  }));
}

/**
 * Position acyclic topology components in stable layers and draw their edges.
 */
function layoutRelationshipGraph(stack, components, harness) {
  const padding = 30;
  const layerGap = 54;
  const rowGap = 40;
  let componentTop = padding;
  let maximumRight = 760 - padding;
  components.forEach((component) => {
    const rowsByDepth = new Map();
    const nodesByDepth = new Map();
    component.nodes.forEach((node) => {
      const row = rowsByDepth.get(node.depth) || 0;
      rowsByDepth.set(node.depth, row + 1);
      if (!nodesByDepth.has(node.depth)) nodesByDepth.set(node.depth, []);
      nodesByDepth.get(node.depth).push(node);
      node.row = row;
      node.width = node.element.scrollWidth || (node.kind === "pathway" ? 278 : 154);
      node.height = node.element.scrollHeight || (node.kind === "pathway" ? 92 : 76);
    });
    const rowHeight = Math.max(
      112,
      ...component.nodes.map((node) => node.height),
    );
    const componentRows = Math.max(1, ...rowsByDepth.values());
    const layerWidths = new Map(
      [...nodesByDepth].map(([depth, nodes]) => [
        depth,
        Math.max(...nodes.map((node) => node.width)),
      ]),
    );
    const layerLefts = new Map();
    let nextLeft = padding;
    [...layerWidths.keys()].sort((left, right) => left - right).forEach((depth) => {
      layerLefts.set(depth, nextLeft);
      nextLeft += layerWidths.get(depth) + layerGap;
    });
    component.nodes.forEach((node) => {
      const nodesAtDepth = rowsByDepth.get(node.depth);
      const centeredRow = node.row + (componentRows - nodesAtDepth) / 2;
      node.left = layerLefts.get(node.depth)
        + (layerWidths.get(node.depth) - node.width) / 2;
      node.top = componentTop + centeredRow * (rowHeight + rowGap);
      node.element.style.left = `${node.left}px`;
      node.element.style.top = `${node.top}px`;
    });
    maximumRight = Math.max(maximumRight, nextLeft - layerGap);
    componentTop += componentRows * (rowHeight + rowGap) + layerGap;
  });
  const canvasWidth = Math.max(760, maximumRight + padding);
  const canvasHeight = Math.max(componentTop - layerGap + padding, 260);
  const overlay = svgElement("svg", {
    class: "relationship-topology-edges",
    viewBox: `0 0 ${canvasWidth} ${canvasHeight}`,
    preserveAspectRatio: "none",
    "aria-hidden": "true",
  });
  components.forEach((component) => {
    const nodes = new Map(component.nodes.map((node) => [node.id, node]));
    component.edges.forEach((edge) => {
      const source = nodes.get(edge.sourceId);
      const target = nodes.get(edge.targetId);
      if (!source || !target) return;
      const sourceX = source.left + source.width;
      const targetX = target.left;
      const sourceY = source.top + source.height / 2;
      const targetY = target.top + target.height / 2;
      const middleX = (sourceX + targetX) / 2;
      const curve = `M ${sourceX} ${sourceY} C ${middleX} ${sourceY}, ${middleX} ${targetY}, ${targetX} ${targetY}`;
      overlay.append(svgElement("path", {
        class: "structural-trace",
        d: curve,
        "data-junction-id": edge.junction.junctionId,
        "data-pathway-id": edge.relationship.pathwayId,
        "data-endpoint": edge.relationship.endpoint,
        "data-source-x": `${sourceX}`,
        "data-source-y": `${sourceY}`,
        "data-target-x": `${targetX}`,
        "data-target-y": `${targetY}`,
      }));
      const wires = relationshipEndpointWires(
        harness,
        edge.junction,
        edge.relationship,
      );
      wires.forEach((wire) => {
        overlay.append(svgElement("path", {
          class: "wire-trace",
          d: curve,
          stroke: wire.materials?.mainColor?.hex || "#1777c8",
          "data-wire-id": wire.wireId,
        }));
      });
    });
  });
  stack.insertBefore(overlay, stack.children[0] || null);
  stack.style.width = `${canvasWidth}px`;
  stack.style.height = `${canvasHeight}px`;
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
    show(event, [
      { label: "Add pathway", action: addPathway },
      { label: "Add junction", action: addJunction },
    ]);
  });
  workspace.root.append(menu);
  return show;
}

function renderRelationshipPathwayNode(
  harness, candidate, connections, query, collapseLimit, showContextMenu,
) {
  const groups = {
    start: relationshipEndGroups(harness, candidate.pathwayId, "start", connections),
    end: relationshipEndGroups(harness, candidate.pathwayId, "end", connections),
  };
  const pathwayMatches = !query || (
    `${candidate.name} ${candidate.startName || ""} ${candidate.endName || ""}`
      .toLocaleLowerCase().includes(query)
  );
  const visibleStart = pathwayMatches
    ? groups.start : groups.start.filter((group) => group.searchable.includes(query));
  const visibleEnd = pathwayMatches
    ? groups.end : groups.end.filter((group) => group.searchable.includes(query));
  const matchingWireIds = new Set(
    [...visibleStart, ...visibleEnd].flatMap((group) => group.wires.map((wire) => wire.wireId)),
  );
  const pathwayWires = relationshipPathwayWires(harness, candidate.pathwayId)
    .filter((wire) => pathwayMatches || matchingWireIds.has(wire.wireId));
  const pathwayGroup = document.createElement("div");
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
  pathwayGroup.className = "relationship-pathway-group";
  pathwayGroup.dataset.pathwayId = candidate.pathwayId;
  pathwayGroup.style.gridTemplateColumns = [
    groups.start.length ? "210px" : "max-content",
    "32px",
    "154px",
    "32px",
    groups.end.length ? "210px" : "max-content",
  ].join(" ");
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
  return pathwayGroup;
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
    const renderedComponents = [];
    stack.className = "relationship-pathway-stack";
    stack.dataset.diagramContractVersion = RELATIONSHIP_DIAGRAM_CONTRACT_VERSION;
    stack.dataset.diagramLayout = RELATIONSHIP_DIAGRAM_LAYOUT;
    relationshipTopology(harness).forEach((component) => {
      const searchable = component.nodes.map((node) => {
        if (node.kind === "junction") return node.item.name || "";
        const wires = relationshipPathwayWires(harness, node.item.pathwayId);
        const endpointSearch = ["start", "end"].flatMap((endpoint) => (
          relationshipEndGroups(harness, node.item.pathwayId, endpoint, connections)
            .map((group) => group.searchable)
        )).join(" ");
        const wireSearch = wires.reduce((search, wire) => `${search} ${wireLabel(wire)}`, "");
        return `${node.item.name} ${node.item.startName || ""} ${node.item.endName || ""} ${wireSearch} ${endpointSearch}`;
      }).join(" ").toLocaleLowerCase();
      if (query && !searchable.includes(query)) return;
      component.nodes.forEach((node) => {
        const wrapper = document.createElement("div");
        wrapper.className = `relationship-topology-node relationship-topology-${node.kind}`;
        wrapper.dataset.nodeId = node.id;
        if (node.kind === "junction") {
          wrapper.dataset.junctionId = node.item.junctionId;
          wrapper.append(renderRelationshipJunctionHub(harness, node.item));
        } else {
          wrapper.dataset.pathwayId = node.item.pathwayId;
          wrapper.append(renderRelationshipPathwayNode(
            harness,
            node.item,
            connections,
            query,
            collapseLimit,
            showContextMenu,
          ));
        }
        node.element = wrapper;
        stack.append(wrapper);
      });
      renderedComponents.push(component);
    });
    if (!renderedComponents.length) {
      const message = emptyMessage(
        harness.pathways.length || (harness.junctions || []).length
          ? "No relationships match this filter."
          : "No pathways or junctions to display yet.",
      );
      message.className = "empty relationship-map-empty";
      workspace.stage.append(message);
      window.requestAnimationFrame(() => workspace.fit());
      return;
    }
    workspace.stage.append(stack);
    window.requestAnimationFrame(() => {
      layoutRelationshipGraph(stack, renderedComponents, harness);
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
