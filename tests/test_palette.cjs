/** Run with node tests/test_palette.cjs; no Fusion or browser dependencies. */
/* global require, __dirname */
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { runInNewContext } = require('node:vm');

/** Run a synchronous regression and propagate assertion failures to the process. */
function test(name, check) {
  check();
  console.log(`PASS ${name}`);
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
    this.textContent = '';
    /** @type {Element|null} */
    this.parentElement = null;
  }
  append(...children) {
    for (const child of children) if (typeof child === 'object') child.parentElement = this;
    this.children.push(...children);
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
    return descendants(this, (child) => editorId
      ? child.dataset.editorId === editorId[1] : child.tag === selector)[0];
  }
  focus() {}
  select() {}
  showModal() { this.open = true; }
  close() { this.open = false; this.events.close(); }
  replaceChildren(...children) { this.children = children; }
  addEventListener(event, handler) { this.events[event] = handler; }
  setAttribute(key, value) { this.attributes[key] = value; }
}

/** Evaluate the complete palette script with the Fusion transport mocked. */
function palette(storage = new Map()) {
  const calls = [];
  /** @type {*} Palette functions are defined dynamically by the evaluated HTML script. */
  const context = {
    document: {
      body: new Element('body'),
      createElement: (tag) => new Element(tag),
      getElementById: () => new Element('div'),
    },
    window: { sessionStorage: {
      getItem: (key) => storage.get(key) || null,
      setItem: (key, value) => storage.set(key, value),
    } },
  };
  const html = readFileSync(join(__dirname, '..', 'palette.html'), 'utf8');
  runInNewContext(html.match(/<script>([\s\S]*?)<\/script>/)[1], context);
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
  return {
    harnessId: 'h', profiles: [{ profileId: 'profile', name: 'Profile', diameterMm: 1.5 }], controls: [],
    pathways: [{ pathwayId: 'p', name: 'lower fuse box path', startName: 'O2-sensor',
      endName: 'CAN_BUS-ctrl', orderedControlIds: [] }],
    connections: [1, 2, 3].flatMap((i) => ['a', 'b'].map((end) => ({
      connectionId: `${end}${i}`, name: `${end}${i}`, hasLinkedGeometry: true,
    }))),
    wires: [1, 2, 3].map((i) => ({ wireId: `w${i}`, wireNumber: `00${i}`,
      profileId: 'profile',
      startConnectionId: `a${i}`, endConnectionId: `b${i}`, orderedPathwayIds: ['p'],
      startEndName: i === 1 ? 'Data input' : '', endEndName: i === 1 ? 'Data output' : '',
    })),
  };
}

test('route labels use precise names and fallbacks', () => {
  const { context } = palette();
  const definition = harness();
  const rendered = context.renderWireRoutes(definition);
  const labels = descendants(rendered, (node) => node.className?.startsWith('route-node'))
    .map((node) => node.textContent);
  assert.ok(labels.includes('End A: Data input'));
  assert.ok(labels.includes('End B: Data output'));
  assert.ok(labels.includes('End A: a2'));
  assert.ok(labels.includes('lower fuse box path from O2-sensor to CAN_BUS-ctrl'));
  assert.equal(context.pathwayRouteLabel({ name: 'Pathway 01' }), 'Pathway 01 from A to B');
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

test('profile node opens wire-wide diameter popup', () => {
  const { context } = palette();
  const rendered = context.renderWireRoutes(harness());
  descendants(rendered, (node) => node.title === 'Edit wire-wide options')[0].events.click();
  const dialog = context.document.body.children[0];
  assert.equal(dialog.open, true);
  assert.equal(descendants(dialog, (node) => node.tag === 'input')[0].value, '1.5');
  descendants(dialog, (node) => node.textContent === 'Cancel')[0].events.click();
  assert.equal(context.document.body.children.length, 0);
});

test('hover scopes distinguish pathway nodes, group headings, and members', () => {
  const { context, calls } = palette();
  context.highlightMember = (_harness, type, id) => calls.push({ type, id });
  const definition = harness();
  definition.controls = [{ controlId: 'g1', name: 'Gate 1', hasLinkedGeometry: true }];
  definition.pathways[0].orderedControlIds = ['g1'];
  const routes = context.renderWireRoutes(definition);
  descendants(routes, (node) => node.className === 'route-node pathway')[0].events.mouseenter();
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
  descendants(missing, (node) => node.textContent === '+ Add End A')[0].events.click();
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
