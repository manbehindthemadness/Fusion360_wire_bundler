/** Run with node tests/test_palette.cjs; no Fusion or browser dependencies. */
/* global require, __dirname, process */
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { runInNewContext } = require('node:vm');
const testNameFilter = (process.argv[2] || '').toLocaleLowerCase();

/** Return whether a regression was selected by the optional command-line filter. */
function selectedTest(name) {
  return !testNameFilter || name.toLocaleLowerCase().includes(testNameFilter);
}

/** Run a synchronous regression and propagate assertion failures to the process. */
function test(name, check) {
  if (!selectedTest(name)) return;
  check();
  console.log(`PASS ${name}`);
}

/** Run an asynchronous regression and preserve a failing process exit status. */
function asyncTest(name, check) {
  if (!selectedTest(name)) return;
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
    this.classList = {
      add: (...names) => {
        this.className = [...new Set([
          ...(this.className || '').split(' ').filter(Boolean), ...names,
        ])].join(' ');
      },
      remove: (...names) => {
        this.className = (this.className || '').split(' ')
          .filter((name) => name && !names.includes(name)).join(' ');
      },
    };
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
    if (selector.startsWith('.')) {
      const className = selector.slice(1);
      return descendants(this, (child) => child.className?.split(' ').includes(className));
    }
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
    let left = 10;
    let top = 10;
    let current = this;
    while (current) {
      left += Number.parseFloat(current.style.left || 0);
      top += Number.parseFloat(current.style.top || 0);
      current = current.parentElement;
    }
    return { left, top, right: left + width, bottom: top + height, width, height };
  }
  getClientRects() { return this.hidden ? [] : [this.getBoundingClientRect()]; }
  dispatchEvent(event) {
    if (this.events[event.type]) this.events[event.type](event);
    return true;
  }
  contains(candidate) {
    let node = candidate;
    while (node) {
      if (node === this) return true;
      node = node.parentElement;
    }
    return false;
  }
}

