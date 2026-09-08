/** Run with node tests/test_palette.cjs; no Fusion or browser dependencies. */
/* global require, __dirname, process */
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { runInNewContext } = require('node:vm');

/** Run a synchronous regression and propagate assertion failures to the process. */
function test(name, check) {
  check();
  console.log(`PASS ${name}`);
}

/** Run an asynchronous regression and preserve a failing process exit status. */
function asyncTest(name, check) {
  Promise.resolve().then(check).then(
    () => console.log(`PASS ${name}`),
    (failure) => {
      console.error(`FAIL ${name}`);
      console.error(failure);
      process.exitCode = 1;
    },
  );
}

/** Minimal DOM boundary for testing the actual palette rendering and events. */
class Element {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this.dataset = {};
    this.style = {};
    /** @type {Object.<string, Function>} */
    this.events = {};
    this.attributes = {};
    this.classList = { add: (...names) => {
      this.className = [this.className || '', ...names].filter(Boolean).join(' ');
    } };
    this.textContent = '';
    this.value = '';
    this.hidden = false;
    this.clientWidth = tag === 'dialog' ? 430 : 120;
    this.clientHeight = tag === 'dialog' ? 500 : 24;
    this.scrollWidth = this.clientWidth;
    this.scrollHeight = this.clientHeight;
    /** @type {Element|null} */
    this.parentElement = null;
  }
  append(...children) {
    for (const child of children) if (typeof child === 'object') child.parentElement = this;
    this.children.push(...children);
  }
  prepend(...children) {
    for (const child of children) if (typeof child === 'object') child.parentElement = this;
    this.children.unshift(...children);
  }
  insertBefore(child, reference) {
    child.parentElement = this;
    this.children.splice(this.children.indexOf(reference), 0, child);
  }
  remove() {
    if (this.parentElement) {
      this.parentElement.children = this.parentElement.children.filter((child) => child !== this);
    }
  }
  querySelector(selector) {
    const editorId = selector.match(/data-editor-id="([^"]+)"/);
    const sectionId = selector.match(/data-section="([^"]+)"/);
    const wireId = selector.match(/data-wire-id="([^"]+)"/);
    return descendants(this, (child) => {
      if (editorId) return child.dataset.editorId === editorId[1];
      if (sectionId) return child.dataset.section === sectionId[1];
      if (wireId) return child.dataset.wireId === wireId[1];
      if (selector.startsWith('.')) return child.className?.split(' ').includes(selector.slice(1));
      return child.tag === selector;
    })[0];
  }
  querySelectorAll(selector) {
    const tags = selector.split(',').map((item) => item.trim());
    return descendants(this, (child) => tags.includes(child.tag));
  }
  focus() {}
  select() {}
  showModal() { this.open = true; }
  close() { this.open = false; if (this.events.close) this.events.close(); }
  replaceChildren(...children) {
    for (const child of children) if (typeof child === 'object') child.parentElement = this;
    this.children = children;
  }
  addEventListener(event, handler) { this.events[event] = handler; }
  setAttribute(key, value) {
    this.attributes[key] = value;
    if (key === 'class') this.className = value;
  }
  scrollIntoView() { this.scrolledIntoView = true; }
  getBoundingClientRect() {
    const width = this.clientWidth;
    const height = this.clientHeight;
    return { left: 10, top: 10, right: 10 + width, bottom: 10 + height, width, height };
  }
  getClientRects() { return this.hidden ? [] : [this.getBoundingClientRect()]; }
  dispatchEvent(event) {
    if (this.events[event.type]) this.events[event.type](event);
    return true;
  }
}

/** Evaluate the complete palette script with the Fusion transport mocked. */
function palette(storage = new Map(), preferences = storage) {
  const calls = [];
  /** @type {*} Palette functions are defined dynamically by the evaluated HTML script. */
  const context = {
    document: {
      body: new Element('body'),
      createElement: (tag) => new Element(tag),
      createElementNS: (_namespace, tag) => new Element(tag),
      getElementById: () => new Element('div'),
    },
    window: {
      innerWidth: 800,
      innerHeight: 700,
      Event: class Event { constructor(type) { this.type = type; } },
      sessionStorage: {
        getItem: (key) => storage.get(key) || null,
        setItem: (key, value) => storage.set(key, value),
        removeItem: (key) => storage.delete(key),
      },
      localStorage: {
        getItem: (key) => preferences.get(key) || null,
        setItem: (key, value) => preferences.set(key, value),
      },
    },
  };
  const html = readFileSync(join(__dirname, '..', 'palette.html'), 'utf8');
  const scripts = [...html.matchAll(/<script src="([^"]+)"><\/script>/g)]
    .map((match) => readFileSync(join(__dirname, '..', match[1]), 'utf8'));
  runInNewContext(scripts.join('\n'), context);
  context.ui = runInNewContext('ui', context);
  context.mutate = (action, payload) => calls.push({ action, payload });
  return { context, calls };
}

/** Collect rendered descendants using a predicate. */
function descendants(root, predicate) {
  return root.children.flatMap((child) => typeof child === 'object'
    ? [...(predicate(child) ? [child] : []), ...descendants(child, predicate)] : []);
}

/** Return three wires sharing one pathway and distinct endpoint profiles. */
function harness() {
  const materialDefaults = {
    insulationMaterial: 'PVC', conductorMaterial: 'Copper',
    mainColor: { name: 'Black', hex: '#202020' }, appearance: null, stripes: [],
    manufacturer: '', partNumber: '', notes: '',
  };
  const definition = {
    harnessId: 'h', profiles: [{ profileId: 'profile', name: 'Profile', diameterMm: 1.5 }], controls: [],
    componentName: 'Harness_001', definitionName: 'Harness_001', schemaVersion: 3,
    routingMode: 'Routing Gates', status: 'valid', validationMessages: [],
    materialDefaults,
    pathways: [{ pathwayId: 'p', name: 'lower fuse box path', startName: 'O2-sensor',
      endName: 'CAN_BUS-ctrl', orderedControlIds: [] }],
    connections: [1, 2, 3].flatMap((i) => ['a', 'b'].map((end) => ({
      connectionId: `${end}${i}`, name: `${end}${i}`, hasLinkedGeometry: true,
    }))),
    wires: [1, 2, 3].map((i) => ({ wireId: `w${i}`, wireNumber: `00${i}`,
      profileId: 'profile',
      materials: materialDefaults,
      materialOverrides: { insulationMaterial: null, conductorMaterial: null,
        mainColor: null, appearance: null, stripes: null, manufacturer: null,
        partNumber: null, notes: null },
      startConnectionId: `a${i}`, endConnectionId: `b${i}`, orderedPathwayIds: ['p'],
      startEndName: i === 1 ? 'Data input' : '', endEndName: i === 1 ? 'Data output' : '',
    })),
  };
  definition.relationshipMap = {
    nodes: [
      ...definition.connections.map((connection) => ({
        nodeId: `connection:${connection.connectionId}`, kind: 'connection',
        memberId: connection.connectionId, label: connection.name, missing: false,
      })),
      { nodeId: 'pathway:p', kind: 'pathway', memberId: 'p',
        label: 'lower fuse box path', missing: false },
    ],
    edges: definition.wires.flatMap((wire) => [0, 1].map((sequence) => ({
      edgeId: `wire:${wire.wireId}:segment:${sequence}`, wireId: wire.wireId, sequence,
    }))),
    routes: definition.wires.map((wire) => ({
      routeId: `wire:${wire.wireId}`, wireId: wire.wireId,
      wireNumber: wire.wireNumber, label: `Wire ${wire.wireNumber}`,
      nodeIds: [`connection:${wire.startConnectionId}`, 'pathway:p', `connection:${wire.endConnectionId}`],
      edgeIds: [0, 1].map((sequence) => `wire:${wire.wireId}:segment:${sequence}`),
    })),
    pathwayOccupancy: [{ pathwayId: 'p', wireIds: ['w1', 'w2', 'w3'] }],
    connectionUsage: definition.connections.map((connection) => ({
      connectionId: connection.connectionId,
      endpoints: definition.wires.flatMap((wire) => [
        ...(wire.startConnectionId === connection.connectionId ? [{ end: 'start', wireId: wire.wireId }] : []),
        ...(wire.endConnectionId === connection.connectionId ? [{ end: 'end', wireId: wire.wireId }] : []),
      ]),
    })),
    auditIssues: [],
  };
  return definition;
}

