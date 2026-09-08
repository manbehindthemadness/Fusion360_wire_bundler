function openHarness(key) {
  const harness = currentState.harnesses.find((candidate) => harnessKey(candidate) === key);
  if (!harness) return;
  selectedHarnessKey = key;
  writeSession("wireBundler.selectedHarness", key);
  ui.libraryView.hidden = true;
  ui.editorView.hidden = false;
  renderEditor(harness);
  window.scrollTo(0, 0);
}

function closeEditor() {
  send("clear_highlight").catch(() => {});
  selectedHarnessKey = "";
  removeSession("wireBundler.selectedHarness");
  ui.editorView.hidden = true;
  ui.libraryView.hidden = false;
  ui.editor.replaceChildren();
  ui.harnessFilter.focus();
}

function render(state) {
  const scrollTop = document.scrollingElement.scrollTop;
  currentState = state;
  appendNotice(state.notice);
  renderLibrary();
  const selected = state.harnesses.find(
    (harness) => harnessKey(harness) === selectedHarnessKey,
  );
  if (selected) {
    ui.libraryView.hidden = true;
    ui.editorView.hidden = false;
    renderEditor(selected);
  } else {
    selectedHarnessKey = "";
    removeSession("wireBundler.selectedHarness");
    ui.editorView.hidden = true;
    ui.libraryView.hidden = false;
  }
  window.requestAnimationFrame(() => window.scrollTo(0, scrollTop));
}

function appendNotice(message, isError = false) {
  if (!message) return;
  const previous = ui.notice.children[ui.notice.children.length - 1];
  if (previous?.dataset.message === message
      && previous.className.includes(isError ? "error" : "notice-entry")) return;
  const entry = document.createElement("div");
  entry.className = `notice-entry${isError ? " error" : ""}`;
  entry.dataset.message = message;
  updateNoticeEntry(entry);
  ui.notice.append(entry);
  ui.notice.scrollTop = ui.notice.scrollHeight;
}

function updateNoticeEntry(entry) {
  const marker = " Routing diagnostic: ";
  const message = entry.dataset.message || "";
  const markerIndex = message.indexOf(marker);
  entry.textContent = markerIndex >= 0 && !ui.verboseDiagnostics.checked
    ? message.slice(0, markerIndex)
    : message;
}

function setDeveloperMode(enabled) {
  developerModeEnabled = enabled;
  ui.developerMode.checked = enabled;
  ui.verboseDiagnostics.disabled = !enabled;
  writePreference(DEVELOPER_MODE_STORAGE_KEY, String(enabled));
  if (enabled) {
    writePreference(DEVELOPER_CONSENT_STORAGE_KEY, DEVELOPER_MODE_DISCLOSURE_VERSION);
  } else {
    ui.verboseDiagnostics.checked = false;
    writePreference("wireBundler.verboseDiagnostics", "false");
  }
  Array.from(ui.notice.children).forEach(updateNoticeEntry);
}

function openDeveloperConsent() {
  ui.developerMode.checked = developerModeEnabled;
  ui.developerConsentAgreement.checked = false;
  ui.developerConsentEnable.disabled = true;
  ui.developerConsent.showModal();
}

function closeDeveloperConsent() {
  ui.developerConsent.close();
}

function persistNoticeHeight() {
  if (!ui.notice.getBoundingClientRect) return;
  const height = Math.round(ui.notice.getBoundingClientRect().height);
  if (Number.isFinite(height)) writeSession("wireBundler.noticeHeight", String(height));
}

function handleQaProbe(data) {
  if (!developerModeEnabled) return "DENIED";
  let payload;
  try {
    payload = JSON.parse(data);
  } catch (_error) {
    return "INVALID";
  }
  const validText = (value) => typeof value === "string" && value.length > 0
    && value.length <= 160;
  if (payload?.operation !== "observe_wire"
      || !validText(payload.harnessId)
      || !validText(payload.wireId)
      || !validText(payload.expectedLabel)) return "INVALID";
  const harness = currentState.harnesses.find(
    (candidate) => harnessKey(candidate) === payload.harnessId,
  );
  const wire = harness?.wires?.find((candidate) => candidate.wireId === payload.wireId);
  if (!harness || !wire || wireLabel(wire) !== payload.expectedLabel) return "MISMATCH";
  openHarness(payload.harnessId);
  const card = Array.from(ui.editor.querySelectorAll("div"))
    .find((candidate) => candidate.dataset.wireId === payload.wireId);
  const label = card?.querySelector(".member-reference");
  if (ui.editorView.hidden || !ui.libraryView.hidden || !card
      || label?.textContent !== payload.expectedLabel) return "MISMATCH";
  void send("clear_highlight").catch(() => {});
  return "OK";
}

