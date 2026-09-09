function svgElement(tag, attributes = {}) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  Object.entries(attributes).forEach(([name, value]) => node.setAttribute(name, `${value}`));
  return node;
}

function truncateGraphicLabel(value, length = 22) {
  const text = value || "Unnamed";
  return text.length > length ? `${text.slice(0, length - 1)}…` : text;
}

const BLOCK_DIAGRAM_MIN_SCALE = 0.3;
const BLOCK_DIAGRAM_MAX_SCALE = 2.5;

function createBlockDiagramWorkspace(label) {
  const root = document.createElement("div");
  const toolbar = document.createElement("div");
  const zoomOut = document.createElement("button");
  const zoomValue = document.createElement("output");
  const zoomIn = document.createElement("button");
  const actualSize = document.createElement("button");
  const fit = document.createElement("button");
  const viewport = document.createElement("div");
  const stage = document.createElement("div");
  let scale = 1;
  let offsetX = 0;
  let offsetY = 0;
  let pan = null;

  root.className = "block-diagram-workspace";
  toolbar.className = "block-diagram-toolbar";
  viewport.className = "block-diagram-viewport";
  viewport.tabIndex = 0;
  viewport.setAttribute("aria-label", label);
  stage.className = "block-diagram-stage";
  zoomOut.type = "button";
  zoomOut.textContent = "−";
  zoomOut.title = "Zoom out";
  zoomIn.type = "button";
  zoomIn.textContent = "+";
  zoomIn.title = "Zoom in";
  actualSize.type = "button";
  actualSize.textContent = "100%";
  actualSize.title = "Reset zoom";
  fit.type = "button";
  fit.textContent = "Fit";
  fit.title = "Fit diagram";
  zoomValue.className = "block-diagram-zoom";

  const renderTransform = () => {
    stage.style.transform = `translate(${offsetX}px, ${offsetY}px) scale(${scale})`;
    zoomValue.value = `${Math.round(scale * 100)}%`;
    zoomValue.textContent = zoomValue.value;
  };
  const setScale = (nextScale, anchorX = viewport.clientWidth / 2,
    anchorY = viewport.clientHeight / 2) => {
    const clamped = Math.min(BLOCK_DIAGRAM_MAX_SCALE, Math.max(
      BLOCK_DIAGRAM_MIN_SCALE, nextScale,
    ));
    const localX = (anchorX - offsetX) / scale;
    const localY = (anchorY - offsetY) / scale;
    scale = clamped;
    offsetX = anchorX - localX * scale;
    offsetY = anchorY - localY * scale;
    renderTransform();
  };
  const fitDiagram = () => {
    const width = Math.max(1, stage.scrollWidth);
    const height = Math.max(1, stage.scrollHeight);
    const availableWidth = Math.max(1, viewport.clientWidth - 24);
    const availableHeight = Math.max(1, viewport.clientHeight - 24);
    scale = Math.min(1, Math.max(
      BLOCK_DIAGRAM_MIN_SCALE,
      Math.min(availableWidth / width, availableHeight / height),
    ));
    offsetX = Math.max(12, (viewport.clientWidth - width * scale) / 2);
    offsetY = Math.max(12, (viewport.clientHeight - height * scale) / 2);
    renderTransform();
  };
  const interactiveTarget = (target) => {
    let node = target;
    while (node && node !== viewport) {
      if (["BUTTON", "INPUT", "SELECT", "SUMMARY", "A"].includes(
        String(node.tagName || node.tag || "").toUpperCase(),
      )) return true;
      const classes = String(node.getAttribute?.("class") || node.className || "");
      if (/relationship-(node|end-entry|pathway-hub)|wire-relationship-node/.test(classes)) {
        return true;
      }
      node = node.parentElement;
    }
    return false;
  };

  zoomOut.addEventListener("click", () => setScale(scale / 1.2));
  zoomIn.addEventListener("click", () => setScale(scale * 1.2));
  actualSize.addEventListener("click", () => {
    scale = 1;
    offsetX = 12;
    offsetY = 12;
    renderTransform();
  });
  fit.addEventListener("click", fitDiagram);
  viewport.addEventListener("wheel", (event) => {
    event.preventDefault();
    const bounds = viewport.getBoundingClientRect();
    setScale(
      scale * (event.deltaY < 0 ? 1.12 : 1 / 1.12),
      event.clientX - bounds.left,
      event.clientY - bounds.top,
    );
  }, { passive: false });
  viewport.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || interactiveTarget(event.target)) return;
    pan = { pointerId: event.pointerId, x: event.clientX, y: event.clientY,
      offsetX, offsetY };
    viewport.classList.add("panning");
    viewport.setPointerCapture?.(event.pointerId);
  });
  viewport.addEventListener("pointermove", (event) => {
    if (!pan || pan.pointerId !== event.pointerId) return;
    offsetX = pan.offsetX + event.clientX - pan.x;
    offsetY = pan.offsetY + event.clientY - pan.y;
    renderTransform();
  });
  const stopPan = (event) => {
    if (!pan || pan.pointerId !== event.pointerId) return;
    viewport.releasePointerCapture?.(event.pointerId);
    pan = null;
    viewport.classList.remove?.("panning");
  };
  viewport.addEventListener("pointerup", stopPan);
  viewport.addEventListener("pointercancel", stopPan);

  toolbar.append(zoomOut, zoomValue, zoomIn, actualSize, fit);
  viewport.append(stage);
  root.append(toolbar, viewport);
  renderTransform();
  return { root, stage, fit: fitDiagram, zoomValue, viewport };
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
  const workspace = createBlockDiagramWorkspace(
    `${wireLabel(wire)} zoomable route diagram`,
  );
  workspace.stage.append(svg);
  container.append(workspace.root);
  window.requestAnimationFrame(() => workspace.fit());
  return container;
}
