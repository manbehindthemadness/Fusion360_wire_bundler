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

function renderRelationshipConnector(groups, fromEndList, expanded) {
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
  details.className = "relationship-end-list";
  details.dataset.endpoint = endpoint;
  details.open = query
    ? visibleGroups.length > 0
    : override ?? groups.length <= collapseLimit;
  label.textContent = `End ${side}`;
  count.textContent = query && visibleGroups.length !== groups.length
    ? `${visibleGroups.length} of ${groups.length}`
    : `${groups.length}`;
  summary.append(label, count);
  hoverHighlight(summary, () => highlightMember(harness, "pathway_wires", pathway.pathwayId));
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
  container.className = "section-content relationship-map";
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

  const draw = () => {
    const query = filter.value.trim().toLocaleLowerCase();
    const collapseLimit = clampRelationshipCollapseLimit(collapseInput.value);
    relationshipFilters.set(harnessKey(harness), query);
    viewport.replaceChildren();
    const stack = document.createElement("div");
    let visiblePathways = 0;
    stack.className = "relationship-pathway-stack";
    harness.pathways.forEach((pathway) => {
      const startGroups = relationshipEndGroups(harness, pathway, "start", connections);
      const endGroups = relationshipEndGroups(harness, pathway, "end", connections);
      const pathwayMatches = `${pathway.name} ${pathway.startName || ""} ${pathway.endName || ""}`
        .toLocaleLowerCase().includes(query);
      const visibleStart = !query || pathwayMatches
        ? startGroups : startGroups.filter((group) => group.searchable.includes(query));
      const visibleEnd = !query || pathwayMatches
        ? endGroups : endGroups.filter((group) => group.searchable.includes(query));
      if (query && !pathwayMatches && !visibleStart.length && !visibleEnd.length) return;
      const card = document.createElement("div");
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
        visibleStart, true, startList.open,
      );
      const endConnector = renderRelationshipConnector(
        visibleEnd, false, endList.open,
      );
      card.className = "relationship-pathway-card";
      card.dataset.pathwayId = pathway.pathwayId;
      hub.type = "button";
      hub.className = "relationship-pathway-hub";
      hub.title = "Open pathway configuration";
      hubName.textContent = pathway.name || "Unnamed pathway";
      hubDirection.textContent = pathwayDirection(pathway);
      hub.append(hubName, hubDirection);
      hoverHighlight(hub, () => highlightMember(harness, "pathway_gates", pathway.pathwayId));
      hub.addEventListener("click", () => navigateToPathway(pathway.pathwayId));
      startList.redrawConnector = startConnector.redraw;
      endList.redrawConnector = endConnector.redraw;
      card.append(startList, startConnector, hub, endConnector, endList);
      stack.append(card);
      visiblePathways += 1;
    });
    if (!visiblePathways) {
      const message = emptyMessage(
        harness.pathways.length
          ? "No relationships match this filter."
          : "No pathways to display yet.",
      );
      message.className = "empty relationship-map-empty";
      viewport.append(message);
      return;
    }
    viewport.append(stack);
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

