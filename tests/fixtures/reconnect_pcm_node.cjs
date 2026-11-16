// Same-document transport, snapshot and PCM contracts with a bounded virtual clock.
// Production callbacks/player; fake socket, DOM and silent audio. No SDK/network/device IO.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const appSource = fs.readFileSync(process.argv[2], 'utf8');
const pcmSource = fs.readFileSync(process.argv[3], 'utf8');
const probe = process.argv.includes('--probe-admission');
function slice(start, end) {
    const a = appSource.indexOf(start), b = appSource.indexOf(end, a);
    assert(a >= 0 && b > a, 'production function boundaries');
    return appSource.slice(a, b);
}
const production = slice('    // ===== 3.1 Application State =====', '    // ===== DOM refs =====') +
    slice('    function connectWebSocket()', '    function handleReadiness(msg)') +
    slice('    function handleTtsQueue(msg)', '    function handleProviderCapacityWarning(msg)') +
    slice('    function clearTtsPlaybackState(reset)', '    function applyLocalTtsMuteEffects()');
const enableStart = appSource.indexOf('        els.enableAudioBtn.addEventListener("click", function () {');
const enableEnd = appSource.indexOf('        els.catchUpBtn.addEventListener', enableStart);
assert(enableStart >= 0 && enableEnd > enableStart, 'production enable callback boundaries');
const enable = appSource.slice(enableStart, enableEnd);
const pcm = Buffer.alloc(16).toString('base64'); // Four generated silent float32 samples.
const totals = {checks: [], reconnects: 0, staleCallbacks: 0, virtualCycles: 0,
    timerPeak: 0, clipPeak: 0, bytePeak: 0, retiredPeak: 0, nodePeak: 0};

