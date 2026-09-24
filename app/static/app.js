(function () {
    "use strict";

    // ===== 3.1 Application State =====

    const FONT_SIZES = [20, 24, 28, 32, 36, 40];
    const DEFAULT_FONT_SIZE = 28;
    const CAPTIONS_ONLY_KEY = "captionBridge.captionsOnly";

    const TTS_SUPPORTED_LANGUAGES = new Set([
        "en", "fr", "de", "es", "nl", "pt", "it", "hi", "ar",
    ]);

    let audioContext = null;
    let ttsChunkBuffers = {};
    let ttsPlaybackQueue = [];
    let ttsActiveSourceNode = null;
    let ttsPlaybackStarting = false;

    const appState = {
        status: "idle_blocked",
        checks: [],
        sourcePartial: "",
        segments: [],
        captions: [],
        exported: false,
        exportPath: null,
        recoveryNotice: null,
        elapsed: 0,
        startedAt: null,
        endedAt: null,
        fontSize: DEFAULT_FONT_SIZE,
        sourceVisible: true,
        autoScroll: true,
        modalVisible: false,
        recoverySuppressed: false,
        exportFailure: null,
        exportFailureModalVisible: false,
        recoveryFailure: null,
        targetLanguage: "en",
        availableTargetLanguages: [],
        drawerOpen: false,
        ttsEnabled: true,
        // Audio permission is document-scoped: a browser replacement must
        // require a fresh user gesture before translated speech can play.
        ttsAudioUnlocked: false,
        providerOutage: null,
        ttsSpeakingSeq: null,
        currentTtsEpoch: 0,
        ttsMuted: false,
        captionsOnly: false,
        providerCapacityWarning: null,
    };
    let providerNoticeTimer = null;
    let providerCapacityTimer = null;
    const modalReturnFocus = new WeakMap();

    let ws = null;
    let reconnectAttempt = 0;
    let reconnectTimer = null;
    let isFirstConnect = true;
    let confirmedTargetLanguage = "en";
    let programmaticScroll = false;

    function scrollToTop(container) {
        programmaticScroll = true;
        container.scrollTop = 0;
        requestAnimationFrame(function () {
            programmaticScroll = false;
        });
    }

    // ===== DOM refs =====

    const $ = (id) => document.getElementById(id);

    const els = {};
    function cacheDom() {
        els.elapsed = $("elapsed");
        els.statusDot = $("status-dot");
        els.statusLabel = $("status-label");
        els.recoveryNotice = $("recovery-notice");
        els.recoveryPath = $("recovery-path");
        els.dismissRecovery = $("dismiss-recovery");
        els.idlePanel = $("idle-panel");
        els.checklist = $("checklist");
        els.startBtn = $("start-btn");
        els.idleHint = $("idle-hint");
        els.sourcePartial = $("source-partial");
        els.captionLog = $("caption-log");
        els.jumpLatest = $("jump-latest");
        els.summaryBar = $("summary-bar");
        els.captionCount = $("caption-count");
        els.exportWarning = $("export-warning");
        els.exportConfirm = $("export-confirm");
        els.exportBtn = $("export-btn");
        els.newSessionBtn = $("new-session-btn");
        els.controlsFooter = $("controls-footer");
        els.footerHints = $("footer-hints");
        els.stopBtn = $("stop-btn");
        els.fullscreenBtn = $("fullscreen-btn");
        els.fontDec = $("font-dec");
        els.fontInc = $("font-inc");
        els.discardModal = $("discard-modal");
        els.cancelDiscard = $("cancel-discard");
        els.confirmDiscard = $("confirm-discard");
        els.exportFailureModal = $("export-failure-modal");
        els.exportFailureError = $("export-failure-error");
        els.retryExportBtn = $("retry-export-btn");
        els.discardExportBtn = $("discard-export-btn");
        els.recoveryFailureWarning = $("recovery-failure-warning");
        els.recoveryFailureError = $("recovery-failure-error");
        els.retryRecoveryBtn = $("retry-recovery-btn");
        els.discardRecoveryBtn = $("discard-recovery-btn");
        els.gearBtn = $("gear-btn");
        els.drawerClose = $("drawer-close");
        els.settingsDrawer = $("settings-drawer");
        els.drawerTargetSelect = $("drawer-target-select");
        els.sourceToggle = $("source-toggle");
        els.idleTargetSelect = $("idle-target-select");
        els.headerLang = $("header-lang");
        els.providerNotice = $("provider-notice");
        els.providerNoticeTitle = $("provider-notice-title");
        els.providerNoticeDetail = $("provider-notice-detail");
        els.capacityNotice = $("capacity-notice");
        els.capacityNoticeDetail = $("capacity-notice-detail");
        els.drawerLangError = $("drawer-lang-error");
        els.audioEnableBanner = $("audio-enable-banner");
        els.enableAudioBtn = $("enable-audio-btn");
        els.ttsToggleBtn = $("tts-toggle-btn");
        els.ttsDrawerToggle = $("tts-drawer-toggle");
        els.captionsOnlyIdle = $("captions-only-idle");
        els.captionsOnlyDrawer = $("captions-only-drawer");
        els.buildIdentity = $("build-identity");
    }

    // ===== 3.2 WebSocket Connection =====

    function connectWebSocket() {
        const proto = location.protocol === "https:" ? "wss:" : "ws:";
        const url = `${proto}//${location.host}/ws`;

        ws = new WebSocket(url);

        ws.onopen = function () {
            reconnectAttempt = 0;
            if (reconnectTimer) {
                clearTimeout(reconnectTimer);
                reconnectTimer = null;
            }
            send({ type: "tts_mute", muted: appState.ttsMuted });
            if (appState.ttsAudioUnlocked && !appState.captionsOnly) {
                send({ type: "tts_audio_enabled" });
            }
        };

        ws.onmessage = function (event) {
            if (event.data instanceof Blob) {
                event.data.text().then(function (text) {
                    try {
                        handleMessage(JSON.parse(text));
                    } catch (_) { /* malformed JSON */ }
                });
                return;
            }
            if (event.data instanceof ArrayBuffer) {
                try {
                    var text = new TextDecoder().decode(event.data);
                    handleMessage(JSON.parse(text));
                } catch (_) { /* malformed JSON */ }
                return;
            }
            try {
                handleMessage(JSON.parse(event.data));
            } catch (_) { /* malformed JSON */ }
        };

        ws.onclose = function () {
            scheduleReconnect();
        };

        ws.onerror = function () {
            // onclose fires after onerror, reconnect handled there
        };
    }

    function scheduleReconnect() {
        if (reconnectTimer) return;
        const delays = [1000, 2000, 4000, 8000, 15000];
        const delay = delays[Math.min(reconnectAttempt, delays.length - 1)];
        reconnectAttempt++;
        reconnectTimer = setTimeout(function () {
            reconnectTimer = null;
            connectWebSocket();
        }, delay);
    }

    function send(obj) {
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify(obj));
        }
    }

    // ===== 3.3 Message Handlers =====

    function handleMessage(msg) {
        switch (msg.type) {
            case "session_snapshot":
                handleSnapshot(msg);
                break;
            case "readiness":
                handleReadiness(msg);
                break;
            case "status":
                handleStatus(msg);
                break;
            case "source_partial":
                handleSourcePartial(msg);
                break;
            case "caption":
                handleCaption(msg);
                break;
            case "export_result":
                handleExportResult(msg);
                break;
            case "error":
                handleError(msg);
                break;
            case "elapsed":
                handleElapsed(msg);
                break;
            case "tts_speaking":
                handleTtsSpeaking(msg);
                break;
            case "tts_audio":
                handleTtsAudio(msg);
                break;
            case "tts_error":
                handleTtsError(msg);
                break;
            case "tts_skipped":
                handleTtsSkipped(msg);
                break;
            case "provider_capacity_warning":
                handleProviderCapacityWarning(msg);
                break;
            case "provider_temporarily_unavailable":
            case "reconnect_attempt":
            case "recovered":
            case "reconnect_cancelled":
                handleProviderRecovery(msg);
                break;
            default:
                console.log("Unknown event type:", msg.type);
        }
    }

    function handleSnapshot(msg) {
        appState.status = msg.status;
        if (msg.status === "idle_blocked" || msg.status === "idle_ready") {
            appState.providerOutage = null;
        }
        if (msg.tts_epoch != null) {
            appState.currentTtsEpoch = msg.tts_epoch;
        }
        ttsChunkBuffers = {};
        appState.ttsSpeakingSeq = null;
        clearTtsPlaybackState();

        appState.checks = msg.checks || [];
        appState.sourcePartial = msg.source_partial || "";
        appState.exported = msg.exported || false;
        appState.exportPath = msg.export_path || null;
        appState.startedAt = msg.started_at || null;
        appState.endedAt = msg.ended_at || null;

        appState.availableTargetLanguages = msg.available_target_languages || [];
        appState.targetLanguage = msg.target_language || "en";
        confirmedTargetLanguage = appState.targetLanguage;

        appState.exportFailure = msg.export_failure || null;
        if (appState.exportFailure && msg.status === "session_ended") {
            appState.exportFailureModalVisible = true;
        } else {
            appState.exportFailureModalVisible = false;
        }

        var notice = msg.recovery_notice;
        if (notice && notice.status === "failed") {
            appState.recoveryFailure = notice;
            appState.recoveryNotice = null;
        } else {
            appState.recoveryFailure = null;
            appState.recoveryNotice = (notice && !appState.recoverySuppressed)
                ? notice
                : null;
        }

        const wasReviewing = !appState.autoScroll;

        appState.captions = [];
        const segments = msg.segments || [];
        for (let i = 0; i < segments.length; i++) {
            const seg = segments[i];
            if (seg.translation_status === "pending") continue;
            appState.captions.push({
                seq: seg.seq,
                sourceText: seg.source_text,
                translatedText: seg.translated_text,
                segmentKind: seg.segment_kind,
                translationStatus: seg.translation_status,
                createdAt: seg.created_at,
                targetLanguage: seg.target_language,
            });
        }
        appState.captions.reverse();
        appState.segments = segments;

        if (appState.startedAt && (appState.status === "listening" || appState.status === "reconnecting")) {
            appState.elapsed = Math.floor((Date.now() - new Date(appState.startedAt).getTime()) / 1000);
        }

        if (appState.startedAt && appState.endedAt && appState.status === "session_ended") {
            appState.elapsed = Math.floor(
                (new Date(appState.endedAt).getTime() - new Date(appState.startedAt).getTime()) / 1000
            );
        }

        if (isFirstConnect) {
            resetSessionPreferences();
            if (appState.status === "idle_blocked" || appState.status === "idle_ready") {
                send({ type: "tts_mute", muted: appState.ttsMuted });
            }
            isFirstConnect = false;
        } else if (appState.status === "idle_blocked" || appState.status === "idle_ready") {
            resetSessionPreferences();
            send({ type: "tts_mute", muted: appState.ttsMuted });
        }

        populateLanguageDropdowns();
        fullRender();

        if (wasReviewing) {
            appState.autoScroll = false;
            els.jumpLatest.classList.remove("hidden");
        }
    }

    function handleReadiness(msg) {
        appState.checks = msg.checks || [];
        render();
    }

    function handleStatus(msg) {
        appState.status = msg.status;

        if (msg.tts_epoch != null) {
            appState.currentTtsEpoch = msg.tts_epoch;
            ttsChunkBuffers = {};
            appState.ttsSpeakingSeq = null;
            clearTtsPlaybackState();
            renderSpeakingHighlight();
        }

        if (msg.started_at) {
            appState.startedAt = msg.started_at;
        }

        if (msg.status === "session_ended" && appState.startedAt) {
            if (appState.endedAt) {
                appState.elapsed = Math.floor(
                    (new Date(appState.endedAt).getTime() - new Date(appState.startedAt).getTime()) / 1000
                );
            } else {
                appState.elapsed = Math.floor((Date.now() - new Date(appState.startedAt).getTime()) / 1000);
            }
        }

        if (msg.status === "idle_blocked" || msg.status === "idle_ready") {
            appState.exportFailureModalVisible = false;
        }

        render();
    }

    function handleSourcePartial(msg) {
        appState.sourcePartial = msg.text || "";
        if (els.sourcePartial) {
            els.sourcePartial.textContent = appState.sourcePartial;
        }
    }

    function handleCaption(msg) {
        const entry = {
            seq: msg.seq,
            sourceText: msg.source_text,
            translatedText: msg.translated_text,
            segmentKind: msg.segment_kind,
            translationStatus: msg.translation_status,
            createdAt: msg.created_at,
            targetLanguage: msg.target_language,
        };
        appState.captions.unshift(entry);
        prependCaptionEntry(entry);
        if (typeof entry.seq === "number") {
            send({ type: "render_ack", seq: entry.seq });
        }

        if (appState.autoScroll && els.captionLog) {
            scrollToTop(els.captionLog);
        }
    }

    function handleExportResult(msg) {
        if (msg.success) {
            appState.exported = true;
            appState.exportPath = msg.path || null;
            appState.exportFailure = null;
            appState.exportFailureModalVisible = false;
            renderSummary();
            renderExportFailureModal();
        } else {
            appState.exportFailure = {
                error: msg.error || "Export failed",
                created_at: new Date().toISOString(),
            };
            appState.exportFailureModalVisible = true;
            render();
        }
    }

    function handleError(msg) {
        console.error("Server error:", msg.message);

        if (msg.message && /language/i.test(msg.message)) {
            appState.targetLanguage = confirmedTargetLanguage;
            if (els.drawerTargetSelect) {
                els.drawerTargetSelect.value = confirmedTargetLanguage;
            }
            if (els.idleTargetSelect) {
                els.idleTargetSelect.value = confirmedTargetLanguage;
            }
            renderHeaderLang();
            if (els.drawerLangError) {
                els.drawerLangError.textContent = msg.message;
                els.drawerLangError.classList.remove("hidden");
                setTimeout(function () {
                    els.drawerLangError.classList.add("hidden");
                }, 4000);
            }
        }
    }

    function handleProviderRecovery(msg) {
        if (providerNoticeTimer) {
            clearTimeout(providerNoticeTimer);
            providerNoticeTimer = null;
        }

        if (msg.type === "reconnect_cancelled") {
            appState.providerOutage = null;
            renderProviderNotice();
            return;
        }

        if (msg.type === "recovered") {
            appState.providerOutage = {
                outcome: "recovered",
                attempts: msg.attempts || 0,
                downtime_ms: msg.downtime_ms || 0,
            };
            renderProviderNotice();
            providerNoticeTimer = setTimeout(function () {
                appState.providerOutage = null;
                providerNoticeTimer = null;
                renderProviderNotice();
            }, 6000);
            return;
        }

        if (msg.type === "reconnect_attempt") {
            const current = appState.providerOutage || { outcome: "retrying" };
            current.outcome = "retrying";
            current.attempt = msg.attempt;
            current.max_attempts = msg.max_attempts;
            appState.providerOutage = current;
        } else {
            appState.providerOutage = msg;
        }
        renderProviderNotice();
    }

    function renderProviderNotice() {
        if (!els.providerNotice) return;
        const notice = appState.providerOutage;
        if (!notice) {
            els.providerNotice.classList.add("hidden");
            els.providerNotice.classList.remove("exhausted");
            return;
        }

        els.providerNotice.classList.remove("hidden");
        const terminal = notice.outcome === "exhausted" || notice.outcome === "permanent";
        els.providerNotice.classList.toggle("exhausted", terminal);

        if (notice.outcome === "recovered") {
            els.providerNoticeTitle.textContent = "Transcription recovered";
            els.providerNoticeDetail.textContent =
                "Recovered after " + notice.attempts + " attempt(s).";
        } else if (terminal) {
            els.providerNoticeTitle.textContent = "Transcription unavailable";
            els.providerNoticeDetail.textContent =
                "Stopped safely after " + (notice.attempts || 0) +
                " attempt(s). Export this session, then start a new one to retry.";
        } else {
            els.providerNoticeTitle.textContent = "Transcription temporarily unavailable";
            if (notice.attempt && notice.max_attempts) {
                els.providerNoticeDetail.textContent =
                    "Reconnect attempt " + notice.attempt + " of " + notice.max_attempts + "…";
            } else {
                els.providerNoticeDetail.textContent = "Preparing a bounded reconnect…";
            }
        }
    }


    function handleElapsed(msg) {
        appState.elapsed = msg.seconds || 0;
        if (els.elapsed) {
            els.elapsed.textContent = formatTime(appState.elapsed);
        }
    }

    function handleTtsSpeaking(msg) {
        if (appState.ttsMuted || msg.tts_epoch == null || msg.seq == null) return;
        var incomingEpoch = msg.tts_epoch;
        if (incomingEpoch !== appState.currentTtsEpoch) {
            clearTtsPlaybackState();
            purgeTtsChunkBuffersNotEpoch(incomingEpoch);
        }
        appState.currentTtsEpoch = incomingEpoch;
        appState.ttsSpeakingSeq = msg.seq;
        renderSpeakingHighlight();
    }

    function handleTtsAudio(msg) {
        if (appState.ttsMuted || msg.tts_epoch !== appState.currentTtsEpoch) return;
        var key = msg.seq + ":" + msg.tts_epoch;
        if (!ttsChunkBuffers[key]) {
            ttsChunkBuffers[key] = { chunks: [], done: false };
        }
        if (msg.data) {
            ttsChunkBuffers[key].chunks.push(msg.data);
        }
        if (msg.is_last === true) {
            ttsChunkBuffers[key].done = true;
            enqueueTtsPlaybackFromKey(key);
        }
    }

    function handleTtsError(msg) {
        if (msg.tts_epoch !== appState.currentTtsEpoch) return;
        removeFromTtsPlaybackQueue(msg.seq, msg.tts_epoch);
        if (appState.ttsSpeakingSeq === msg.seq) {
            appState.ttsSpeakingSeq = null;
            renderSpeakingHighlight();
        }
        delete ttsChunkBuffers[msg.seq + ":" + msg.tts_epoch];
    }

    function handleTtsSkipped(msg) {
        handleTtsError(msg);
    }

    function handleProviderCapacityWarning(msg) {
        console.warn("Provider capacity warning:", msg);
        appState.providerCapacityWarning = msg;
        const detail =
            "Translation provider capacity is temporarily limited. " +
            "Some captions may be skipped; processing will continue.";
        if (providerCapacityTimer) {
            clearTimeout(providerCapacityTimer);
        }
        if (els.capacityNotice && els.capacityNoticeDetail) {
            els.capacityNoticeDetail.textContent = detail;
            els.capacityNotice.classList.remove("hidden");
            providerCapacityTimer = setTimeout(function () {
                els.capacityNotice.classList.add("hidden");
                providerCapacityTimer = null;
            }, 5000);
        }
        if (els.drawerLangError) {
            els.drawerLangError.textContent = detail;
            els.drawerLangError.classList.remove("hidden");
            setTimeout(function () {
                els.drawerLangError.classList.add("hidden");
            }, 5000);
        }
    }

    function purgeTtsChunkBuffersNotEpoch(epoch) {
        var suf = ":" + String(epoch);
        Object.keys(ttsChunkBuffers).forEach(function (k) {
            if (!k.endsWith(suf)) {
                delete ttsChunkBuffers[k];
            }
        });
    }

    function discardTtsChunkBuffersForEpoch(epoch) {
        var suf = ":" + String(epoch);
        Object.keys(ttsChunkBuffers).forEach(function (k) {
            if (k.endsWith(suf)) {
                delete ttsChunkBuffers[k];
            }
        });
    }

    function clearTtsPlaybackState() {
        ttsPlaybackQueue.length = 0;
        ttsPlaybackStarting = false;
        if (ttsActiveSourceNode) {
            try {
                ttsActiveSourceNode._cbCancelled = true;
                ttsActiveSourceNode.onended = null;
                ttsActiveSourceNode.stop(0);
            } catch (_) { /* node may already be stopped */ }
            ttsActiveSourceNode = null;
        }
    }

    function removeFromTtsPlaybackQueue(seq, epoch) {
        ttsPlaybackQueue = ttsPlaybackQueue.filter(function (item) {
            return item.seq !== seq || item.epoch !== epoch;
        });
    }

    function decodeTtsChunkEntryToItem(key) {
        var buf = ttsChunkBuffers[key];
        if (!buf || !buf.done) return null;
        var colon = key.lastIndexOf(":");
        var seq = parseInt(key.slice(0, colon), 10);
        var epoch = parseInt(key.slice(colon + 1), 10);
        if (Number.isNaN(seq) || Number.isNaN(epoch)) return null;

        var totalLen = 0;
        var i;
        var decoded = [];
        for (i = 0; i < buf.chunks.length; i++) {
            var binStr = atob(buf.chunks[i]);
            var u8 = new Uint8Array(binStr.length);
            for (var j = 0; j < binStr.length; j++) {
                u8[j] = binStr.charCodeAt(j);
            }
            decoded.push(u8);
            totalLen += u8.length;
        }
        var pcm = new Uint8Array(totalLen);
        var off = 0;
        for (i = 0; i < decoded.length; i++) {
            pcm.set(decoded[i], off);
            off += decoded[i].length;
        }

        delete ttsChunkBuffers[key];

        var numSamples = Math.floor(pcm.length / 4);
        var view = new DataView(pcm.buffer, pcm.byteOffset, pcm.byteLength);
        var float32 = new Float32Array(numSamples);
        for (i = 0; i < numSamples; i++) {
            float32[i] = view.getFloat32(i * 4, true);
        }

        if (!audioContext) {
            audioContext = new AudioContext();
        }
        var ab = audioContext.createBuffer(1, float32.length, 24000);
        ab.getChannelData(0).set(float32);
        return { seq: seq, epoch: epoch, audioBuffer: ab, numSamples: numSamples };
    }

    function enqueueTtsPlaybackFromKey(key) {
        var item = decodeTtsChunkEntryToItem(key);
        if (!item) return;

        if (item.numSamples === 0) {
            if (appState.ttsSpeakingSeq === item.seq && appState.currentTtsEpoch === item.epoch) {
                appState.ttsSpeakingSeq = null;
                renderSpeakingHighlight();
            }
            tryStartTtsPlayback();
            return;
        }

        ttsPlaybackQueue.push({
            seq: item.seq,
            epoch: item.epoch,
            audioBuffer: item.audioBuffer,
        });
        tryStartTtsPlayback();
    }

    function tryStartTtsPlayback() {
        if (ttsActiveSourceNode || ttsPlaybackStarting || ttsPlaybackQueue.length === 0) {
            return;
        }
        if (appState.ttsMuted) {
            return;
        }
        if (!audioContext) {
            audioContext = new AudioContext();
        }

        var queued = ttsPlaybackQueue.shift();
        var seq = queued.seq;
        var epoch = queued.epoch;
        var ab = queued.audioBuffer;

        ttsPlaybackStarting = true;
        audioContext.resume().then(function () {
            ttsPlaybackStarting = false;
            if (ttsActiveSourceNode) {
                ttsPlaybackQueue.unshift(queued);
                tryStartTtsPlayback();
                return;
            }
            if (appState.ttsMuted || epoch !== appState.currentTtsEpoch) {
                tryStartTtsPlayback();
                return;
            }

            var srcNode = audioContext.createBufferSource();
            ttsActiveSourceNode = srcNode;
            srcNode.buffer = ab;
            srcNode.connect(audioContext.destination);
            srcNode._cbCancelled = false;
            srcNode.onended = function () {
                if (ttsActiveSourceNode === srcNode) {
                    ttsActiveSourceNode = null;
                }
                if (appState.ttsSpeakingSeq === seq && appState.currentTtsEpoch === epoch) {
                    appState.ttsSpeakingSeq = null;
                    renderSpeakingHighlight();
                }
                if (!srcNode._cbCancelled && appState.currentTtsEpoch === epoch) {
                    send({ type: "tts_playback_complete", seq: seq });
                }
                tryStartTtsPlayback();
            };
            try {
                srcNode.start();
                send({ type: "tts_playback_start", seq: seq });
            } catch (_) {
                ttsActiveSourceNode = null;
                tryStartTtsPlayback();
            }
        });
    }

    function applyLocalTtsMuteEffects() {
        clearTtsPlaybackState();
        discardTtsChunkBuffersForEpoch(appState.currentTtsEpoch);
        appState.ttsSpeakingSeq = null;
        renderSpeakingHighlight();
        renderReplayButtons();
    }

    function renderSpeakingHighlight() {
        if (!els.captionLog) return;
        var entries = els.captionLog.querySelectorAll(".caption-entry");
        var speaking = appState.ttsSpeakingSeq;
        for (var i = 0; i < entries.length; i++) {
            var el = entries[i];
            var ds = el.getAttribute("data-seq");
            var seq = ds == null ? null : parseInt(ds, 10);
            if (speaking != null && seq === speaking) {
                el.classList.add("speaking");
            } else {
                el.classList.remove("speaking");
            }
        }
    }

    function getLangLabel(code) {
        var lang = appState.availableTargetLanguages.find(function (l) {
            return l.code === code;
        });
        return lang ? lang.label : code;
    }

    function renderReplayButtons() {
        if (!els.captionLog) return;
        var buttons = els.captionLog.querySelectorAll(".replay-btn");
        var s = appState.status;
        for (var i = 0; i < buttons.length; i++) {
            var replayBtn = buttons[i];
            var ds = replayBtn.getAttribute("data-seq");
            var seq = ds == null ? null : parseInt(ds, 10);
            var entry = appState.captions.find(function (c) { return c.seq === seq; });
            var targetLanguage = entry ? entry.targetLanguage : "";
            var supported = TTS_SUPPORTED_LANGUAGES.has(targetLanguage);
            var langLabel = getLangLabel(targetLanguage);
            var enabled;
            if (s === "session_ended") {
                enabled = supported && !appState.ttsMuted;
            } else if (s === "listening" || s === "reconnecting") {
                enabled = supported && !appState.ttsMuted;
            } else {
                enabled = false;
            }
            replayBtn.disabled = !enabled;
            replayBtn.title = enabled
                ? "Replay"
                : (supported ? "Muted" : "TTS not available for " + langLabel);
        }
    }

    function renderTtsControls() {
        var s = appState.status;
        var banner = els.audioEnableBanner;
        if (banner) {
            if ((s === "listening" || s === "reconnecting" || s === "session_ended") && !appState.ttsAudioUnlocked && !appState.ttsMuted) {
                banner.classList.remove("hidden");
            } else {
                banner.classList.add("hidden");
            }
        }

        var supported = TTS_SUPPORTED_LANGUAGES.has(appState.targetLanguage);
        var langLabel = getLangLabel(appState.targetLanguage);
        var unsupportedTitle = "TTS not available for " + langLabel;
        var toggleTitle = supported
            ? (appState.captionsOnly ? "Turn on spoken readback" : (appState.ttsMuted ? "Unmute TTS" : "Mute TTS"))
            : unsupportedTitle;
        if (els.captionsOnlyIdle) els.captionsOnlyIdle.checked = appState.captionsOnly;
        if (els.captionsOnlyDrawer) els.captionsOnlyDrawer.checked = appState.captionsOnly;

        if (els.ttsToggleBtn) {
            els.ttsToggleBtn.disabled = !supported;
            els.ttsToggleBtn.title = toggleTitle;
            els.ttsToggleBtn.setAttribute("aria-label", toggleTitle);
            els.ttsToggleBtn.classList.toggle("active", !appState.ttsMuted);
            els.ttsToggleBtn.classList.toggle("tts-muted", appState.ttsMuted);
            els.ttsToggleBtn.textContent = appState.ttsMuted ? "🔇" : "🔊";
        }

        if (els.ttsDrawerToggle) {
            els.ttsDrawerToggle.disabled = !supported;
            els.ttsDrawerToggle.title = toggleTitle;
            els.ttsDrawerToggle.setAttribute("aria-label", toggleTitle);
            els.ttsDrawerToggle.classList.toggle("active", !appState.ttsMuted);
            els.ttsDrawerToggle.classList.toggle("tts-muted", appState.ttsMuted);
            els.ttsDrawerToggle.textContent = appState.ttsMuted ? "🔇" : "🔊";
        }
    }

    // ===== 3.4 Render Function =====

    function render() {
        document.body.dataset.state = appState.status;
        renderHeader();
        renderHeaderLang();
        renderIdlePanel();
        renderRecoveryNotice();
        renderRecoveryFailureWarning();
        renderProviderNotice();
        renderSourcePartial();
        renderSummary();
        renderModal();
        renderExportFailureModal();
        renderFooter();
        renderSourceVisibility();
        renderFontSize();
        renderDrawer();
        renderTtsControls();
        renderReplayButtons();
        renderSpeakingHighlight();
    }

    function fullRender() {
        render();
        rebuildCaptionLog();
    }

    function renderHeader() {
        const s = appState.status;

        els.statusDot.className = "status-dot";
        if (s === "idle_ready" || s === "listening") {
            els.statusDot.classList.add("green");
        } else {
            els.statusDot.classList.add("yellow");
        }

        const labels = {
            idle_blocked: "Not ready",
            idle_ready: "Ready",
            listening: "Listening",
            reconnecting: "Reconnecting…",
            session_ended: "Session ended",
        };
        els.statusLabel.textContent = labels[s] || s;

        if (s === "session_ended") {
            els.elapsed.textContent = formatTime(appState.elapsed) + " total";
        } else {
            els.elapsed.textContent = formatTime(appState.elapsed);
        }
    }

    function renderHeaderLang() {
        const s = appState.status;
        if (s === "listening" || s === "reconnecting" || s === "session_ended") {
            const lang = appState.availableTargetLanguages.find(
                function (l) { return l.code === appState.targetLanguage; }
            );
            els.headerLang.textContent = lang ? lang.label : appState.targetLanguage;
            els.headerLang.classList.remove("hidden");
        } else {
            els.headerLang.classList.add("hidden");
        }
    }

    function renderIdlePanel() {
        if (appState.status !== "idle_blocked" && appState.status !== "idle_ready") return;

        els.checklist.innerHTML = "";
        for (let i = 0; i < appState.checks.length; i++) {
            const check = appState.checks[i];
            const row = document.createElement("div");
            row.className = "check-item " + (check.ready ? "check-ready" : "check-blocked");

            const name = document.createElement("span");
            name.className = "check-name";
            name.textContent = check.name;

            const status = document.createElement("span");
            status.className = "check-status";
            status.textContent = check.detail;

            row.appendChild(name);
            row.appendChild(status);
            els.checklist.appendChild(row);
        }

        els.startBtn.disabled = appState.status !== "idle_ready" || appState.recoveryFailure !== null;

        if (appState.recoveryFailure !== null) {
            els.idleHint.textContent = "Resolve the failed recovery above to enable Start.";
        } else if (appState.status === "idle_blocked") {
            els.idleHint.textContent = "Resolve checklist blockers to enable Start.";
        } else {
            els.idleHint.textContent = "";
        }
    }

    function renderRecoveryNotice() {
        var isIdle = appState.status === "idle_blocked" || appState.status === "idle_ready";
        if (appState.recoveryNotice && isIdle && !appState.recoverySuppressed) {
            els.recoveryNotice.classList.remove("hidden");
            els.recoveryPath.textContent = appState.recoveryNotice.export_path || "";
        } else {
            els.recoveryNotice.classList.add("hidden");
        }
    }

    function renderSourcePartial() {
        if (els.sourcePartial) {
            els.sourcePartial.textContent = appState.sourcePartial;
        }
    }

    function rebuildCaptionLog() {
        els.captionLog.innerHTML = "";
        for (let i = 0; i < appState.captions.length; i++) {
            appendCaptionEntry(appState.captions[i]);
        }
        els.captionLog.style.setProperty("--caption-font-size", appState.fontSize + "px");

        if (appState.autoScroll) {
            scrollToTop(els.captionLog);
        }
        renderReplayButtons();
        renderSpeakingHighlight();
    }

    function buildCaptionEntry(entry) {
        const div = document.createElement("div");
        div.className = "caption-entry";
        div.dataset.seq = String(entry.seq);

        const speakingLabel = document.createElement("span");
        speakingLabel.className = "speaking-label";
        speakingLabel.textContent = "🔊 SPEAKING";
        div.appendChild(speakingLabel);

        if (entry.segmentKind === "reconnect_fragment") {
            div.classList.add("reconnect-fragment");
            const label = document.createElement("span");
            label.className = "fragment-label";
            label.textContent = "[incomplete fragment]";
            div.appendChild(label);
        }

        if (entry.createdAt && appState.startedAt) {
            const tcDiv = document.createElement("div");
            tcDiv.className = "caption-timecode";
            const createdAt = new Date(entry.createdAt);
            const startedAt = new Date(appState.startedAt);
            const offsetSeconds = Math.max(0, Math.floor((createdAt - startedAt) / 1000));
            const relative = formatTime(offsetSeconds);
            const wall = createdAt.toLocaleTimeString("en-GB", { hour12: false });
            tcDiv.textContent = relative + " \u00b7 " + wall;
            div.appendChild(tcDiv);
        }

        const trans = document.createElement("div");
        trans.className = "caption-translated";

        if (
            entry.translatedText == null ||
            entry.translationStatus === "pending" ||
            entry.translationStatus === "timed_out" ||
            entry.translationStatus === "failed"
        ) {
            trans.textContent = "translation unavailable";
            trans.classList.add("translation-unavailable");
        } else {
            trans.textContent = entry.translatedText;
        }
        div.appendChild(trans);

        const src = document.createElement("div");
        src.className = "caption-source";
        src.textContent = entry.sourceText || "";
        div.appendChild(src);

        const replayBtn = document.createElement("button");
        replayBtn.className = "replay-btn";
        replayBtn.textContent = "▶";
        replayBtn.setAttribute("aria-label", "Replay");
        replayBtn.dataset.seq = String(entry.seq);
        replayBtn.addEventListener("click", function () {
            send({ type: "tts_replay", seq: entry.seq });
        });
        div.appendChild(replayBtn);

        return div;
    }

    function prependCaptionEntry(entry) {
        const node = buildCaptionEntry(entry);
        els.captionLog.insertBefore(node, els.captionLog.firstChild);
        renderReplayButtons();
        renderSpeakingHighlight();
    }

    function appendCaptionEntry(entry) {
        const node = buildCaptionEntry(entry);
        els.captionLog.appendChild(node);
    }

    function renderSummary() {
        if (appState.status !== "session_ended") return;

        const count = appState.captions.length;
        els.captionCount.textContent = count + " caption" + (count !== 1 ? "s" : "");

        if (appState.exported) {
            els.exportWarning.classList.add("hidden");
            els.exportConfirm.classList.remove("hidden");
            els.exportConfirm.textContent = "Saved to " + (appState.exportPath || "disk");
        } else {
            els.exportWarning.classList.remove("hidden");
            els.exportConfirm.classList.add("hidden");
        }

        const errEl = els.summaryBar.querySelector(".export-error");
        if (errEl && appState.exported) {
            errEl.remove();
        }
    }

    function setModalVisible(modal, visible, firstControl) {
        const wasVisible = modal.classList.contains("visible");
        if (visible === wasVisible) return;

        if (visible) {
            modalReturnFocus.set(modal, document.activeElement);
            modal.classList.add("visible");
            firstControl.focus();
        } else {
            modal.classList.remove("visible");
            const previous = modalReturnFocus.get(modal);
            modalReturnFocus.delete(modal);
            if (previous && previous !== document.body &&
                previous.isConnected && previous.getClientRects().length) {
                previous.focus();
            } else {
                els.statusLabel.focus();
            }
        }
    }

    function renderModal() {
        setModalVisible(els.discardModal, appState.modalVisible, els.cancelDiscard);
    }

    function renderExportFailureModal() {
        if (appState.exportFailureModalVisible && appState.exportFailure) {
            els.exportFailureError.textContent = appState.exportFailure.error || "Export failed";
        }
        setModalVisible(
            els.exportFailureModal,
            appState.exportFailureModalVisible && Boolean(appState.exportFailure),
            els.retryExportBtn
        );
    }

    function renderRecoveryFailureWarning() {
        if (appState.recoveryFailure) {
            els.recoveryFailureWarning.classList.remove("hidden");
            els.recoveryFailureError.textContent = appState.recoveryFailure.error || "Unknown error";
        } else {
            els.recoveryFailureWarning.classList.add("hidden");
        }
    }

    function renderFooter() {
        const s = appState.status;

        if (s === "idle_blocked" || s === "idle_ready") {
            els.footerHints.textContent = "F \u2014 Fullscreen \u00b7 Space \u2014 Start when ready";
        } else if (s === "session_ended") {
            els.footerHints.textContent = "S \u2014 Export \u00b7 F \u2014 Fullscreen";
        } else if (s === "listening" || s === "reconnecting") {
            els.footerHints.textContent = "";
        } else {
            els.footerHints.textContent = "";
        }
    }

    function renderSourceVisibility() {
        document.body.classList.toggle("source-hidden", !appState.sourceVisible);

        if (els.sourceToggle) {
            els.sourceToggle.classList.toggle("active", appState.sourceVisible);
        }
    }

    function renderFontSize() {
        if (els.captionLog) {
            els.captionLog.style.setProperty("--caption-font-size", appState.fontSize + "px");
        }
    }

    function renderDrawer() {
        if (!els.settingsDrawer) return;

        const s = appState.status;
        if (appState.drawerOpen && s !== "listening" && s !== "reconnecting") {
            appState.drawerOpen = false;
        }
        const wasOpen = els.settingsDrawer.classList.contains("open");
        if (wasOpen && !appState.drawerOpen &&
            els.settingsDrawer.contains(document.activeElement)) {
            if (els.gearBtn.getClientRects().length) {
                els.gearBtn.focus();
            } else {
                els.statusLabel.focus();
            }
        }
        els.settingsDrawer.classList.toggle("open", appState.drawerOpen);
        els.settingsDrawer.inert = !appState.drawerOpen;
        els.settingsDrawer.setAttribute("aria-hidden", String(!appState.drawerOpen));
        els.gearBtn.setAttribute("aria-expanded", String(appState.drawerOpen));
        if (appState.drawerOpen && !wasOpen) {
            els.drawerClose.focus();
        }
    }

    function toggleDrawer() {
        appState.drawerOpen = !appState.drawerOpen;
        renderDrawer();
    }

    function populateLanguageDropdowns() {
        var langs = appState.availableTargetLanguages;
        if (langs.length === 0) {
            langs = [{ code: "en", label: "English" }];
        }

        [els.idleTargetSelect, els.drawerTargetSelect].forEach(function (sel) {
            if (!sel) return;
            sel.innerHTML = "";
            for (var i = 0; i < langs.length; i++) {
                var opt = document.createElement("option");
                opt.value = langs[i].code;
                opt.textContent = langs[i].label;
                sel.appendChild(opt);
            }
            sel.value = appState.targetLanguage;
        });
    }

    function handleDrawerTargetChange(e) {
        var newLang = e.target.value;
        appState.targetLanguage = newLang;
        send({ type: "set_target_language", language: newLang });
        if (els.idleTargetSelect) {
            els.idleTargetSelect.value = newLang;
        }
        renderHeaderLang();
        renderTtsControls();
    }

    // ===== 3.5 Auto-Scroll =====

    function setupAutoScroll() {
        els.captionLog.addEventListener("scroll", function () {
            if (programmaticScroll) return;
            appState.autoScroll = false;
            els.jumpLatest.classList.remove("hidden");
        });

        ["wheel", "touchmove", "pointerdown"].forEach(function (evt) {
            els.captionLog.addEventListener(evt, function () {
                appState.autoScroll = false;
                els.jumpLatest.classList.remove("hidden");
            });
        });

        els.jumpLatest.addEventListener("click", function () {
            appState.autoScroll = true;
            scrollToTop(els.captionLog);
            els.jumpLatest.classList.add("hidden");
        });
    }

    // ===== 3.6 Controls & Event Listeners =====

    function setupControls() {
        els.startBtn.addEventListener("click", function () {
            appState.recoverySuppressed = true;
            appState.recoveryNotice = null;
            send({ type: "start", target_language: appState.targetLanguage, tts_muted: appState.ttsMuted });
        });

        els.stopBtn.addEventListener("click", function () {
            send({ type: "stop" });
            appState.drawerOpen = false;
            renderDrawer();
        });

        els.exportBtn.addEventListener("click", function () {
            send({ type: "export" });
        });

        els.newSessionBtn.addEventListener("click", function () {
            if (!appState.exported) {
                appState.modalVisible = true;
                render();
            } else {
                appState.recoverySuppressed = true;
                appState.recoveryNotice = null;
                send({ type: "new_session", tts_muted: appState.captionsOnly });
            }
        });

        els.fullscreenBtn.addEventListener("click", toggleFullscreen);

        els.fontInc.addEventListener("click", function () {
            stepFontSize(1);
        });

        els.fontDec.addEventListener("click", function () {
            stepFontSize(-1);
        });

        els.gearBtn.addEventListener("click", toggleDrawer);

        els.drawerClose.addEventListener("click", function () {
            appState.drawerOpen = false;
            renderDrawer();
        });

        els.sourceToggle.addEventListener("click", function () {
            appState.sourceVisible = !appState.sourceVisible;
            renderSourceVisibility();
        });

        els.drawerTargetSelect.addEventListener("change", handleDrawerTargetChange);

        els.idleTargetSelect.addEventListener("change", function (e) {
            appState.targetLanguage = e.target.value;
            renderHeaderLang();
        });

        els.dismissRecovery.addEventListener("click", function () {
            appState.recoverySuppressed = true;
            appState.recoveryNotice = null;
            els.recoveryNotice.classList.add("hidden");
        });

        els.cancelDiscard.addEventListener("click", function () {
            appState.modalVisible = false;
            render();
        });

        els.confirmDiscard.addEventListener("click", function () {
            appState.modalVisible = false;
            appState.recoverySuppressed = true;
            appState.recoveryNotice = null;
            send({ type: "new_session", tts_muted: appState.captionsOnly });
            resetSessionPreferences();
            render();
        });

        els.retryExportBtn.addEventListener("click", function () {
            send({ type: "export" });
        });

        els.discardExportBtn.addEventListener("click", function () {
            appState.exportFailureModalVisible = false;
            appState.exportFailure = null;
            send({ type: "new_session", tts_muted: appState.captionsOnly });
        });

        els.retryRecoveryBtn.addEventListener("click", function () {
            send({ type: "retry_recovery" });
        });

        els.discardRecoveryBtn.addEventListener("click", function () {
            send({ type: "discard_recovery" });
        });

        els.enableAudioBtn.addEventListener("click", function () {
            if (!audioContext) {
                audioContext = new AudioContext();
            }
            audioContext.resume().then(function () {
                appState.ttsAudioUnlocked = true;
                send({ type: "tts_audio_enabled" });
                renderTtsControls();
            });
        });

        [els.ttsToggleBtn, els.ttsDrawerToggle].forEach(function (button) {
            button.addEventListener("click", toggleTtsMute);
        });
        [els.captionsOnlyIdle, els.captionsOnlyDrawer].forEach(function (checkbox) {
            checkbox.addEventListener("change", function () {
                setCaptionsOnlyPreference(checkbox.checked);
            });
        });
    }

    function toggleFullscreen() {
        if (document.fullscreenElement) {
            document.exitFullscreen();
        } else {
            document.documentElement.requestFullscreen().catch(function () {});
        }
    }

    function stepFontSize(direction) {
        const idx = FONT_SIZES.indexOf(appState.fontSize);
        const next = idx + direction;
        if (next >= 0 && next < FONT_SIZES.length) {
            appState.fontSize = FONT_SIZES[next];
            renderFontSize();
        }
    }

    // ===== 3.7 Keyboard Shortcuts =====

    function handleModalKeyboard(e, modal) {
        if (e.key === "Escape" && modal === els.discardModal) {
            e.preventDefault();
            appState.modalVisible = false;
            render();
            return;
        }
        if (e.key !== "Tab") return;

        const controls = Array.from(modal.querySelectorAll("button:not([disabled])"));
        if (!controls.length) return;
        const first = controls[0];
        const last = controls[controls.length - 1];
        if (e.shiftKey && (document.activeElement === first || !modal.contains(document.activeElement))) {
            e.preventDefault();
            last.focus();
        } else if (!e.shiftKey && (document.activeElement === last || !modal.contains(document.activeElement))) {
            e.preventDefault();
            first.focus();
        }
    }

    function setupKeyboard() {
        document.addEventListener("keydown", function (e) {
            const modal = els.discardModal.classList.contains("visible")
                ? els.discardModal
                : (els.exportFailureModal.classList.contains("visible") ? els.exportFailureModal : null);
            if (modal) {
                handleModalKeyboard(e, modal);
                return;
            }
            if (e.key === "Escape" && appState.drawerOpen) {
                e.preventDefault();
                appState.drawerOpen = false;
                renderDrawer();
                return;
            }
            const tag = e.target.tagName.toLowerCase();
            if (tag === "input" || tag === "textarea" || tag === "button" || tag === "select") return;

            const s = appState.status;

            if (e.code === "Space") {
                e.preventDefault();
                if (s === "idle_ready" && appState.recoveryFailure === null) {
                    appState.recoverySuppressed = true;
                    appState.recoveryNotice = null;
                    send({ type: "start", target_language: appState.targetLanguage, tts_muted: appState.ttsMuted });
                } else if (s === "listening" || s === "reconnecting") {
                    send({ type: "stop" });
                }
                return;
            }

            if (e.key === "f" || e.key === "F") {
                toggleFullscreen();
                return;
            }

            if (e.key === "+" || e.key === "=") {
                if (s === "listening" || s === "reconnecting") {
                    stepFontSize(1);
                }
                return;
            }

            if (e.key === "-") {
                if (s === "listening" || s === "reconnecting") {
                    stepFontSize(-1);
                }
                return;
            }

            if (e.key === "s" || e.key === "S") {
                if (s === "session_ended") {
                    send({ type: "export" });
                }
                return;
            }

            if (e.key === "g" || e.key === "G") {
                if (s === "listening" || s === "reconnecting") {
                    toggleDrawer();
                }
                return;
            }
        });
    }

    // ===== 3.8 Session Preferences Reset =====

    function loadCaptionsOnlyPreference() {
        try {
            appState.captionsOnly = localStorage.getItem(CAPTIONS_ONLY_KEY) === "true";
        } catch (_) {
            appState.captionsOnly = false;
        }
        appState.ttsMuted = appState.captionsOnly;
    }

    function setCaptionsOnlyPreference(enabled) {
        appState.captionsOnly = enabled;
        appState.ttsMuted = enabled;
        try {
            localStorage.setItem(CAPTIONS_ONLY_KEY, String(enabled));
        } catch (_) { /* storage may be unavailable */ }
        if (enabled) {
            applyLocalTtsMuteEffects();
        } else if (appState.ttsAudioUnlocked) {
            send({ type: "tts_audio_enabled" });
        }
        send({ type: "tts_mute", muted: appState.ttsMuted });
        renderTtsControls();
        renderReplayButtons();
    }

    function toggleTtsMute() {
        if (appState.captionsOnly) {
            setCaptionsOnlyPreference(false);
            return;
        }
        appState.ttsMuted = !appState.ttsMuted;
        if (appState.ttsMuted) {
            applyLocalTtsMuteEffects();
        }
        send({ type: "tts_mute", muted: appState.ttsMuted });
        renderTtsControls();
        renderReplayButtons();
    }

    function resetSessionPreferences() {
        appState.fontSize = DEFAULT_FONT_SIZE;
        appState.sourceVisible = true;
        appState.ttsMuted = appState.captionsOnly;
        appState.ttsSpeakingSeq = null;
        ttsChunkBuffers = {};
        clearTtsPlaybackState();
        appState.drawerOpen = false;
        document.body.classList.remove("source-hidden");
        if (els.captionLog) {
            els.captionLog.style.setProperty("--caption-font-size", DEFAULT_FONT_SIZE + "px");
        }
        populateLanguageDropdowns();
        renderHeaderLang();
        renderDrawer();
    }

    // ===== Utility =====

    function formatTime(seconds) {
        const s = Math.max(0, Math.floor(seconds));
        const m = Math.floor(s / 60);
        const sec = s % 60;
        return String(m).padStart(2, "0") + ":" + String(sec).padStart(2, "0");
    }

    // ===== Init =====

    function loadBuildIdentity() {
        if (!els.buildIdentity) {
            return;
        }
        fetch("/version", { cache: "no-store" })
            .then(function (response) { return response.ok ? response.json() : null; })
            .then(function (data) {
                if (!data || !els.buildIdentity) {
                    return;
                }
                var sha = data.git_sha ? String(data.git_sha).slice(0, 12) : "unknown";
                els.buildIdentity.textContent = data.package_version + " (" + sha + ")";
            })
            .catch(function () {});
    }

    document.addEventListener("DOMContentLoaded", function () {
        cacheDom();
        loadCaptionsOnlyPreference();
        loadBuildIdentity();
        setupAutoScroll();
        setupControls();
        setupKeyboard();
        connectWebSocket();
    });
})();
