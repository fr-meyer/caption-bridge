// Production connection callbacks under an in-memory socket/clock/DOM model.
// No browser, network, permissions, storage, or audio is created.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[2], 'utf8');
function slice(start, end) {
    const a = source.indexOf(start), b = source.indexOf(end, a);
    assert(a >= 0 && b > a, 'production function boundaries');
    return source.slice(a, b);
}
const functions = slice('    function connectWebSocket()', '    // ===== 3.3 Message Handlers =====') +
    slice('    function handleSnapshot(msg)', '    function handleReadiness(msg)') +
    slice('    function renderHeader()', '    function renderAsrNotice()');
function model() {
    const context = vm.createContext({ Date, TextDecoder, ArrayBuffer, Blob });
    vm.runInContext(`
        var sockets = [], timers = new Map(), timerCounter = 0, received = [], playbackCancels = 0;
        var location = {protocol:'http:', host:'synthetic.invalid'};
        var ws = null, reconnectTimer = null, reconnectAttempt = 0, isFirstConnect = true;
        var activeGlossary = null, confirmedTargetLanguage = 'en', audioDevices = null;
        var appState = { connectionState:'connecting', connectionLifecycle:null, ownershipBlocked:false,
            status:'idle_ready', pipelineDiagnostics:null, ttsMuted:false, ttsAudioUnlocked:true,
            captionsOnly:false, ttsSpeakingSeq:1, elapsed:0, autoScroll:true, recoverySuppressed:false };
        function element() { return {textContent:'', disabled:false, className:'',
            classList:{add(){}, toggle(){}, remove(){}}}; }
        var els = { statusDot:element(), statusLabel:element(), elapsed:element(), catchUpNotice:element(),
            startBtn:element(), stopBtn:element(), exportBtn:element(), newSessionBtn:element(),
            enableAudioBtn:element(), footerHints:element(), connectionOwnershipNotice:element() };
        function setTimeout(callback, delay) { var id=++timerCounter;timers.set(id,{callback,delay});return id; }
        function clearTimeout(id) { timers.delete(id); }
        function tick() { var pending=[...timers.values()]; timers.clear();pending.forEach(t=>t.callback()); }
        function clearTtsPlaybackState() { playbackCancels++; }
        function formatTime(value) { return String(value); }
        function render() { renderHeader(); renderConnectionOwnership(); }
        function fullRender() { render(); }
        function resetSessionPreferences() {}
        function restoreCaptionProfile() {}
        function restoreTerminologyState() {}
        function populateLanguageDropdowns() {}
        function populateModelDropdowns() {}
        function populateThinkingDropdowns() {}
        function renderGlossary() {}
        function handleMessage(msg) {
            received.push(msg.type);
            if (msg.type === 'connection_lifecycle') handleConnectionLifecycle(msg);
            if (msg.type === 'session_snapshot') handleSnapshot(msg);
        }
        class WebSocket {
            static OPEN=1;
            constructor() { this.readyState=0; this.commands=[];sockets.push(this); }
            send(raw) { this.commands.push(JSON.parse(raw)); }
            open() { this.readyState=1;this.onopen(); }
            message(msg) { this.onmessage({data:JSON.stringify(msg)}); }
            close(code=1006,reason='') { this.readyState=3;this.onclose({code,reason}); }
        }
    ` + functions, context);
    return context;
}
function run(context, code) { return vm.runInContext(code, context); }
function admitted(context, id='conn-000001') {
    run(context, `sockets.at(-1).message({type:'connection_lifecycle',connection_id:'${id}',state:'admitted',reason:'owner_admitted'});`);
    run(context, `sockets.at(-1).message({type:'session_snapshot',status:'idle_ready',segments:[],connection_lifecycle:{connection_id:'${id}',state:'admitted',reason:'owner_admitted'}});`);
}
let tests = 0;
for (const close of [{code:1000, reason:'replaced'}, {code:4409, reason:'owner_active'}, {code:4409, reason:'PRIVATE untrusted close body'}]) {
    const c = model(); run(c, 'connectWebSocket();sockets[0].open();');
    assert.equal(run(c, 'sockets[0].commands.length'), 0, 'open alone cannot send commands');
    admitted(c);
    run(c, `sockets[0].close(${close.code},${JSON.stringify(close.reason)});`);
    assert.equal(run(c, 'appState.connectionState'), 'ownership_blocked');
    assert.equal(run(c, 'timers.size'), 0, 'ownership close cannot schedule reconnect');
    run(c, "send({type:'start'});send({type:'tts_audio_enabled'});scheduleReconnect();connectWebSocket();tick();");
    assert.equal(run(c, 'sockets.length'), 1);
    assert.equal(run(c, 'appState.ttsAudioUnlocked'), false);
    assert.equal(run(c, 'els.stopBtn.disabled'), true);
    assert.equal(run(c, 'els.startBtn.disabled'), true);
    assert.equal(run(c, 'els.statusLabel.textContent'), 'Another page controls this session');
    assert.equal(run(c, "sockets[0].commands.filter(x=>x.type==='start').length"), 0);
    assert.equal(run(c, "sockets[0].commands.filter(x=>x.type==='tts_audio_enabled').length"), 1, 'only admitted snapshot restored audio');
    assert.equal(run(c, 'JSON.stringify(appState.connectionLifecycle).includes("PRIVATE")'), false);
    tests++;
}
{
    const c = model();run(c,'connectWebSocket();sockets[0].open();');
    run(c,"sockets[0].message({type:'connection_lifecycle',connection_id:'conn-000002',state:'rejected',reason:'owner_active'});");
    run(c,"sockets[0].message({type:'session_snapshot',status:'idle_ready',segments:[]});sockets[0].close(4409,'owner_active');tick();");
    assert.equal(run(c, 'appState.connectionState'), 'ownership_blocked');
    assert.equal(run(c, 'sockets[0].commands.length'), 0, 'rejected page sends no controls');
    assert.equal(run(c, 'received.filter(x=>x==="session_snapshot").length'), 0, 'post-rejection messages ignored');
    assert.equal(run(c, 'sockets.length'), 1); tests++;
}
{
    const c = model();run(c,'connectWebSocket();sockets[0].open();');admitted(c);
    run(c,"sockets[0].close(1006,'PRIVATE network body');");
    assert.equal(run(c,'appState.connectionState'),'reconnecting');
    assert.equal(run(c,'[...timers.values()][0].delay'),1000);
    run(c,'tick();sockets[1].open();');
    assert.equal(run(c,'sockets[1].commands.length'),0, 'new socket waits for snapshot');
    run(c,"sockets[0].message({type:'session_snapshot',status:'listening'});");
    assert.equal(run(c,'appState.connectionState'),'reconnecting');
    admitted(c, 'conn-000002');
    assert.equal(run(c,'appState.connectionState'),'connected');
    assert.equal(run(c,'appState.connectionLifecycle.connection_id'),'conn-000002');
    assert.equal(run(c,"sockets.flatMap(s=>s.commands).filter(x=>x.type==='start').length"),0);
    assert.equal(run(c,'appState.ttsAudioUnlocked'),true, 'ordinary reconnect retains document gesture');tests++;
}
{
    const c = model();run(c,'connectWebSocket();sockets[0].open();');admitted(c);
    run(c,"sockets[0].close(1011,'writer_failed');");
    const pending = run(c,'[...timers.values()][0].callback');
    run(c,"handleConnectionLifecycle({connection_id:'conn-000002',state:'rejected',reason:'owner_active'});");
    assert.equal(run(c,'timers.size'),0);pending();
    assert.equal(run(c,'sockets.length'),1, 'already captured reconnect callback remains terminal');tests++;
}
{
    const c = model();run(c,'connectWebSocket();sockets[0].open();');
    assert.equal(run(c,"handleConnectionLifecycle({connection_id:'PRIVATE device',state:'admitted',reason:'owner_admitted'})"),false);
    assert.equal(run(c,"handleConnectionLifecycle({connection_id:'conn-000001',state:'admitted',reason:'PRIVATE body'})"),false);
    run(c,"handleSnapshot({status:'idle_ready',connection_lifecycle:{connection_id:'PRIVATE',state:'admitted',reason:'owner_admitted'}});");
    assert.equal(run(c,'appState.connectionState'),'connecting');
    assert.equal(run(c,'sockets[0].commands.length'),0);tests++;
}
process.stdout.write(JSON.stringify({tests,passed:true,real_browser:false,network:false,audio:false,storage:false})+'\n');