function model() {
    const c = vm.createContext({assert, window: {}, Date, TextDecoder, ArrayBuffer, Uint8Array,
        Float32Array, DataView, Map, Set, Number, Promise,
        atob: s => Buffer.from(s, 'base64').toString('latin1')});
    vm.runInContext(`
        var now = 0, timerId = 0, timers = new Map(), sockets = [], nodes = new Set();
        var deferredResumes = [], deferResume = false, rejectedResumes = false, resumeCalls = 0;
        var location = {protocol:'http:', host:'synthetic.invalid'};
        var peaks = {timers:0, clips:0, bytes:0, retired:0, nodes:0};
        function setTimeout(callback, delay) {
            var id = ++timerId; timers.set(id,{callback,due:now+delay});
            peaks.timers = Math.max(peaks.timers,timers.size); return id;
        }
        function clearTimeout(id) { timers.delete(id); }
        function advance(ms) {
            var target = now + ms, fired = 0;
            while (true) {
                var entries = [...timers.entries()].filter(item=>item[1].due<=target)
                    .sort((a,b)=>a[1].due-b[1].due || a[0]-b[0]);
                if (!entries.length) break;
                assert(++fired<=128,'bounded virtual timer advancement');
                var [id,timer] = entries[0]; timers.delete(id); now=timer.due; timer.callback();
            }
            now = target;
        }
        var performance = {now:()=>now};
        class Blob {
            constructor(text) { this.raw=text; this.resolve=null; }
            text() { return new Promise(resolve=>this.resolve=()=>resolve(this.raw)); }
        }
        class WebSocket {
            static OPEN = 1;
            constructor() { this.readyState=0; this.commands=[]; sockets.push(this); }
            send(raw) { this.commands.push(JSON.parse(raw)); }
            open() { this.readyState=1; this.onopen(); }
            emit(message) {
                var text=JSON.stringify(message), bytes=new TextEncoder().encode(text);
                this.onmessage({data:bytes.buffer});
            }
            close(code=1006,reason='') { this.readyState=3; this.onclose({code,reason}); }
        }
        class AudioContext {
            get currentTime() { return now/1000; }
            constructor() { this.destination={}; }
            resume() {
                resumeCalls++;
                if (deferResume) return new Promise((resolve,reject)=>deferredResumes.push({resolve,reject}));
                return rejectedResumes ? Promise.reject(Error('synthetic_locked')) : Promise.resolve();
            }
            createBuffer(channels,n) { var data=new Float32Array(n); return {getChannelData:()=>data}; }
            createBufferSource() {
                var node={buffer:null,started:false,stopped:false,connect(){},
                    start(){this.started=true;},stop(){this.stopped=true;},
                    disconnect(){nodes.delete(this);this.buffer=null;}};
                nodes.add(node); peaks.nodes=Math.max(peaks.nodes,nodes.size); return node;
            }
        }
        function element() { return {textContent:'',disabled:false,classList:{remove(){},add(){},toggle(){}},
            addEventListener(type,callback){this[type]=callback;}}; }
        var els={catchUpNotice:element(),jumpLatest:element(),enableAudioBtn:element()};
        function render() {} function fullRender() {} function renderTtsControls() {}
        function renderSpeakingHighlight() {} function resetSessionPreferences() {}
        function restoreCaptionProfile() {} function restoreTerminologyState() {}
        function populateLanguageDropdowns() {} function populateModelDropdowns() {}
        function populateThinkingDropdowns() {} function renderGlossary() {}
    `, c);
    c.TextEncoder = TextEncoder;
    vm.runInContext(pcmSource + '\n' + production + '\n' + enable, c);
    return c;
}
function run(c, code) { return vm.runInContext(code, c, {timeout: 500}); }
function value(c, code) { return run(c, code); }
function emit(c, message, index = -1) {
    c.nextMessage = message;
    run(c, `sockets.at(${index}).emit(nextMessage)`);
    delete c.nextMessage;
    sample(c);
}
function lifecycle(id) {
    return {connection_id: `conn-${String(id).padStart(6, '0')}`,
        state: 'admitted', reason: 'owner_admitted'};
}
function admitted(c, id, epoch = 0) {
    emit(c, {type: 'connection_lifecycle', ...lifecycle(id)});
    emit(c, {type: 'session_snapshot', status: 'listening', segments: [],
        tts_epoch: epoch, connection_lifecycle: lifecycle(id)});
}
function clip(c, id, epoch, last = true) {
    emit(c, {type: 'tts_speaking', seq: 1, clip_id: id, tts_epoch: epoch});
    emit(c, {type: 'tts_audio', seq: 1, clip_id: id, tts_epoch: epoch,
        chunk_index: 0, is_last: last, data: pcm});
}
function count(c, type) {
    return value(c, `sockets.reduce((n,s)=>n+s.commands.filter(m=>m.type===${JSON.stringify(type)}).length,0)`);
}
function sample(c) {
    run(c, `if(pcmPlayer) {
        peaks.clips=Math.max(peaks.clips,pcmPlayer.clips.size);
        peaks.bytes=Math.max(peaks.bytes,pcmPlayer.bytes);
        peaks.retired=Math.max(peaks.retired,pcmPlayer.retired.size);
    }`);
}
function clean(c, pendingReconnect = false) {
    sample(c);
    assert.equal(value(c, 'pcmPlayer ? pcmPlayer.bytes : 0'), 0, 'PCM bytes released');
    assert.equal(value(c, 'pcmPlayer ? pcmPlayer.clips.size : 0'), 0, 'PCM clips released');
    assert.equal(value(c, 'pcmPlayer ? pcmPlayer.queue.length : 0'), 0, 'PCM queue released');
    assert.equal(value(c, 'pcmPlayer ? pcmPlayer.active : null'), null, 'PCM active released');
    assert.equal(value(c, 'pcmPlayer ? pcmPlayer.starting : false'), false, 'resume state released');
    assert.equal(value(c, 'nodes.size'), 0, 'fake audio nodes disconnected');
    assert.equal(value(c, 'timers.size'), pendingReconnect ? 1 : 0, 'only owned reconnect may remain');
}
function collect(c) {
    const p = value(c, 'peaks');
    totals.timerPeak = Math.max(totals.timerPeak, p.timers);
    totals.clipPeak = Math.max(totals.clipPeak, p.clips);
    totals.bytePeak = Math.max(totals.bytePeak, p.bytes);
    totals.retiredPeak = Math.max(totals.retiredPeak, p.retired);
    totals.nodePeak = Math.max(totals.nodePeak, p.nodes);
}
async function flush(c) {
    await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); sample(c);
}
function closeAndOpen(c) {
    run(c, 'sockets.at(-1).close();'); sample(c);
    run(c, 'advance(1000);sockets.at(-1).open();');
    totals.reconnects++;
}
function check(name) { totals.checks.push(name); }