test('master relationship graphic is last and independently cross-checked', () => {
  const { context } = palette();
  const definition = harness();
  context.renderEditor(definition);
  const sections = Array.from(context.ui.editor.children).filter((node) => node.tag === 'details');
  assert.deepEqual(
    sections.map((section) => section.dataset.section),
    ['wire-routes', 'pathways', 'validation', 'master-relationship-graphic'],
  );
  const audit = descendants(sections[2], (node) => node.className === 'relationship-audit')[0];
  assert.match(audit.textContent, /agrees with wire routes/);
  const pathwayCards = descendants(sections[3], (node) => node.className === 'relationship-pathway-card');
  assert.equal(pathwayCards.length, 1);
  const endLists = descendants(pathwayCards[0], (node) => node.className === 'relationship-end-list');
  assert.equal(endLists.length, 2);
  assert.ok(endLists.every((list) => list.open));
  const wireGraphics = descendants(sections[0], (node) => node.className === 'wire-relationship-graphic');
  assert.equal(wireGraphics.length, 3);
  const pathwayBubble = descendants(wireGraphics[0], (node) => (
    node.className === 'relationship-node pathway'
  ))[0];
  assert.equal(pathwayBubble.attributes.width, '150');
  assert.equal(pathwayBubble.attributes.transform, undefined);
  const graphicLabels = descendants(wireGraphics[0], (node) => node.tag === 'text')
    .map((node) => node.textContent);
  assert.ok(graphicLabels.includes('Data input'));
  assert.ok(graphicLabels.includes('lower fuse box path'));
  assert.ok(graphicLabels.includes('Data output'));
  const connectors = descendants(sections[3], (node) => node.className === 'relationship-connector');
  assert.equal(connectors.length, 2);
  assert.ok(connectors.every((connector) => (
    descendants(connector, (node) => node.tag === 'path').length === 3
  )));
  endLists[0].open = false;
  endLists[0].events.toggle();
  assert.equal(descendants(connectors[0], (node) => node.tag === 'path').length, 1);
  assert.equal(sections[3].open, true);
});

test('palette entry point loads organized local style and script resources', () => {
  const html = readFileSync(join(__dirname, '..', 'palette.html'), 'utf8');
  assert.match(html, /<link rel="stylesheet" href="palette\/styles\.css">/);
  assert.deepEqual(
    [...html.matchAll(/<script src="([^"]+)"><\/script>/g)].map((match) => match[1]),
    [
      'palette/foundation.js',
      'palette/route-editors.js',
      'palette/materials.js',
      'palette/relationship-audit.js',
      'palette/wire-graphic.js',
      'palette/master-graphic.js',
      'palette/editor.js',
      'palette/host.js',
    ],
  );
  assert.doesNotMatch(html, /<style>|<script>/);
});

test('master relationship filtering, hover, navigation, and mismatch reporting work', () => {
  const { context, calls } = palette();
  const definition = harness();
  definition.relationshipMap.routes[0].nodeIds.reverse();
  const issues = context.relationshipAuditIssues(definition);
  assert.ok(issues.some((issue) => issue.code === 'palette_wire_route_mismatch'));
  context.highlightMember = (_harness, type, id) => calls.push({ type, id });
  context.renderEditor(definition);
  const graphic = context.ui.editor.children[context.ui.editor.children.length - 1];
  const filter = descendants(graphic, (node) => node.attributes['aria-label'] === 'Filter master relationship graphic')[0];
  filter.value = '002';
  filter.events.input();
  const pathwayCards = descendants(graphic, (node) => node.className === 'relationship-pathway-card');
  assert.equal(pathwayCards.length, 1);
  const entries = descendants(graphic, (node) => node.className === 'relationship-end-entry');
  assert.equal(entries.length, 2);
  entries[0].events.mouseenter();
  assert.deepEqual(calls[calls.length - 1], { type: 'connection', id: 'a2' });
  entries[0].events.click();
  const wireCard = context.ui.editor.querySelector('[data-wire-id="w2"]');
  assert.equal(wireCard.scrolledIntoView, true);
  assert.equal(wireCard.querySelector('.wire-details').hidden, false);
  const validation = context.ui.editor.querySelector('[data-section="validation"]');
  assert.ok(descendants(validation, (node) => node.textContent?.includes('does not match')).length);
});

test('expanded master traces use wire colors and stripes while pathway hubs navigate', () => {
  const storage = new Map();
  const { context } = palette(storage);
  const definition = harness();
  definition.wires[0].materials = {
    ...definition.materialDefaults,
    mainColor: { name: 'Red', hex: '#cc1122' },
    stripes: [
      { color: { name: 'White', hex: '#ffffff' }, pattern: 'solid' },
      { color: { name: 'Blue', hex: '#2255cc' }, pattern: 'dashed' },
    ],
  };
  definition.wires[1].materials = {
    ...definition.materialDefaults,
    mainColor: { name: 'Green', hex: '#228844' },
  };
  definition.wires[2].materials = {
    ...definition.materialDefaults,
    mainColor: { name: 'Yellow', hex: '#e8c51c' },
  };
  definition.wires[1].startConnectionId = 'a1';
  context.renderEditor(definition);
  const master = context.ui.editor.querySelector('[data-section="master-relationship-graphic"]');
  const connectors = descendants(master, (node) => node.className === 'relationship-connector');
  const wireTraces = descendants(connectors[0], (node) => node.className === 'wire-trace');
  assert.deepEqual(wireTraces.map((trace) => trace.attributes.stroke), [
    '#cc1122', '#228844', '#e8c51c',
  ]);
  assert.deepEqual(wireTraces.map((trace) => trace.attributes['data-wire-id']), ['w1', 'w2', 'w3']);
  const stripes = descendants(connectors[0], (node) => node.className === 'stripe-trace');
  assert.deepEqual(stripes.map((stripe) => stripe.attributes.stroke), ['#ffffff', '#2255cc']);
  assert.deepEqual(stripes.map((stripe) => stripe.attributes['stroke-dasharray']), ['none', '8 5']);
  const endList = descendants(master, (node) => node.className === 'relationship-end-list')[0];
  endList.open = false;
  endList.events.toggle();
  const collapsedTraces = descendants(connectors[0], (node) => node.tag === 'path');
  assert.equal(collapsedTraces.length, 1);
  assert.equal(collapsedTraces[0].className, 'aggregate-trace');

  const pathwaySection = context.ui.editor.querySelector('[data-section="pathway:p"]');
  descendants(master, (node) => node.className === 'relationship-pathway-hub')[0].events.click();
  assert.equal(context.ui.editor.querySelector('[data-section="pathways"]').open, true);
  assert.equal(pathwaySection.open, true);
  assert.equal(pathwaySection.scrolledIntoView, true);
  assert.match(storage.get('wireBundler.expandedSections'), /pathway:p/);
});

