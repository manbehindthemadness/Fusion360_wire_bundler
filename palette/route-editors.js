function enableSequenceDrag(
  sequence, memberRows, row, memberIndex, onMove, onActivate = null,
  locked = false, lockedIndexes = new Set(),
) {
  const position = document.createElement("span");
  position.className = "sequence-position";
  position.textContent = `${memberIndex + 1}`;
  position.setAttribute("aria-label", `Position ${memberIndex + 1}`);
  row.insertBefore(position, row.children[0]);
  row.dataset.reorder = locked ? "locked" : "true";
  memberRows.push(row);
  if (locked) return;
  let drag = null;
  const clearDrag = () => {
    drag = null;
    delete row.dataset.dragging;
    memberRows.forEach((item) => { delete item.dataset.drop; });
  };
  row.addEventListener("dragstart", (event) => event.preventDefault());
  row.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || event.target.closest(".icon-button")) return;
    drag = { x: event.clientX, y: event.clientY, active: false, target: memberIndex };
    row.setPointerCapture(event.pointerId);
  });
  row.addEventListener("pointermove", (event) => {
    if (!drag) return;
    if (!drag.active && Math.hypot(event.clientX - drag.x, event.clientY - drag.y) < 5) return;
    event.preventDefault();
    drag.active = true;
    row.dataset.dragging = "true";
    memberRows.forEach((item) => { delete item.dataset.drop; });
    const bounds = sequence.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right ||
        event.clientY < bounds.top - 12 || event.clientY > bounds.bottom + 12) {
      drag.target = null;
      return;
    }
    const others = memberRows.filter((item) => item !== row);
    const next = others.findIndex((item) => {
      const rect = item.getBoundingClientRect();
      return event.clientY < rect.top + rect.height / 2;
    });
    drag.target = next < 0 ? others.length : next;
    if (lockedIndexes.has(0)) drag.target = Math.max(1, drag.target);
    if (lockedIndexes.has(memberRows.length - 1)) {
      drag.target = Math.min(memberRows.length - 2, drag.target);
    }
    if (others.length) {
      const marker = memberRows[drag.target] || memberRows[memberRows.length - 1];
      marker.dataset.drop = drag.target >= memberRows.length - 1 ? "after" : "before";
    }
  });
  row.addEventListener("pointerup", (event) => {
    if (!drag) return;
    const target = drag.target;
    const clicked = !drag.active;
    const moved = drag.active && target !== null && target !== memberIndex;
    clearDrag();
    if (row.hasPointerCapture(event.pointerId)) row.releasePointerCapture(event.pointerId);
    if (moved) onMove(target);
    else if (clicked && onActivate) onActivate();
  });
  row.addEventListener("pointercancel", clearDrag);
  row.addEventListener("lostpointercapture", clearDrag);
}

function renderEndpointSequence(harness, wires, connections, endpoint) {
  const sequence = document.createElement("div");
  sequence.className = "sequence";
  wires.forEach((wire) => {
    const connectionId = endpoint === "start" ? wire.startConnectionId : wire.endConnectionId;
    const connection = connections.get(connectionId);
    const members = connection?.members || (connection ? [{ index: 0, hasLinkedGeometry: connection.hasLinkedGeometry, usesDefaults: true }] : []);
    const payload = { harnessId: harness.harnessId, wireId: wire.wireId, endpoint, expectedMembers: members.length };
    const memberRows = [];
    members.forEach((member, memberIndex) => {
      const row = memberRow(
        member.memberId ? `#${member.memberId.slice(0, 8)}` : `${memberIndex + 1}`,
        () => highlightMember(harness, "connection", connectionId, { memberIndex }),
        [
          optionsButton("End member interpolation options", () => openInterpolationOptions(
            harness, "end", connectionId,
            `${endpoint === "start" ? "End A" : "End B"} · #${member.memberId?.slice(0, 8) || memberIndex + 1}`,
            member.interpolation || connection?.interpolation, member.memberId, member.usesDefaults ?? true,
          ), !member.memberId),
          actionButton("+", "Add member after this member", () => mutate(
            "edit_end_members", { ...payload, memberIndex, editAction: "add" }, "Select connection profiles…",
          )),
          actionButton("⇄", "Replace member", () => mutate(
            "edit_end_members", { ...payload, memberIndex, editAction: "replace" }, "Select replacement profile…",
          )),
          actionButton("×", "Remove member", () => {
            if (members.length === 1 && !window.confirm(
              "Delete this end sequence? The wire will have a missing end.",
            )) return;
            void mutate("remove_end_member", { ...payload, memberIndex }, "Removing end member…");
          }, false, true),
        ],
        !member.hasLinkedGeometry,
      );
      row.title = `Drag to reorder this end member${member.memberId ? ` (${member.memberId})` : ""}`;
      enableSequenceDrag(sequence, memberRows, row, memberIndex, (target) => mutate(
        "move_end_member", { ...payload, memberIndex, targetIndex: target }, "Reordering end member…",
      ));
      sequence.append(row);
    });
  });
  return sequence;
}