(async () => {
    if (!probe) {
        const c = model(); run(c, 'connectWebSocket();sockets[0].open();');
        emit(c, {type: 'session_snapshot', status: 'listening', segments: [], tts_epoch: 0});
        assert.equal(value(c, 'appState.connectionState'), 'connecting', 'initial unowned snapshot ignored');
        emit(c, {type: 'session_snapshot', status: 'listening', segments: [], tts_epoch: 0,
            connection_lifecycle: {...lifecycle(1), reason: 'invalid_reason'}});
        assert.equal(value(c, 'appState.connectionState'), 'connecting', 'invalid admission ignored');
        emit(c, {type: 'connection_lifecycle', ...lifecycle(1)});
        assert.equal(value(c, 'sockets[0].commands.length'), 0, 'initial admission waits for snapshot');
        emit(c, {type: 'session_snapshot', status: 'listening', segments: [], tts_epoch: 0});
        assert.equal(value(c, 'appState.connectionState'), 'connected', 'current admitted metadata preserved');
        assert.equal(value(c, 'appState.connectionLifecycle.connection_id'), 'conn-000001');
        assert.equal(count(c, 'tts_audio_enabled'), 0, 'initial admission cannot invent activation');
        clean(c); collect(c); check('snapshot_uses_valid_current_socket_admission_without_inventing_activation');
    }
    {
        const c = model();
        run(c, 'connectWebSocket();sockets[0].open();');
        admitted(c, 1, 3);
        assert.equal(count(c, 'tts_audio_enabled'), 0, 'initial document has no inherited unlock');
        run(c, 'els.enableAudioBtn.click();'); await flush(c);
        assert.equal(count(c, 'tts_audio_enabled'), 1, 'explicit fake activation enables owner');
        closeAndOpen(c);
        assert.equal(value(c, 'sockets.at(-1).commands.length'), 0, 'socket open alone cannot restore audio');
        emit(c, {type: 'session_snapshot', status: 'listening', segments: [], tts_epoch: 4});
        const blocked = value(c, 'appState.connectionState') === 'reconnecting' &&
            value(c, 'sockets.at(-1).commands.length') === 0;
        if (probe) {
            process.stdout.write(JSON.stringify({missing_admission_snapshot_blocked: blocked,
                observed_connection_state: value(c, 'appState.connectionState'),
                restored_audio_commands: value(c, "sockets.at(-1).commands.filter(m=>m.type==='tts_audio_enabled').length"),
                source_only: true, real_browser: false, network: false, audio: false}) + '\n');
            return;
        }
        assert(blocked, 'unowned reconnect snapshot cannot restore document unlock');
        emit(c, {type: 'connection_lifecycle', ...lifecycle(2)});
        assert.equal(value(c, 'sockets.at(-1).commands.length'), 0, 'admission alone waits for snapshot');
        emit(c, {type: 'session_snapshot', status: 'session_ended', segments: [],
            tts_epoch: 8, connection_lifecycle: lifecycle(1)});
        assert.equal(value(c, 'appState.connectionState'), 'reconnecting', 'old owner snapshot ignored');
        assert.equal(value(c, 'appState.currentTtsEpoch'), 3, 'old owner cannot overwrite epoch');
        emit(c, {type: 'session_snapshot', status: 'listening', segments: [], tts_epoch: 4,
            connection_lifecycle: lifecycle(2)});
        assert.equal(value(c, 'appState.connectionState'), 'connected');
        assert.equal(value(c, 'appState.ttsAudioUnlocked'), true, 'same-document gesture retained');
        assert.equal(count(c, 'tts_audio_enabled'), 2, 'audio restored once after admitted snapshot');
        assert.equal(count(c, 'start'), 0, 'reconnect never restarts capture');
        clean(c); collect(c); check('audio_restore_requires_current_admission_and_snapshot');
    }
    {
        const c = model(); run(c, 'connectWebSocket();sockets[0].open();'); admitted(c, 1, 0);
        run(c, 'els.enableAudioBtn.click();'); await flush(c);
        clip(c, 10, 0); await flush(c);
        clip(c, 11, 0, false); clip(c, 12, 0);
        run(c, 'var oldEnded=[...nodes][0].onended;var oldTimeout=[...timers.values()][0].callback;');
        run(c, `var delayed=new Blob(JSON.stringify({type:'tts_audio',seq:1,clip_id:99,tts_epoch:0,
            chunk_index:0,is_last:true,data:${JSON.stringify(pcm)}}));sockets[0].onmessage({data:delayed});`);
        run(c, 'sockets[0].close(1011,"writer_failed");'); clean(c, true);
        const oldClose = value(c, 'sockets[0].onclose');
        run(c, 'advance(1000);sockets[1].open();'); totals.reconnects++;
        admitted(c, 2, 1);
        run(c, 'oldEnded();oldTimeout();delayed.resolve();'); await flush(c);
        oldClose({code: 1006, reason: ''});
        emit(c, {type: 'session_snapshot', status: 'session_ended', segments: [],
            tts_epoch: 0, connection_lifecycle: lifecycle(1)}, 0);
        emit(c, {type: 'tts_audio', seq: 1, clip_id: 10, tts_epoch: 0,
            chunk_index: 0, is_last: true, data: pcm}); await flush(c);
        assert.equal(value(c, 'appState.currentTtsEpoch'), 1);
        assert.equal(value(c, 'appState.connectionState'), 'connected');
        assert.equal(count(c, 'tts_playback_complete'), 0, 'old callbacks cannot acknowledge on new socket');
        assert.equal(count(c, 'tts_playback_error'), 0, 'old timeout cannot fail on new socket');
        clean(c);
        clip(c, 13, 1); await flush(c);
        run(c, 'var ended=[...nodes][0].onended;ended();ended();'); await flush(c);
        assert.equal(count(c, 'tts_playback_complete'), 1, 'new clip completes exactly once');
        clean(c); collect(c); totals.staleCallbacks += 5;
        check('socket_loss_releases_pcm_and_ignores_old_blob_end_timeout_close_epoch');
    }
    {
        const c = model(); run(c, 'connectWebSocket();sockets[0].open();'); admitted(c, 1, 0);
        run(c, 'els.enableAudioBtn.click();'); await flush(c);
        run(c, 'deferResume=true;'); clip(c, 20, 0); await flush(c);
        assert.equal(value(c, 'deferredResumes.length'), 1);
        closeAndOpen(c); admitted(c, 2, 1);
        run(c, 'deferResume=false;deferredResumes.shift().resolve();'); await flush(c);
        assert.equal(count(c, 'tts_playback_start'), 0, 'old pending resume cannot play on reconnect');
        clean(c);
        run(c, 'deferResume=true;'); clip(c, 21, 1); await flush(c);
        closeAndOpen(c); admitted(c, 3, 2);
        run(c, 'deferResume=false;deferredResumes.shift().reject(Error("synthetic_locked"));'); await flush(c);
        assert.equal(value(c, 'appState.ttsAudioUnlocked'), true, 'old rejected resume cannot relock new owner');
        clip(c, 22, 2); await flush(c); run(c, '[...nodes][0].onended();'); await flush(c);
        assert.equal(count(c, 'tts_playback_complete'), 1); clean(c); collect(c);
        totals.staleCallbacks += 2; check('deferred_resume_resolution_and_rejection_are_generation_scoped');
    }
    {
        const c = model(); run(c, 'connectWebSocket();sockets[0].open();'); admitted(c, 1, 0);
        run(c, 'els.enableAudioBtn.click();'); await flush(c); clip(c, 30, 0, false);
        run(c, 'sockets[0].close();var capturedReconnect=[...timers.values()][0].callback;');
        emit(c, {type: 'connection_lifecycle', connection_id: 'conn-000002',
            state: 'rejected', reason: 'owner_active'}); // Closed socket deliberately drops it.
        run(c, 'advance(1000);sockets.at(-1).open();');
        emit(c, {type: 'connection_lifecycle', connection_id: 'conn-000002',
            state: 'rejected', reason: 'owner_active'});
        run(c, 'capturedReconnect();scheduleReconnect();send({type:"tts_audio_enabled"});');
        assert.equal(value(c, 'appState.ownershipBlocked'), true);
        assert.equal(value(c, 'appState.ttsAudioUnlocked'), false);
        assert.equal(value(c, 'sockets.length'), 2);
        clean(c); collect(c); check('ownership_rejection_cancels_reconnect_and_retained_unlock');
    }
    {
        const c = model(); run(c, 'connectWebSocket();sockets[0].open();'); admitted(c, 1, 0);
        run(c, 'els.enableAudioBtn.click();'); await flush(c);
        for (let i = 0; i < 24; i++) {
            const base = 100 + i * 5;
            clip(c, base, i); await flush(c);
            clip(c, base + 1, i, false); clip(c, base + 2, i);
            run(c, 'var staleEnded=[...nodes][0].onended;var staleTimer=[...timers.values()][0].callback;');
            closeAndOpen(c);
            admitted(c, i + 2, i + 1);
            run(c, 'staleEnded();staleTimer();advance(269000);'); await flush(c);
            clean(c);
            clip(c, base + 3, i + 1, false);
            // A stalled new-owner stream reaches its timeout after reconnect cleanup.
            run(c, 'advance(30000);'); await flush(c);
            assert.equal(count(c, 'tts_playback_error'), i + 1);
            clean(c);
            assert.equal(value(c, 'now'), (i + 1) * 300000, 'monotonic five-minute virtual checkpoint');
            totals.virtualCycles++; totals.staleCallbacks += 2;
        }
        assert.equal(value(c, 'now'), 7200000, 'two virtual hours only');
        assert.equal(count(c, 'tts_playback_complete'), 0, 'interrupted clip never falsely completes');
        assert.equal(count(c, 'start'), 0);
        assert.equal(count(c, 'tts_audio_enabled'), 25);
        assert.equal(value(c, 'sockets.length'), 25);
        assert.equal(value(c, 'deferredResumes.length'), 0);
        clean(c); collect(c); check('bounded_virtual_time_composes_reconnect_timeout_and_pcm_accumulation');
    }
    assert(totals.timerPeak <= 2 && totals.clipPeak <= 3 && totals.bytePeak <= 48 &&
        totals.nodePeak <= 1 && totals.retiredPeak <= 4, 'observed finite resource budgets');
    process.stdout.write(JSON.stringify({passed:true,tests:totals.checks.length,...totals,
        virtual_elapsed_ms:7200000,real_elapsed_endurance:false,real_browser:false,
        transport:'fake_socket_running_production_callbacks',sdk:'not_instantiated',
        media:'not_instantiated',audio:'silent_fake_context',network:false,
        remaining:{pcm_bytes:0,pcm_clips:0,pcm_queue:0,audio_nodes:0,timers:0,resume_promises:0}}) + '\n');
})().catch(error => {
    process.stderr.write(String(error.stack) + '\n'); process.exitCode=1;
});
