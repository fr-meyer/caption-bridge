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