function renderEndEditor(harness, wires, connections, endpoint, id) {
  const editor = document.createElement("div");
  const heading = document.createElement("div");
  const label = document.createElement("strong");
  const metadata = document.createElement("span");
  const endLabel = endpoint === "start" ? "End A" : "End B";
  editor.id = id;
  editor.dataset.stateKey = `end:${harness.harnessId}:${wires[0].wireId}:${endpoint}`;
  editor.className = "end-editor";
  editor.hidden = !expandedSections.has(editor.dataset.stateKey);
  heading.className = "end-editor-heading";
  label.textContent = `${endLabel} Ordering`;
  metadata.className = "item-meta";
  metadata.textContent = wireLabel(wires[0]);
  heading.append(label, metadata);
  const nameLabel = document.createElement("label");
  const nameInput = document.createElement("input");
  nameLabel.textContent = `${endLabel} Name`;
  nameInput.type = "text";
  nameInput.className = "filter";
  nameInput.value = wires[0][endpoint === "start" ? "startEndName" : "endEndName"] || "";
  nameInput.placeholder = "Optional name";
  nameInput.addEventListener("change", () => mutate("rename_route_end", {
    harnessId: harness.harnessId,
    wireId: wires[0].wireId,
    endpoint,
    name: nameInput.value,
  }, "Saving end name…"));
  nameLabel.append(nameInput);
  editor.append(heading, nameLabel, renderEndpointSequence(harness, wires, connections, endpoint));
  return editor;
}

function wireHeader(harness, wire, details, missing) {
  const row = memberRow(wireLabel(wire), () => {
    details.hidden = !details.hidden;
    const stateKey = `wire:${harness.harnessId}:${wire.wireId}`;
    if (details.hidden) expandedSections.delete(stateKey);
    else expandedSections.add(stateKey);
    writeSession("wireBundler.expandedSections", JSON.stringify([...expandedSections]));
    label.setAttribute("aria-expanded", `${!details.hidden}`);
  }, [], missing, true);
  const label = row.children[0];
  const actions = row.children[1];
  label.title = "Expand or collapse wire";
  label.setAttribute("aria-expanded", `${!details.hidden}`);
  label.setAttribute("aria-controls", details.id);
  hoverHighlight(row, () => highlightMember(harness, "preview_wire", wire.wireId));
  const rename = actionButton("✎", "Rename wire", () => {
    if (row.querySelector("input")) return;
    const input = document.createElement("input");
    input.className = "filter";
    input.value = wire.displayName || "";
    input.placeholder = wireLabel(wire);
    input.setAttribute("aria-label", "Wire name");
    label.hidden = true;
    row.insertBefore(input, actions);
    let finished = false;
    const finish = (save) => {
      if (finished) return;
      finished = true;
      input.remove();
      label.hidden = false;
      if (save) void mutate("rename_wire", {
        harnessId: harness.harnessId, wireId: wire.wireId, name: input.value,
      }, "Saving wire name…");
    };
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === "Escape") {
        event.preventDefault();
        finish(event.key === "Enter");
      }
    });
    input.addEventListener("blur", () => finish(true));
    input.focus();
    input.select();
  });
  actions.append(rename, actionButton(
    "×", `Remove ${wireLabel(wire)}`, () => removeWirePair(harness, wire), false, true,
  ));
  return row;
}