function waitForFusionHost() {
  return new Promise((resolve, reject) => {
    let attempts = 0;
    const timer = window.setInterval(() => {
      const fusionHost = window["adsk"];
      if (fusionHost && fusionHost.fusionSendData) {
        window.clearInterval(timer);
        resolve(fusionHost);
        return;
      }
      attempts += 1;
      if (attempts >= 50) {
        window.clearInterval(timer);
        reject(new Error("Fusion did not initialize the palette bridge."));
      }
    }, 100);
  });
}

async function send(action, payload = {}) {
  const fusionHost = await waitForFusionHost();
  const response = await fusionHost.fusionSendData(action, JSON.stringify(payload));
  return JSON.parse(response);
}

function generateSolids() {
  const harness = currentState.harnesses.find((item) => harnessKey(item) === selectedHarnessKey);
  if (!harness || harness.status === "damaged" || !harness.wires?.length) return;
  if (!window.confirm("Build wire solids? This replaces previous generated wire components, including manual edits inside them.")) return;
  return mutate("generate_solids", { harnessId: harness.harnessId, replaceExisting: true }, "Generating wire solids…");
}

function clearSolids() {
  const harness = currentState.harnesses.find((item) => harnessKey(item) === selectedHarnessKey);
  if (!harness || harness.status === "damaged") return;
  if (!window.confirm("Clear generated wire solids? This removes manual edits inside generated wire components.")) return;
  return mutate("clear_solids", { harnessId: harness.harnessId }, "Clearing wire solids…");
}

async function refresh() {
  try {
    render(await send("get_state"));
  } catch (error) {
    appendNotice(error.message, true);
  }
}

async function createHarness() {
  appendNotice("Opening Create Harness…");
  try {
    const response = await send("create_harness");
    if (!response.ok) {
      appendNotice(response.error || "Create Harness could not be opened.", true);
    }
  } catch (error) {
    appendNotice(error.message, true);
  }
}

async function mutate(action, payload, progress) {
  appendNotice(progress);
  try {
    const response = await send(action, payload);
    if (!response.ok) {
      appendNotice(response.error || "The harness edit could not be completed.", true);
    }
  } catch (error) {
    appendNotice(error.message, true);
  }
}

async function highlightMember(harness, memberType, memberId, extra = {}) {
  try {
    const response = await send("highlight_member", {
      harnessId: harness.harnessId,
      memberType,
      memberId,
      ...extra,
    });
    if (!response.ok) {
      appendNotice(response.error || "Linked geometry could not be highlighted.", true);
    }
  } catch (error) {
    appendNotice(error.message, true);
  }
}

async function appendPathwayGates(harness, pathway) {
  appendNotice(`Selecting additional gates for ${pathway.name}…`);
  try {
    const response = await send("append_pathway_gates", {
      harnessId: harness.harnessId,
      pathwayId: pathway.pathwayId,
    });
    if (!response.ok) {
      appendNotice(response.error || "Add Gates could not be opened.", true);
    }
  } catch (error) {
    appendNotice(error.message, true);
  }
}

function removeGate(harness, pathway, controlId, name) {
  if (!window.confirm(`Remove ${name} from ${pathway.name}?`)) return;
  void mutate(
    "remove_pathway_gate",
    { harnessId: harness.harnessId, pathwayId: pathway.pathwayId, controlId },
    "Removing gate…",
  );
}

function removeWirePair(harness, wire) {
  if (!window.confirm(`Remove wire #${wire.wireNumber} and both connection assignments?`)) return;
  void mutate(
    "remove_wire",
    { harnessId: harness.harnessId, wireId: wire.wireId },
    `Removing wire #${wire.wireNumber}…`,
  );
}

async function addPathway() {
  const harness = currentState.harnesses.find(
    (candidate) => harnessKey(candidate) === selectedHarnessKey,
  );
  if (!harness || harness.status === "damaged") return;
  appendNotice("Opening Add Pathway…");
  try {
    const response = await send("add_pathway", { harnessId: harness.harnessId });
    if (!response.ok) {
      appendNotice(response.error || "Add Pathway could not be opened.", true);
    }
  } catch (error) {
    appendNotice(error.message, true);
  }
}

