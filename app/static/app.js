(function () {
    "use strict";

    // ===== 3.1 Application State =====

    const FONT_SIZES = [20, 24, 28, 32, 36, 40];
    const DEFAULT_FONT_SIZE = 28;
    const CAPTIONS_ONLY_KEY = "captionBridge.captionsOnly";
    const GLOSSARY_KEY = "captionBridge.glossary";
    const CAPTION_PROFILE_KEY = "captionBridge.sessionProfile";
    let savedCaptionProfile = null;
    let defaultProfileTargetLanguage = "en";
    let captionProfileStorageNotice = "";

    const glossaryDrafts = Object.create(null);
    let activeGlossary = null;
    let terminologyState = { sessionId: null, version: 0, canUndo: false, changes: 0 };
    let termContext = null;
    let termPending = false;

    const TTS_SUPPORTED_LANGUAGES = new Set([
        "en", "fr", "de", "es", "nl", "pt", "it", "hi", "ar",
    ]);

    let audioContext = null;
    let pcmPlayer = null;
    let audioDevices = null;
    function getAudioContext() {
        if (!audioContext) audioContext = new AudioContext();
        return audioContext;
    }

    const appState = {
        status: "idle_blocked",
        connectionState: "connecting",
        connectionLifecycle: null,
        ownershipBlocked: false,
        pipelineDiagnostics: null,
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
        captionProfileId: "current",
        availableCaptionProfiles: [],
        availableTargetLanguages: [],
        translationModel: "mistral-medium-latest",
        translationReasoningEffort: "default",
        availableTranslationModels: [],
        drawerOpen: false,
        ttsEnabled: true,
        ttsStreaming: false,
        // Audio permission is document-scoped: a browser replacement must
        // require a fresh user gesture before translated speech can play.
        ttsAudioUnlocked: false,
        providerOutage: null,
        ttsSpeakingSeq: null,
        currentTtsEpoch: 0,
        ttsMuted: false,
        ttsPendingCount: 0,
        ttsCatchUpPending: false,
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
        els.drawerModelSelect = $("drawer-model-select");
        els.drawerThinkingSelect = $("drawer-thinking-select");
        els.idleThinkingSelect = $("idle-thinking-select");
        els.drawerModelError = $("drawer-model-error");
        els.idleModelSelect = $("idle-model-select");
        els.sourceToggle = $("source-toggle");
        els.idleTargetSelect = $("idle-target-select");
        els.headerLang = $("header-lang");
        els.translationModelStatus = $("translation-model-status");
        els.asrNotice = $("asr-notice");
        els.connectionOwnershipNotice = $("connection-ownership-notice");
        els.idleModelHelp = $("idle-model-help");
        els.drawerModelHelp = $("drawer-model-help");
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
        els.speechBacklog = $("speech-backlog");
        els.speechBacklogStatus = $("speech-backlog-status");
        els.catchUpBtn = $("catch-up-btn");
        els.catchUpNotice = $("catch-up-notice");
        els.captionsOnlyIdle = $("captions-only-idle");
        els.captionsOnlyDrawer = $("captions-only-drawer");
        els.buildIdentity = $("build-identity");
        els.captionProfileEditor = $("caption-profile-editor");
        els.captionTiming = $("caption-timing");
        els.captionProfileRemember = $("caption-profile-remember");
        els.captionProfileClear = $("caption-profile-clear");
        els.captionProfileHelp = $("caption-profile-help");
        els.captionProfileSessionNote = $("caption-profile-session-note");
        els.glossaryTerms = $("glossary-terms");
        els.glossaryRemember = $("glossary-remember");
        els.glossaryClear = $("glossary-clear");
        els.glossaryError = $("glossary-error");
        els.glossaryLanguage = $("glossary-language");
        els.glossarySessionNote = $("glossary-session-note");
        ["dialog", "caption", "version", "list", "form", "kind", "source", "preferred",
            "error", "save", "undo", "close"].forEach(function (name) {
            els["term" + name[0].toUpperCase() + name.slice(1)] = $("term-" + name);
        });
        els.sessionTerms = $("session-terms");
    }

    // ===== 3.2 WebSocket Connection =====

    function connectWebSocket() {
        if (appState.ownershipBlocked) return;
        const proto = location.protocol === "https:" ? "wss:" : "ws:";
        const url = `${proto}//${location.host}/ws`;

        ws = new WebSocket(url);
        appState.connectionLifecycle = null;
        // Synchronous decoding preserves frame order (Blob.text promises can race).
        ws.binaryType = "arraybuffer";
        const connection = ws;
        let connectionClosed = false;

        ws.onopen = function () {
            if (connectionClosed || connection !== ws) return;
            reconnectAttempt = 0;
            if (reconnectTimer) {
                clearTimeout(reconnectTimer);
                reconnectTimer = null;
            }
            // Restore mute/audio only after an authoritative admitted snapshot.
        };

        ws.onmessage = function (event) {
            if (connectionClosed || connection !== ws || appState.ownershipBlocked) return;
            if (event.data instanceof Blob) {
                event.data.text().then(function (text) {
                    if (connectionClosed || connection !== ws || appState.ownershipBlocked) return;
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

        ws.onclose = function (event) {
            connectionClosed = true;
            if (connection !== ws) return;
            if (appState.ownershipBlocked || (event && event.code === 4409) ||
                (event && event.code === 1000 && event.reason === "replaced")) {
                blockConnectionOwnership(event && event.code === 1000 ? "ownership_lost" : "owner_active");
                return;
            }
            if (appState.connectionLifecycle) {
                appState.connectionLifecycle.state = "closed";
                appState.connectionLifecycle.reason = event && event.code === 1011 && event.reason === "writer_failed"
                    ? "writer_failed" : "transport_closed";
            }
            appState.connectionState = "reconnecting";
            clearTtsPlaybackState();
            appState.ttsSpeakingSeq = null;
            render();
            scheduleReconnect();
        };

        ws.onerror = function () {
            // onclose fires after onerror, reconnect handled there
        };
    }

    function scheduleReconnect() {
        if (appState.ownershipBlocked) return;
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
        if (!appState.ownershipBlocked && appState.connectionState === "connected" &&
            ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify(obj));
        }
    }

    function blockConnectionOwnership(reason) {
        appState.ownershipBlocked = true;
        appState.connectionState = "ownership_blocked";
        if (appState.connectionLifecycle) {
            appState.connectionLifecycle.state = reason === "owner_active" ? "rejected" : "closed";
            appState.connectionLifecycle.reason = reason;
        }
        if (reconnectTimer) {
            clearTimeout(reconnectTimer);
            reconnectTimer = null;
        }
        appState.ttsAudioUnlocked = false;
        appState.ttsSpeakingSeq = null;
        appState.pipelineDiagnostics = null;
        clearTtsPlaybackState();
        render();
    }

    function handleConnectionLifecycle(msg) {
        const states = ["admitted", "rejected", "closed"];
        const reasons = ["owner_admitted", "owner_active", "transport_closed", "writer_failed",
            "handler_failed", "cancelled", "ownership_lost"];
        if (!msg || typeof msg.connection_id !== "string" || !/^conn-[0-9]{6,}$/.test(msg.connection_id) ||
            !states.includes(msg.state) || !reasons.includes(msg.reason)) return false;
        if ((msg.state === "admitted" && msg.reason !== "owner_admitted") ||
            (msg.state === "rejected" && msg.reason !== "owner_active") ||
            (msg.state === "closed" && ["owner_admitted", "owner_active"].includes(msg.reason))) return false;
        appState.connectionLifecycle = {
            connection_id: msg.connection_id, state: msg.state, reason: msg.reason,
        };
        if (msg.state === "rejected" || msg.reason === "ownership_lost") {
            blockConnectionOwnership(msg.reason === "ownership_lost" ? "ownership_lost" : "owner_active");
        }
        return true;
    }

    // ===== 3.3 Message Handlers =====

    function handleMessage(msg) {
        switch (msg.type) {
            case "input_devices":
                if (audioDevices) audioDevices.inventory(msg);
                break;
            case "session_snapshot":
                handleSnapshot(msg);
                break;
            case "connection_lifecycle":
                handleConnectionLifecycle(msg);
                break;
            case "translation_model_changed":
                handleTranslationModelChanged(msg);
                break;
            case "readiness":
                handleReadiness(msg);
                break;
            case "status":
                handleStatus(msg);
                break;
            case "asr_state":
                appState.pipelineDiagnostics = { capture: msg.capture, asr: msg.asr, protocol: msg.protocol };
                renderHeader();
                renderAsrNotice();
                break;
            case "source_partial":
                handleSourcePartial(msg);
                break;
            case "caption":
                handleCaption(msg);
                break;
            case "terminology_updated":
            case "terminology_error":
                handleTerminology(msg);
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
            case "tts_queue":
                handleTtsQueue(msg);
                break;
            case "tts_caught_up":
                handleTtsCaughtUp(msg);
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
        if (appState.ownershipBlocked) return;
        const lifecycle = msg.connection_lifecycle || appState.connectionLifecycle;
        if (!lifecycle || (appState.connectionLifecycle &&
            lifecycle.connection_id !== appState.connectionLifecycle.connection_id) ||
            !handleConnectionLifecycle(lifecycle) || lifecycle.state !== "admitted") return;
        appState.connectionState = "connected";
        if (audioDevices) {
            audioDevices.snapshot(msg.input_devices, msg.status, msg.session_id);
            audioDevices.refresh();
        }
        appState.status = msg.status;
        appState.pipelineDiagnostics = msg.pipeline_diagnostics || null;
        if (msg.status === "idle_blocked" || msg.status === "idle_ready") {
            appState.providerOutage = null;
        }
        if (msg.tts_epoch != null) {
            appState.currentTtsEpoch = msg.tts_epoch;
        }
        // Audio is scoped to this document/epoch.
        appState.ttsSpeakingSeq = null;
        appState.ttsCatchUpPending = false;
        appState.ttsStreaming = msg.tts_streaming_playback === true;
        appState.ttsPendingCount = msg.tts_queue ? msg.tts_queue.pending_count : 0;
        if (els.catchUpNotice) els.catchUpNotice.textContent = "";
        clearTtsPlaybackState(true);

        appState.checks = msg.checks || [];
        appState.sourcePartial = msg.source_partial || "";
        appState.exported = msg.exported || false;
        appState.exportPath = msg.export_path || null;
        appState.startedAt = msg.started_at || null;
        appState.endedAt = msg.ended_at || null;

        appState.availableTargetLanguages = msg.available_target_languages || [];
        appState.availableTranslationModels = msg.available_translation_models || [];
        appState.translationModel = msg.translation_model ||
            (appState.availableTranslationModels[0] && appState.availableTranslationModels[0].id) ||
            "mistral-medium-latest";
        appState.translationReasoningEffort = msg.translation_reasoning_effort || "default";
        appState.targetLanguage = msg.target_language || "en";
        confirmedTargetLanguage = appState.targetLanguage;
        restoreCaptionProfile(msg);
        activeGlossary = msg.glossary || null;
        restoreTerminologyState(msg);

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
                translationModel: seg.translation_model,
                terminologyVersion: seg.terminology_version || 0,
                terminologyStatus: seg.terminology_status || "empty",
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
            isFirstConnect = false;
        } else if (appState.status === "idle_blocked" || appState.status === "idle_ready") {
            resetSessionPreferences();
        }
        send({ type: "tts_mute", muted: appState.ttsMuted });
        if (appState.ttsAudioUnlocked && !appState.captionsOnly) send({ type: "tts_audio_enabled" });

        populateLanguageDropdowns();
        populateModelDropdowns();
        populateThinkingDropdowns();
        renderGlossary();
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
        if (audioDevices) audioDevices.updateStatus(msg.status);

        if (msg.tts_epoch != null) {
            appState.currentTtsEpoch = msg.tts_epoch;
            // Audio is scoped to this document/epoch.
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

        renderGlossary();
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
            translationModel: msg.translation_model,
            terminologyVersion: msg.terminology_version || 0,
            terminologyStatus: msg.terminology_status || "empty",
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

    function handleTranslationModelChanged(msg) {
        if (typeof msg.model !== "string") return;
        appState.translationModel = msg.model;
        if (msg.reasoning_effort === "default" || msg.reasoning_effort === "high") {
            appState.translationReasoningEffort = msg.reasoning_effort;
        }
        populateModelDropdowns();
        populateThinkingDropdowns();
    }

    function handleError(msg) {
        console.error("Server error:", msg.message);

        if (msg.message && /model|thinking/i.test(msg.message)) {
            populateModelDropdowns();
            populateThinkingDropdowns();
            if (els.drawerModelError) {
                els.drawerModelError.textContent = msg.message;
                els.drawerModelError.classList.remove("hidden");
                setTimeout(function () {
                    els.drawerModelError.classList.add("hidden");
                }, 4000);
            }
        }
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

    function handleTtsQueue(msg) {
        if (!Number.isInteger(msg.tts_epoch) || msg.tts_epoch < appState.currentTtsEpoch) return;
        if (appState.ttsCatchUpPending && msg.tts_epoch <= appState.currentTtsEpoch) return;
        if (msg.tts_epoch !== appState.currentTtsEpoch) {
            clearTtsPlaybackState();
            // Audio is scoped to this document/epoch.
            appState.ttsSpeakingSeq = null;
            appState.ttsCatchUpPending = false;
            appState.currentTtsEpoch = msg.tts_epoch;
            renderSpeakingHighlight();
        }
        appState.ttsPendingCount = Number.isInteger(msg.pending_count) ? Math.max(0, msg.pending_count) : 0;
        renderTtsControls();
    }

    function handleTtsCaughtUp(msg) {
        if (msg.tts_epoch < appState.currentTtsEpoch) return;
        handleTtsQueue(msg);
        appState.ttsCatchUpPending = false;
        els.catchUpNotice.textContent = "Speech caught up. Current clip stopped; " +
            msg.skipped_count + " pending clip(s) skipped. All captions kept and replayable.";
        renderTtsControls();
    }

    function catchUpSpeech() {
        if (!ws || ws.readyState !== WebSocket.OPEN || appState.ttsCatchUpPending) return;
        appState.ttsCatchUpPending = true;
        clearTtsPlaybackState();
        // Audio is scoped to this document/epoch.
        appState.ttsSpeakingSeq = null;
        renderSpeakingHighlight();
        send({ type: "tts_catch_up", tts_epoch: appState.currentTtsEpoch });
        renderTtsControls();
    }

    function getPcmPlayer() {
        if (pcmPlayer) return pcmPlayer;
        function ack(type, msg, extra) {
            send(Object.assign({ type: type, seq: msg.seq, tts_epoch: msg.tts_epoch,
                clip_id: msg.clip_id }, extra || {}));
        }
        pcmPlayer = new window.CaptionPcmPlayer({
            streaming: () => appState.ttsStreaming,
            canPlay: () => !appState.ttsMuted && appState.ttsAudioUnlocked && !appState.ttsCatchUpPending,
            context: getAudioContext,
            onFirstChunk: msg => ack("tts_chunk_received", msg),
            onStart: msg => {
                appState.ttsSpeakingSeq = msg.seq;
                renderSpeakingHighlight();
                ack("tts_playback_start", msg);
            },
            onComplete: (msg, stats) => {
                appState.ttsSpeakingSeq = null;
                renderSpeakingHighlight();
                ack("tts_playback_stats", msg, stats);
                ack("tts_playback_complete", msg);
            },
            onError: (msg, reason) => {
                appState.ttsSpeakingSeq = pcmPlayer.active && pcmPlayer.active.started
                    ? pcmPlayer.active.msg.seq : null;
                renderSpeakingHighlight();
                els.catchUpNotice.textContent = "Spoken readback interrupted. Captions stay available for replay.";
                ack("tts_playback_error", msg, {reason: reason});
            },
            onLocked: () => { appState.ttsAudioUnlocked = false; renderTtsControls(); },
        });
        return pcmPlayer;
    }

    function acceptTtsMessage(msg) {
        return !appState.ttsMuted && !appState.ttsCatchUpPending &&
            msg.tts_epoch === appState.currentTtsEpoch;
    }

    function handleTtsSpeaking(msg) {
        if (appState.ttsMuted || appState.ttsCatchUpPending || !Number.isInteger(msg.tts_epoch) ||
            msg.tts_epoch < appState.currentTtsEpoch || msg.seq == null) return;
        if (msg.tts_epoch !== appState.currentTtsEpoch) {
            clearTtsPlaybackState();
            appState.currentTtsEpoch = msg.tts_epoch;
        }
        getPcmPlayer().begin(msg);
    }

    function handleTtsAudio(msg) {
        if (!acceptTtsMessage(msg)) return;
        getPcmPlayer().receive(msg);
    }

    function handleTtsError(msg) {
        if (msg.tts_epoch !== appState.currentTtsEpoch) return;
        // Legacy never-emitted errors cannot refer to buffered audio for the same caption.
        if (msg.clip_id == null && msg.audio_emitted === false) return;
        getPcmPlayer().cancel(msg);
        appState.ttsSpeakingSeq = pcmPlayer.active && pcmPlayer.active.started
            ? pcmPlayer.active.msg.seq : null;
        renderSpeakingHighlight();
    }

    function handleTtsSkipped(msg) {
        if (msg.clip_id == null && msg.audio_emitted === false) return;
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

    function clearTtsPlaybackState(reset) {
        if (pcmPlayer) {
            pcmPlayer.cancelAll();
            if (reset) pcmPlayer.retired.clear();
        }
    }

    function tryStartTtsPlayback() {
        if (pcmPlayer) pcmPlayer.pump();
    }

    function applyLocalTtsMuteEffects() {
        clearTtsPlaybackState();

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
        var hasSession = s === "listening" || s === "reconnecting" || s === "session_ended";
        if (els.speechBacklog) els.speechBacklog.classList.toggle("hidden", !hasSession);
        if (els.speechBacklogStatus) {
            els.speechBacklogStatus.textContent = appState.ttsCatchUpPending
                ? "Catching up speech…"
                : (appState.ttsMuted ? "Speech muted." :
                    "Speech: " + appState.ttsPendingCount + " clip(s) pending, including the current clip.");
        }
        if (els.catchUpBtn) {
            els.catchUpBtn.disabled = appState.ttsCatchUpPending || appState.ttsMuted ||
                appState.ttsPendingCount === 0 || !ws || ws.readyState !== WebSocket.OPEN;
        }
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
        var toggleLabel = supported
            ? (appState.captionsOnly ? "Turn on spoken readback" : (appState.ttsMuted ? "Unmute translated speech" : "Mute translated speech"))
            : "Translated speech unavailable for " + langLabel;
        if (els.captionsOnlyIdle) els.captionsOnlyIdle.checked = appState.captionsOnly;
        if (els.captionsOnlyDrawer) els.captionsOnlyDrawer.checked = appState.captionsOnly;

        if (els.ttsToggleBtn) {
            els.ttsToggleBtn.disabled = !supported;
            els.ttsToggleBtn.title = toggleTitle;
            els.ttsToggleBtn.setAttribute("aria-label", toggleLabel);
            els.ttsToggleBtn.classList.toggle("active", !appState.ttsMuted);
            els.ttsToggleBtn.classList.toggle("tts-muted", appState.ttsMuted);
            els.ttsToggleBtn.textContent = appState.ttsMuted ? "🔇" : "🔊";
        }

        if (els.ttsDrawerToggle) {
            els.ttsDrawerToggle.disabled = !supported;
            els.ttsDrawerToggle.title = toggleTitle;
            els.ttsDrawerToggle.setAttribute("aria-label", toggleLabel);
            els.ttsDrawerToggle.classList.toggle("active", !appState.ttsMuted);
            els.ttsDrawerToggle.classList.toggle("tts-muted", appState.ttsMuted);
            els.ttsDrawerToggle.textContent = appState.ttsMuted ? "🔇" : "🔊";
        }
    }

    // ===== 3.4 Render Function =====

    function render() {
        if (appState.exportFailureModalVisible && appState.exportFailure) {
            appState.modalVisible = false;
        }
        document.body.dataset.state = appState.status;
        renderHeader();
        renderAsrNotice();
        renderHeaderLang();
        renderIdlePanel();
        renderModelSelectors();
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
        renderConnectionOwnership();
    }

    function fullRender() {
        if (audioDevices) audioDevices.updateStatus(appState.status);
        render();
        rebuildCaptionLog();
    }

    function renderHeader() {
        const s = appState.status;
        const asr = appState.pipelineDiagnostics && appState.pipelineDiagnostics.asr;

        els.statusDot.className = "status-dot";
        if (appState.connectionState === "connected" &&
            (s === "idle_ready" || (s === "listening" && (!asr || asr.state === "ready")))) {
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
        if (asr && asr.state === "connecting") labels.listening = "Connecting transcription…";
        if (asr && asr.state === "ready") labels.listening = "Listening · transcription ready";
        if (asr && asr.state === "draining") labels.listening = "Finishing transcription…";
        if (asr && asr.reason === "input_finished") labels.listening = "Input finished · completing captions";
        if (asr && asr.state === "failed") {
            labels.listening = "Transcription failed";
            labels.session_ended = "Transcription failed · session ended";
        }
        els.statusLabel.textContent = appState.connectionState === "connected"
            ? (labels[s] || s)
            : (appState.connectionState === "ownership_blocked"
                ? "Another page controls this session"
            : (appState.connectionState === "connecting"
                ? "Connecting…" : "Connection lost · reconnecting…"));

        if (s === "session_ended") {
            els.elapsed.textContent = formatTime(appState.elapsed) + " total";
        } else {
            els.elapsed.textContent = formatTime(appState.elapsed);
        }
    }

    function renderConnectionOwnership() {
        els.connectionOwnershipNotice.classList.toggle("hidden", !appState.ownershipBlocked);
        els.connectionOwnershipNotice.textContent = appState.ownershipBlocked
            ? "Another page controls CaptionBridge. This page will stay disconnected. Reload after that page disconnects to try again."
            : "";
        [els.stopBtn, els.exportBtn, els.newSessionBtn, els.enableAudioBtn].forEach(function (button) {
            if (button) button.disabled = appState.ownershipBlocked;
        });
        if (appState.ownershipBlocked) {
            els.startBtn.disabled = true;
            els.footerHints.textContent = "";
        }
    }

    function renderAsrNotice() {
        const diagnostics = appState.pipelineDiagnostics;
        const asr = diagnostics && diagnostics.asr;
        const active = diagnostics && diagnostics.capture && diagnostics.capture.active;
        if (!asr || asr.state === "idle" || (asr.state === "stopped" && asr.reason !== "input_finished")) {
            els.asrNotice.classList.add("hidden");
            els.asrNotice.textContent = "";
            return;
        }
        els.asrNotice.classList.remove("hidden");
        if (asr.state === "connecting") {
            els.asrNotice.textContent = (active ? "Microphone active" : "Microphone stopped") +
                " · connecting to transcription. Wait for transcription readiness before speaking or playing audio. Stop is available.";
        } else if (asr.state === "ready") {
            els.asrNotice.textContent = (active ? "Microphone active" : "Microphone stopped") + " · transcription ready.";
        } else if (asr.state === "draining") {
            els.asrNotice.textContent = "Microphone stopped · finishing transcription. Captions and translated speech can continue. Stop is available.";
        } else if (asr.reason === "input_finished") {
            els.asrNotice.textContent = "Microphone stopped · input finished. Remaining captions and translated speech can continue.";
        } else {
            const reasons = {
                initial_timeout: "Transcription did not become ready within the startup deadline.",
                provider_error: "The transcription provider reported a failure.",
                transport_error: "The transcription connection failed.",
                send_failed: "Sending audio to transcription failed.",
                closed_before_ready: "The transcription connection closed before readiness.",
                closed_before_done: "The transcription connection closed before completion.",
                settings_mismatch: "The transcription provider acknowledged different audio settings.",
                stream_done: "The transcription stream ended.",
                invalid_audio: "Transcription received an invalid audio frame.",
                microphone_error: "Microphone capture failed to start.",
            };
            els.asrNotice.textContent = (reasons[asr.reason] || "Transcription failed.") +
                (active ? " Capture is stopping." : " Microphone capture stopped.") +
                " Export the session, then create a new session to retry manually.";
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

        els.startBtn.disabled = appState.connectionState !== "connected" ||
            appState.status !== "idle_ready" || appState.recoveryFailure !== null;

        if (appState.connectionState === "ownership_blocked") {
            els.idleHint.textContent = "Another page controls this session.";
        } else if (appState.connectionState !== "connected") {
            els.idleHint.textContent = "Waiting for the server to restore the session.";
        } else if (appState.recoveryFailure !== null) {
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

        const termsLabel = document.createElement("small");
        termsLabel.className = "caption-terms-version";
        termsLabel.textContent = "Terms v" + (entry.terminologyVersion || 0) +
            (entry.terminologyStatus === "paused" ? " (paused)" : "");
        div.appendChild(termsLabel);
        const correctBtn = document.createElement("button");
        correctBtn.className = "term-correction-btn btn-secondary";
        correctBtn.textContent = "Correct term";
        correctBtn.setAttribute("aria-label", "Correct term in caption " + entry.seq);
        correctBtn.disabled = !canEditTerms();
        correctBtn.addEventListener("click", function () { openTermEditor(entry); });
        div.appendChild(correctBtn);

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
        renderGlossary();
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

    function populateModelDropdowns() {
        [els.idleModelSelect, els.drawerModelSelect].forEach(function (sel) {
            if (!sel) return;
            sel.innerHTML = "";
            appState.availableTranslationModels.forEach(function (model) {
                var option = document.createElement("option");
                option.value = model.id;
                option.textContent = model.label;
                sel.appendChild(option);
            });
            sel.value = appState.translationModel;
        });
        renderModelSelectors();
    }

    function supportsHighReasoning(model) {
        return ["mistral-small-latest", "mistral-medium-latest",
            "zai-glm-5-3"].includes(model);
    }

    function populateThinkingDropdowns() {
        [els.idleThinkingSelect, els.drawerThinkingSelect].forEach(function (sel) {
            sel.innerHTML = "";
            [["default", "Provider default"], ["high", "High reasoning (experimental)"]].forEach(function (item) {
                const option = document.createElement("option");
                option.value = item[0];
                option.textContent = item[1];
                option.disabled = item[0] === "high" &&
                    !supportsHighReasoning(appState.translationModel);
                sel.appendChild(option);
            });
            sel.value = appState.translationReasoningEffort;
        });
    }

    function renderModelSelectors() {
        var experimental = appState.translationModel === "zai-glm-5-3";
        var note = "GLM is experimental and may miss or delay captions. Medium is recommended for now.";
        els.idleModelHelp.textContent = note;
        els.idleModelHelp.classList.toggle("hidden", !experimental);
        els.drawerModelHelp.textContent = "Changes apply to future captions. Requests already underway keep their model." +
            (experimental ? " " + note : "");
        var selected = appState.availableTranslationModels.find(function (model) {
            return model.id === appState.translationModel;
        });
        els.translationModelStatus.textContent = "Translation: " +
            (selected ? selected.label : appState.translationModel);
        els.translationModelStatus.classList.toggle("hidden",
            !["listening", "reconnecting", "stopping", "session_ended"].includes(appState.status));
        if (els.drawerModelSelect) {
            els.drawerModelSelect.disabled = appState.status === "session_ended";
            els.drawerThinkingSelect.disabled = appState.status === "session_ended";
        }
    }

    function handleDrawerModelChange(e) {
        var model = e.target.value;
        var effort = supportsHighReasoning(model) ?
            appState.translationReasoningEffort : "default";
        if (appState.status === "idle_ready" || appState.status === "idle_blocked") {
            appState.translationModel = model;
            appState.translationReasoningEffort = effort;
            els.idleModelSelect.value = model;
            populateThinkingDropdowns();
            renderModelSelectors();
        } else {
            send({ type: "set_translation_model", model: model, reasoning_effort: effort });
        }
    }

    function handleDrawerThinkingChange(e) {
        var effort = e.target.value;
        if (appState.status === "idle_ready" || appState.status === "idle_blocked") {
            appState.translationReasoningEffort = effort;
            els.idleThinkingSelect.value = effort;
        } else {
            send({ type: "set_translation_model", model: els.drawerModelSelect.value,
                reasoning_effort: effort });
        }
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
        renderGlossary();
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
        els.captionTiming.addEventListener("change", function () {
            appState.captionProfileId = els.captionTiming.value;
            if (els.captionProfileRemember.checked) persistCaptionProfile();
            renderCaptionProfile();
        });
        els.captionProfileRemember.addEventListener("change", persistCaptionProfile);
        els.captionProfileClear.addEventListener("click", function () {
            els.captionProfileRemember.checked = false;
            persistCaptionProfile();
            appState.captionProfileId = "current";
            appState.targetLanguage = defaultProfileTargetLanguage;
            populateLanguageDropdowns();
            renderHeaderLang();
            renderCaptionProfile();
        });
        els.sessionTerms.addEventListener("click", function () { openTermEditor(null); });
        els.termClose.addEventListener("click", function () { els.termDialog.close(); });
        els.termDialog.addEventListener("close", restoreTermFocus);
        els.termForm.addEventListener("submit", function (event) {
            event.preventDefault();
            saveCaptionTerm();
        });
        els.termUndo.addEventListener("click", function () { sendTermChange(null, true); });
        els.glossaryTerms.addEventListener("input", function () {
            glossaryDrafts[appState.targetLanguage] = els.glossaryTerms.value;
            els.glossaryError.classList.add("hidden");
            // Only explicit opt-in allows content to reach browser storage.
            if (els.glossaryRemember.checked) {
                try { parseGlossaryText(els.glossaryTerms.value); persistGlossary(); }
                catch (_) { /* retain the last valid saved draft */ }
            }
        });
        els.glossaryRemember.addEventListener("change", function () {
            glossaryDrafts[appState.targetLanguage] = els.glossaryTerms.value;
            if (!els.glossaryRemember.checked) { persistGlossary(); return; }
            try { parseGlossaryText(els.glossaryTerms.value); persistGlossary(); }
            catch (error) {
                els.glossaryRemember.checked = false;
                persistGlossary();
                els.glossaryError.textContent = error.message;
                els.glossaryError.classList.remove("hidden");
            }
        });
        els.glossaryClear.addEventListener("click", function () {
            glossaryDrafts[appState.targetLanguage] = "";
            persistGlossary();
            renderGlossary();
        });
        els.startBtn.addEventListener("click", function () {
            appState.recoverySuppressed = true;
            appState.recoveryNotice = null;
            startWithGlossary();
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
        els.drawerModelSelect.addEventListener("change", handleDrawerModelChange);
        els.drawerThinkingSelect.addEventListener("change", handleDrawerThinkingChange);
        els.idleModelSelect.addEventListener("change", function (e) {
            appState.translationModel = e.target.value;
            renderModelSelectors();
            if (!supportsHighReasoning(appState.translationModel)) {
                appState.translationReasoningEffort = "default";
            }
            els.drawerModelSelect.value = e.target.value;
            populateThinkingDropdowns();
        });
        els.idleThinkingSelect.addEventListener("change", function (e) {
            appState.translationReasoningEffort = e.target.value;
            els.drawerThinkingSelect.value = e.target.value;
        });

        els.idleTargetSelect.addEventListener("change", function (e) {
            appState.targetLanguage = e.target.value;
            if (els.captionProfileRemember.checked) persistCaptionProfile();
            renderHeaderLang();
            renderGlossary();
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
                getAudioContext();
            }
            audioContext.resume().then(function () {
                appState.ttsAudioUnlocked = true;
                send({ type: "tts_audio_enabled" });
                renderTtsControls();
                tryStartTtsPlayback();
            });
        });

        els.catchUpBtn.addEventListener("click", catchUpSpeech);

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
            if (els.termDialog.open) return; // native dialog traps focus and handles Escape
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
                    startWithGlossary();
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

    // ===== Terminology preferences =====

    function canEditTerms() {
        return canOpenTerms() && terminologyState.changes < 100;
    }

    function canOpenTerms() {
        return !!terminologyState.sessionId && !termPending &&
            (appState.status === "listening" || appState.status === "reconnecting");
    }

    function currentTerms() {
        return activeGlossary && activeGlossary.target_language === appState.targetLanguage
            ? activeGlossary.entries.slice() : [];
    }

    function restoreTerminologyState(msg) {
        const previousId = terminologyState.sessionId;
        terminologyState = { sessionId: msg.session_id || null,
            version: msg.terminology_version || 0, canUndo: !!msg.terminology_can_undo,
            changes: msg.terminology_changes || 0 };
        termPending = false;
        if (termContext && previousId !== terminologyState.sessionId) {
            els.termDialog.close();
            termContext = null;
        }
        renderTermEditor();
    }

    function handleTerminology(msg) {
        activeGlossary = msg.glossary || null;
        restoreTerminologyState(msg);
        if (termContext) termContext.version = terminologyState.version;
        if (msg.type === "terminology_error") {
            els.termError.textContent = msg.message;
            els.termError.classList.remove("hidden");
        } else {
            els.termError.classList.add("hidden");
            els.termSource.value = "";
            els.termPreferred.value = "";
            if (termContext) termContext.editSource = null;
        }
        renderGlossary();
    }

    function openTermEditor(entry) {
        if (!canOpenTerms()) return;
        termContext = { captionSeq: entry ? entry.seq : null, editSource: null,
            version: terminologyState.version, language: appState.targetLanguage };
        const selection = window.getSelection();
        const selected = selection && selection.anchorNode &&
            els.captionLog.contains(selection.anchorNode) ? selection.toString().trim() : "";
        els.termSource.value = entry && entry.sourceText.includes(selected) &&
            Array.from(selected).length <= 80 ? selected : "";
        els.termPreferred.value = "";
        els.termKind.value = "target";
        els.termCaption.textContent = entry ? "Original: " + entry.sourceText +
            "\nTranslation: " + (entry.translatedText || "unavailable") : "";
        els.termError.classList.add("hidden");
        renderTermEditor();
        modalReturnFocus.set(els.termDialog, document.activeElement);
        els.termDialog.showModal();
        (canEditTerms() ? els.termSource : els.termClose).focus();
    }

    function restoreTermFocus() {
        if (els.termDialog.open) return;
        const previous = modalReturnFocus.get(els.termDialog);
        modalReturnFocus.delete(els.termDialog);
        if (previous && previous !== document.body && previous.isConnected &&
            !previous.disabled && previous.getClientRects().length && !previous.closest("[inert]")) {
            previous.focus();
        } else {
            els.statusLabel.focus();
        }
    }

    function renderTermEditor() {
        if (!els.termList) return;
        const focused = els.termDialog.open && els.termList.contains(document.activeElement)
            ? document.activeElement : null;
        let nextFocus = null;
        els.termVersion.textContent = "Session terms v" + terminologyState.version +
            " · " + currentTerms().length + "/20 pairs" +
            (terminologyState.changes >= 100 ? " · 100-change limit reached" : "") +
            (activeGlossary && activeGlossary.target_language !== appState.targetLanguage
                ? " · Previous language terms are paused. Saving replaces that list; Undo restores it." : "");
        els.termList.replaceChildren();
        currentTerms().forEach(function (term) {
            const row = document.createElement("div");
            row.className = "term-row";
            const label = document.createElement("span");
            label.textContent = term.source + " → " + term.preferred +
                (term.kind === "source" ? " (source correction)" : " (translation)");
            row.appendChild(label);
            const edit = document.createElement("button");
            edit.type = "button";
            edit.textContent = "Edit";
            edit.setAttribute("aria-label", "Edit term: " + term.source);
            edit.dataset.termSource = term.source;
            edit.dataset.termAction = "edit";
            edit.disabled = !canEditTerms();
            if (focused && focused.dataset.termSource === term.source &&
                focused.dataset.termAction === "edit" && !edit.disabled) nextFocus = edit;
            edit.addEventListener("click", function () {
                termContext.captionSeq = null;
                termContext.editSource = term.source;
                els.termSource.value = term.source;
                els.termPreferred.value = term.preferred;
                els.termKind.value = term.kind || "target";
                els.termSource.focus();
            });
            row.appendChild(edit);
            const remove = document.createElement("button");
            remove.type = "button";
            remove.textContent = "Remove";
            remove.setAttribute("aria-label", "Remove term: " + term.source);
            remove.dataset.termSource = term.source;
            remove.dataset.termAction = "remove";
            remove.disabled = !canEditTerms();
            if (focused && focused.dataset.termSource === term.source &&
                focused.dataset.termAction === "remove" && !remove.disabled) nextFocus = remove;
            remove.addEventListener("click", function () {
                termContext.captionSeq = null;
                sendTermChange(currentTerms().filter(function (item) { return item.source !== term.source; }));
            });
            row.appendChild(remove);
            els.termList.appendChild(row);
        });
        els.termSave.disabled = !canEditTerms();
        els.termUndo.disabled = !canEditTerms() || !terminologyState.canUndo;
        if (focused) (nextFocus || els.termClose).focus();
    }

    function sendTermChange(entries, undo) {
        if (!canEditTerms() || !termContext) return;
        if (termContext.language !== appState.targetLanguage) {
            els.termError.textContent = "Target language changed. Close and reopen the terminology editor.";
            els.termError.classList.remove("hidden");
            return;
        }
        const message = { type: undo ? "undo_terminology" : "update_terminology",
            session_id: terminologyState.sessionId, expected_version: termContext.version,
            target_language: termContext.language };
        if (!undo) {
            message.glossary = entries;
            if (termContext.captionSeq != null) message.caption_seq = termContext.captionSeq;
        }
        send(message);
        termPending = true;
        renderTermEditor();
    }

    function saveCaptionTerm() {
        try {
            const source = els.termSource.value.trim().normalize("NFC");
            const preferred = els.termPreferred.value.trim().normalize("NFC");
            if ([source, preferred].some(function (value) {
                return !value || Array.from(value).length > 80 || /[\p{Cc}\p{Cf}\p{Cs}]/u.test(value);
            })) throw new Error("Each term needs 1–80 characters without control characters.");
            const pair = { source: source, preferred: preferred };
            pair.kind = els.termKind.value;
            const entries = currentTerms().filter(function (item) {
                return item.source !== termContext.editSource &&
                    item.source.toLowerCase() !== pair.source.toLowerCase();
            });
            entries.push(pair);
            if (entries.length > 20) throw new Error("Use at most 20 terminology pairs.");
            sendTermChange(entries);
        } catch (error) {
            els.termError.textContent = error.message;
            els.termError.classList.remove("hidden");
        }
    }

    function parseGlossaryText(text) {
        const lines = text.split("\n").map(function (line) { return line.trim(); }).filter(Boolean);
        if (lines.length > 20) throw new Error("Use at most 20 terminology pairs.");
        const seen = new Set();
        return lines.map(function (line) {
            const at = line.indexOf("=>");
            if (at < 0) throw new Error("Use Source term => preferred rendering on each line.");
            const source = line.slice(0, at).trim().normalize("NFC");
            const preferred = line.slice(at + 2).trim().normalize("NFC");
            if ([source, preferred].some(function (term) {
                return !term || Array.from(term).length > 80 || /[\p{Cc}\p{Cf}\p{Cs}]/u.test(term);
            })) throw new Error("Each term needs 1–80 characters without control characters.");
            const key = source.toLowerCase();
            if (seen.has(key)) throw new Error("Each source term must be unique.");
            seen.add(key);
            return { source: source, preferred: preferred };
        });
    }

    function loadGlossaryPreference() {
        try {
            const savedText = localStorage.getItem(GLOSSARY_KEY);
            if (!savedText || savedText.length > 5000) return;
            const saved = JSON.parse(savedText);
            if (typeof saved.targetLanguage !== "string" || typeof saved.text !== "string" ||
                saved.text.length > 4000 || !/^[a-z]{2,3}(?:-[A-Z]{2})?$/.test(saved.targetLanguage)) return;
            parseGlossaryText(saved.text);
            glossaryDrafts[saved.targetLanguage] = saved.text;
            els.glossaryRemember.checked = true;
        } catch (_) { /* invalid or unavailable storage does not activate terms */ }
    }

    function persistGlossary() {
        try {
            const text = glossaryDrafts[appState.targetLanguage] || "";
            if (els.glossaryRemember.checked && text.trim()) {
                localStorage.setItem(GLOSSARY_KEY, JSON.stringify({
                    targetLanguage: appState.targetLanguage, text: text
                }));
            } else {
                const saved = JSON.parse(localStorage.getItem(GLOSSARY_KEY) || "null");
                if (!els.glossaryRemember.checked ||
                    (saved && saved.targetLanguage === appState.targetLanguage)) {
                    localStorage.removeItem(GLOSSARY_KEY);
                }
            }
        } catch (_) { /* storage may be unavailable */ }
    }

    function renderGlossary() {
        renderCaptionProfile();
        if (!els.glossaryTerms) return;
        const label = appState.availableTargetLanguages.find(function (lang) {
            return lang.code === appState.targetLanguage;
        });
        els.glossaryLanguage.textContent = label ? label.label : appState.targetLanguage;
        els.glossaryTerms.value = glossaryDrafts[appState.targetLanguage] || "";
        els.glossaryError.classList.add("hidden");
        const active = activeGlossary && Array.isArray(activeGlossary.entries) &&
            activeGlossary.entries.length > 0;
        els.glossarySessionNote.classList.toggle("hidden", (!active && !terminologyState.version) ||
            appState.status === "idle_ready" || appState.status === "idle_blocked");
        if (active) {
            els.glossarySessionNote.textContent = activeGlossary.target_language === appState.targetLanguage
                ? "Session terminology v" + terminologyState.version + " applies to future captions."
                : "Session terminology is paused for this target language.";
        } else if (terminologyState.version) {
            els.glossarySessionNote.textContent = "Session terminology v" + terminologyState.version + " is empty.";
        }
        els.sessionTerms.disabled = !canOpenTerms();
        els.captionLog.querySelectorAll(".term-correction-btn").forEach(function (button) {
            button.disabled = !canEditTerms();
        });
        renderTermEditor();
    }

    function startWithGlossary() {
        if (appState.connectionState !== "connected") return;
        let entries;
        try {
            entries = parseGlossaryText(els.glossaryTerms.value);
        } catch (error) {
            els.glossaryError.textContent = error.message;
            els.glossaryError.classList.remove("hidden");
            els.glossaryTerms.focus();
            return;
        }
        glossaryDrafts[appState.targetLanguage] = els.glossaryTerms.value;
        persistGlossary();
        activeGlossary = entries.length ? {
            entries: entries, target_language: appState.targetLanguage
        } : null;
        send({ type: "start", target_language: appState.targetLanguage,
            translation_model: appState.translationModel,
            translation_reasoning_effort: appState.translationReasoningEffort,
            tts_muted: appState.ttsMuted, glossary: entries,
            caption_profile: appState.captionProfileId,
            input_device: audioDevices ? audioDevices.input : "default" });
    }


    // ===== Language and caption timing profile =====

    function loadCaptionProfile() {
        try {
            const raw = localStorage.getItem(CAPTION_PROFILE_KEY);
            if (!raw || raw.length > 256) return;
            const saved = JSON.parse(raw);
            if (!saved || Array.isArray(saved) ||
                Object.keys(saved).sort().join(",") !== "id,targetLanguage,version" ||
                saved.version !== 1 || typeof saved.targetLanguage !== "string" ||
                !["current", "shorter", "longer"].includes(saved.id)) return;
            savedCaptionProfile = saved;
            els.captionProfileRemember.checked = true;
        } catch (_) { /* storage is optional */ }
    }

    function restoreCaptionProfile(msg) {
        appState.availableCaptionProfiles = msg.available_caption_profiles || [];
        const idle = msg.status === "idle_ready" || msg.status === "idle_blocked";
        appState.captionProfileId = (msg.caption_profile && msg.caption_profile.id) || "current";
        if (idle) {
            defaultProfileTargetLanguage = appState.targetLanguage;
            if (savedCaptionProfile &&
                appState.availableTargetLanguages.some(function (item) {
                    return item.code === savedCaptionProfile.targetLanguage;
                }) &&
                appState.availableCaptionProfiles.some(function (item) {
                    return item.id === savedCaptionProfile.id;
                })) {
                appState.targetLanguage = savedCaptionProfile.targetLanguage;
                appState.captionProfileId = savedCaptionProfile.id;
            } else if (savedCaptionProfile) {
                savedCaptionProfile = null;
                els.captionProfileRemember.checked = false;
            }
        }
    }

    function persistCaptionProfile() {
        captionProfileStorageNotice = "";
        try {
            if (els.captionProfileRemember.checked) {
                savedCaptionProfile = { version: 1, targetLanguage: appState.targetLanguage,
                    id: appState.captionProfileId };
                localStorage.setItem(CAPTION_PROFILE_KEY, JSON.stringify(savedCaptionProfile));
            } else {
                localStorage.removeItem(CAPTION_PROFILE_KEY);
                savedCaptionProfile = null;
            }
        } catch (_) {
            savedCaptionProfile = null;
            els.captionProfileRemember.checked = false;
            captionProfileStorageNotice = "Could not remember this profile. Your current selection still works.";
        }
        renderCaptionProfile();
    }

    function renderCaptionProfile() {
        const profiles = appState.availableCaptionProfiles;
        els.captionProfileEditor.classList.toggle("hidden", profiles.length === 0);
        const selected = profiles.find(function (item) { return item.id === appState.captionProfileId; });
        els.captionTiming.innerHTML = "";
        profiles.forEach(function (item) {
            const option = document.createElement("option");
            option.value = item.id;
            option.textContent = item.label;
            els.captionTiming.appendChild(option);
        });
        els.captionTiming.value = appState.captionProfileId;
        const idle = appState.status === "idle_ready" || appState.status === "idle_blocked";
        els.captionTiming.disabled = !idle;
        els.captionProfileRemember.disabled = !idle;
        els.captionProfileClear.disabled = !idle || !savedCaptionProfile;
        els.captionProfileHelp.textContent = captionProfileStorageNotice ||
            (selected ? selected.description : "");
        els.captionProfileSessionNote.classList.toggle("hidden", idle || !selected);
        if (selected) {
            els.captionProfileSessionNote.textContent =
                "Caption timing: " + selected.label + ". Fixed until New Session.";
        }
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
        // Audio is scoped to this document/epoch.
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
        audioDevices = new window.CaptionAudioDevices({
            send: send,
            context: getAudioContext,
            canRoute: () => typeof AudioContext !== "undefined" &&
                typeof AudioContext.prototype.setSinkId === "function",
            unavailable: () => {
                appState.ttsMuted = true;
                applyLocalTtsMuteEffects();
                send({type: "tts_mute", muted: true});
                renderTtsControls();
            },
        });
        audioDevices.mount(document);
        loadCaptionsOnlyPreference();
        loadGlossaryPreference();
        loadCaptionProfile();
        loadBuildIdentity();
        setupAutoScroll();
        setupControls();
        setupKeyboard();
        renderHeader();
        renderIdlePanel();
        connectWebSocket();
    });
})();