function openInterpolationOptions(harness, target, targetId = null, name = "", settings = {}, memberId = null, useDefaults = false) {
  const { dialog, form, heading, note, error, actions, cancel, save } = createOptionsDialog(
    "wire-options",
  );
  const isDefaults = target === "defaults";
  heading.textContent = isDefaults ? "Generation defaults" : `Interpolation · ${name}`;
  dialog.setAttribute("aria-label", heading.textContent);
  note.textContent = "Leave a distance blank for Auto. Auto expands toward the wire's safe bend minimum; crowded values are reduced to the feasible range, and crowded spans use a direct profile-to-profile curve when it preserves that radius. "
    + (isDefaults ? "Presets are used for new controls. Existing controls follow defaults unless individually customized."
      : target === "end" ? "These settings apply only to this member, in terminal → pathway order. The first member uses only its pathway-side distance."
        : "Approach and departure follow the gate traversal order. Changes affect all wires through this gate.");
  form.append(heading, note);
  const applyExisting = document.createElement("input");
  applyExisting.type = "checkbox";
  applyExisting.checked = true;
  if (isDefaults) {
    const applyLabel = document.createElement("label");
    applyLabel.className = "apply-existing";
    const applyText = document.createElement("span");
    applyText.textContent = "Update existing controls using defaults";
    applyExisting.setAttribute("aria-label", applyText.textContent);
    applyLabel.append(applyExisting, applyText);
    form.append(applyLabel);
  }
  const status = document.createElement("p");
  const updateStatus = () => { status.textContent = useDefaults ? "Using harness defaults" : "Custom settings"; };
  if (!isDefaults) { updateStatus(); form.append(status); }
  const fields = [];
  const addFields = (prefix, initial, endSection) => {
    const inputs = {};
    for (const [key, text] of [["approach_mm", endSection ? "Terminal-side transition" : "Approach transition"],
      ["departure_mm", endSection ? "Pathway-side transition" : "Departure transition"]]) {
      const label = document.createElement("label");
      const input = document.createElement("input");
      label.textContent = `${prefix}${text} (mm)`;
      input.type = "number";
      input.className = "filter";
      input.step = "any";
      input.min = "0";
      input.placeholder = "Auto";
      input.value = initial?.[key] == null ? "" : `${initial[key]}`;
      input.addEventListener("input", () => { useDefaults = false; updateStatus(); });
      input.setAttribute("aria-label", label.textContent);
      label.append(input);
      form.append(label);
      fields.push(input);
      inputs[key] = input;
    }
    return inputs;
  };
  const primary = addFields(isDefaults ? "Gates · " : "", isDefaults ? harness.gateDefaults : settings, target === "end");
  const ends = isDefaults ? addFields("Ends · ", harness.endDefaults, true) : null;
  if (!isDefaults) {
    const reset = document.createElement("button");
    reset.type = "button";
    reset.className = "button";
    reset.textContent = "Use harness defaults";
    reset.addEventListener("click", () => {
      useDefaults = true;
      updateStatus();
      const defaults = target === "gate" ? harness.gateDefaults : harness.endDefaults;
      for (const [key, input] of Object.entries(primary)) {
        input.value = defaults?.[key] == null ? "" : `${defaults[key]}`;
      }
    });
    form.append(reset);
  }
  const values = (inputs) => Object.fromEntries(Object.entries(inputs).map(([key, input]) =>
    [key, input.value.trim() === "" ? null : Number(input.value)]));
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (fields.some((input) => input.validity?.badInput || (input.value.trim() !== ""
      && (!Number.isFinite(Number(input.value)) || Number(input.value) < 0)))) {
      error.textContent = "Enter nonnegative distances in millimeters, or leave blank for Auto.";
      return;
    }
    save.disabled = true;
    try {
      const response = await send("set_interpolation", {
        harnessId: harness.harnessId, target, targetId, memberId, useDefaults, settings: values(primary),
        ...(ends ? { endDefaults: values(ends), applyExisting: applyExisting.checked } : {}),
      });
      if (response.ok) dialog.close();
      else error.textContent = response.error || "Could not save interpolation options.";
    } catch (failure) {
      error.textContent = failure.message;
    } finally {
      save.disabled = false;
    }
  });
  dialog.addEventListener("close", () => dialog.remove());
  actions.append(cancel, save);
  form.append(error, actions);
  dialog.append(form);
  document.body.append(dialog);
  dialog.showModal();
}