test('master collapse limit defaults to seven, clamps, persists, and search reveals matches', () => {
  const storage = new Map();
  const definition = harness();
  const template = definition.wires[0];
  definition.connections = Array.from({ length: 8 }, (_, index) => ['a', 'b'].map((end) => ({
    connectionId: `${end}${index + 1}`, name: `${end}${index + 1}`, hasLinkedGeometry: true,
  }))).flat();
  definition.wires = Array.from({ length: 8 }, (_, index) => ({
    ...template,
    wireId: `w${index + 1}`,
    wireNumber: `${index + 1}`.padStart(3, '0'),
    startConnectionId: `a${index + 1}`,
    endConnectionId: `b${index + 1}`,
    startEndName: index === 0 ? 'Data input' : '',
    endEndName: index === 0 ? 'Data output' : '',
  }));
  let { context } = palette(storage);
  let rendered = context.renderRelationshipMap(definition, []);
  let limit = descendants(rendered, (node) => (
    node.attributes['aria-label'] === 'Connections before end lists collapse'
  ))[0];
  assert.equal(limit.value, '7');
  let endLists = descendants(rendered, (node) => node.className === 'relationship-end-list');
  assert.ok(endLists.every((list) => !list.open));
  let connectors = descendants(rendered, (node) => node.className === 'relationship-connector');
  assert.ok(connectors.every((connector) => (
    descendants(connector, (node) => node.tag === 'path').length === 1
  )));
  const sevenConnectionHarness = {
    ...definition,
    connections: definition.connections.filter((connection) => !connection.connectionId.endsWith('8')),
    wires: definition.wires.slice(0, 7),
  };
  const boundary = context.renderRelationshipMap(sevenConnectionHarness, []);
  assert.ok(descendants(boundary, (node) => node.className === 'relationship-end-list')
    .every((list) => list.open));
  limit.value = '20';
  limit.events.change();
  endLists = descendants(rendered, (node) => node.className === 'relationship-end-list');
  assert.ok(endLists.every((list) => list.open));
  assert.equal(storage.get('wireBundler.relationshipCollapseLimit:h'), '20');
  ({ context } = palette(storage));
  rendered = context.renderRelationshipMap(definition, []);
  limit = descendants(rendered, (node) => (
    node.attributes['aria-label'] === 'Connections before end lists collapse'
  ))[0];
  assert.equal(limit.value, '20');
  limit.value = '0';
  limit.events.change();
  assert.equal(limit.value, '1');
  const filter = descendants(rendered, (node) => (
    node.attributes['aria-label'] === 'Filter master relationship graphic'
  ))[0];
  filter.value = 'Data input';
  filter.events.input();
  endLists = descendants(rendered, (node) => node.className === 'relationship-end-list');
  assert.equal(endLists[0].open, true);
  assert.equal(endLists[1].open, false);
  assert.equal(endLists[0].children[0].children[1].textContent, '1 of 8');
  connectors = descendants(rendered, (node) => node.className === 'relationship-connector');
  assert.equal(descendants(connectors[0], (node) => node.tag === 'path').length, 1);
  assert.equal(descendants(connectors[1], (node) => node.tag === 'path').length, 0);
});

test('master and per-wire graphics preserve scoped Fusion highlighting', () => {
  const { context, calls } = palette();
  const definition = harness();
  context.highlightMember = (_harness, type, id) => calls.push({ type, id });
  const master = context.renderRelationshipMap(definition, []);
  descendants(master, (node) => node.className === 'relationship-pathway-hub')[0]
    .events.mouseenter();
  assert.deepEqual(calls.pop(), { type: 'pathway_gates', id: 'p' });
  const endList = descendants(master, (node) => node.className === 'relationship-end-list')[0];
  endList.children[0].events.mouseenter();
  assert.deepEqual(calls.pop(), { type: 'pathway_wires', id: 'p' });
  descendants(master, (node) => node.className === 'relationship-end-entry')[0]
    .events.mouseenter();
  assert.deepEqual(calls.pop(), { type: 'connection', id: 'a1' });
  const wireGraphic = descendants(
    context.renderWireRoutes(definition),
    (node) => node.className === 'wire-relationship-graphic',
  )[0];
  descendants(wireGraphic, (node) => node.dataset.endpoint === 'start')[0]
    .events.mouseenter();
  assert.deepEqual(calls.pop(), { type: 'connection', id: 'a1' });
  descendants(wireGraphic, (node) => node.className === 'wire-relationship-route')[0]
    .events.mouseenter();
  assert.deepEqual(calls.pop(), { type: 'preview_wire', id: 'w1' });
});

test('interactive wire diagram replaces the old node strip and uses precise names', () => {
  const { context } = palette();
  const definition = harness();
  const rendered = context.renderWireRoutes(definition);
  const labels = descendants(rendered, (node) => node.tag === 'text')
    .map((node) => node.textContent);
  assert.ok(labels.includes('Data input'));
  assert.ok(labels.includes('Data output'));
  assert.ok(labels.includes('a2'));
  assert.ok(labels.includes('lower fuse box path'));
  assert.equal(descendants(rendered, (node) => node.className === 'route-flow').length, 0);
  assert.equal(descendants(rendered, (node) => node.className?.split(' ').includes('route-node')).length, 3);
});

test('wire diagram nodes configure ends and navigate to pathways by mouse or keyboard', () => {
  const storage = new Map();
  const { context } = palette(storage);
  const definition = harness();
  context.renderEditor(definition);
  const startNode = descendants(context.ui.editor, (node) => (
    node.dataset.editorId === 'end-a-w1'
  ))[0];
  const endNode = descendants(context.ui.editor, (node) => (
    node.dataset.editorId === 'end-b-w1'
  ))[0];
  const startEditor = descendants(context.ui.editor, (node) => node.id === 'end-a-w1')[0];
  const endEditor = descendants(context.ui.editor, (node) => node.id === 'end-b-w1')[0];
  assert.equal(startEditor.hidden, true);
  startNode.events.keydown({ key: 'Enter', preventDefault() {} });
  assert.equal(startEditor.hidden, false);
  assert.equal(startNode.attributes['aria-expanded'], 'true');
  endNode.events.click();
  assert.equal(startEditor.hidden, true);
  assert.equal(endEditor.hidden, false);
  assert.equal(startNode.attributes['aria-expanded'], 'false');
  const pathwayNode = descendants(context.ui.editor, (node) => (
    node.className === 'wire-relationship-node pathway' && node.dataset.pathwayId === 'p'
  ))[0];
  pathwayNode.events.keydown({ key: ' ', preventDefault() {} });
  const pathwaysSection = context.ui.editor.querySelector('[data-section="pathways"]');
  const pathwaySection = context.ui.editor.querySelector('[data-section="pathway:p"]');
  assert.equal(pathwaysSection.open, true);
  assert.equal(pathwaySection.open, true);
  assert.equal(pathwaySection.scrolledIntoView, true);
  assert.match(storage.get('wireBundler.expandedSections'), /pathway:p/);
});

