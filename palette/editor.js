function renderEditor(harness) {
  ui.editor.replaceChildren();
  ui.generateSolids.disabled = harness.status === "damaged" || !harness.wires?.length;
  ui.defaults.disabled = harness.status === "damaged";
  ui.materialDefaults.disabled = harness.status === "damaged";
  ui.addWires.disabled = harness.status === "damaged" || !harness.pathways?.length;
  ui.previewRoutes.disabled = harness.status === "damaged" || !harness.wires?.length;
  const heading = document.createElement("div");
  const title = document.createElement("h2");
  const meta = document.createElement("div");
  heading.className = "editor-heading";
  meta.className = "meta";
  title.textContent = harness.componentName;
  meta.textContent = harness.status === "damaged"
    ? "Damaged harness metadata"
    : `${harness.routingMode} · ${harness.status}`;
  heading.append(title, meta);
  ui.editor.append(heading);

  if (harness.status === "damaged") {
    closePathwayPopup();
    closeJunctionRelationships();
    const error = document.createElement("div");
    const actions = document.createElement("div");
    const remove = document.createElement("button");
    error.className = "error-panel";
    error.textContent = harness.error || "The stored definition could not be loaded.";
    actions.className = "damaged-harness-actions";
    remove.type = "button";
    remove.className = "button danger";
    remove.textContent = "Delete damaged harness";
    remove.disabled = !harness.deletionToken;
    remove.title = harness.deletionToken
      ? "Delete this damaged harness component"
      : "Refresh to locate this damaged harness component";
    remove.addEventListener("click", () => {
      if (!window.confirm(
        `Delete damaged harness “${harness.componentName}”? This removes its Fusion component and everything inside it.`,
      )) return;
      void mutate(
        "delete_damaged_harness",
        { deletionToken: harness.deletionToken },
        `Deleting damaged harness ${harness.componentName}…`,
      );
    });
    actions.append(remove);
    ui.editor.append(error, actions);
    return;
  }

  const overview = document.createElement("dl");
  const overviewRows = [
    ["Definition", harness.definitionName],
    ["Schema", harness.schemaVersion],
    ["Harness ID", harness.harnessId],
  ];
  overview.className = "overview";
  overviewRows.forEach(([label, value]) => {
    const term = document.createElement("dt");
    const description = document.createElement("dd");
    term.textContent = label;
    description.textContent = value;
    overview.append(term, description);
  });
  ui.editor.append(overview);

  const validation = document.createElement("div");
  const auditIssues = relationshipAuditIssues(harness);
  const audit = document.createElement("div");
  validation.className = "section-content";
  audit.className = `relationship-audit${auditIssues.length ? " findings" : ""}`;
  audit.textContent = auditIssues.length
    ? `Relationship cross-check found ${auditIssues.length} ${auditIssues.length === 1 ? "inconsistency" : "inconsistencies"}.`
    : "Relationship cross-check agrees with wire routes, pathway occupancy, and connection usage.";
  validation.append(audit);
  if (harness.validationMessages.length) {
    const list = document.createElement("ul");
    list.className = "validation-list errors";
    harness.validationMessages.forEach((message) => {
      const item = document.createElement("li");
      item.textContent = String(message);
      list.append(item);
    });
    validation.append(list);
  } else {
    validation.append(emptyMessage("No logical validation findings."));
  }
  if (auditIssues.length) {
    const list = document.createElement("ul");
    list.className = "validation-list errors";
    auditIssues.forEach((issue) => {
      const item = document.createElement("li");
      item.textContent = issue.message;
      if (issue.memberType && issue.memberId) {
        hoverHighlight(item, () => highlightMember(
          harness,
          issue.memberType === "wire" ? "preview_wire" : issue.memberType,
          issue.memberId,
        ));
      }
      list.append(item);
    });
    validation.append(list);
  }

  const findingCount = harness.validationMessages.length + auditIssues.length;

  ui.editor.append(
    editorSection(
      "wire-routes",
      "Wire Routes",
      `${harness.wires.length}`,
      renderWireRoutes(harness),
      false,
    ),
    editorSection(
      "validation",
      "Validation",
      findingCount ? `${findingCount} findings` : "Clear",
      validation,
      findingCount > 0,
    ),
    editorSection(
      "master-relationship-graphic",
      "Master Relationship Graphic",
      auditIssues.length ? `${auditIssues.length} findings` : `${harness.pathways.length} pathways`,
      renderRelationshipMap(harness, auditIssues),
      true,
    ),
  );
  if (openPathwayPopupId) openPathwayPopup(harness, openPathwayPopupId);
  if (openJunctionPopupId) {
    const junction = (harness.junctions || []).find(
      (candidate) => candidate.junctionId === openJunctionPopupId,
    );
    if (junction) openJunctionRelationships(harness, junction);
    else closeJunctionRelationships();
  }
}
