// Production terminology functions in a bounded DOM model. No browser or I/O beyond source reads.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const root = path.resolve(__dirname, "../..");
const source = fs.readFileSync(path.join(root, "app/static/app.js"), "utf8");
function slice(start, end) {
    const a = source.indexOf(start), b = source.indexOf(end, a);
    assert(a >= 0 && b > a, "production function boundaries");
    return source.slice(a, b);
}
const functions = slice("    function canEditTerms()", "    function restoreTerminologyState(") +
    slice("    function openTermEditor(entry)", "    function saveCaptionTerm()");
function model() {
    const context = vm.createContext({});
    vm.runInContext(`
        var document = {activeElement:null};
        class Element {
            constructor(tag='div') {
                this.tagName=tag.toUpperCase(); this.children=[]; this.parentElement=null;
                this.isConnected=false; this.disabled=false; this.hidden=false; this.inert=false;
                this.dataset={}; this.attributes={}; this.listeners={}; this.value=''; this.textContent='';
                this.classList={add(){},remove(){}};
            }
            attach(connected) { this.isConnected=connected;this.children.forEach(el=>el.attach(connected)); }
            appendChild(el) { this.children.push(el);el.parentElement=this;el.attach(this.isConnected); }
            contains(el) { for (;el;el=el.parentElement) if (el===this) return true;return false; }
            replaceChildren() {
                if (this.children.some(el=>el.contains(document.activeElement))) document.activeElement=document.body;
                this.children.forEach(el=>{el.attach(false);el.parentElement=null;});this.children=[];
            }
            setAttribute(name,value) { this.attributes[name]=String(value); }
            getAttribute(name) { return this.attributes[name] ?? null; }
            addEventListener(name,callback) { this.listeners[name]=callback; }
            closest(selector) {
                assertSelector(selector);
                for (var el=this;el;el=el.parentElement) if (el.inert) return el;
                return null;
            }
            getClientRects() {
                for (var el=this;el;el=el.parentElement) if (el.hidden) return [];
                return this.isConnected ? [{}] : [];
            }
            focus() {
                if (this.isConnected && !this.disabled && this.getClientRects().length && !this.closest('[inert]'))
                    document.activeElement=this;
            }
            showModal() { this.open=true; }
            close() { this.open=false; }
        }
        function assertSelector(selector) { if (selector!=='[inert]') throw Error('unexpected selector'); }
        document.createElement=tag=>new Element(tag);
        document.body=new Element('body');document.body.attach(true);document.activeElement=document.body;
        var els={};
        ['termDialog','termList','termVersion','termSource','termPreferred','termKind','termCaption',
         'termError','termSave','termUndo','termClose','captionLog','statusLabel'].forEach(name=>els[name]=new Element());
        document.body.appendChild(els.termDialog);document.body.appendChild(els.captionLog);
        document.body.appendChild(els.statusLabel);
        ['termList','termVersion','termSource','termPreferred','termKind','termCaption','termError',
         'termSave','termUndo','termClose'].forEach(name=>els.termDialog.appendChild(els[name]));
        var window={getSelection:()=>({anchorNode:null})};
        var appState={status:'listening',targetLanguage:'en'};
        var terminologyState={sessionId:'synthetic-session',version:1,canUndo:true,changes:1};
        var activeGlossary={target_language:'en',entries:[
            {source:'alpha',preferred:'A',kind:'target'}, {source:'beta',preferred:'B',kind:'source'}]};
        var termPending=false,termContext={language:'en',version:1},modalReturnFocus=new WeakMap();
        var sent=[];function send(msg) { sent.push(msg); }
        function opener() { var el=new Element('button');document.body.appendChild(el);el.focus();return el; }
    ` + functions, context);
    return context;
}
function run(context, code) { return vm.runInContext(code, context); }
let tests = 0;
{
    const c = model();
    run(c, "els.termDialog.open=true;renderTermEditor();els.termList.children[1].children[1].focus();renderTermEditor();");
    assert.equal(run(c, "document.activeElement===els.termList.children[1].children[1]"), true,
        "an unrelated term-list rebuild must keep the same row's Edit focused"); tests++;
}
{
    const c = model();
    run(c, "els.termDialog.open=true;renderTermEditor();els.termList.children[1].children[2].focus();renderTermEditor();");
    assert.equal(run(c, "document.activeElement===els.termList.children[1].children[2]"), true,
        "an unrelated term-list rebuild must keep the same row's Remove focused"); tests++;
}
{
    const c = model();
    run(c, "els.termDialog.open=true;renderTermEditor();els.termList.children[0].children[2].focus();" +
        "els.termList.children[0].children[2].listeners.click();");
    assert.equal(run(c, "sent.length"), 1);
    assert.equal(run(c, "document.activeElement===els.termClose"), true,
        "a pending Remove must move focus to the enabled Close control");
    run(c, "termPending=false;activeGlossary.entries=activeGlossary.entries.slice(1);renderTermEditor();");
    assert.equal(run(c, "document.activeElement===els.termClose"), true); tests++;
}
{
    const c = model();
    run(c, "els.termDialog.open=true;renderTermEditor();els.termSource.value='unsaved';els.termSource.focus();renderTermEditor();");
    assert.equal(run(c, "document.activeElement===els.termSource && els.termSource.value==='unsaved'"), true,
        "list updates must leave the focused draft field alone"); tests++;
}
{
    const c = model();
    run(c, "els.termDialog.open=true;renderTermEditor();els.termList.children[0].children[2].focus();" +
        "activeGlossary.entries=activeGlossary.entries.slice(1);renderTermEditor();");
    assert.equal(run(c, "document.activeElement===els.termClose"), true,
        "a removed focused row must leave focus on an available dialog control"); tests++;
}
{
    const c = model();run(c, "terminologyState.changes=100;opener();openTermEditor(null);");
    assert.equal(run(c, "els.termSave.disabled && els.termUndo.disabled"), true);
    assert.equal(run(c, "document.activeElement===els.termClose"), true,
        "read-only inspection starts on Close rather than an unsaveable draft"); tests++;
}
for (const state of ["available", "disabled", "hidden", "detached", "inert"]) {
    const c = model();run(c, "var trigger=opener();openTermEditor(null);els.termDialog.close();");
    if (state === "disabled") run(c, "trigger.disabled=true;");
    if (state === "hidden") run(c, "trigger.hidden=true;");
    if (state === "detached") run(c, "trigger.attach(false);");
    if (state === "inert") run(c, "trigger.inert=true;");
    run(c, "restoreTermFocus();");
    assert.equal(run(c, state === "available" ? "document.activeElement===trigger" :
        "document.activeElement===els.statusLabel"), true, state + " opener restoration"); tests++;
}
{
    const c = model();run(c, "opener();openTermEditor(null);restoreTermFocus();");
    assert.equal(run(c, "document.activeElement===els.termSource"), true,
        "a queued close event must not steal focus from a reopened native dialog"); tests++;
}
{
    const c = model();run(c, "renderTermEditor();");
    assert.equal(run(c, "els.termList.children[0].children[1].getAttribute('aria-label')"), "Edit term: alpha");
    assert.equal(run(c, "els.termList.children[1].children[2].getAttribute('aria-label')"), "Remove term: beta"); tests++;
}
{
    const html = fs.readFileSync(path.join(root, "app/static/index.html"), "utf8");
    for (const panel of ["idle", "drawer"]) {
        for (const suffix of ["output-help", "output-permission-hint", "audio-device-status"]) {
            assert.equal(html.match(new RegExp('id="' + panel + '-' + suffix + '"', 'g'))?.length, 1);
        }
        const output = html.match(new RegExp('<select[^>]*id="' + panel + '-output-device"[^>]*>'))[0];
        assert(output.includes('aria-describedby="' + panel + '-output-help ' + panel + '-audio-device-status"'));
        const reveal = html.match(new RegExp('<button[^>]*aria-describedby="' + panel + '-output-permission-hint ' +
            panel + '-audio-device-status"[^>]*>'))[0];
        assert(reveal.includes('data-reveal-audio-outputs'));
    }
    const css = fs.readFileSync(path.join(root, "app/static/styles.css"), "utf8");
    assert(css.includes("input:focus-visible"), "terminology text fields need an explicit visible-focus outline"); tests++;
}
process.stdout.write(JSON.stringify({tests,passed:true,real_browser:false,network:false,audio:false,
    permissions:false,storage:false}) + "\n");
