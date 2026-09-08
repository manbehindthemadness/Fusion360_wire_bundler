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
    const error = document.createElement("div");
    error.className = "error-panel";
    error.textContent = harness.error || "The stored definition could not be loaded.";
    ui.editor.append(error);
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
      "topology",
      "Junctions & Extensions",
      `${harness.topology?.nodes?.filter((node) => node.kind === "junction").length || 0} junctions`,
      renderTopologyEditor(harness),
      false,
    ),
    editorSection(
      "wire-routes",
      "Wire Routes",
      `${harness.wires.length}`,
      renderWireRoutes(harness),
      false,
    ),
    editorSection(
      "pathways",
      "Pathways & Occupancy",
      `${harness.pathways.length}`,
      renderPathways(harness),
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
}
