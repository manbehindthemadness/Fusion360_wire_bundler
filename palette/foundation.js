const ui = {
  back: document.getElementById("back"),
  addWires: document.getElementById("add-wires"),
  previewRoutes: document.getElementById("preview-routes"),
  clearPreview: document.getElementById("clear-preview"),
  generateSolids: document.getElementById("generate-solids"),
  clearSolids: document.getElementById("clear-solids"),
  defaults: document.getElementById("interpolation-defaults"),
  materialDefaults: document.getElementById("material-defaults"),
  create: document.getElementById("create"),
  createFromEditor: document.getElementById("create-from-editor"),
  editor: document.getElementById("editor"),
  editorView: document.getElementById("editor-view"),
  harnessFilter: document.getElementById("harness-filter"),
  libraryView: document.getElementById("library-view"),
  list: document.getElementById("harnesses"),
  notice: document.getElementById("notice"),
  developerMode: document.getElementById("developer-mode"),
  developerConsent: document.getElementById("developer-consent"),
  developerConsentForm: document.getElementById("developer-consent-form"),
  developerConsentAgreement: document.getElementById("developer-consent-agreement"),
  developerConsentCancel: document.getElementById("developer-consent-cancel"),
  developerConsentEnable: document.getElementById("developer-consent-enable"),
  verboseDiagnostics: document.getElementById("verbose-diagnostics"),
  refresh: document.getElementById("refresh"),
};

function readSession(key) {
  try { return window.sessionStorage.getItem(key); }
  catch (_error) { return null; }
}

function writeSession(key, value) {
  try { window.sessionStorage.setItem(key, value); }
  catch (_error) { /* Palette storage is an optional convenience. */ }
}

function removeSession(key) {
  try { window.sessionStorage.removeItem(key); }
  catch (_error) { /* Palette storage is an optional convenience. */ }
}

function readPreference(key) {
  try { return window.localStorage.getItem(key); }
  catch (_error) { return null; }
}

function writePreference(key, value) {
  try { window.localStorage.setItem(key, value); }
  catch (_error) { /* Palette storage is an optional convenience. */ }
}

let currentState = { harnesses: [], notice: "" };
let selectedHarnessKey = readSession("wireBundler.selectedHarness") || "";
let openPathwayPopupId = "";
let openJunctionPopupId = "";
const routeFilters = new Map();
const relationshipFilters = new Map();
const relationshipEndListOverrides = new Map();
const DEFAULT_RELATIONSHIP_COLLAPSE_LIMIT = 7;
const MIN_RELATIONSHIP_COLLAPSE_LIMIT = 1;
const MAX_RELATIONSHIP_COLLAPSE_LIMIT = 999;
const DEVELOPER_MODE_DISCLOSURE_VERSION = "1";
const DEVELOPER_MODE_STORAGE_KEY = "wireBundler.developerMode";
const DEVELOPER_CONSENT_STORAGE_KEY = "wireBundler.developerConsentVersion";
const storedExpandedSections = readSession("wireBundler.expandedSections");
let hasStoredExpansionState = storedExpandedSections !== null;
let expandedSectionIds = [];
try {
  expandedSectionIds = JSON.parse(storedExpandedSections || "[]");
  if (!Array.isArray(expandedSectionIds)) expandedSectionIds = [];
} catch (_error) {
  expandedSectionIds = [];
}
const expandedSections = new Set(expandedSectionIds);
let developerModeEnabled = readPreference(DEVELOPER_MODE_STORAGE_KEY) === "true"
  && readPreference(DEVELOPER_CONSENT_STORAGE_KEY) === DEVELOPER_MODE_DISCLOSURE_VERSION;
if (!developerModeEnabled) writePreference(DEVELOPER_MODE_STORAGE_KEY, "false");
ui.developerMode.checked = developerModeEnabled;
ui.verboseDiagnostics.checked = developerModeEnabled
  && readPreference("wireBundler.verboseDiagnostics") === "true";
