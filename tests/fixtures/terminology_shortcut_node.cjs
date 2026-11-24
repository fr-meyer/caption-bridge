// Source-driven protocol/keyboard MODEL ONLY: no browser, audio or network.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '../..');
const source = fs.readFileSync(path.join(root, 'app/static/app.js'), 'utf8');
const audioSource = fs.readFileSync(path.join(root, 'app/static/audio-devices.js'), 'utf8');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
function section(start, end) {
    const begin = source.indexOf(start), finish = source.indexOf(end, begin);
    if (begin < 0 || finish < 0) throw Error('missing source boundary: ' + start);
    return source.slice(begin, finish);
}
let keyboard = section('    function setupKeyboard()', '    // ===== Terminology preferences =====');
const guard = 'if (els.termDialog.open) return;';
if (keyboard.split(guard).length !== 2) throw Error('guard source drift');
if (input.remove_guard) keyboard = keyboard.replace(guard, '');
const received = [], rendered = [];
let keydown;
class Socket {
    static OPEN = 1;
    constructor() { this.readyState = Socket.OPEN; }
    send(payload) { received.push(JSON.parse(payload)); }
}
const nothing = () => {};
const context = {
    window: {}, WebSocket: Socket, connectInFlight: true, reconnectAttempt: 0,
    reconnectTimer: null, isFirstConnect: true, providerNoticeTimer: null,
    confirmedTargetLanguage: null, activeGlossary: null, DEFAULT_FONT_SIZE: 28,
    appState: { ownershipBlocked: false, connectionState: 'connecting', captionsOnly: false, autoScroll: true },
    els: { termDialog: { open: true }, discardModal: { classList: { contains: () => false } },
        exportFailureModal: { classList: { contains: () => false } } },
    document: { addEventListener: (type, callback) => { if (type === 'keydown') keydown = callback; },
        body: { classList: { remove: nothing } }, getElementById: () => null },
    blockConnectionOwnership: () => { throw Error('unexpected ownership rejection'); },
    prependCaptionEntry: message => rendered.push(message.seq),
};
for (const name of ['render', 'clearTtsPlaybackState', 'restoreCaptionProfile',
    'restoreTerminologyState', 'populateLanguageDropdowns', 'populateModelDropdowns',
    'populateThinkingDropdowns', 'renderGlossary', 'fullRender', 'renderHeaderLang', 'renderDrawer']) {
    context[name] = nothing;
}
vm.createContext(context);
// The identical observer used in the real browser test wraps native send; it is
// not cleared or replaced by a manually populated history.
vm.runInContext(input.observer, context);
context.ws = new Socket();
context.connection = context.ws;
context.connectionClosed = false;
vm.runInContext(audioSource, context);
context.audioDevices = new context.window.CaptionAudioDevices({
    send: message => context.send(message), state: context.appState, canRoute: () => false,
    media: { enumerateDevices: async () => [] },
});
context.audioDevices.render = nothing; // DOM-only renderer, not refresh/snapshot/send.
vm.runInContext(section('    function send(obj)', '    function blockConnectionOwnership'), context);
vm.runInContext(section('    function handleConnectionLifecycle', '    // ===== 3.3 Message Handlers'), context);
vm.runInContext(section('    function handleSnapshot', '    function handleReadiness'), context);
vm.runInContext(section('    function handleCaption(msg)', '    function handleExportResult'), context);
vm.runInContext(section('    function resetSessionPreferences', '    // ===== Utility ====='), context);
vm.runInContext(section('        ws.onopen = function ()', '        ws.onmessage = function ('), context);
context.ws.onopen();
// Inputs are the real SessionManager admission/snapshot/_try_deliver messages.
for (const message of input.initial_messages) {
    if (message.type === 'connection_lifecycle') context.handleConnectionLifecycle(message);
    else if (message.type === 'session_snapshot') context.handleSnapshot(message);
    else if (message.type === 'caption') context.handleCaption(message);
    else throw Error('unexpected initial production message');
}
const copy = value => JSON.parse(JSON.stringify(value));
const startupClient = copy(context.window.termShortcutFrames), startupServer = copy(received);
vm.runInContext(keyboard, context);
context.setupKeyboard();
keydown({ target: { tagName: 'P' }, code: 'Space', preventDefault: nothing });
process.stdout.write(JSON.stringify({ model_only: true, actual_browser: false,
    guard_removed: input.remove_guard, rendered,
    startup_client: startupClient, startup_server: startupServer,
    final_client: copy(context.window.termShortcutFrames), final_server: copy(received) }));