test('each end editor contains only its own profile and sends its wire identity', () => {
  const { context, calls } = palette();
  const rendered = context.renderWireRoutes(harness());
  const editors = descendants(rendered, (node) => node.className === 'end-editor');
  assert.equal(editors.length, 6);
  for (const editor of editors) {
    assert.equal(descendants(editor, (node) => node.className === 'member-row').length, 1);
    assert.equal(descendants(editor, (node) => node.className === 'member-reference')[0].textContent, '1');
  }
  const input = descendants(editors[2], (node) => node.tag === 'input')[0];
  input.value = 'Second input';
  input.events.change();
  assert.equal(calls[0].payload.wireId, 'w2');
  assert.equal(calls[0].payload.name, 'Second input');
});

test('wire and pathway names are editable and traversal fields bracket gates', () => {
  const { context, calls } = palette();
  const wires = context.renderWireRoutes(harness());
  assert.equal(descendants(wires, (node) => node.textContent === 'Wire Name').length, 0);
  const pen = descendants(wires, (node) => node.title === 'Rename wire')[0];
  pen.events.click();
  const wireField = descendants(wires, (node) => node.attributes['aria-label'] === 'Wire name')[0];
  wireField.value = 'Signal';
  wireField.events.keydown({ key: 'Enter', preventDefault() {} });
  assert.equal(calls[0].action, 'rename_wire');
  const pathways = context.renderPathways(harness());
  const fields = descendants(pathways, (node) => node.tag === 'label');
  assert.deepEqual(fields.map((node) => node.textContent), ['Pathway Name', 'Start Name', 'End Name']);
  fields[0].children[0].value = 'New path';
  fields[0].children[0].events.change();
  assert.equal(calls[1].payload.field, 'name');
  const gateContainer = descendants(pathways, (node) => node.children.some((child) => child.textContent === 'Start Name'))[0];
  assert.equal(gateContainer.children[0].textContent, 'Start Name');
  assert.equal(gateContainer.children[1].className, 'sequence');
  assert.equal(gateContainer.children[2].textContent, 'End Name');
});

test('wire header collapses details and highlights only on hover', () => {
  const storage = new Map();
  const { context, calls } = palette(storage);
  context.highlightMember = (...args) => calls.push(args);
  const rendered = context.renderWireRoutes(harness());
  const header = descendants(rendered, (node) => node.title === 'Expand or collapse wire')[0];
  const details = descendants(rendered, (node) => node.className === 'wire-details')[0];
  assert.equal(details.hidden, true);
  header.events.click();
  assert.equal(details.hidden, false);
  assert.equal(calls.length, 0);
  header.parentElement.events.mouseenter();
  assert.equal(calls[0][1], 'preview_wire');
  assert.equal(calls[0][2], 'w1');
  const restored = palette(storage).context.renderWireRoutes(harness());
  assert.equal(descendants(restored, (node) => node.className === 'wire-details')[0].hidden, false);
  header.events.click();
  assert.equal(details.hidden, true);
  assert.equal(descendants(rendered, (node) => node.textContent === '↔').length, 0);
});

test('clearly labeled wire options combine diameter and material controls', () => {
  const { context } = palette();
  const rendered = context.renderWireRoutes(harness());
  const button = descendants(rendered, (node) => (
    node.title === 'Edit wire diameter and material options'
  ))[0];
  assert.match(button.textContent, /^Wire options · 1\.5 mm · Black PVC/);
  button.events.click();
  const dialog = context.document.body.children[0];
  assert.equal(dialog.open, true);
  assert.equal(descendants(dialog, (node) => node.tag === 'h2')[0].textContent, 'Wire options · Wire #001');
  const diameter = descendants(dialog, (node) => node.type === 'number')[0];
  assert.equal(diameter.value, '1.5');
  descendants(dialog, (node) => node.textContent === 'Cancel')[0].events.click();
  assert.equal(context.document.body.children.length, 0);
});

test('diagram stripe cues stay centered within each wire trace', () => {
  const { context } = palette();
  const definition = harness();
  definition.wires[0].materials = {
    ...definition.materialDefaults,
    stripes: [{ color: { name: 'White', hex: '#ffffff' }, pattern: 'solid' }],
  };
  const graphic = descendants(
    context.renderWireRoutes(definition),
    (node) => node.className === 'wire-relationship-graphic',
  )[0];
  const stripeLines = descendants(graphic, (node) => (
    node.tag === 'line' && node.attributes.stroke === '#ffffff'
  ));
  const baseLines = descendants(graphic, (node) => (
    node.tag === 'line' && node.attributes.stroke === '#202020'
  ));
  assert.ok(stripeLines.length > 0);
  assert.equal(stripeLines.length, baseLines.length);
  assert.ok(stripeLines.every((line, index) => (
    line.attributes.y1 === baseLines[index].attributes.y1
      && line.attributes.y2 === baseLines[index].attributes.y2
  )));
  const master = context.renderRelationshipMap(definition, []);
  const connector = descendants(master, (node) => node.className === 'relationship-connector')[0];
  const base = descendants(connector, (node) => (
    node.className === 'wire-trace' && node.attributes['data-wire-id'] === 'w1'
  ))[0];
  const stripe = descendants(connector, (node) => (
    node.className === 'stripe-trace' && node.attributes['data-wire-id'] === 'w1'
  ))[0];
  assert.equal(stripe.attributes.d, base.attributes.d);
  assert.equal(context.centeredStripeOffset(0, 2, 2), -1);
  assert.equal(context.centeredStripeOffset(1, 2, 2), 1);
});

test('hover scopes distinguish pathway nodes, group headings, and members', () => {
  const { context, calls } = palette();
  context.highlightMember = (_harness, type, id) => calls.push({ type, id });
  const definition = harness();
  definition.controls = [{ controlId: 'g1', name: 'Gate 1', hasLinkedGeometry: true }];
  definition.pathways[0].orderedControlIds = ['g1'];
  const routes = context.renderWireRoutes(definition);
  descendants(routes, (node) => node.className === 'wire-relationship-node pathway')[0]
    .events.mouseenter();
  assert.equal(calls.pop().type, 'pathway_gates');
  const pathways = context.renderPathways(definition);
  const sections = descendants(pathways, (node) => node.tag === 'details');
  sections.find((node) => node.dataset.section === 'pathway:p').children[0].events.mouseenter();
  assert.equal(calls.pop().type, 'pathway');
  sections.find((node) => node.dataset.section === 'pathway:p:gates').children[0].events.mouseenter();
  assert.equal(calls.pop().type, 'pathway_gates');
  sections.find((node) => node.dataset.section === 'pathway:p:occupancy').children[0].events.mouseenter();
  assert.equal(calls.pop().type, 'pathway_wires');
  const gateRow = descendants(pathways, (node) => node.className === 'member-row')[0];
  gateRow.events.mouseenter();
  assert.deepEqual(calls.pop(), { type: 'control', id: 'g1' });
});