ui.verboseDiagnostics.disabled = !developerModeEnabled;
const storedNoticeHeight = Number(readSession("wireBundler.noticeHeight"));
if (Number.isFinite(storedNoticeHeight) && storedNoticeHeight >= 72) {
  ui.notice.style.height = `${Math.min(600, storedNoticeHeight)}px`;
}

function harnessKey(harness) {
  return harness.harnessId || `component:${harness.componentName}`;
}

function relationshipCollapseStorageKey(harness) {
  return `wireBundler.relationshipCollapseLimit:${harnessKey(harness)}`;
}

function clampRelationshipCollapseLimit(value) {
  const parsed = Math.round(Number(value));
  if (!Number.isFinite(parsed)) return DEFAULT_RELATIONSHIP_COLLAPSE_LIMIT;
  return Math.min(
    MAX_RELATIONSHIP_COLLAPSE_LIMIT,
    Math.max(MIN_RELATIONSHIP_COLLAPSE_LIMIT, parsed),
  );
}

function relationshipCollapseLimit(harness) {
  const stored = readSession(relationshipCollapseStorageKey(harness));
  return stored === null
    ? DEFAULT_RELATIONSHIP_COLLAPSE_LIMIT
    : clampRelationshipCollapseLimit(stored);
}

function emptyMessage(text) {
  const paragraph = document.createElement("p");
  paragraph.className = "empty";
  paragraph.textContent = text;
  return paragraph;
}

function statusBadge(harness) {
  const badge = document.createElement("span");
  badge.className = "status";
  badge.dataset.status = harness.status;
  badge.textContent = harness.status;
  return badge;
}

function renderLibrary() {
  const query = ui.harnessFilter.value.trim().toLocaleLowerCase();
  const harnesses = currentState.harnesses.filter((harness) => {
    const searchable = `${harness.componentName} ${harness.routingMode || ""} ${harness.status}`;
    return searchable.toLocaleLowerCase().includes(query);
  });
  ui.list.replaceChildren();
  if (!harnesses.length) {
    const message = currentState.harnesses.length
      ? "No harnesses match this filter."
      : "No procedural harnesses in this design.";
    ui.list.append(emptyMessage(message));
    return;
  }
  harnesses.forEach((harness) => {
    const button = document.createElement("button");
    const name = document.createElement("strong");
    const summary = document.createElement("span");
    button.type = "button";
    button.className = "harness-card";
    button.dataset.status = harness.status;
    name.textContent = harness.componentName;
    summary.className = "summary";
    summary.textContent = harness.status === "damaged"
      ? "Metadata could not be loaded"
      : `${harness.routingMode} · ${harness.wires.length} wires`;
    button.append(name, statusBadge(harness), summary);
    button.addEventListener("click", () => openHarness(harnessKey(harness)));
    ui.list.append(button);
  });
}

function editorSection(id, title, count, content, openByDefault = false) {
  const section = document.createElement("details");
  const summary = document.createElement("summary");
  const label = document.createElement("span");
  const counter = document.createElement("span");
  section.dataset.section = id;
  section.open = expandedSections.has(id) || (openByDefault && !hasStoredExpansionState);
  label.textContent = title;
  counter.className = "count";
  counter.textContent = count;
  summary.append(label, counter);
  section.append(summary, content);
  section.addEventListener("toggle", () => {
    hasStoredExpansionState = true;
    if (section.open) expandedSections.add(id);
    else expandedSections.delete(id);
    writeSession(
      "wireBundler.expandedSections",
      JSON.stringify([...expandedSections]),
    );
  });
  return section;
}

function nestedSection(id, title, count, content, onHover) {
  const section = editorSection(id, title, count, content);
  section.className = "nested-details";
  if (onHover) hoverHighlight(section.children[0], onHover);
  return section;
}

function actionButton(label, title, handler, disabled = false, danger = false) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `icon-button${danger ? " danger" : ""}`;
  button.textContent = label;
  button.title = title;
  button.setAttribute("aria-label", title);
  button.disabled = disabled;
  button.addEventListener("click", handler);
  return button;
}

function optionsButton(title, handler, disabled = false) {
  const button = actionButton("Options", title, handler, disabled);
  button.className = "icon-button options-button";
  return button;
}