async function addWires(pathwayId = null) {
  const harness = currentState.harnesses.find(
    (candidate) => harnessKey(candidate) === selectedHarnessKey,
  );
  if (!harness || harness.status === "damaged" || !harness.pathways.length) return;
  appendNotice("Opening Add Wires…");
  try {
    const response = await send("add_wires", { harnessId: harness.harnessId, pathwayId });
    if (!response.ok) {
      appendNotice(response.error || "Add Wires could not be opened.", true);
    }
  } catch (error) {
    appendNotice(error.message, true);
  }
}

async function previewRoutes() {
  const harness = currentState.harnesses.find(
    (candidate) => harnessKey(candidate) === selectedHarnessKey,
  );
  if (!harness || harness.status === "damaged" || !harness.wires.length) return;
  appendNotice("Solving route preview…");
  try {
    const response = await send("preview_routes", { harnessId: harness.harnessId });
    if (!response.ok) {
      appendNotice(response.error || "Routes could not be previewed.", true);
    }
  } catch (error) {
    appendNotice(error.message, true);
  }
}

async function clearPreview() {
  try {
    const response = await send("clear_preview");
    if (!response.ok) {
      appendNotice(response.error || "Route preview could not be cleared.", true);
    } else {
      appendNotice(response.notice);
    }
  } catch (error) {
    appendNotice(error.message, true);
  }
}

ui.addPathway.addEventListener("click", addPathway);
ui.addWires.addEventListener("click", () => addWires());
ui.defaults.addEventListener("click", () => {
  const harness = currentState.harnesses.find((item) => harnessKey(item) === selectedHarnessKey);
  if (harness && harness.status !== "damaged") openInterpolationOptions(harness, "defaults");
});
ui.materialDefaults.addEventListener("click", () => {
  const harness = currentState.harnesses.find((item) => harnessKey(item) === selectedHarnessKey);
  if (harness && harness.status !== "damaged") openMaterialOptions(harness);
});
ui.generateSolids.addEventListener("click", generateSolids);
ui.clearSolids.addEventListener("click", clearSolids);
ui.previewRoutes.addEventListener("click", previewRoutes);
ui.clearPreview.addEventListener("click", clearPreview);
ui.back.addEventListener("click", closeEditor);
ui.create.addEventListener("click", createHarness);
ui.createFromEditor.addEventListener("click", createHarness);
ui.harnessFilter.addEventListener("input", renderLibrary);
ui.refresh.addEventListener("click", refresh);
ui.developerMode.addEventListener("change", () => {
  if (ui.developerMode.checked) {
    openDeveloperConsent();
  } else {
    setDeveloperMode(false);
  }
});
ui.developerConsentAgreement.addEventListener("change", () => {
  ui.developerConsentEnable.disabled = !ui.developerConsentAgreement.checked;
});
ui.developerConsentCancel.addEventListener("click", closeDeveloperConsent);
ui.developerConsentForm.addEventListener("submit", (event) => {
  event.preventDefault();
  if (!ui.developerConsentAgreement.checked) return;
  setDeveloperMode(true);
  closeDeveloperConsent();
});
ui.developerConsent.addEventListener("cancel", (event) => {
  event.preventDefault();
  closeDeveloperConsent();
});
ui.developerConsent.addEventListener("close", () => {
  ui.developerMode.checked = developerModeEnabled;
  ui.developerConsentAgreement.checked = false;
  ui.developerConsentEnable.disabled = true;
});
ui.verboseDiagnostics.addEventListener("change", () => {
  if (!developerModeEnabled) {
    ui.verboseDiagnostics.checked = false;
    writePreference("wireBundler.verboseDiagnostics", "false");
    return;
  }
  writePreference("wireBundler.verboseDiagnostics", String(ui.verboseDiagnostics.checked));
  Array.from(ui.notice.children).forEach(updateNoticeEntry);
});
ui.notice.addEventListener("mouseup", persistNoticeHeight);
window.fusionJavaScriptHandler = { handle(action, data) {
  if (action === "state") render(JSON.parse(data));
  if (action === "qa_probe") return handleQaProbe(data);
  return "OK";
}};
void refresh();