test('end member controls target one member and warn before deleting the last', () => {
  const { context, calls } = palette();
  const definition = harness();
  const rendered = context.renderWireRoutes(definition);
  const editor = descendants(rendered, (node) => node.className === 'end-editor')[0];
  const replace = descendants(editor, (node) => node.title === 'Replace member')[0];
  replace.events.click();
  assert.equal(calls.pop().payload.editAction, 'replace');
  context.window.confirm = () => false;
  const remove = descendants(editor, (node) => node.title === 'Remove member')[0];
  remove.events.click();
  assert.equal(calls.length, 0);
  context.window.confirm = () => true;
  remove.events.click();
  assert.equal(calls.pop().action, 'remove_end_member');
  descendants(editor, (node) => node.title === 'Add member after this member')[0].events.click();
  assert.equal(calls.pop().payload.editAction, 'add');
  definition.connections = definition.connections.filter((connection) => connection.connectionId !== 'a1');
  const missing = context.renderWireRoutes(definition);
  descendants(missing, (node) => node.dataset.editorId === 'end-a-w1')[0].events.click();
  assert.equal(calls.pop().payload.expectedMembers, 0);
});

test('end menu retains state after replacement and palette reload', () => {
  const storage = new Map();
  const { context, calls } = palette(storage);
  const definition = harness();
  let rendered = context.renderWireRoutes(definition);
  const endA = descendants(rendered, (node) => node.dataset.editorId === 'end-a-w1')[0];
  endA.events.click();
  const editor = descendants(rendered, (node) => node.id === 'end-a-w1')[0];
  assert.equal(editor.hidden, false);
  descendants(editor, (node) => node.title === 'Replace member')[0].events.click();
  assert.equal(calls.pop().payload.editAction, 'replace');
  definition.connections[0].name = 'Replacement';
  rendered = context.renderWireRoutes(definition);
  assert.equal(descendants(rendered, (node) => node.id === 'end-a-w1')[0].hidden, false);
  assert.equal(descendants(rendered, (node) => node.dataset.editorId === 'end-a-w1')[0].attributes['aria-expanded'], 'true');
  rendered = palette(storage).context.renderWireRoutes(definition);
  assert.equal(descendants(rendered, (node) => node.id === 'end-a-w1')[0].hidden, false);
  const endB = descendants(rendered, (node) => node.dataset.editorId === 'end-b-w1')[0];
  endB.events.click();
  const restored = palette(storage).context.renderWireRoutes(definition);
  assert.equal(descendants(restored, (node) => node.id === 'end-a-w1')[0].hidden, true);
  assert.equal(descendants(restored, (node) => node.id === 'end-b-w1')[0].hidden, false);
  assert.equal(descendants(restored, (node) => node.id === 'end-a-w2')[0].hidden, true);
});

test('pointer dragging marks exact insertion and commits on release', () => {
  const { context, calls } = palette();
  const definition = harness();
  definition.connections[0].members = Array.from({length: 4}, (_, index) => ({index, hasLinkedGeometry: true}));
  const rendered = context.renderWireRoutes(definition);
  const editor = descendants(rendered, (node) => node.id === 'end-a-w1')[0];
  const rows = descendants(editor, (node) => node.dataset.reorder === 'true');
  rows[0].parentElement.getBoundingClientRect = () => ({left: 0, right: 300, top: 0, bottom: 160, x: 0, y: 0, width: 300, height: 160, toJSON() { return {}; }});
  rows.forEach((row, index) => {
    row.getBoundingClientRect = () => ({top: index * 40, height: 40});
    row.setPointerCapture = () => {};
    row.hasPointerCapture = () => true;
    row.releasePointerCapture = () => {};
  });
  const event = (y, x = 50) => ({button: 0, pointerId: 1, clientX: x, clientY: y,
    target: {closest: () => null}, preventDefault() {}});
  rows[3].events.pointerdown(event(140));
  rows[3].events.pointermove(event(55));
  assert.equal(rows[1].dataset.drop, 'before');
  rows[3].events.pointerup(event(55));
  assert.equal(calls.at(-1).action, 'move_end_member');
  assert.equal(calls.at(-1).payload.memberIndex, 3);
  assert.equal(calls.at(-1).payload.targetIndex, 1);
  assert.equal(rows[1].dataset.drop, undefined);
  rows[0].events.pointerdown(event(20));
  rows[0].events.pointermove(event(159));
  assert.equal(rows[3].dataset.drop, 'after');
  rows[0].events.pointerup(event(159));
  assert.equal(calls.at(-1).payload.targetIndex, 3);
  rows[0].events.pointerdown(event(20));
  rows[0].events.pointermove(event(55, 400));
  rows[0].events.pointerup(event(55, 400));
  assert.equal(calls.length, 2);
  rows[0].events.pointerdown(event(20));
  rows[0].events.pointermove(event(55));
  rows[0].events.pointercancel();
  rows[0].events.pointerup(event(55));
  assert.equal(calls.length, 2);
  assert.equal(rows[1].dataset.drop, undefined);
  rows[0].events.pointerdown(event(20));
  rows[0].events.pointerup(event(20));
  assert.equal(calls.length, 2);
});

test('member labels follow persistent identity instead of row position', () => {
  const { context } = palette();
  const definition = harness();
  const members = [
    { memberId: 'abcd1234-0000-0000-0000-000000000001', hasLinkedGeometry: true },
    { memberId: 'dcba4321-0000-0000-0000-000000000002', hasLinkedGeometry: true },
  ];
  definition.connections[0].members = members;
  let editor = descendants(context.renderWireRoutes(definition), (node) => node.id === 'end-a-w1')[0];
  const labels = (node) => descendants(node, (child) => child.className === 'member-reference').map((child) => child.textContent);
  assert.deepEqual(labels(editor), ['#abcd1234', '#dcba4321']);
  definition.connections[0].members = [...members].reverse();
  editor = descendants(context.renderWireRoutes(definition), (node) => node.id === 'end-a-w1')[0];
  assert.deepEqual(labels(editor), ['#dcba4321', '#abcd1234']);
});

test('gate stacks share drag placement and both stacks have a left position column', () => {
  const { context, calls } = palette();
  const definition = harness();
  definition.controls = [1, 2, 3].map((index) => ({controlId: `gate000${index}`, name: `Gate ${index}`, hasLinkedGeometry: true}));
  definition.pathways[0].orderedControlIds = definition.controls.map((gate) => gate.controlId);
  const gateRows = descendants(context.renderPathways(definition), (node) => node.dataset.reorder === 'true');
  assert.deepEqual(gateRows.map((row) => row.children[0].textContent), ['1', '2', '3']);
  assert.equal(gateRows[0].children[1].textContent, 'Gate 1 #gate0001');
  assert.equal(descendants(gateRows[0], (node) => ['↑', '↓'].includes(node.textContent)).length, 0);
  const endRows = descendants(context.renderWireRoutes(definition), (node) => node.dataset.reorder === 'true');
  assert.equal(endRows[0].children[0].className, 'sequence-position');
  assert.equal(endRows[0].children[0].textContent, '1');
  gateRows[0].parentElement.getBoundingClientRect = () => ({left: 0, right: 300, top: 0, bottom: 120, x: 0, y: 0, width: 300, height: 120, toJSON() { return {}; }});
  gateRows.forEach((row, index) => {
    row.getBoundingClientRect = () => ({top: index * 40, height: 40});
    row.setPointerCapture = () => {};
    row.hasPointerCapture = () => true;
    row.releasePointerCapture = () => {};
  });
  const event = (y) => ({button: 0, pointerId: 1, clientX: 50, clientY: y, target: {closest: () => null}, preventDefault() {}});
  gateRows[0].events.pointerdown(event(20));
  gateRows[0].events.pointermove(event(115));
  assert.equal(gateRows[2].dataset.drop, 'after');
  gateRows[0].events.pointerup(event(115));
  assert.equal(calls.at(-1).action, 'move_pathway_gate');
  assert.equal(calls.at(-1).payload.controlId, 'gate0001');
  assert.equal(calls.at(-1).payload.offset, 2);
  definition.pathways[0].orderedControlIds = ['gate0002', 'gate0003', 'gate0001'];
  const updated = descendants(context.renderPathways(definition), (node) => node.dataset.reorder === 'true');
  assert.deepEqual(updated.map((row) => row.children[0].textContent), ['1', '2', '3']);
  assert.equal(updated[2].children[1].textContent, 'Gate 1 #gate0001');
});