function hoverHighlight(node, onHover) {
  node.addEventListener("mouseenter", onHover);
  node.addEventListener("mouseleave", () => send("clear_highlight").catch(() => {}));
}

function memberRow(label, onReveal, actions = [], missing = false, clickToActivate = false) {
  const row = document.createElement("div");
  const reference = document.createElement("button");
  const actionContainer = document.createElement("div");
  row.className = `member-row${missing ? " missing" : ""}`;
  reference.type = "button";
  reference.className = "member-reference";
  reference.textContent = missing ? `${label} (geometry missing)` : label;
  reference.title = "Show linked sketch profile in Fusion";
  if (clickToActivate) reference.addEventListener("click", onReveal);
  else hoverHighlight(row, onReveal);
  actionContainer.className = "member-actions";
  actionContainer.append(...actions);
  row.append(reference, actionContainer);
  return row;
}

function nameField(
  label, value, action, payload, placeholder = "Optional name", { showLabel = true } = {},
) {
  const field = document.createElement("label");
  const input = document.createElement("input");
  if (showLabel) field.textContent = label;
  input.type = "text";
  input.className = "filter";
  input.value = value || "";
  input.placeholder = placeholder;
  input.setAttribute("aria-label", label);
  input.addEventListener("change", () => mutate(
    action, { ...payload, name: input.value }, "Saving name…",
  ));
  field.append(input);
  return field;
}

function wireLabel(wire) {
  return wire.displayName || `Wire #${wire.wireNumber}`;
}

function pathwayDirection(pathway) {
  const start = pathway?.startName || "A";
  const end = pathway?.endName || "B";
  return `${start} → ${end}`;
}

function centeredStripeOffset(index, count, spacing) {
  return (index - (count - 1) / 2) * spacing;
}

function createOptionsDialog(className) {
  const dialog = document.createElement("dialog");
  const form = document.createElement("form");
  const heading = document.createElement("h2");
  const note = document.createElement("p");
  const error = document.createElement("p");
  const actions = document.createElement("div");
  const cancel = document.createElement("button");
  const save = document.createElement("button");
  dialog.className = className;
  error.setAttribute("role", "alert");
  error.style.color = "var(--danger)";
  actions.className = "actions";
  cancel.type = "button";
  cancel.className = "button";
  cancel.textContent = "Cancel";
  cancel.addEventListener("click", () => {
    if (typeof dialog.cancelOptions === "function") return dialog.cancelOptions();
    dialog.close();
    return undefined;
  });
  dialog.addEventListener("cancel", (event) => {
    if (typeof dialog.cancelOptions !== "function") return;
    event.preventDefault();
    void dialog.cancelOptions();
  });
  save.type = "submit";
  save.className = "button primary";
  save.textContent = "Save";
  return { dialog, form, heading, note, error, actions, cancel, save };
}

