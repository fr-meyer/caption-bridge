const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('app/static/app.js', 'utf8');
function code(name) {
  const start = source.indexOf('    function ' + name + '(');
  const end = source.indexOf('\n    function ', start + 1);
  assert.ok(start >= 0 && end > start);
  return source.slice(start, end);
}
function selector() {
  return {children: [], value: '', set innerHTML(_) { this.children = []; },
    appendChild(child) { this.children.push(child); }};
}
for (const reason of ['lifecycle_retired', 'lifecycle_unknown', 'execution_policy_unverified']) {
  test('selector shows disabled reason: ' + reason, () => {
    const idle = selector(), drawer = selector();
    const context = {appState: {translationModel: 'old', availableTranslationModels: [
      {id: 'old', label: 'Historical', enabled: false, reason},
      {id: 'active', label: 'Active', enabled: true, efforts: ['default', 'high']}]},
      els: {idleModelSelect: idle, drawerModelSelect: drawer},
      document: {createElement() { return {}; }}, renderModelSelectors() {}};
    vm.runInNewContext(code('populateModelDropdowns') + '\npopulateModelDropdowns();', context);
    assert.equal(idle.children[0].disabled, true);
    assert.match(idle.children[0].textContent, new RegExp(reason));
    assert.equal(drawer.value, 'old');
    assert.equal(idle.children[1].disabled, false);
  });
}
test('retired restored identity never silently selects another family', () => {
  const idle = selector();
  const context = {appState: {translationModel: 'retired', availableTranslationModels: []},
    els: {idleModelSelect: idle}, document: {createElement() { return {}; }},
    renderModelSelectors() {}};
  vm.runInNewContext(code('populateModelDropdowns') + '\npopulateModelDropdowns();', context);
  assert.equal(idle.value, 'retired');
  assert.equal(idle.children[0].disabled, true);
});
test('thinking control uses supplied execution capabilities, not model-name guessing', () => {
  const context = {appState: {availableTranslationModels: [
    {id: 'third-party', efforts: ['default', 'high']}, {id: 'mistral-large-latest', efforts: ['default']} ]}};
  vm.createContext(context);
  vm.runInContext(code('supportsHighReasoning'), context);
  assert.equal(context.supportsHighReasoning('third-party'), true);
  assert.equal(context.supportsHighReasoning('mistral-large-latest'), false);
  assert.equal(context.supportsHighReasoning('invented-latest'), false);
});
test('metadata refresh never resets player, speed, captions or requested identity', () => {
  const state = {translationModel: 'retired', segments: [{seq: 9}],
    ttsMuted: true, ttsEpoch: 7, playbackRate: 1.25};
  const originalSegments = state.segments;
  const context = {appState: state, populateModelDropdowns() {}, populateThinkingDropdowns() {}};
  vm.createContext(context);
  vm.runInContext(code('handleMessage'), context);
  context.handleMessage({type: 'translation_catalogue', available_translation_models: [],
    translation_catalogue: {fresh: false, error: 'catalogue_refresh_failed'}});
  assert.equal(state.segments, originalSegments);
  assert.equal(state.translationModel, 'retired');
  assert.equal(state.ttsMuted, true);
  assert.equal(state.ttsEpoch, 7);
  assert.equal(state.playbackRate, 1.25);
});
test('status uses metadata label; independent experimental warning persists until model reset', () => {
  function element() {
    return {textContent: '', toggles: {}, classList: {toggle(name, value) {
      this.owner.toggles[name] = value;
    }}};
  }
  const els = {idleModelHelp: element(), drawerModelHelp: element(), translationModelStatus: element()};
  for (const el of Object.values(els)) el.classList.owner = el;
  const context = {els, appState: {status: 'listening', translationModel: 'zai-glm-5-3',
    translationCatalogue: {fresh: true}, availableTranslationModels: [
      {id: 'zai-glm-5-3', label: 'Z.ai GLM 5.3', enabled: true},
      {id: 'mistral-small-latest', label: 'Mistral Small (latest)', enabled: true}]}};
  vm.createContext(context);
  vm.runInContext(code('renderModelSelectors'), context);
  for (const restored of [false, true]) {
    if (restored) context.appState = JSON.parse(JSON.stringify(context.appState));
    context.renderModelSelectors();
    assert.equal(els.translationModelStatus.textContent, 'Translation: Z.ai GLM 5.3');
    assert.equal(els.translationModelStatus.toggles.hidden, false);
    for (const help of [els.idleModelHelp, els.drawerModelHelp]) {
      assert.match(help.textContent, /Experimental caption qualification/);
      assert.match(help.textContent, /may miss or delay captions/);
      assert.match(help.textContent, /no automatic fallback/);
    }
  }
  context.appState.translationModel = 'mistral-small-latest';
  context.appState.status = 'idle_ready';
  context.renderModelSelectors();
  assert.equal(els.translationModelStatus.toggles.hidden, true);
  assert.match(els.idleModelHelp.textContent, /Account metadata verified/);
  assert.doesNotMatch(els.idleModelHelp.textContent, /Experimental caption qualification/);
  context.appState.translationCatalogue = {fresh: false};
  context.renderModelSelectors();
  assert.match(els.idleModelHelp.textContent, /Account metadata not current; refresh required/);
});
