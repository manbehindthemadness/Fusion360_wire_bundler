function relationshipAuditIssues(harness) {
  const projection = harness.relationshipMap || {};
  const issues = [...(projection.auditIssues || [])];
  const routes = new Map((projection.routes || []).map((route) => [route.wireId, route]));
  const occupancy = new Map(
    (projection.pathwayOccupancy || []).map((item) => [item.pathwayId, item.wireIds || []]),
  );
  const usage = new Map(
    (projection.connectionUsage || []).map((item) => [item.connectionId, item.endpoints || []]),
  );
  const junctions = new Map((harness.junctions || []).map((junction) => [
    `${junction.precedingPathwayId}:${junction.followingPathwayId}`,
    junction,
  ]));
  const addIssue = (code, message, memberType = "", memberId = "") => {
    if (!issues.some((issue) => issue.code === code && issue.memberId === memberId)) {
      issues.push({ code, message, memberType, memberId });
    }
  };
  harness.wires.forEach((wire) => {
    const route = routes.get(wire.wireId);
    const expectedNodes = [`connection:${wire.startConnectionId}`];
    wire.orderedPathwayIds.forEach((id, index) => {
      expectedNodes.push(`pathway:${id}`);
      const followingId = wire.orderedPathwayIds[index + 1];
      const junction = junctions.get(`${id}:${followingId}`);
      if (junction) expectedNodes.push(`junction:${junction.junctionId}`);
    });
    expectedNodes.push(`connection:${wire.endConnectionId}`);
    if (!route || JSON.stringify(route.nodeIds || []) !== JSON.stringify(expectedNodes)) {
      addIssue(
        "palette_wire_route_mismatch",
        `${wireLabel(wire)} does not match its master-graphic route.`,
        "wire",
        wire.wireId,
      );
    }
  });
  if (routes.size !== harness.wires.length) {
    addIssue(
      "palette_wire_count_mismatch",
      "Master graphic wire count disagrees with Wire Routes.",
    );
  }
  harness.pathways.forEach((pathway) => {
    const expected = harness.wires
      .filter((wire) => wire.orderedPathwayIds.includes(pathway.pathwayId))
      .map((wire) => wire.wireId);
    if (JSON.stringify(occupancy.get(pathway.pathwayId) || []) !== JSON.stringify(expected)) {
      addIssue(
        "palette_pathway_occupancy_mismatch",
        `${pathway.name} occupancy disagrees with Wire Routes.`,
        "pathway",
        pathway.pathwayId,
      );
    }
  });
  harness.connections.forEach((connection) => {
    const expected = [];
    harness.wires.forEach((wire) => {
      if (wire.startConnectionId === connection.connectionId) {
        expected.push(`${wire.wireId}:start`);
      }
      if (wire.endConnectionId === connection.connectionId) {
        expected.push(`${wire.wireId}:end`);
      }
    });
    const actual = (usage.get(connection.connectionId) || []).map(
      (endpoint) => `${endpoint.wireId}:${endpoint.end}`,
    );
    if (JSON.stringify(actual) !== JSON.stringify(expected)) {
      addIssue(
        "palette_connection_usage_mismatch",
        `${connection.name} usage disagrees with Wire Routes.`,
        "connection",
        connection.connectionId,
      );
    }
  });
  return issues;
}