function renderPathways(harness, selectedPathwayId = null) {
  const container = document.createElement("div");
  const controls = new Map(
    harness.controls.map((control) => [control.controlId, control]),
  );
  const connections = new Map(
    harness.connections.map((connection) => [connection.connectionId, connection]),
  );
  const pathways = new Map(
    harness.pathways.map((pathway) => [pathway.pathwayId, pathway]),
  );
  container.className = "section-content";
  if (!harness.pathways.length) {
    container.append(emptyMessage("No pathways defined yet."));
    return container;
  }
  const renderedPathways = harness.pathways.filter(
    (pathway) => !selectedPathwayId || pathway.pathwayId === selectedPathwayId,
  );
  renderedPathways.forEach((pathway) => {
    const pathwayContent = document.createElement("div");
    const gateContent = document.createElement("div");
    const sequence = document.createElement("div");
    const occupancyContent = document.createElement("div");
    const occupancy = document.createElement("div");
    const addGates = document.createElement("button");
    const addRefine = document.createElement("button");
    const addWiresButton = document.createElement("button");
    const members = harness.wires.filter(
      (wire) => wire.orderedPathwayIds.includes(pathway.pathwayId),
    );
    pathwayContent.className = "section-content";
    gateContent.className = "section-content";
    sequence.className = "sequence";
    const relatedEndpoints = new Set(
      (harness.junctions || []).flatMap((junction) => junction.pathwayRelationships || [])
        .filter((relationship) => relationship.pathwayId === pathway.pathwayId)
        .map((relationship) => relationship.endpoint),
    );
    const lockedIndexes = new Set();
    if (pathway.orderedControlIds.length && relatedEndpoints.has("start")) lockedIndexes.add(0);
    if (pathway.orderedControlIds.length && relatedEndpoints.has("end")) {
      lockedIndexes.add(pathway.orderedControlIds.length - 1);
    }
    const gateRows = [];
    pathway.orderedControlIds.forEach((controlId, index) => {
      const control = controls.get(controlId);
      const isRefine = control?.kind === "refine";
      const isLocked = lockedIndexes.has(index);
      const openOptions = () => openInterpolationOptions(
        harness, "gate", controlId, control?.name || "Gate", control?.interpolation, null, control?.usesDefaults ?? true,
      );
      const editControl = isRefine
        ? () => editPathwayRefine(harness, control)
        : openOptions;
      const movePayload = { harnessId: harness.harnessId, pathwayId: pathway.pathwayId, controlId };
      const row = memberRow(
        `${control?.name || "Missing gate"} #${controlId.slice(0, 8)}`,
        () => highlightMember(harness, "control", controlId),
        [
          optionsButton(
            isRefine ? "Move, rotate, or resize refine point" : "Gate interpolation options",
            editControl,
            !control,
          ),
          actionButton("×", "Remove gate", () => removeGate(
            harness, pathway, controlId, control?.name || "this gate",
          ), pathway.orderedControlIds.length === 1 || isLocked, true),
        ],
        !control || !control.hasLinkedGeometry,
      );
      row.children[0].title = isLocked
        ? `Click for ${control?.kind === "refine" ? "refine" : "gate"} options; junction endpoint is locked`
        : `Click for ${control?.kind === "refine" ? "refine" : "gate"} options; drag to reorder`;
      row.children[0].addEventListener("click", (event) => {
        if (event.detail === 0 && control) void editControl();
      });
      row.title = isLocked
        ? `${control?.name || "Gate"} is preserved by a junction relationship`
        : `Drag to reorder ${control?.name || "gate"} (${controlId})`;
      enableSequenceDrag(sequence, gateRows, row, index, (target) => mutate(
        "move_pathway_gate", { ...movePayload, offset: target - index }, "Reordering gate…",
      ), control ? editControl : null, isLocked, lockedIndexes);
      sequence.append(row);
    });
    occupancyContent.className = "section-content";
    occupancy.className = "occupancy";
    if (!members.length) {
      occupancy.append(emptyMessage("No wires occupy this pathway."));
    }
    members.forEach((wire) => {
      const pathwayIndex = wire.orderedPathwayIds.indexOf(pathway.pathwayId);
      const previousPathway = pathways.get(wire.orderedPathwayIds[pathwayIndex - 1]);
      const nextPathway = pathways.get(wire.orderedPathwayIds[pathwayIndex + 1]);
      const startConnection = connections.get(wire.startConnectionId);
      const endConnection = connections.get(wire.endConnectionId);
      const entry = pathwayIndex === 0
        ? `End A: ${wire.startEndName || startConnection?.name || "Missing connection"}`
        : `From ${previousPathway?.name || "missing pathway"}`;
      const exit = pathwayIndex === wire.orderedPathwayIds.length - 1
        ? `End B: ${wire.endEndName || endConnection?.name || "Missing connection"}`
        : `Continue to ${nextPathway?.name || "missing pathway"}`;
      const hasMissingGeometry = (pathwayIndex === 0 && !startConnection?.hasLinkedGeometry)
        || (pathwayIndex === wire.orderedPathwayIds.length - 1
          && !endConnection?.hasLinkedGeometry);
      occupancy.append(memberRow(
        `${wireLabel(wire)} · ${entry} → ${exit}`,
        () => highlightMember(harness, "preview_wire", wire.wireId),
        [],
        hasMissingGeometry,
      ));
    });
    addGates.type = "button";
    addGates.className = "button compact";
    addGates.textContent = "+ Add Gates";
    const hasInteriorInsertion = !(
      pathway.orderedControlIds.length === 1
      && relatedEndpoints.has("start")
      && relatedEndpoints.has("end")
    );
    addGates.disabled = !hasInteriorInsertion;
    addGates.title = hasInteriorInsertion
      ? ""
      : "Detach one junction endpoint before adding controls";
    addGates.addEventListener("click", () => appendPathwayGates(harness, pathway));
    addRefine.type = "button";
    addRefine.className = "button compact";
    addRefine.textContent = "+ Add Refine Point";
    addRefine.disabled = !hasInteriorInsertion;
    addRefine.title = addGates.title;
    addRefine.addEventListener("click", () => addPathwayRefine(harness, pathway));
    addWiresButton.type = "button";
    addWiresButton.className = "button compact";
    addWiresButton.textContent = "+ Add Wire Pairs";
    addWiresButton.addEventListener("click", () => addWires(pathway.pathwayId));
    const namePayload = { harnessId: harness.harnessId, pathwayId: pathway.pathwayId };
    gateContent.append(
      nameField("Start Name", pathway.startName, "rename_pathway", {
        ...namePayload, field: "start_name",
      }),
      sequence,
      nameField("End Name", pathway.endName, "rename_pathway", {
        ...namePayload, field: "end_name",
      }),
      addGates,
      addRefine,
    );
    occupancyContent.append(occupancy, addWiresButton);
    pathwayContent.append(
      nameField("", pathway.name, "rename_pathway", {
        ...namePayload, field: "name",
      }),
      nestedSection(
        `pathway:${pathway.pathwayId}:gates`,
        "Routing Controls · Traversal Order",
        `${pathway.orderedControlIds.length}`,
        gateContent,
        () => highlightMember(harness, "pathway_gates", pathway.pathwayId),
      ),
      nestedSection(
        `pathway:${pathway.pathwayId}:occupancy`,
        "Wire Occupancy",
        `${members.length}`,
        occupancyContent,
        () => highlightMember(harness, "pathway_wires", pathway.pathwayId),
      ),
    );
    container.append(nestedSection(
      `pathway:${pathway.pathwayId}`,
      pathway.name,
      `${pathwayDirection(pathway)} · ${members.length} wires`,
      pathwayContent,
      () => highlightMember(harness, "pathway", pathway.pathwayId),
    ));
  });
  return container;
}

