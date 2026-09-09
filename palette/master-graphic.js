const RELATIONSHIP_DIAGRAM_CONTRACT_VERSION = "1";
const RELATIONSHIP_DIAGRAM_LAYOUT = "flexible-layered-graph";

function relationshipEndGroups(harness, pathway, endpoint, connections) {
  const connectionField = endpoint === "start" ? "startConnectionId" : "endConnectionId";
  const endpointNameField = endpoint === "start" ? "startEndName" : "endEndName";
  const groups = new Map();
  harness.wires
    .filter((wire) => wire.orderedPathwayIds.includes(pathway.pathwayId))
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

function renderRelationshipConnector(groups, fromEndList, expanded, showPlaceholder = false) {
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
    if (!groups.length && showPlaceholder) {
      svg.append(svgElement("path", {
        class: "placeholder-trace",
        d: curvePath(50, 50),
      }));
      return;
    }
    if (!groups.length) return;
    if (!isExpanded) {
      svg.append(svgElement("path", { class: "aggregate-trace", d: curvePath(50, 50) }));
      return;
    }
    const wireCount = groups.reduce((count, group) => count + group.wires.length, 0);
    let wireIndex = 0;
    groups.forEach((group, groupIndex) => {
      const groupY = 20 + 75 * ((groupIndex + 0.5) / groups.length);
      const listSpacing = Math.min(6, 14 / Math.max(1, group.wires.length - 1));
      const hubSpacing = Math.min(2.5, 14 / Math.max(1, wireCount - 1));
      group.wires.forEach((wire, groupWireIndex) => {
        const listY = groupY + (groupWireIndex - (group.wires.length - 1) / 2) * listSpacing;
        const hubY = 50 + (wireIndex - (wireCount - 1) / 2) * hubSpacing;
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
        wireIndex += 1;
      });
    });
  };
  svg.redraw = redraw;
  redraw(expanded);
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
    if (details.redrawDiagram) details.redrawDiagram();
  });
  details.append(summary, items);
  return details;
}

/**
 * Draw continuous junction edges against the final rendered node bounds.
 *
 * The overlay and nodes share the same transformed stack, so the measured local
 * coordinates remain exact while the workspace is zoomed or panned.
 */
function drawRelationshipJunctionOverlay(stack, pathwayHubs, pathwayEnds, junctionBindings) {
  const previousOverlay = Array.from(stack.children).find(
    (child) => child.className === "relationship-junction-overlay",
  );
  previousOverlay?.remove();
  if (!junctionBindings.length) return;
  const stackRect = stack.getBoundingClientRect();
  const width = Math.max(1, stack.scrollWidth);
  const height = Math.max(1, stack.scrollHeight);
  const scaleX = stackRect.width > 0 ? width / stackRect.width : 1;
  const scaleY = stackRect.height > 0 ? height / stackRect.height : 1;
  const anchor = (node, verticalSide) => {
    const rect = node.getBoundingClientRect();
    return {
      x: (rect.left - stackRect.left + rect.width / 2) * scaleX,
      y: (rect[verticalSide] - stackRect.top) * scaleY,
    };
  };
  const overlay = svgElement("svg", {
    class: "relationship-junction-overlay",
    width,
    height,
    viewBox: `0 0 ${width} ${height}`,
    preserveAspectRatio: "none",
    "aria-hidden": "true",
  });
  let connectorCount = 0;
  junctionBindings.forEach(({ junction, node, attachments }) => {
    const parent = pathwayHubs.get(junction.pathwayId);
    if (!parent) return;
    const parentTop = anchor(parent, "top");
    const parentBottom = anchor(parent, "bottom");
    const junctionTop = anchor(node, "top");
    const junctionBottom = anchor(node, "bottom");
    const junctionIsAbove = junctionTop.y < parentTop.y;
    const parentStart = junctionIsAbove ? parentTop : parentBottom;
    const junctionEnd = junctionIsAbove ? junctionBottom : junctionTop;
    overlay.append(svgElement("path", {
      class: "relationship-junction-edge parent",
      d: `M ${parentStart.x} ${parentStart.y} L ${junctionEnd.x} ${junctionEnd.y}`,
      "data-parent-pathway-id": junction.pathwayId,
      "data-parent-side": junctionIsAbove ? "top" : "bottom",
      "data-junction-id": junction.nodeId,
    }));
    connectorCount += 1;
    attachments.forEach((attachment) => {
      const target = pathwayEnds.get(`${attachment.pathwayId}:${attachment.pathwayEnd}`);
      if (!target) return;
      const targetTop = anchor(target, "top");
      const targetBottom = anchor(target, "bottom");
      const targetIsAbove = targetTop.y < junctionTop.y;
      const junctionStart = targetIsAbove ? junctionTop : junctionBottom;
      const targetEnd = targetIsAbove ? targetBottom : targetTop;
      const middleY = junctionStart.y + (targetEnd.y - junctionStart.y) / 2;
      overlay.append(svgElement("path", {
        class: "relationship-junction-edge target",
        d: `M ${junctionStart.x} ${junctionStart.y} C ${junctionStart.x} ${middleY}, ${targetEnd.x} ${middleY}, ${targetEnd.x} ${targetEnd.y}`,
        "data-junction-id": junction.nodeId,
        "data-target-pathway-id": attachment.pathwayId,
        "data-target-pathway-end": attachment.pathwayEnd,
        "data-target-side": targetIsAbove ? "bottom" : "top",
      }));
      connectorCount += 1;
    });
  });
  overlay.dataset.connectorCount = `${connectorCount}`;
  overlay.dataset.maxEndpointGap = "0";
  stack.prepend(overlay);
}

