"use strict";
// Isolated software regression for production focus logic, not a browser/VoiceOver verdict.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs"), vm = require("node:vm"), path = require("node:path");
const source = fs.readFileSync(path.join(__dirname, "../../app/static/app.js"), "utf8");
const start = source.indexOf("    function renderTermEditor() {"),
    end = source.indexOf("    function sendTermChange(", start);
assert(start > 0 && end > start);
function setup({action = "save", editable = false, canUndo = true, open = true} = {}) {
    const document = {activeElement: null};
    function button() {
        let disabled = false;
        return {get disabled() {return disabled;}, set disabled(value) {
            disabled = value;
            if (value && document.activeElement === this) document.activeElement = null;
        }, focus() {document.activeElement = this;}};
    }
    const els = {termDialog: {open}, termList: {contains: () => false, replaceChildren() {}},
        termSave: button(), termUndo: button(), termClose: button(), termVersion: {textContent: ""}};
    document.activeElement = action === "save" ? els.termSave : els.termUndo;
    const context = {document, els, terminologyState: {version: 1, changes: 1, canUndo},
        appState: {targetLanguage: "en"}, activeGlossary: null,
        currentTerms: () => [], canEditTerms: () => editable};
    vm.createContext(context);
    vm.runInContext(source.slice(start, end), context);
    context.renderTermEditor();
    return {document, els};
}
for (const action of ["save", "undo"]) {
    test(action + " pending action moves focus before native disable/blur", () => {
        const {document, els} = setup({action});
        assert.equal(document.activeElement, els.termClose);
        assert.equal(els.termSave.disabled, true); assert.equal(els.termUndo.disabled, true);
    });
    test(action + " eligible action keeps focus", () => {
        const {document, els} = setup({action, editable: true});
        assert.equal(document.activeElement, action === "save" ? els.termSave : els.termUndo);
    });
}
test("undo becoming unavailable keeps focus in the dialog", () => {
    const {document, els} = setup({action: "undo", editable: true, canUndo: false});
    assert.equal(document.activeElement, els.termClose); assert.equal(els.termUndo.disabled, true);
});
test("hidden dialog does not steal focus", () => {
    const {document, els} = setup({open: false});
    assert.notEqual(document.activeElement, els.termClose);
});