function closePathwayPopup() {
  const dialog = document.body.querySelector(".pathway-popup");
  openPathwayPopupId = "";
  if (dialog?.open) dialog.close();
  else dialog?.remove();
}

function openPathwayPopup(harness, pathwayId) {
  closeJunctionRelationships();
  const pathway = harness.pathways.find((candidate) => candidate.pathwayId === pathwayId);
  const existing = document.body.querySelector(".pathway-popup");
  if (existing) {
    existing.remove();
    if (existing.open) existing.close();
  }
  if (!pathway) {
    openPathwayPopupId = "";
    return;
  }
  openPathwayPopupId = pathwayId;
  const dialog = document.createElement("dialog");
  const rendered = renderPathways(harness, pathwayId);
  const entry = rendered.children[0];
  const actions = document.createElement("div");
  const close = document.createElement("button");
  dialog.className = "pathway-popup";
  dialog.setAttribute("aria-label", `Pathway configuration: ${pathway.name}`);
  entry.open = true;
  entry.classList.add("pathway-popup-entry");
  actions.className = "pathway-popup-actions";
  close.type = "button";
  close.className = "button";
  close.textContent = "Close";
  close.addEventListener("click", closePathwayPopup);
  dialog.addEventListener("close", () => {
    if (document.body.querySelector(".pathway-popup") === dialog) {
      openPathwayPopupId = "";
    }
    dialog.remove();
  });
  actions.append(close);
  dialog.append(entry, actions);
  document.body.append(dialog);
  dialog.showModal();
}