/**
 * Position pathway groups and junctions as a layered graph on a free-size canvas.
 *
 * Pathway ordering supplies a stable top/bottom preference while topology assigns
 * related pathways to adjacent layers. Independent nodes share a layer horizontally.
 */
function layoutRelationshipGraph(stack, harness, pathwayGroups, junctionBindings) {
  const pathwayIndex = new Map(
    harness.pathways.map((pathway, index) => [pathway.pathwayId, index]),
  );
  const junctionById = new Map(
    (harness.topology?.nodes || []).filter(
      (node) => node.kind === "junction",
    ).map((junction) => [junction.nodeId, junction]),
  );
  const layers = new Map(harness.pathways.map((pathway) => [pathway.pathwayId, 0]));
  for (let pass = 0; pass < harness.pathways.length; pass += 1) {
    let changed = false;
    (harness.topology?.junctionAttachments || []).forEach((attachment) => {
      const junction = junctionById.get(attachment.junctionId);
      if (!junction || junction.pathwayId === attachment.pathwayId) return;
      const parentIndex = pathwayIndex.get(junction.pathwayId) ?? 0;
      const targetIndex = pathwayIndex.get(attachment.pathwayId) ?? parentIndex + 1;
      const direction = targetIndex < parentIndex ? -1 : 1;
      const candidate = (layers.get(junction.pathwayId) || 0) + direction;
      const current = layers.get(attachment.pathwayId) || 0;
      if ((direction > 0 && candidate > current) || (direction < 0 && candidate < current)) {
        layers.set(attachment.pathwayId, candidate);
        changed = true;
      }
    });
    if (!changed) break;
  }
  const horizontalGap = 70;
  const verticalGap = 180;
  const padding = 30;
  const measured = new Map();
  pathwayGroups.forEach((group, pathwayId) => {
    measured.set(pathwayId, {
      group,
      width: Math.max(760, group.scrollWidth),
      height: Math.max(92, group.scrollHeight),
      layer: layers.get(pathwayId) || 0,
    });
  });
  const layerValues = [...new Set([...measured.values()].map((item) => item.layer))]
    .sort((left, right) => left - right);
  const rows = layerValues.map((layer) => {
    const items = [...measured.values()].filter((item) => item.layer === layer);
    const width = items.reduce((total, item) => total + item.width, 0)
      + Math.max(0, items.length - 1) * horizontalGap;
    const height = Math.max(...items.map((item) => item.height));
    return { layer, items, width, height };
  });
  const canvasWidth = Math.max(760, ...rows.map((row) => row.width)) + padding * 2;
  let nextY = padding;
  rows.forEach((row) => {
    let nextX = (canvasWidth - row.width) / 2;
    row.items.forEach((item) => {
      item.left = nextX;
      item.top = nextY;
      item.group.style.left = `${nextX}px`;
      item.group.style.top = `${nextY}px`;
      nextX += item.width + horizontalGap;
    });
    nextY += row.height + verticalGap;
  });
  const junctionSiblingGroups = new Map();
  junctionBindings.forEach((binding) => {
    const parent = measured.get(binding.junction.pathwayId);
    const targetLayers = binding.attachments.map(
      (attachment) => measured.get(attachment.pathwayId)?.layer,
    ).filter((layer) => Number.isFinite(layer));
    const direction = targetLayers.length
      && targetLayers.reduce((total, layer) => total + layer, 0) / targetLayers.length
        < (parent?.layer || 0) ? -1 : 1;
    binding.direction = direction;
    const key = `${binding.junction.pathwayId}:${direction}`;
    if (!junctionSiblingGroups.has(key)) junctionSiblingGroups.set(key, []);
    junctionSiblingGroups.get(key).push(binding);
  });
  junctionSiblingGroups.forEach((bindings) => {
    bindings.forEach((binding, index) => {
      const parent = measured.get(binding.junction.pathwayId);
      if (!parent) return;
      const nodeWidth = Math.max(130, binding.node.scrollWidth);
      const nodeHeight = Math.max(34, binding.node.scrollHeight);
      const targetItems = binding.attachments.map(
        (attachment) => measured.get(attachment.pathwayId),
      ).filter(Boolean);
      const siblingOffset = (index - (bindings.length - 1) / 2) * (nodeWidth + 18);
      const desiredCenter = parent.left + parent.width / 2 + siblingOffset;
      const left = Math.max(padding, Math.min(canvasWidth - padding - nodeWidth,
        desiredCenter - nodeWidth / 2));
      const nearestTarget = targetItems.sort((leftItem, rightItem) => (
        Math.abs(leftItem.top - parent.top) - Math.abs(rightItem.top - parent.top)
      ))[0];
      const top = binding.direction < 0 && nearestTarget
        ? nearestTarget.top + nearestTarget.height
          + (parent.top - nearestTarget.top - nearestTarget.height - nodeHeight) / 2
        : parent.top + parent.height
          + ((nearestTarget?.top ?? parent.top + parent.height + verticalGap)
            - parent.top - parent.height - nodeHeight) / 2;
      binding.node.parentElement.style.left = `${left}px`;
      binding.node.parentElement.style.top = `${top}px`;
    });
  });
  const canvasHeight = Math.max(nextY - verticalGap + padding, 260);
  stack.style.width = `${canvasWidth}px`;
  stack.style.height = `${canvasHeight}px`;
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
  const viewport = document.createElement("div");
  const workspace = createBlockDiagramWorkspace("Zoomable master relationship diagram");
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
  viewport.className = "relationship-map-viewport";
  viewport.append(workspace.root);

  const draw = () => {
    const query = filter.value.trim().toLocaleLowerCase();
    const collapseLimit = clampRelationshipCollapseLimit(collapseInput.value);
    relationshipFilters.set(harnessKey(harness), query);
    workspace.stage.replaceChildren();
    const stack = document.createElement("div");
    const pathwayHubs = new Map();
    const pathwayEnds = new Map();
    const pathwayGroups = new Map();
    const junctionBindings = [];
    const junctionTargetKeys = new Set(
      (harness.topology?.junctionAttachments || []).map(
        (attachment) => `${attachment.pathwayId}:${attachment.pathwayEnd}`,
      ),
    );
    let visiblePathways = 0;
    stack.className = "relationship-pathway-stack";
    stack.dataset.diagramContractVersion = RELATIONSHIP_DIAGRAM_CONTRACT_VERSION;
    stack.dataset.diagramLayout = RELATIONSHIP_DIAGRAM_LAYOUT;
    harness.pathways.forEach((pathway) => {
      const junctions = (harness.topology?.nodes || []).filter(
        (node) => node.kind === "junction" && node.pathwayId === pathway.pathwayId,
      );
      const startGroups = relationshipEndGroups(harness, pathway, "start", connections);
      const endGroups = relationshipEndGroups(harness, pathway, "end", connections);
      const pathwayMatches = `${pathway.name} ${pathway.startName || ""} ${pathway.endName || ""}`
        .toLocaleLowerCase().includes(query);
      const visibleStart = !query || pathwayMatches
        ? startGroups : startGroups.filter((group) => group.searchable.includes(query));
      const visibleEnd = !query || pathwayMatches
        ? endGroups : endGroups.filter((group) => group.searchable.includes(query));
      if (query && !pathwayMatches && !visibleStart.length && !visibleEnd.length) return;
      const pathwayGroup = document.createElement("div");
      const hub = document.createElement("button");
      const hubName = document.createElement("strong");
      const hubDirection = document.createElement("small");
      const startList = renderRelationshipEndList(
        harness, pathway, "start", startGroups, visibleStart, query, collapseLimit,
      );
      const endList = renderRelationshipEndList(
        harness, pathway, "end", endGroups, visibleEnd, query, collapseLimit,
      );
      const startConnector = renderRelationshipConnector(
        visibleStart, true, startList.open, startGroups.length === 0,
      );
      const endConnector = renderRelationshipConnector(
        visibleEnd, false, endList.open, endGroups.length === 0,
      );
      pathwayGroup.className = "relationship-pathway-group";
      pathwayGroup.dataset.pathwayId = pathway.pathwayId;
      const pathwayNodeWidth = Math.max(170, junctions.length * 148);
      pathwayGroup.style.gridTemplateColumns = `minmax(210px, 1fr) 54px ${pathwayNodeWidth}px 54px minmax(210px, 1fr)`;
      pathwayGroups.set(pathway.pathwayId, pathwayGroup);
      if (junctionTargetKeys.has(`${pathway.pathwayId}:a`)) {
        startList.classList.add("junction-target");
      }
      if (junctionTargetKeys.has(`${pathway.pathwayId}:b`)) {
        endList.classList.add("junction-target");
      }
      hub.type = "button";
      hub.className = "relationship-pathway-hub";
      hub.title = "Open pathway configuration";
      hubName.textContent = pathway.name || "Unnamed pathway";
      hubDirection.textContent = pathwayDirection(pathway);
      hub.append(hubName, hubDirection);
      pathwayHubs.set(pathway.pathwayId, hub);
      pathwayEnds.set(`${pathway.pathwayId}:a`, startList);
      pathwayEnds.set(`${pathway.pathwayId}:b`, endList);
      hoverHighlight(hub, () => highlightMember(harness, "pathway_gates", pathway.pathwayId));
      hub.addEventListener("click", () => navigateToPathway(pathway.pathwayId));
      startList.redrawConnector = startConnector.redraw;
      endList.redrawConnector = endConnector.redraw;
      pathwayGroup.append(startList, startConnector, hub, endConnector, endList);
      stack.append(pathwayGroup);
      junctions.forEach((junction, index) => {
        const chain = document.createElement("div");
        const junctionNode = document.createElement("button");
        chain.className = "relationship-junction-chain";
        chain.dataset.parentPathwayId = pathway.pathwayId;
        junctionNode.type = "button";
        junctionNode.className = "relationship-junction-node";
        junctionNode.textContent = junction.name || `Junction ${index + 1}`;
        junctionNode.addEventListener("click", () => navigateToJunction(junction.nodeId));
        chain.append(junctionNode);
        const attachments = (harness.topology?.junctionAttachments || []).filter(
          (item) => item.junctionId === junction.nodeId,
        );
        junctionBindings.push({ junction, node: junctionNode, attachments });
        stack.append(chain);
      });
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
    const redrawDiagram = () => {
      layoutRelationshipGraph(stack, harness, pathwayGroups, junctionBindings);
      drawRelationshipJunctionOverlay(stack, pathwayHubs, pathwayEnds, junctionBindings);
    };
    pathwayEnds.forEach((end) => {
      end.redrawDiagram = () => window.requestAnimationFrame(redrawDiagram);
    });
    window.requestAnimationFrame(() => {
      redrawDiagram();
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
  container.append(toolbar, settings, viewport);
  draw();
  return container;
}
