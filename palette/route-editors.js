function enableSequenceDrag(sequence, memberRows, row, memberIndex, onMove, onActivate = null) {
  const position = document.createElement("span");
  position.className = "sequence-position";
  position.textContent = `${memberIndex + 1}`;
  position.setAttribute("aria-label", `Position ${memberIndex + 1}`);
  row.insertBefore(position, row.children[0]);
  row.dataset.reorder = "true";
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
    if (others.length) {
      const marker = next < 0 ? others[others.length - 1] : others[next];
      marker.dataset.drop = next < 0 ? "after" : "before";
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
  memberRows.push(row);
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
      label.textContent = lengthFieldLabel(`${prefix}${text}`);
      input.type = "number";
      input.className = "filter";
      input.step = "any";
      input.min = "0";
      input.placeholder = "Auto";
      input.value = initial?.[key] == null ? "" : `${displayLength(initial[key])}`;
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
        input.value = defaults?.[key] == null ? "" : `${displayLength(defaults[key])}`;
      }
    });
    form.append(reset);
  }
  const values = (inputs) => Object.fromEntries(Object.entries(inputs).map(([key, input]) =>
    [key, input.value.trim() === "" ? null : canonicalLength(input.value)]));
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (fields.some((input) => input.validity?.badInput || (input.value.trim() !== ""
      && (!Number.isFinite(Number(input.value)) || Number(input.value) < 0)))) {
      error.textContent = `Enter nonnegative distances in ${activeLengthUnit()}, or leave blank for Auto.`;
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

function topologyOption(value, label) {
  const option = document.createElement("option");
  option.value = value;
  option.textContent = label;
  return option;
}

function renderTopologyEditor(harness) {
  const container = document.createElement("div");
  const topology = harness.topology;
  container.className = "section-content topology-editor";

  const createForm = document.createElement("form");
  const pathway = document.createElement("select");
  const slice = document.createElement("select");
  const distance = document.createElement("input");
  const pickPathway = document.createElement("button");
  const create = document.createElement("button");
  createForm.className = "topology-create-row";
  harness.pathways.forEach((item) => pathway.append(
    topologyOption(item.pathwayId, item.name || item.pathwayId.slice(0, 8)),
  ));
  const updateSlices = () => {
    slice.replaceChildren(topologyOption("", "Virtual slice"));
    const selected = harness.pathways.find((item) => item.pathwayId === pathway.value)
      || harness.pathways[0];
    (selected?.orderedControlIds || []).forEach((controlId) => {
      const control = harness.controls.find((item) => item.controlId === controlId);
      if (control?.kind === "routing_gate") {
        slice.append(topologyOption(controlId, control.name || controlId.slice(0, 8)));
      }
    });
  };
  pathway.value = harness.pathways[0]?.pathwayId || "";
  pathway.setAttribute("aria-label", "Junction parent pathway");
  pathway.addEventListener("change", updateSlices);
  updateSlices();
  distance.type = "number";
  distance.min = "0";
  distance.step = "any";
  distance.required = true;
  distance.placeholder = lengthFieldLabel("Distance");
  distance.setAttribute("aria-label", lengthFieldLabel("Junction distance"));
  pickPathway.type = "button";
  pickPathway.className = "button compact";
  pickPathway.textContent = "Pick pathway in Fusion…";
  pickPathway.addEventListener("click", () => mutate("pick_junction_pathway", {
    harnessId: harness.harnessId,
    distanceMm: canonicalLength(distance.value || "0"),
  }, "Select a pathway gate in Fusion…"));
  create.type = "submit";
  create.className = "button compact primary";
  create.textContent = "+ Junction";
  createForm.addEventListener("submit", (event) => {
    event.preventDefault();
    void mutate("add_junction", {
      harnessId: harness.harnessId,
      pathwayId: pathway.value,
      sliceControlId: slice.value || null,
      distanceMm: canonicalLength(distance.value),
      diameterFactor: null,
    }, "Adding junction…");
  });
  const pathwayLabel = document.createElement("label");
  const sliceLabel = document.createElement("label");
  const distanceLabel = document.createElement("label");
  const distanceField = document.createElement("span");
  const distanceUnit = document.createElement("span");
  pathwayLabel.textContent = "Parent pathway";
  sliceLabel.textContent = "Slice";
  distanceLabel.textContent = "Location";
  distanceField.className = "unit-input";
  distanceUnit.className = "unit-input-suffix";
  distanceUnit.textContent = activeLengthUnit();
  pathwayLabel.append(pathway);
  sliceLabel.append(slice);
  distanceField.append(distance, distanceUnit);
  distanceLabel.append(distanceField);
  createForm.append(pathwayLabel, pickPathway, sliceLabel, distanceLabel, create);
  container.append(createForm);

  if (!topology) {
    container.append(emptyMessage("Add the first junction to enable graph route editing."));
    return container;
  }

  const pathNames = new Map(harness.pathways.map((item) => [item.pathwayId, item.name]));
  const junctions = topology.nodes.filter((node) => node.kind === "junction");
  junctions.forEach((junction) => {
    const card = document.createElement("details");
    const heading = document.createElement("summary");
    const title = document.createElement("strong");
    const remove = actionButton("×", "Delete junction", () => {
      if (window.confirm && !window.confirm("Delete this empty junction?")) return;
      void mutate("remove_junction", {
        harnessId: harness.harnessId, junctionId: junction.nodeId,
      }, "Deleting junction…");
    }, false, true);
    card.className = "topology-junction-card";
    card.open = true;
    card.dataset.junctionId = junction.nodeId;
    heading.className = "topology-junction-heading";
    title.textContent = junction.name || "Junction";
    heading.append(title, remove);

    const settings = document.createElement("div");
    const position = document.createElement("input");
    const positionField = document.createElement("span");
    const positionUnit = document.createElement("span");
    const name = document.createElement("input");
    const rename = document.createElement("button");
    const move = document.createElement("button");
    position.type = "number";
    position.min = "0";
    position.step = "any";
    position.value = `${displayLength(junction.distanceMm)}`;
    position.setAttribute("aria-label", lengthFieldLabel("Junction distance"));
    positionField.className = "unit-input";
    positionUnit.className = "unit-input-suffix";
    positionUnit.textContent = activeLengthUnit();
    positionField.append(position, positionUnit);
    name.type = "text";
    name.value = junction.name || "Junction";
    name.setAttribute("aria-label", "Junction name");
    rename.type = "button";
    rename.className = "button compact";
    rename.textContent = "Rename";
    rename.addEventListener("click", () => mutate("rename_junction", {
      harnessId: harness.harnessId,
      junctionId: junction.nodeId,
      name: name.value,
    }, "Renaming junction…"));
    move.type = "button";
    move.className = "button compact";
    move.textContent = "Move";
    move.addEventListener("click", () => mutate("move_junction", {
      harnessId: harness.harnessId,
      junctionId: junction.nodeId,
      distanceMm: canonicalLength(position.value),
    }, "Moving junction…"));
    settings.append(name, rename, positionField, move);
    if (junction.sliceControlId) {
      const factor = document.createElement("input");
      const saveFactor = document.createElement("button");
      factor.type = "number";
      factor.min = "0.01";
      factor.step = "any";
      factor.placeholder = "Default 2.0";
      factor.value = junction.diameterFactor == null ? "" : `${junction.diameterFactor}`;
      factor.setAttribute("aria-label", "Junction diameter factor");
      saveFactor.type = "button";
      saveFactor.className = "button compact";
      saveFactor.textContent = "Set factor";
      saveFactor.addEventListener("click", () => mutate("set_junction_diameter_factor", {
        harnessId: harness.harnessId,
        junctionId: junction.nodeId,
        diameterFactor: factor.value.trim() === "" ? null : Number(factor.value),
      }, "Saving junction factor…"));
      settings.append(factor, saveFactor);
    }
    settings.className = "topology-junction-settings";
    card.append(heading, settings);

    const attachments = topology.junctionAttachments.filter(
      (item) => item.junctionId === junction.nodeId,
    );
    attachments.forEach((attachment) => {
      const block = document.createElement("div");
      const label = document.createElement("strong");
      const detach = actionButton("×", "Detach empty pathway", () => mutate(
        "detach_junction_pathway",
        {
          harnessId: harness.harnessId,
          junctionId: junction.nodeId,
          pathwayId: attachment.pathwayId,
          pathwayEnd: attachment.pathwayEnd,
        },
        "Detaching pathway…",
      ), false, true);
      block.className = "topology-attachment";
      label.textContent = `→ ${pathNames.get(attachment.pathwayId) || "Pathway"} · ${attachment.pathwayEnd.toUpperCase()}`;
      block.append(label, detach);
      const incoming = new Set(topology.edges.filter((edge) => (
        edge.kind === "pathway"
          && edge.pathwayId === junction.pathwayId
          && (edge.startNodeId === junction.nodeId || edge.endNodeId === junction.nodeId)
      )).map((edge) => edge.physicalWireId));
      [...incoming].sort().forEach((wireId) => {
        const row = document.createElement("label");
        const select = document.createElement("select");
        const existing = topology.junctionDispositions.find((item) => (
          item.junctionId === junction.nodeId
            && item.pathwayId === attachment.pathwayId
            && item.pathwayEnd === attachment.pathwayEnd
            && item.incomingWireId === wireId
        ));
        row.textContent = `Member ${wireId.slice(0, 8)}`;
        select.append(
          topologyOption("exclude_branch", "Exclude"),
          topologyOption("branch", "Branch"),
          topologyOption("redirect_branch", "Redirect"),
        );
        select.value = existing?.disposition || "exclude_branch";
        select.addEventListener("change", () => mutate("set_junction_disposition", {
          harnessId: harness.harnessId,
          junctionId: junction.nodeId,
          pathwayId: attachment.pathwayId,
          pathwayEnd: attachment.pathwayEnd,
          physicalWireId: wireId,
          disposition: select.value,
        }, "Updating junction member…"));
        const pigtail = document.createElement("button");
        pigtail.type = "button";
        pigtail.className = "button compact";
        pigtail.textContent = "Add pigtail end…";
        pigtail.addEventListener("click", () => mutate("edit_end_members", {
          harnessId: harness.harnessId,
          editAction: "topology_add_end",
          junctionId: junction.nodeId,
          physicalWireId: wireId,
          name: `${pathNames.get(junction.pathwayId) || "Junction"} Pigtail`,
        }, "Select the pigtail end profile…"));
        row.append(select, pigtail);
        block.append(row);
      });
      const branchAll = document.createElement("button");
      branchAll.type = "button";
      branchAll.className = "button compact";
      branchAll.textContent = "Create Y junction for all members";
      branchAll.addEventListener("click", () => mutate("branch_all_junction_members", {
        harnessId: harness.harnessId,
        junctionId: junction.nodeId,
        pathwayId: attachment.pathwayId,
        pathwayEnd: attachment.pathwayEnd,
      }, "Branching all members…"));
      block.append(branchAll);
      card.append(block);
    });

    const occupiedPathways = new Set(topology.edges.filter(
      (edge) => edge.kind === "pathway",
    ).map((edge) => edge.pathwayId));
    const available = harness.pathways.filter((item) => (
      item.pathwayId !== junction.pathwayId && !occupiedPathways.has(item.pathwayId)
    ));
    if (available.length) {
      const attachRow = document.createElement("div");
      const attachPath = document.createElement("select");
      const attachEnd = document.createElement("select");
      const attach = document.createElement("button");
      available.forEach((item) => attachPath.append(topologyOption(item.pathwayId, item.name)));
      attachEnd.append(topologyOption("a", "End A"), topologyOption("b", "End B"));
      attachPath.value = available[0].pathwayId;
      attachEnd.value = "a";
      attach.type = "button";
      attach.className = "button compact";
      attach.textContent = "Attach empty pathway";
      attach.addEventListener("click", () => mutate("attach_junction_pathway", {
        harnessId: harness.harnessId,
        junctionId: junction.nodeId,
        pathwayId: attachPath.value,
        pathwayEnd: attachEnd.value,
      }, "Attaching pathway…"));
      attachRow.className = "topology-attach-row";
      attachRow.append(attachPath, attachEnd, attach);
      card.append(attachRow);
    }
    container.append(card);
  });

  const openExits = topology.exitStates.filter((item) => item.state === "open");
  if (openExits.length) {
    const extension = document.createElement("div");
    const source = document.createElement("select");
    const targetPath = document.createElement("select");
    const targetEnd = document.createElement("select");
    const connect = document.createElement("button");
    const endName = document.createElement("input");
    const addEnd = document.createElement("button");
    openExits.forEach((item, index) => source.append(topologyOption(
      `${index}`,
      `${pathNames.get(item.pathwayId) || "Pathway"} ${item.pathwayEnd.toUpperCase()} · ${item.physicalWireId.slice(0, 8)}`,
    )));
    source.value = "0";
    harness.pathways.forEach((item) => targetPath.append(topologyOption(item.pathwayId, item.name)));
    targetPath.value = harness.pathways[0]?.pathwayId || "";
    targetEnd.append(topologyOption("a", "End A"), topologyOption("b", "End B"));
    targetEnd.value = "a";
    connect.type = "button";
    connect.className = "button compact primary";
    connect.textContent = "Extend member";
    connect.addEventListener("click", () => {
      const selected = openExits[Number(source.value) || 0];
      void mutate("extend_pathway_member", {
        harnessId: harness.harnessId,
        physicalWireId: selected.physicalWireId,
        sourcePathwayId: selected.pathwayId,
        sourceEnd: selected.pathwayEnd,
        targetPathwayId: targetPath.value,
        targetEnd: targetEnd.value,
      }, "Extending pathway member…");
    });
    endName.type = "text";
    endName.placeholder = "New end name";
    endName.setAttribute("aria-label", "New external end name");
    addEnd.type = "button";
    addEnd.className = "button compact";
    addEnd.textContent = "Add end…";
    addEnd.addEventListener("click", () => {
      const selected = openExits[Number(source.value) || 0];
      const name = endName.value.trim()
        || `${pathNames.get(selected.pathwayId) || "Pathway"} ${selected.pathwayEnd.toUpperCase()} End`;
      void mutate("edit_end_members", {
        harnessId: harness.harnessId,
        editAction: "topology_add_end",
        physicalWireId: selected.physicalWireId,
        pathwayId: selected.pathwayId,
        pathwayEnd: selected.pathwayEnd,
        name,
      }, "Select the external end profile…");
    });
    extension.className = "topology-extension-row";
    extension.append(source, targetPath, targetEnd, connect, endName, addEnd);
    container.append(extension);
  }

  topology.edges.filter((edge) => edge.kind === "extension").forEach((edge) => {
    const details = document.createElement("details");
    const summary = document.createElement("summary");
    const settings = document.createElement("div");
    const name = document.createElement("input");
    const rename = document.createElement("button");
    details.className = "topology-extension-card";
    summary.append(memberRow(
      edge.name || `Extension ${edge.edgeId.slice(0, 8)}`,
      () => {},
      [actionButton("×", "Disconnect extension", () => mutate(
        "disconnect_pathway_extension",
        { harnessId: harness.harnessId, edgeId: edge.edgeId },
        "Disconnecting extension…",
      ), false, true)],
    ));
    name.type = "text";
    name.value = edge.name || "Extension 1";
    name.setAttribute("aria-label", "Extension name");
    rename.type = "button";
    rename.className = "button compact";
    rename.textContent = "Rename extension";
    rename.addEventListener("click", () => mutate("rename_pathway_extension", {
      harnessId: harness.harnessId,
      edgeId: edge.edgeId,
      name: name.value,
    }, "Renaming extension…"));
    settings.className = "topology-junction-settings";
    settings.append(name, rename);
    details.append(summary, settings);
    container.append(details);
  });
  topology.nodes.filter((node) => node.kind === "external_end").forEach((node) => {
    const name = harness.connections.find(
      (connection) => connection.connectionId === node.connectionId,
    )?.name || "External end";
    container.append(memberRow(
      name,
      () => highlightMember(harness, "connection", node.connectionId),
      [actionButton("×", "Remove external end", () => {
        if (window.confirm && !window.confirm(`Remove ${name}?`)) return;
        void mutate("remove_external_end", {
          harnessId: harness.harnessId, nodeId: node.nodeId,
        }, "Removing wire end…");
      }, false, true)],
    ));
  });
  return container;
}
