function svgElement(tag, attributes = {}) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  Object.entries(attributes).forEach(([name, value]) => node.setAttribute(name, `${value}`));
  return node;
}

function truncateGraphicLabel(value, length = 22) {
  const text = value || "Unnamed";
  return text.length > length ? `${text.slice(0, length - 1)}…` : text;
}

function navigateToWire(wireId) {
  const section = ui.editor.querySelector('[data-section="wire-routes"]');
  const card = ui.editor.querySelector(`[data-wire-id="${wireId}"]`);
  if (section) {
    section.open = true;
    expandedSections.add("wire-routes");
  }
  if (!card) return;
  const details = card.querySelector(".wire-details");
  if (details) details.hidden = false;
  card.scrollIntoView({ behavior: "smooth", block: "center" });
}

function navigateToPathway(pathwayId) {
  const section = ui.editor.querySelector('[data-section="pathways"]');
  const pathway = ui.editor.querySelector(`[data-section="pathway:${pathwayId}"]`);
  if (section) {
    section.open = true;
    expandedSections.add("pathways");
  }
  if (!pathway) return;
  pathway.open = true;
  expandedSections.add(`pathway:${pathwayId}`);
  writeSession("wireBundler.expandedSections", JSON.stringify([...expandedSections]));
  pathway.scrollIntoView({ behavior: "smooth", block: "center" });
}