test('interpolation popups target native gates and ends without changing expansion state', () => {
  const storage = new Map([['wireBundler.expandedSections', '["end:h:w1:start"]']]);
  const { context } = palette(storage);
  const definition = harness();
  definition.connections.forEach((connection) => {
    connection.members = [{ memberId: `member-${connection.connectionId}`, index: 0, hasLinkedGeometry: true }];
  });
  definition.controls = [{ controlId: 'gate-001', name: 'Gate 1', hasLinkedGeometry: true,
    interpolation: { approach_mm: 3, departure_mm: null } }];
  definition.pathways[0].orderedControlIds = ['gate-001'];
  const requests = [];
  context.send = async (action, payload) => { requests.push({ action, payload }); return { ok: true }; };
  const paths = context.renderPathways(definition);
  descendants(paths, (item) => item.title === 'Gate interpolation options')[0].events.click();
  let dialog = context.document.body.children.at(-1);
  let inputs = descendants(dialog, (item) => item.tag === 'input');
  assert.equal(inputs[0].value, '3');
  assert.equal(inputs[1].value, '');
  inputs[1].value = '7';
  inputs[1].events.input();
  dialog.children[0].events.submit({ preventDefault() {} });
  assert.equal(requests[0].payload.targetId, 'gate-001');
  assert.equal(requests[0].payload.settings.departure_mm, 7);
  assert.equal(requests[0].payload.useDefaults, false);
  const wires = context.renderWireRoutes(definition);
  descendants(wires, (item) => item.title === 'End member interpolation options')[1].events.click();
  dialog = context.document.body.children.at(-1);
  inputs = descendants(dialog, (item) => item.tag === 'input');
  assert.ok(inputs[0].attributes['aria-label'].startsWith('Terminal-side'));
  dialog.children[0].events.submit({ preventDefault() {} });
  assert.equal(requests[1].payload.target, 'end');
  assert.equal(requests[1].payload.targetId, 'b1');
  assert.equal(requests[1].payload.memberId, 'member-b1');
  assert.equal(storage.get('wireBundler.expandedSections'), '["end:h:w1:start"]');
});

test('defaults popup saves both presets together and rejects invalid distances', () => {
  const { context } = palette();
  const requests = [];
  context.send = async (action, payload) => { requests.push({ action, payload }); return { ok: true }; };
  context.openInterpolationOptions(harness(), 'defaults');
  const dialog = context.document.body.children.at(-1);
  const inputs = descendants(dialog, (item) => item.tag === 'input' && item.type === 'number');
  assert.equal(inputs.length, 4);
  inputs[0].value = '-1';
  dialog.children[0].events.submit({ preventDefault() {} });
  assert.equal(requests.length, 0);
  inputs[0].value = '2.5';
  inputs[3].value = '6';
  dialog.children[0].events.submit({ preventDefault() {} });
  assert.equal(requests.length, 1);
  assert.equal(requests[0].action, 'set_interpolation');
  assert.equal(requests[0].payload.settings.approach_mm, 2.5);
  assert.equal(requests[0].payload.settings.departure_mm, null);
  assert.equal(requests[0].payload.endDefaults.departure_mm, 6);
  assert.equal(requests[0].payload.applyExisting, true);
});

test('member popup can restore inheritance without changing other members', () => {
  const { context } = palette();
  const definition = harness();
  definition.endDefaults = { approach_mm: 2, departure_mm: 5 };
  definition.connections[0].members = [
    { index: 0, memberId: 'terminal-001', interpolation: { approach_mm: 1, departure_mm: 9 }, usesDefaults: false },
    { index: 1, memberId: 'guide-002', interpolation: { approach_mm: 3, departure_mm: 7 }, usesDefaults: false },
  ];
  const requests = [];
  context.send = async (action, payload) => { requests.push({ action, payload }); return { ok: true }; };
  const wires = context.renderWireRoutes(definition);
  const buttons = descendants(wires, (item) => item.title === 'End member interpolation options');
  buttons[1].events.click();
  const dialog = context.document.body.children.at(-1);
  const inputs = descendants(dialog, (item) => item.type === 'number');
  assert.equal(inputs[1].value, '7');
  descendants(dialog, (item) => item.textContent === 'Use harness defaults')[0].events.click();
  assert.equal(inputs[1].value, '5');
  dialog.children[0].events.submit({ preventDefault() {} });
  assert.equal(requests[0].payload.memberId, 'guide-002');
  assert.equal(requests[0].payload.useDefaults, true);
});

test('solid generation requires confirmation and targets the selected harness', () => {
  const { context, calls } = palette();
  runInNewContext('currentState = { harnesses: [definition] }; selectedHarnessKey = harnessKey(definition);',
    Object.assign(context, { definition: harness() }));
  context.window.confirm = () => false;
  context.generateSolids();
  assert.equal(calls.length, 0);
  context.window.confirm = (message) => message.includes('manual edits');
  context.generateSolids();
  assert.equal(calls[0].action, 'generate_solids');
  assert.equal(calls[0].payload.harnessId, 'h');
  assert.equal(calls[0].payload.replaceExisting, true);
});

test('clear solids requires confirmation and targets the selected harness', () => {
  const { context, calls } = palette();
  runInNewContext('currentState = { harnesses: [definition] }; selectedHarnessKey = harnessKey(definition);',
    Object.assign(context, { definition: harness() }));
  context.window.confirm = () => false;
  context.clearSolids();
  assert.equal(calls.length, 0);
  context.window.confirm = (message) => message.includes('manual edits');
  context.clearSolids();
  assert.equal(calls[0].action, 'clear_solids');
  assert.equal(calls[0].payload.harnessId, 'h');
});

test('event console retains messages and marks failures', () => {
  const { context } = palette();
  context.appendNotice('Solving route preview…');
  context.appendNotice('Wire 001: dynamically adjusted transitions.');
  context.appendNotice('Wire 001: dynamically adjusted transitions.');
  context.appendNotice('Sweep failed', true);
  const entries = runInNewContext('ui.notice.children', context);
  assert.deepEqual(
    entries.map((entry) => entry.textContent),
    ['Solving route preview…', 'Wire 001: dynamically adjusted transitions.', 'Sweep failed'],
  );
  assert.equal(entries[2].className, 'notice-entry error');
});

