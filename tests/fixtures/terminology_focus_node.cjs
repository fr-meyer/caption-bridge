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
const functions = slice("    function trapTermFocus(", "    function parseGlossaryText(");
function model() {
    const context = vm.createContext({assert});
    vm.runInContext(`
        var document = {activeElement:null};
        class Element {
            constructor(tag='div') {
                this.tagName=tag.toUpperCase(); this.children=[]; this.parentElement=null;
                this.isConnected=false; this.disabled=false; this.hidden=false; this.inert=false;
                this.tabIndex=['BUTTON','INPUT','SELECT','TEXTAREA','A'].includes(this.tagName) ? 0 : -1;
                this.dataset={}; this.attributes={}; this.listeners={}; this.value=''; this.textContent='';
                const classes=new Set();
                this.classList={add(name){classes.add(name);},remove(name){classes.delete(name);},
                    contains(name){return classes.has(name);}};
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
                for (var el=this;el;el=el.parentElement)
                    if (el.inert || (selector.includes('[hidden]') && el.hidden)) return el;
                return null;
            }
            querySelectorAll(selector) {
                assert.equal(selector, 'button, input, select, textarea, a[href], [tabindex]');
                const result=[];
                const visit=element=>{ for (const child of element.children) {
                    if (['BUTTON','INPUT','SELECT','TEXTAREA','A'].includes(child.tagName) || child.tabIndex>=0)
                        result.push(child);
                    visit(child);
                }};
                visit(this);return result;
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
        function assertSelector(selector) {
            if (!['[inert]', '[inert], [hidden]'].includes(selector)) throw Error('unexpected selector');
        }
        document.createElement=tag=>new Element(tag);
        document.body=new Element('body');document.body.attach(true);document.activeElement=document.body;
        var els={};
        ['termDialog','termList','termVersion','termSource','termPreferred','termKind','termCaption',
         'termError','termSave','termUndo','termClose','captionLog','statusLabel'].forEach(name=>{
            const tag=['termSave','termUndo','termClose'].includes(name) ? 'button' :
                name==='termKind' ? 'select' : ['termSource','termPreferred'].includes(name) ? 'input' : 'div';
            els[name]=new Element(tag);
        });
        document.body.appendChild(els.termDialog);document.body.appendChild(els.captionLog);
        document.body.appendChild(els.statusLabel);
        ['termList','termVersion','termKind','termSource','termPreferred','termCaption','termError',
         'termSave','termUndo','termClose'].forEach(name=>els.termDialog.appendChild(els[name]));
        els.termError.classList.add('hidden');
        var window={getSelection:()=>({anchorNode:null})};
        var appState={status:'listening',targetLanguage:'en'};
        var terminologyState={sessionId:'synthetic-session',version:1,canUndo:true,changes:1};
        var activeGlossary={target_language:'en',entries:[
            {source:'alpha',preferred:'A',kind:'target'}, {source:'beta',preferred:'B',kind:'source'}]};
        var termPending=false,termContext={language:'en',version:1},modalReturnFocus=new WeakMap();
        var sent=[];function send(msg) { sent.push(msg); }
        function renderGlossary() { renderTermEditor(); }
        function termEvent(type,message) { return {type,message,session_id:'synthetic-session',
            terminology_version:1,terminology_can_undo:true,terminology_changes:1,glossary:activeGlossary}; }
        function opener() { var el=new Element('button');document.body.appendChild(el);el.focus();return el; }
        function tab(shiftKey=false, extra={}) {
            var prevented=false;trapTermFocus({key:'Tab',shiftKey,...extra,preventDefault(){prevented=true;}});
            return prevented;
        }
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
function showError(context, kind) {
    if (kind === "validation") run(context, "els.termSource.value='';els.termPreferred.value='valid';saveCaptionTerm();");
    else run(context, "handleTerminology(termEvent('terminology_error','Synthetic server validation error'));");
    assert.equal(run(context, "!els.termError.classList.contains('hidden') && els.termError.textContent.length>0"), true,
        kind + " error remains available while active");
}
for (const kind of ["validation", "server"]) {
    const c = model();run(c, "opener();openTermEditor(null);");showError(c, kind);
    run(c, "els.termSource.value='gamma';els.termPreferred.value='G';saveCaptionTerm();" +
        "handleTerminology(termEvent('terminology_updated'));renderTermEditor();");
    assert.equal(run(c, "els.termError.classList.contains('hidden') && els.termError.textContent===''"), true,
        kind + " error must not persist in a directly referenced accessible description after success"); tests++;
}
for (const kind of ["validation", "server"]) {
    const c = model();run(c, "var trigger=opener();openTermEditor(null);");showError(c, kind);
    run(c, "els.termDialog.close();restoreTermFocus();openTermEditor(null);");
    assert.equal(run(c, "els.termError.classList.contains('hidden') && els.termError.textContent===''"), true,
        kind + " error must not persist in a directly referenced accessible description after reopening"); tests++;
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
function keyCase(name, setup, condition) {
    const c=model();run(c, "activeGlossary=null;opener();openTermEditor(null);" + setup);
    assert.equal(run(c, condition), true, name);tests++;
}
keyCase("forward boundary wraps to first current control",
    "els.termClose.focus();var stopped=tab();",
    "stopped && document.activeElement===els.termKind && sent.length===0");
keyCase("reverse boundary wraps to Close",
    "els.termKind.focus();var stopped=tab(true);",
    "stopped && document.activeElement===els.termClose");
keyCase("ordinary forward/backward order stays native-like",
    "els.termSource.focus();var forward=tab();var preferred=document.activeElement===els.termPreferred;var back=tab(true);",
    "forward && preferred && back && document.activeElement===els.termSource");
keyCase("pending save skips disabled actions",
    "termPending=true;renderTermEditor();els.termClose.focus();var stopped=tab(true);",
    "stopped && els.termSave.disabled && els.termUndo.disabled && document.activeElement===els.termPreferred");
keyCase("pending undo wraps without visiting its disabled invoking action",
    "termPending=true;renderTermEditor();els.termClose.focus();var stopped=tab();",
    "stopped && document.activeElement===els.termKind && els.termUndo.disabled");
keyCase("list insertion and pending/re-enabled rebuild recompute the sequence",
    "activeGlossary={target_language:'en',entries:[{source:'fresh',preferred:'new',kind:'target'}]};renderTermEditor();" +
    "els.termClose.focus();tab();var row=document.activeElement===els.termList.children[0].children[1];" +
    "termPending=true;renderTermEditor();els.termClose.focus();tab();var pending=document.activeElement===els.termKind;" +
    "termPending=false;renderTermEditor();els.termClose.focus();tab();",
    "row && pending && document.activeElement===els.termList.children[0].children[1]");
keyCase("hidden inert and negative-tab-index controls are excluded",
    "els.termSource.hidden=true;els.termPreferred.inert=true;els.termSave.tabIndex=-1;els.termUndo.disabled=true;" +
    "els.termKind.focus();var stopped=tab();",
    "stopped && document.activeElement===els.termClose");
keyCase("programmatic help focus enters current control cycle",
    "var help=new Element('p');els.termDialog.appendChild(help);help.focus();var stopped=tab();",
    "stopped && document.activeElement===els.termKind");
keyCase("closed non-Tab and modified navigation keep their default behavior",
    "els.termSource.focus();var escape=tab(false,{key:'Escape'});var control=tab(false,{ctrlKey:true});" +
    "els.termDialog.open=false;var closed=tab();",
    "!escape && !control && !closed && document.activeElement===els.termSource");
keyCase("no eligible controls still prevents background default and anchors Close",
    "els.termDialog.querySelectorAll=()=>[];els.termSource.focus();var stopped=tab();",
    "stopped && document.activeElement===els.termClose");
process.stdout.write(JSON.stringify({tests,passed:true,real_browser:false,network:false,audio:false,
    permissions:false,storage:false}) + "\n");