function renderWireRelationshipGraphic(
  harness, wire, connections, pathways, endAEditor, endBEditor,
) {
  const container = document.createElement("div");
  const startConnection = connections.get(wire.startConnectionId);
  const endConnection = connections.get(wire.endConnectionId);
  const nodeItems = [
    {
      kind: "connection",
      kindLabel: "End A",
      endpoint: "start",
      connection: startConnection,
      connectionId: wire.startConnectionId,
      editor: endAEditor,
      otherEditor: endBEditor,
      label: wire.startEndName
        || startConnection?.name
        || "+ Add End A",
      missing: !startConnection?.hasLinkedGeometry,
    },
    ...wire.orderedPathwayIds.map((pathwayId) => {
      const pathway = pathways.get(pathwayId);
      return {
        kind: "pathway",
        kindLabel: "Pathway",
        pathwayId,
        label: pathway?.name || "Missing pathway",
        missing: !pathway,
      };
    }),
    {
      kind: "connection",
      kindLabel: "End B",
      endpoint: "end",
      connection: endConnection,
      connectionId: wire.endConnectionId,
      editor: endBEditor,
      otherEditor: endAEditor,
      label: wire.endEndName
        || endConnection?.name
        || "+ Add End B",
      missing: !endConnection?.hasLinkedGeometry,
    },
  ];
  const width = Math.max(560, 100 + (nodeItems.length - 1) * 180);
  const y = 44;
  const startX = 70;
  const step = (width - 140) / Math.max(1, nodeItems.length - 1);
  const points = nodeItems.map((_item, index) => startX + index * step);
  const svg = svgElement("svg", {
    class: "relationship-map-svg",
    width,
    height: 88,
    viewBox: `0 0 ${width} 88`,
    role: "group",
    "aria-label": `${wireLabel(wire)} relationship route`,
  });
  const routeGroup = svgElement("g", {
    class: "wire-relationship-route",
    "aria-label": `Highlight ${wireLabel(wire)}`,
  });
  for (let index = 0; index < points.length - 1; index += 1) {
    routeGroup.append(svgElement("line", {
      class: "relationship-link",
      x1: points[index], y1: y, x2: points[index + 1], y2: y,
      stroke: wire.materials?.mainColor?.hex || "#1777c8", "stroke-width": 9,
    }));
    const stripes = (wire.materials?.stripes || []).slice(0, 3);
    stripes.forEach((stripe, stripeIndex) => {
      const stripeOffset = centeredStripeOffset(stripeIndex, stripes.length, 2.5);
      routeGroup.append(svgElement("line", {
        class: "relationship-link",
        x1: points[index], y1: y + stripeOffset,
        x2: points[index + 1], y2: y + stripeOffset,
        stroke: stripe.color?.hex || "#fff", "stroke-width": 1.7,
        "stroke-dasharray": stripe.pattern === "solid" ? "none" : "8 5",
      }));
    });
  }
  hoverHighlight(routeGroup, () => highlightMember(harness, "preview_wire", wire.wireId));
  svg.append(routeGroup);
  const nodeGroups = new Map();
  const activateEnd = (item) => {
    if (!item.connection) {
      mutate("edit_end_members", {
        harnessId: harness.harnessId,
        wireId: wire.wireId,
        endpoint: item.endpoint,
        editAction: "add",
        expectedMembers: 0,
      }, `Select ${item.kindLabel} profiles…`);
      return;
    }
    const willOpen = item.editor.hidden;
    item.editor.hidden = !willOpen;
    item.otherEditor.hidden = true;
    if (willOpen) expandedSections.add(item.editor.dataset.stateKey);
    else expandedSections.delete(item.editor.dataset.stateKey);
    expandedSections.delete(item.otherEditor.dataset.stateKey);
    writeSession("wireBundler.expandedSections", JSON.stringify([...expandedSections]));
    nodeGroups.get(item.endpoint)?.setAttribute("aria-expanded", `${willOpen}`);
    const otherEndpoint = item.endpoint === "start" ? "end" : "start";
    nodeGroups.get(otherEndpoint)?.setAttribute("aria-expanded", "false");
  };
  nodeItems.forEach((item, index) => {
    const x = points[index];
    const group = svgElement("g", {
      class: `wire-relationship-node ${item.kind}${item.missing ? " missing" : ""}`,
      tabindex: "0",
      role: "button",
      "aria-label": item.kind === "pathway"
        ? `Open pathway ${item.label}`
        : `Configure ${item.kindLabel}: ${item.label}`,
    });
    const shape = item.kind === "pathway"
      ? svgElement("rect", {
        class: `relationship-node pathway${item.missing ? " missing" : ""}`,
        x: x - 75, y: y - 18, width: 150, height: 36, rx: 18,
      })
      : svgElement("rect", {
        class: `relationship-node connection${item.missing ? " missing" : ""}`,
        x: x - 52, y: y - 16, width: 104, height: 32, rx: 7,
      });
    const label = svgElement("text", { class: "relationship-node-label", x, y: y + 3 });
    const kind = svgElement("text", { class: "relationship-node-kind", x, y: y - 22 });
    const title = svgElement("title");
    label.textContent = truncateGraphicLabel(item.label, item.kind === "pathway" ? 21 : 18);
    kind.textContent = item.kindLabel;
    title.textContent = item.kind === "pathway"
      ? `Open pathway configuration: ${item.label}`
      : `Configure ${item.kindLabel}: ${item.label}`;
    shape.append(title);
    group.append(shape, label, kind);
    if (item.kind === "pathway") {
      group.dataset.pathwayId = item.pathwayId;
      hoverHighlight(group, () => highlightMember(
        harness, "pathway_gates", item.pathwayId,
      ));
      group.addEventListener("click", () => navigateToPathway(item.pathwayId));
    } else {
      group.dataset.editorId = item.editor.id;
      group.dataset.endpoint = item.endpoint;
      group.setAttribute("aria-controls", item.editor.id);
      group.setAttribute("aria-expanded", `${!item.editor.hidden}`);
      nodeGroups.set(item.endpoint, group);
      if (item.connection) {
        hoverHighlight(group, () => highlightMember(
          harness, "connection", item.connectionId,
        ));
      }
      group.addEventListener("click", () => activateEnd(item));
    }
    group.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      if (item.kind === "pathway") navigateToPathway(item.pathwayId);
      else activateEnd(item);
    });
    svg.append(group);
  });
  container.className = "wire-relationship-graphic";
  container.append(svg);
  return container;
}