test('event console hides diagnostics until verbose output is enabled', () => {
  const storage = new Map([
    ['wireBundler.developerMode', 'true'],
    ['wireBundler.developerConsentVersion', '1'],
  ]);
  const { context } = palette(storage);
  const message = 'Wire 001 failed. Routing diagnostic: points_mm=[(1, 2, 3)]';
  context.appendNotice(message, true);
  const entry = runInNewContext('ui.notice.children[0]', context);
  assert.equal(entry.textContent, 'Wire 001 failed.');
  runInNewContext('ui.verboseDiagnostics.checked = true; ui.verboseDiagnostics.events.change();', context);
  assert.equal(entry.textContent, message);
  assert.equal(storage.get('wireBundler.verboseDiagnostics'), 'true');
});

test('developer mode defaults off and gates verbose diagnostics', () => {
  const storage = new Map([['wireBundler.verboseDiagnostics', 'true']]);
  const { context } = palette(storage);

  assert.equal(context.ui.developerMode.checked, false);
  assert.equal(context.ui.verboseDiagnostics.disabled, true);
  assert.equal(context.ui.verboseDiagnostics.checked, false);

  context.ui.verboseDiagnostics.checked = true;
  context.ui.verboseDiagnostics.events.change();
  assert.equal(context.ui.verboseDiagnostics.checked, false);
  assert.equal(storage.get('wireBundler.verboseDiagnostics'), 'false');
});

test('developer mode requires disclosure agreement before activation', () => {
  const storage = new Map();
  const { context } = palette(storage);

  context.ui.developerMode.checked = true;
  context.ui.developerMode.events.change();
  assert.equal(context.ui.developerConsent.open, true);
  assert.equal(context.ui.developerMode.checked, false);
  assert.equal(context.ui.developerConsentEnable.disabled, true);

  context.ui.developerConsentForm.events.submit({ preventDefault() {} });
  assert.equal(context.ui.developerConsent.open, true);
  assert.equal(storage.get('wireBundler.developerMode'), 'false');

  context.ui.developerConsentAgreement.checked = true;
  context.ui.developerConsentAgreement.events.change();
  assert.equal(context.ui.developerConsentEnable.disabled, false);
  context.ui.developerConsentForm.events.submit({ preventDefault() {} });

  assert.equal(context.ui.developerConsent.open, false);
  assert.equal(context.ui.developerMode.checked, true);
  assert.equal(context.ui.verboseDiagnostics.disabled, false);
  assert.equal(storage.get('wireBundler.developerMode'), 'true');
  assert.equal(storage.get('wireBundler.developerConsentVersion'), '1');

  context.ui.developerMode.checked = false;
  context.ui.developerMode.events.change();
  assert.equal(context.ui.developerMode.checked, false);
  assert.equal(context.ui.verboseDiagnostics.disabled, true);
  assert.equal(storage.get('wireBundler.developerMode'), 'false');
});

test('developer mode and verbose diagnostics survive palette context recreation', () => {
  const preferences = new Map();
  const first = palette(new Map(), preferences).context;
  first.ui.developerMode.checked = true;
  first.ui.developerMode.events.change();
  first.ui.developerConsentAgreement.checked = true;
  first.ui.developerConsentAgreement.events.change();
  first.ui.developerConsentForm.events.submit({ preventDefault() {} });
  first.ui.verboseDiagnostics.checked = true;
  first.ui.verboseDiagnostics.events.change();

  const second = palette(new Map(), preferences).context;

  assert.equal(second.ui.developerMode.checked, true);
  assert.equal(second.ui.verboseDiagnostics.disabled, false);
  assert.equal(second.ui.verboseDiagnostics.checked, true);
});

asyncTest('developer mode QA probe observes the rendered wire DOM through a fixed target', async () => {
  const preferences = new Map([
    ['wireBundler.developerMode', 'true'],
    ['wireBundler.developerConsentVersion', '1'],
  ]);
  const { context } = palette(new Map(), preferences);
  const definition = harness();
  const sent = [];
  context.window.scrollTo = () => {};
  context.send = async (action, payload) => sent.push({ action, payload });
  runInNewContext(
    'currentState = { harnesses: [definition], notice: "" };',
    Object.assign(context, { definition }),
  );

  const result = context.window.fusionJavaScriptHandler.handle('qa_probe', JSON.stringify({
    operation: 'observe_wire',
    harnessId: 'h',
    wireId: 'w1',
    expectedLabel: 'Wire #001',
  }));
  await Promise.resolve();

  assert.equal(result, 'OK');
  assert.deepEqual(sent, [{ action: 'clear_highlight', payload: undefined }]);
  assert.equal(context.ui.libraryView.hidden, true);
  assert.equal(context.ui.editorView.hidden, false);
  assert.equal(
    context.ui.editor.querySelector('[data-wire-id="w1"]')
      .querySelector('.member-reference').textContent,
    'Wire #001',
  );
});

test('palette QA probe is denied without current developer consent', () => {
  const { context } = palette();
  const result = context.window.fusionJavaScriptHandler.handle('qa_probe', JSON.stringify({
    operation: 'observe_wire',
    harnessId: 'h',
    wireId: 'w1',
    expectedLabel: 'Wire #001',
  }));

  assert.equal(result, 'DENIED');
});

test('developer QA probe verifies the fixed wire-options dialog geometry', () => {
  const preferences = new Map([
    ['wireBundler.developerMode', 'true'],
    ['wireBundler.developerConsentVersion', '1'],
  ]);
  const { context } = palette(new Map(), preferences);
  const definition = harness();
  const sent = [];
  context.window.scrollTo = () => {};
  context.send = async (action, payload) => {
    sent.push({ action, payload });
    return action === 'get_appearance_libraries' ? { ok: true, libraries: [] } : { ok: true };
  };
  runInNewContext(
    'currentState = { harnesses: [definition], notice: "", catalog: null };',
    Object.assign(context, { definition }),
  );

  const result = context.window.fusionJavaScriptHandler.handle('qa_probe', JSON.stringify({
    operation: 'observe_wire_dialog', harnessId: 'h', wireId: 'w1',
  }));

  assert.equal(result, 'OK');
  assert.equal(context.document.body.children.some((child) => child.tag === 'dialog'), false);
  assert.deepEqual(sent[0], { action: 'get_appearance_libraries', payload: undefined });
});

test('developer QA dialog probe rejects horizontal overflow', () => {
  const preferences = new Map([
    ['wireBundler.developerMode', 'true'],
    ['wireBundler.developerConsentVersion', '1'],
  ]);
  const { context } = palette(new Map(), preferences);
  const definition = harness();
  const createElement = context.document.createElement;
  context.document.createElement = (tag) => {
    const element = createElement(tag);
    if (tag === 'dialog') element.scrollWidth = element.clientWidth + 20;
    return element;
  };
  context.window.scrollTo = () => {};
  context.send = async (action) => (
    action === 'get_appearance_libraries' ? { ok: true, libraries: [] } : { ok: true }
  );
  runInNewContext(
    'currentState = { harnesses: [definition], notice: "", catalog: null };',
    Object.assign(context, { definition }),
  );

  const result = context.window.fusionJavaScriptHandler.handle('qa_probe', JSON.stringify({
    operation: 'observe_wire_dialog', harnessId: 'h', wireId: 'w1',
  }));

  assert.equal(result, 'MISMATCH');
  assert.equal(context.document.body.children.some((child) => child.tag === 'dialog'), false);
});