/** Evaluate the complete palette script with the Fusion transport mocked. */
function palette(storage = new Map(), preferences = storage) {
  const calls = [];
  /** @type {*} Palette functions are defined dynamically by the evaluated HTML script. */
  const context = {
    document: {
      body: new Element('body'),
      scrollingElement: { scrollTop: 0 },
      events: {},
      createElement: (tag) => new Element(tag),
      createElementNS: (_namespace, tag) => new Element(tag),
      getElementById: () => new Element('div'),
      addEventListener(event, handler) { this.events[event] = handler; },
      removeEventListener(event, handler) {
        if (this.events[event] === handler) delete this.events[event];
      },
      dispatchEvent(event) {
        if (this.events[event.type]) this.events[event.type](event);
      },
    },
    window: {
      innerWidth: 800,
      innerHeight: 700,
      Event: class Event { constructor(type) { this.type = type; } },
      requestAnimationFrame: (callback) => callback(),
      scrollTo: () => {},
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

test('damaged harness editor offers confirmed component deletion', () => {
  const { context, calls } = palette();
  context.window.confirm = () => true;
  context.renderEditor({
    componentName: 'Broken Harness',
    deletionToken: 'current-token',
    error: 'Stored definition is malformed.',
    status: 'damaged',
  });

  const remove = descendants(
    context.ui.editor,
    (node) => node.textContent === 'Delete damaged harness',
  )[0];
  assert.ok(remove);
  remove.events.click();
  assert.equal(calls.length, 1);
  assert.equal(calls[0].action, 'delete_damaged_harness');
  assert.equal(calls[0].payload.deletionToken, 'current-token');
});

asyncTest('empty master graphic owns Add pathway and Add junction', async () => {
  const { context, calls } = palette();
  const definition = harness();
  definition.pathways = [];
  definition.wires = [];
  context.send = async (action, payload) => {
    calls.push({ action, payload });
    return { ok: true };
  };
  runInNewContext(
    'currentState = { harnesses: [definition] }; selectedHarnessKey = "h";',
    Object.assign(context, { definition }),
  );

  const graphic = context.renderRelationshipMap(definition, []);
  const workspace = descendants(
    graphic,
    (node) => node.className === 'block-diagram-workspace',
  )[0];
  const viewport = descendants(
    workspace,
    (node) => node.className === 'block-diagram-viewport',
  )[0];
  const menu = descendants(
    workspace,
    (node) => node.className === 'relationship-map-context-menu',
  )[0];
  assert.ok(descendants(
    graphic, (node) => node.textContent === 'No pathways or junctions to display yet.',
  ).length);
  assert.equal(menu.hidden, true);
  let prevented = false;
  viewport.events.contextmenu({
    clientX: 80,
    clientY: 90,
    preventDefault: () => { prevented = true; },
  });
  assert.equal(prevented, true);
  assert.equal(menu.hidden, false);
  assert.deepEqual(menu.children.map((item) => item.textContent), ['Add pathway', 'Add junction']);
  menu.children[0].events.click();
  await Promise.resolve();
  assert.equal(menu.hidden, true);
  assert.equal(calls[0].action, 'add_pathway');
  assert.equal(calls[0].payload.harnessId, 'h');

  viewport.events.contextmenu({ clientX: 80, clientY: 90, preventDefault: () => {} });
  menu.children[1].events.click();
  await Promise.resolve();
  assert.equal(menu.hidden, true);
  assert.equal(calls[1].action, 'add_junction');
  assert.equal(calls[1].payload.harnessId, 'h');

  const html = readFileSync(join(__dirname, '..', 'palette.html'), 'utf8');
  assert.doesNotMatch(html, /id="add-pathway"/);
  const styles = readFileSync(join(__dirname, '..', 'palette', 'styles.css'), 'utf8');
  assert.match(styles, /\.relationship-map > \.block-diagram-workspace \.block-diagram-viewport \{[^}]*height: 390px;/s);
});

test('isolated junction renders without traces and retains filtering and hover', () => {
  const { context } = palette();
  const definition = harness();
  definition.pathways = [];
  definition.wires = [];
  definition.controls = [{
    controlId: 'c1', name: 'Routing Gate 01', kind: 'routing_gate', hasLinkedGeometry: true,
  }];
  definition.junctions = [{
    junctionId: 'j1', name: 'Junction 01', controlId: 'c1',
    pathwayRelationships: [],
  }];
  const calls = [];
  context.highlightMember = (_harness, type, id) => calls.push({ type, id });

  const graphic = context.renderRelationshipMap(definition, []);
  let junction = descendants(
    graphic, (node) => node.className === 'relationship-junction-hub',
  )[0];
  assert.ok(junction);
  assert.equal(junction.children[0].textContent, 'Junction 01');
  assert.equal(junction.children[1].textContent, 'Unconnected junction');
  assert.equal(descendants(
    graphic, (node) => node.className === 'relationship-connector',
  ).length, 0);
  assert.equal(descendants(
    graphic, (node) => node.className === 'relationship-chain-link',
  ).length, 0);
  junction.events.mouseenter();
  assert.deepEqual(calls, [{ type: 'junction', id: 'j1' }]);

  const filter = descendants(graphic, (node) => node.attributes['aria-label']
    === 'Filter master relationship graphic')[0];
  filter.value = 'missing';
  filter.events.input();
  assert.ok(descendants(
    graphic, (node) => node.textContent === 'No relationships match this filter.',
  ).length);
  filter.value = 'junction 01';
  filter.events.input();
  junction = descendants(
    graphic, (node) => node.className === 'relationship-junction-hub',
  )[0];
  assert.ok(junction);
});

asyncTest('junction popup shows only its collapsed relationship stack and one add control', async () => {
  const { context, calls } = palette();
  const definition = harness();
  definition.pathways.push({
    pathwayId: 'p2', name: 'Branch', startName: '', endName: '', orderedControlIds: [],
  });
  definition.junctions = [
    { junctionId: 'j1', name: 'Intersection', controlId: 'c1', pathwayRelationships: [
      { pathwayId: 'p', endpoint: 'end' },
    ] },
    { junctionId: 'j2', name: 'Owner', controlId: 'c2', pathwayRelationships: [
      { pathwayId: 'p2', endpoint: 'start' },
    ] },
  ];

  const rendered = context.renderRelationshipMap(definition, []);
  descendants(rendered, (node) => (
    node.className === 'relationship-junction-hub'
      && node.children[0].textContent === 'Intersection'
  ))[0].events.click();
  const dialog = context.document.body.querySelector('.junction-relationships-popup');
  const stack = descendants(
    dialog, (node) => node.className === 'junction-relationship-stack',
  )[0];
  assert.ok(!stack.open);
  assert.equal(descendants(dialog, (node) => node.tag === 'input').length, 0);
  const rows = descendants(dialog, (node) => node.className === 'member-row');
  assert.equal(rows.length, 1);
  assert.equal(descendants(
    rows[0], (node) => node.className === 'member-reference',
  )[0].textContent, 'lower fuse box path · End B');
  assert.equal(descendants(
    dialog, (node) => ['Branch', 'Owner'].includes(node.textContent),
  ).length, 0);
  descendants(rows[0], (node) => node.textContent === '×')[0].events.click();
  assert.equal(calls[0].action, 'remove_junction_relationship');
  assert.equal(calls[0].payload.pathwayId, 'p');
  runInNewContext(
    'currentState = { harnesses: [definition] }; selectedHarnessKey = "h";',
    Object.assign(context, { definition }),
  );
  context.send = async (action, payload) => {
    calls.push({ action, payload });
    return { ok: true };
  };
  const add = descendants(dialog, (node) => node.textContent === '+ Add Relationship')[0];
  add.events.click();
  await Promise.resolve();

  assert.equal(calls.at(-1).action, 'add_junction_relationship');
  assert.equal(calls.at(-1).payload.junctionId, 'j1');
});

asyncTest('junction relationship removal warns only for traversing wire pathways', async () => {
  const { context, calls } = palette();
  const definition = harness();
  definition.pathways.push({
    pathwayId: 'p2', name: 'Branch', startName: '', endName: '', orderedControlIds: [],
  });
  definition.junctions = [{
    junctionId: 'j1', name: 'Intersection', controlId: 'c1', pathwayRelationships: [
      { pathwayId: 'p', endpoint: 'end' },
      { pathwayId: 'p2', endpoint: 'start' },
    ],
  }];
  definition.wires.forEach((wire) => { wire.orderedPathwayIds = ['p', 'p2']; });
  const confirmations = [];
  context.window.confirm = (message) => {
    confirmations.push(message);
    return confirmations.length > 1;
  };

  const rendered = context.renderRelationshipMap(definition, []);
  descendants(rendered, (node) => node.className === 'relationship-junction-hub')[0]
    .events.click();
  const dialog = context.document.body.querySelector('.junction-relationships-popup');
  const removes = descendants(dialog, (node) => node.textContent === '×');
  removes[0].events.click();
  await Promise.resolve();
  assert.equal(calls.length, 0);
  assert.match(confirmations[0], /3 wire pathways traverse/);

  removes[0].events.click();
  await Promise.resolve();
  assert.equal(calls[0].action, 'remove_junction_relationship');
  assert.equal(calls[0].payload.pathwayId, 'p');
});

test('branching topology renders each incident endpoint once', () => {
  const { context } = palette();
  const definition = harness();
  definition.pathways.push(
    { pathwayId: 'p2', name: 'Branch A', startName: '', endName: '', orderedControlIds: [] },
    { pathwayId: 'p3', name: 'Branch B', startName: '', endName: '', orderedControlIds: [] },
  );
  definition.junctions = [{
    junctionId: 'j1', name: 'Intersection', controlId: 'c1', pathwayRelationships: [
      { pathwayId: 'p', endpoint: 'end' },
      { pathwayId: 'p2', endpoint: 'start' },
      { pathwayId: 'p3', endpoint: 'start' },
    ],
  }];

  const rendered = context.renderRelationshipMap(definition, []);
  const overlay = descendants(
    rendered, (node) => node.className === 'relationship-topology-edges',
  )[0];

  assert.equal(descendants(
    rendered, (node) => node.className === 'relationship-pathway-hub',
  ).length, 3);
  assert.equal(descendants(
    rendered, (node) => node.className === 'relationship-junction-hub',
  ).length, 1);
  assert.equal(descendants(
    overlay, (node) => node.className === 'structural-trace',
  ).length, 3);
});

asyncTest('pathway node context menu adds a refine to that pathway', async () => {
  const { context, calls } = palette();
  const definition = harness();
  context.send = async (action, payload) => {
    calls.push({ action, payload });
    return { ok: true };
  };
  const graphic = context.renderRelationshipMap(definition, []);
  const workspace = descendants(
    graphic,
    (node) => node.className === 'block-diagram-workspace',
  )[0];
  const hub = descendants(
    workspace,
    (node) => node.className === 'relationship-pathway-hub',
  )[0];
  const menu = descendants(
    workspace,
    (node) => node.className === 'relationship-map-context-menu',
  )[0];
  let prevented = false;
  let stopped = false;

  hub.events.contextmenu({
    clientX: 120,
    clientY: 140,
    preventDefault: () => { prevented = true; },
    stopPropagation: () => { stopped = true; },
  });

  assert.equal(prevented, true);
  assert.equal(stopped, true);
  assert.equal(menu.hidden, false);
  assert.equal(menu.children[0].textContent, 'Add refine point');
  const nestedMenuTarget = new Element('span');
  menu.children[0].append(nestedMenuTarget);
  context.document.dispatchEvent({ type: 'mousedown', target: nestedMenuTarget });
  assert.equal(menu.hidden, false);
  let outsidePrevented = false;
  let outsideStopped = false;
  context.document.dispatchEvent({
    type: 'mousedown',
    target: workspace,
    preventDefault: () => { outsidePrevented = true; },
    stopPropagation: () => { outsideStopped = true; },
  });
  assert.equal(menu.hidden, true);
  assert.equal(outsidePrevented, false);
  assert.equal(outsideStopped, false);

  hub.events.contextmenu({
    clientX: 120,
    clientY: 140,
    preventDefault: () => {},
    stopPropagation: () => {},
  });
  menu.children[0].events.click();
  await Promise.resolve();
  assert.equal(menu.hidden, true);
  assert.equal(calls[0].action, 'add_pathway_refine');
  assert.equal(calls[0].payload.harnessId, 'h');
  assert.equal(calls[0].payload.pathwayId, 'p');
});

asyncTest('pathway context menu segments eligible controls and renders its junction', async () => {
  const { context, calls } = palette();
  const definition = harness();
  definition.controls = [1, 2, 3].map((index) => ({
    controlId: `c${index}`, name: `Routing Gate 0${index}`, kind: 'routing_gate',
  }));
  definition.pathways[0].orderedControlIds = ['c1', 'c2', 'c3'];
  context.send = async (action, payload) => {
    calls.push({ action, payload });
    return { ok: true };
  };
  let graphic = context.renderRelationshipMap(definition, []);
  let workspace = descendants(
    graphic, (node) => node.className === 'block-diagram-workspace',
  )[0];
  let hub = descendants(
    workspace, (node) => node.className === 'relationship-pathway-hub',
  )[0];
  let menu = descendants(
    workspace, (node) => node.className === 'relationship-map-context-menu',
  )[0];
  hub.events.contextmenu({
    clientX: 120, clientY: 140, preventDefault: () => {}, stopPropagation: () => {},
  });
  assert.equal(menu.children[1].textContent, 'Segment');
  assert.equal(menu.children[1].disabled, false);
  menu.children[1].events.click();
  await Promise.resolve();
  assert.equal(calls[0].action, 'segment_pathway');
  assert.equal(calls[0].payload.pathwayId, 'p');

  definition.pathways = [
    { ...definition.pathways[0], orderedControlIds: ['c1'] },
    { pathwayId: 'p2', name: 'lower fuse box path ext 1', startName: '',
      endName: 'CAN_BUS-ctrl', orderedControlIds: ['c3'] },
  ];
  definition.pathways[0].endName = '';
  definition.junctions = [{ junctionId: 'j1', name: 'Junction 01', controlId: 'c2',
    pathwayRelationships: [
      { pathwayId: 'p', endpoint: 'end' },
      { pathwayId: 'p2', endpoint: 'start' },
    ] }];
  definition.wires.forEach((wire) => { wire.orderedPathwayIds = ['p', 'p2']; });
  graphic = context.renderRelationshipMap(definition, []);
  workspace = descendants(graphic, (node) => node.className === 'block-diagram-workspace')[0];
  const junction = descendants(
    workspace, (node) => node.className === 'relationship-junction-hub',
  )[0];
  const endLists = descendants(
    workspace, (node) => node.className?.startsWith('relationship-end-list'),
  );
  const connectors = descendants(
    workspace, (node) => node.className === 'relationship-connector',
  );
  const junctionLinks = descendants(
    workspace, (node) => node.className === 'relationship-topology-edges',
  );
  const pathwayGroup = descendants(
    workspace, (node) => node.className === 'relationship-pathway-group',
  )[0];
  assert.ok(junction);
  assert.equal(junction.children[0].textContent, 'Junction 01');
  assert.deepEqual(endLists.map((list) => [list.dataset.pathwayId, list.dataset.endpoint]), [
    ['p', 'start'], ['p', 'end'], ['p2', 'start'], ['p2', 'end'],
  ]);
  assert.deepEqual(endLists.map((list) => descendants(
    list, (node) => node.className === 'relationship-end-entry',
  ).length), [3, 0, 0, 3]);
  assert.equal(connectors.length, 4);
  assert.ok(connectors.every((connector) => descendants(
    connector, (node) => node.className === 'wire-trace',
  ).length === 3));
  assert.equal(junctionLinks.length, 1);
  assert.equal(descendants(
    junctionLinks[0], (node) => node.className === 'structural-trace',
  ).length, 2);
  assert.equal(descendants(
    junctionLinks[0], (node) => node.className === 'wire-trace',
  ).length, 6);
  assert.equal(pathwayGroup.style.gridTemplateColumns, [
    '210px', '32px', '154px', '32px', 'max-content',
  ].join(' '));
  assert.equal(pathwayGroup.style.width, undefined);
  junction.events.mouseenter();
  await Promise.resolve();
  assert.equal(calls.at(-1).action, 'highlight_member');
  assert.equal(calls.at(-1).payload.memberType, 'junction');
  assert.equal(calls.at(-1).payload.memberId, 'j1');
});

test('multi-junction chains retain pathway ends and continuous procedural traces', () => {
  const { context } = palette();
  const definition = harness();
  definition.pathways = [
    definition.pathways[0],
    { pathwayId: 'p2', name: 'path ext 1', startName: '', endName: '', orderedControlIds: [] },
    { pathwayId: 'p3', name: 'path ext 2', startName: '', endName: 'finish', orderedControlIds: [] },
  ];
  definition.junctions = [
    { junctionId: 'j1', name: 'Junction 01', controlId: 'c1',
      pathwayRelationships: [
        { pathwayId: 'p', endpoint: 'end' },
        { pathwayId: 'p2', endpoint: 'start' },
      ] },
    { junctionId: 'j2', name: 'Junction 02', controlId: 'c2',
      pathwayRelationships: [
        { pathwayId: 'p2', endpoint: 'end' },
        { pathwayId: 'p3', endpoint: 'start' },
      ] },
  ];
  definition.wires.forEach((wire) => { wire.orderedPathwayIds = ['p', 'p2', 'p3']; });

  const rendered = context.renderRelationshipMap(definition, []);
  const endLists = descendants(
    rendered, (node) => node.className?.startsWith('relationship-end-list'),
  );
  const junctionLinks = descendants(
    rendered, (node) => node.className === 'relationship-topology-edges',
  );

  assert.equal(endLists.length, 6);
  assert.deepEqual(endLists.map((list) => descendants(
    list, (node) => node.className === 'relationship-end-entry',
  ).length), [3, 0, 0, 0, 0, 3]);
  assert.equal(junctionLinks.length, 1);
  assert.equal(descendants(
    junctionLinks[0], (node) => node.className === 'structural-trace',
  ).length, 4);
  assert.equal(descendants(
    junctionLinks[0], (node) => node.className === 'wire-trace',
  ).length, 12);
  const topologyNodes = descendants(
    rendered, (node) => node.className?.split(' ').includes('relationship-topology-node'),
  );
  const lefts = topologyNodes.map((node) => Number.parseFloat(node.style.left));
  assert.ok(lefts.every(Number.isFinite));
  assert.ok([...new Set(lefts)].sort((left, right) => left - right)
    .every((left, index, ordered) => index === 0 || left - ordered[index - 1] <= 200));
  const structuralPaths = descendants(
    junctionLinks[0], (node) => node.className === 'structural-trace',
  );
  assert.ok(structuralPaths.every((path) => {
    const coordinates = path.attributes.d.match(/-?\d+(?:\.\d+)?/g).map(Number);
    return coordinates[6] - coordinates[0] <= 60;
  }));

  definition.wires = [];
  const unoccupied = context.renderRelationshipMap(definition, []);
  const structuralLinks = descendants(
    unoccupied, (node) => node.className === 'relationship-topology-edges',
  );
  assert.equal(descendants(
    structuralLinks[0], (node) => node.className === 'structural-trace',
  ).length, 4);

  const styles = readFileSync(join(__dirname, '..', 'palette', 'styles.css'), 'utf8');
  assert.match(styles, /\.relationship-pathway-group \{[^}]*gap: 0;[^}]*width: max-content;/s);
  assert.match(styles, /\.relationship-chain-link \{[^}]*margin-inline: -1px;/s);
  assert.match(styles, /\.relationship-connector \{[^}]*margin-inline: -1px;/s);
});

test('relationship diagrams use zoomable pannable floating workspaces', () => {
  const { context } = palette();
  const definition = harness();
  const perWire = context.renderWireRelationshipGraphic(
    definition, definition.wires[0], new Map(), new Map(), new Element('div'), new Element('div'),
  );
  const master = context.renderRelationshipMap(definition, []);
  for (const diagram of [perWire, master]) {
    assert.equal(descendants(
      diagram, (node) => node.className === 'block-diagram-workspace',
    ).length, 1);
    const viewport = descendants(
      diagram, (node) => node.className === 'block-diagram-viewport',
    )[0];
    const stage = descendants(
      diagram, (node) => node.className === 'block-diagram-stage',
    )[0];
    const zoom = descendants(
      diagram, (node) => node.className === 'block-diagram-zoom',
    )[0];
    const zoomIn = descendants(diagram, (node) => node.title === 'Zoom in')[0];
    const initialZoom = zoom.textContent;
    zoomIn.events.click();
    assert.notEqual(zoom.textContent, initialZoom);
    let prevented = false;
    viewport.events.wheel({
      deltaY: -1, clientX: 50, clientY: 40,
      preventDefault: () => { prevented = true; },
    });
    assert.equal(prevented, true);
    const beforePan = stage.style.transform;
    viewport.events.pointerdown({
      button: 0, pointerId: 7, clientX: 30, clientY: 30, target: viewport,
    });
    viewport.events.pointermove({ pointerId: 7, clientX: 50, clientY: 60 });
    viewport.events.pointerup({ pointerId: 7 });
    assert.notEqual(stage.style.transform, beforePan);
    assert.equal(viewport.className.includes('panning'), false);
  }
});
test('master relationship graphic is last and independently cross-checked', () => {
  const { context } = palette();
  const definition = harness();
  context.renderEditor(definition);
  const sections = Array.from(context.ui.editor.children).filter((node) => node.tag === 'details');
  assert.deepEqual(
    sections.map((section) => section.dataset.section),
    ['wire-routes', 'validation', 'master-relationship-graphic'],
  );
  const audit = descendants(sections[1], (node) => node.className === 'relationship-audit')[0];
  assert.match(audit.textContent, /agrees with wire routes/);
  const pathwayCards = descendants(
    sections[2], (node) => node.className === 'relationship-pathway-group',
  );
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
  const connectors = descendants(sections[2], (node) => node.className === 'relationship-connector');
  assert.equal(connectors.length, 2);
  assert.ok(connectors.every((connector) => (
    descendants(connector, (node) => node.tag === 'path').length === 3
  )));
  endLists[0].open = false;
  endLists[0].events.toggle();
  assert.equal(descendants(connectors[0], (node) => node.tag === 'path').length, 1);
  assert.equal(sections[2].open, true);
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
  const pathwayCards = descendants(graphic, (node) => node.className === 'relationship-pathway-group');
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

test('expanded master traces use wire colors and pathway hubs open their popup', () => {
  const { context } = palette();
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

  descendants(master, (node) => node.className === 'relationship-pathway-hub')[0].events.click();
  const popup = context.document.body.querySelector('.pathway-popup');
  const pathwaySection = popup.querySelector('[data-section="pathway:p"]');
  assert.equal(context.ui.editor.querySelector('[data-section="pathways"]'), undefined);
  assert.equal(popup.open, true);
  assert.equal(pathwaySection.open, true);
  assert.deepEqual(
    descendants(pathwaySection, (node) => node.tag === 'label').map((node) => node.textContent),
    ['Pathway Name', 'Start Name', 'End Name'],
  );
  definition.pathways[0].name = 'Updated pathway';
  context.renderEditor(definition);
  const refreshedPopup = context.document.body.querySelector('.pathway-popup');
  assert.equal(context.document.body.querySelectorAll('.pathway-popup').length, 1);
  assert.equal(refreshedPopup.querySelector('[data-section="pathway:p"]').children[0]
    .children[0].textContent, 'Updated pathway');
  descendants(refreshedPopup, (node) => node.textContent === 'Close')[0].events.click();
  assert.equal(context.document.body.querySelector('.pathway-popup'), undefined);
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
  assert.equal(descendants(connectors[1], (node) => node.tag === 'path').length, 1);
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

test('wire diagram nodes configure ends and open pathway popup by mouse or keyboard', () => {
  const { context } = palette();
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
  const popup = context.document.body.querySelector('.pathway-popup');
  const pathwaySection = popup.querySelector('[data-section="pathway:p"]');
  assert.equal(popup.open, true);
  assert.equal(pathwaySection.open, true);
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

test('junction-related pathway boundary stays locked while interior gates remain draggable', () => {
  const { context, calls } = palette();
  const definition = harness();
  definition.controls = [1, 2, 3].map((index) => ({
    controlId: `gate000${index}`, name: `Gate ${index}`, hasLinkedGeometry: true,
  }));
  definition.pathways[0].orderedControlIds = definition.controls.map((gate) => gate.controlId);
  definition.junctions = [{
    junctionId: 'j1', name: 'Junction 01', controlId: 'junction-gate',
    pathwayRelationships: [{ pathwayId: 'p', endpoint: 'start' }],
  }];

  const rendered = context.renderPathways(definition);
  const locked = descendants(rendered, (node) => node.dataset.reorder === 'locked');
  const movable = descendants(rendered, (node) => node.dataset.reorder === 'true');

  assert.equal(locked.length, 1);
  assert.match(locked[0].title, /preserved by a junction/);
  assert.equal(descendants(locked[0], (node) => node.title === 'Remove gate')[0].disabled, true);
  assert.equal(movable.length, 2);
  assert.equal(calls.length, 0);
});

test('pathway popup replaces its traversal stack before a delayed close event', () => {
  const { context } = palette();
  const definition = harness();
  definition.controls = [1, 2].map((index) => ({
    controlId: `gate000${index}`, name: `Gate ${index}`, kind: 'gate', hasLinkedGeometry: true,
  }));
  definition.pathways[0].orderedControlIds = ['gate0001', 'gate0002'];
  context.openPathwayPopup(definition, 'p');
  const stalePopup = context.document.body.querySelector('.pathway-popup');
  stalePopup.close = () => { stalePopup.open = false; };

  const updated = JSON.parse(JSON.stringify(definition));
  updated.controls = updated.controls.slice(1);
  updated.pathways[0].orderedControlIds = ['gate0002'];
  context.renderEditor(updated);

  const refreshedPopup = context.document.body.querySelector('.pathway-popup');
  const gateRows = descendants(refreshedPopup, (node) => node.dataset.reorder === 'true');
  assert.notEqual(refreshedPopup, stalePopup);
  assert.equal(context.document.body.children.includes(stalePopup), false);
  assert.equal(gateRows.length, 1);
  assert.equal(gateRows[0].children[1].textContent, 'Gate 2 #gate0002');
});

asyncTest('pathway popup opens interactive refine placement', async () => {
  const { context } = palette();
  const definition = harness();
  const requests = [];
  context.send = async (action, payload) => {
    requests.push({ action, payload });
    return { ok: true };
  };
  const paths = context.renderPathways(definition);
  const button = descendants(paths, (node) => node.textContent === '+ Add Refine Point')[0];

  button.events.click();
  await Promise.resolve();

  assert.equal(requests[0].action, 'add_pathway_refine');
  assert.equal(requests[0].payload.harnessId, 'h');
  assert.equal(requests[0].payload.pathwayId, 'p');
});

asyncTest('refine stack row highlights its marker and opens transform editing', async () => {
  const { context, calls } = palette();
  const definition = harness();
  definition.controls = [{
    controlId: 'refine-001', name: 'Refine Point 01', kind: 'refine', hasLinkedGeometry: true,
    interpolation: { approach_mm: null, departure_mm: null }, usesDefaults: true,
  }];
  definition.pathways[0].orderedControlIds = ['refine-001'];
  context.highlightMember = (_harness, type, id) => calls.push({ type, id });
  const requests = [];
  context.send = async (action, payload) => {
    requests.push({ action, payload });
    return { ok: true };
  };
  const paths = context.renderPathways(definition);
  const row = descendants(paths, (node) => node.className === 'member-row')[0];

  row.events.mouseenter();
  assert.deepEqual(calls.pop(), { type: 'control', id: 'refine-001' });
  descendants(row, (node) => node.title === 'Move, rotate, or resize refine point')[0]
    .events.click();
  await Promise.resolve();

  assert.equal(requests[0].action, 'edit_pathway_refine');
  assert.equal(requests[0].payload.controlId, 'refine-001');
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

asyncTest('developer visual QA probe verifies the relationship-diagram structure', async () => {
  const preferences = new Map([
    ['wireBundler.developerMode', 'true'],
    ['wireBundler.developerConsentVersion', '1'],
  ]);
  const { context } = palette(new Map(), preferences);
  const definition = harness();
  definition.pathways.push({
    pathwayId: 'p2', name: 'lower fuse box path ext 1', startName: '', endName: '',
    orderedControlIds: [],
  });
  definition.junctions = [{
    junctionId: 'j1', name: 'Junction 01', controlId: 'c1',
    pathwayRelationships: [
      { pathwayId: 'p', endpoint: 'end' },
      { pathwayId: 'p2', endpoint: 'start' },
    ],
  }];
  definition.wires.forEach((wire) => { wire.orderedPathwayIds = ['p', 'p2']; });
  const sent = [];
  context.window.scrollTo = () => {};
  context.send = async (action, payload) => sent.push({ action, payload });
  runInNewContext(
    'currentState = { harnesses: [definition], notice: "" };',
    Object.assign(context, { definition }),
  );

  const result = context.window.fusionJavaScriptHandler.handle(
    'qa_probe', JSON.stringify({ operation: 'observe_relationship_diagram' }),
  );
  await Promise.resolve();

  assert.equal(result, 'OK');
  assert.equal(JSON.stringify(sent), JSON.stringify([{
    action: 'qa_diagram_observation',
    payload: {
      status: 'passed',
      connectorCount: 20,
      maximumEndpointGap: 0,
      contractVersion: '2',
      layout: 'endpoint-junction-forest',
    },
  }]));
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