test('developer QA probe dispatches fixed connection, pathway, and wire hover events', () => {
  const preferences = new Map([
    ['wireBundler.developerMode', 'true'],
    ['wireBundler.developerConsentVersion', '1'],
  ]);
  const { context } = palette(new Map(), preferences);
  const definition = harness();
  const calls = [];
  context.window.scrollTo = () => {};
  context.highlightMember = (_harness, type, id) => calls.push({ type, id });
  context.send = async (action) => calls.push({ action });
  runInNewContext(
    'currentState = { harnesses: [definition], notice: "" };',
    Object.assign(context, { definition }),
  );
  const probe = (payload) => context.window.fusionJavaScriptHandler.handle(
    'qa_probe', JSON.stringify({ harnessId: 'h', wireId: 'w1', ...payload }),
  );

  assert.equal(probe({ operation: 'hover_connection', endpoint: 'start' }), 'OK');
  assert.equal(probe({ operation: 'leave_hover' }), 'OK');
  assert.equal(probe({ operation: 'hover_pathway', pathwayId: 'p' }), 'OK');
  assert.equal(probe({ operation: 'leave_hover' }), 'OK');
  assert.equal(probe({ operation: 'hover_wire' }), 'OK');
  assert.equal(probe({ operation: 'leave_hover' }), 'OK');
  assert.deepEqual(calls, [
    { type: 'connection', id: 'a1' },
    { action: 'clear_highlight' },
    { type: 'pathway_gates', id: 'p' },
    { action: 'clear_highlight' },
    { type: 'preview_wire', id: 'w1' },
    { action: 'clear_highlight' },
  ]);
});

test('developer mode rejects stale consent and remains off after cancel or Escape', () => {
  const storage = new Map([
    ['wireBundler.developerMode', 'true'],
    ['wireBundler.developerConsentVersion', '0'],
  ]);
  const { context } = palette(storage);
  assert.equal(context.ui.developerMode.checked, false);
  assert.equal(storage.get('wireBundler.developerMode'), 'false');

  context.ui.developerMode.checked = true;
  context.ui.developerMode.events.change();
  context.ui.developerConsentCancel.events.click();
  assert.equal(context.ui.developerConsent.open, false);
  assert.equal(context.ui.developerMode.checked, false);

  context.ui.developerMode.checked = true;
  context.ui.developerMode.events.change();
  context.ui.developerConsent.events.cancel({ preventDefault() {} });
  assert.equal(context.ui.developerConsent.open, false);
  assert.equal(context.ui.developerMode.checked, false);
  assert.equal(storage.get('wireBundler.developerMode'), 'false');
});

test('developer disclosure explains capture scope and separate opt-in', () => {
  const html = readFileSync(join(__dirname, '..', 'palette.html'), 'utf8');
  assert.match(html, /Screen Recording or Accessibility permission/);
  assert.match(html, /design names, geometry, paths, and other project/);
  assert.match(html, /Each external QA run remains separately opt-in/);
  assert.match(html, /I have read and understand this disclosure and agree/);
});

test('event console exposes a bounded vertical resize control', () => {
  const styles = readFileSync(join(__dirname, '..', 'palette', 'styles.css'), 'utf8');
  assert.match(styles, /#notice \{[^}]*min-height: 72px;[^}]*max-height: 60vh;[^}]*resize: vertical;/s);
});

test('material text fields use controlled autocomplete instead of native datalists', () => {
  const { context } = palette();
  const definition = harness();
  runInNewContext('currentState = { catalog };', Object.assign(context, { catalog: {
    insulationMaterials: ['PVC', 'ETFE'], conductorMaterials: ['Copper'],
    colors: [{ name: 'Black', hex: '#202020' }], stripePatterns: [],
  } }));
  context.send = async (action) => action === 'get_appearance_libraries'
    ? { ok: true, libraries: [] } : { ok: true, appearances: [] };

  context.openMaterialOptions(definition);

  const dialog = context.document.body.children.at(-1);
  assert.equal(descendants(dialog, (item) => item.tag === 'datalist').length, 0);
  const insulation = descendants(dialog, (item) => item.type === 'text')[0];
  const choices = descendants(dialog, (item) => item.className === 'autocomplete-suggestions')[0];
  assert.equal(choices.hidden, true);
  insulation.events.click();
  assert.equal(choices.hidden, false);
  assert.deepEqual(choices.children.map((item) => item.textContent), ['PVC']);
  insulation.value = '';
  insulation.events.input();
  assert.deepEqual(choices.children.map((item) => item.textContent), ['PVC', 'ETFE']);
});

asyncTest('wire options Cancel restores the values rendered by Apply', async () => {
  const { context } = palette();
  const definition = harness();
  const requests = [];
  runInNewContext('currentState = { catalog };', Object.assign(context, { catalog: {
    insulationMaterials: ['PVC', 'ETFE'], conductorMaterials: ['Copper'],
    colors: [{ name: 'Black', hex: '#202020' }], stripePatterns: [],
  } }));
  context.send = async (action, payload) => {
    if (action === 'get_appearance_libraries') return { ok: true, libraries: [] };
    requests.push({ action, payload });
    return { ok: true };
  };

  context.openMaterialOptions(definition, definition.wires[0]);
  const dialog = context.document.body.children.at(-1);
  const diameter = descendants(dialog, (item) => item.type === 'number')[0];
  const insulation = descendants(dialog, (item) => item.type === 'text')[0];
  const override = descendants(dialog, (item) => item.type === 'checkbox')[0];
  const apply = descendants(dialog, (item) => item.textContent === 'Apply')[0];
  diameter.value = '2';
  override.checked = true;
  override.events.change();
  insulation.value = 'ETFE';

  await apply.events.click();
  assert.deepEqual(requests.map((request) => request.action), [
    'set_wire_diameter', 'set_wire_material_overrides',
  ]);
  assert.equal(requests[0].payload.diameterMm, 2);
  assert.equal(requests[1].payload.overrides.insulationMaterial, 'ETFE');

  await dialog.cancelOptions();
  assert.deepEqual(requests.map((request) => request.action), [
    'set_wire_diameter', 'set_wire_material_overrides',
    'set_wire_diameter', 'set_wire_material_overrides',
  ]);
  assert.equal(requests[2].payload.diameterMm, 1.5);
  assert.equal(
    JSON.stringify(requests[3].payload.overrides),
    JSON.stringify(definition.wires[0].materialOverrides),
  );
  assert.equal(dialog.open, false);
});

test('material dialog constrains library controls to its horizontal bounds', () => {
  const styles = readFileSync(join(__dirname, '..', 'palette', 'styles.css'), 'utf8');
  assert.match(styles, /\.material-options \{[^}]*overflow-x: hidden;/);
  assert.match(styles, /\.material-options select, \.material-options textarea \{[^}]*max-width: 100%;/s);
});

test('master relationship viewport uses a distinct darker backdrop', () => {
  const styles = readFileSync(join(__dirname, '..', 'palette', 'styles.css'), 'utf8');
  assert.match(styles, /\.relationship-map-viewport \{[^}]*background: #dfe5ea;/s);
});
