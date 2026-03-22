(function () {
    "use strict";

    // ===== 3.1 Application State =====

    const FONT_SIZES = [20, 24, 28, 32, 36, 40];
    const DEFAULT_FONT_SIZE = 28;

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
        koreanVisible: true,
        autoScroll: true,
        modalVisible: false,
        recoverySuppressed: false,
        exportFailure: null,
        exportFailureModalVisible: false,
        recoveryFailure: null,
    };

    let ws = null;
    let reconnectAttempt = 0;
    let reconnectTimer = null;
    let isFirstConnect = true;

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
        els.koreanPartial = $("korean-partial");
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
        els.koreanToggle = $("korean-toggle");
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
            default:
                console.log("Unknown event type:", msg.type);
        }
    }

    function handleSnapshot(msg) {
        appState.status = msg.status;
        appState.checks = msg.checks || [];
        appState.sourcePartial = msg.source_partial || "";
        appState.exported = msg.exported || false;
        appState.exportPath = msg.export_path || null;
        appState.startedAt = msg.started_at || null;
        appState.endedAt = msg.ended_at || null;

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

        // Rebuild captions from snapshot segments — include every row so
        // reconnect and reload hydrate the full transcript history.
        appState.captions = [];
        const segments = msg.segments || [];
        for (let i = 0; i < segments.length; i++) {
            const seg = segments[i];
            appState.captions.push({
                seq: seg.seq,
                sourceText: seg.source_text,
                englishText: seg.english_text,
                segmentKind: seg.segment_kind,
                translationStatus: seg.translation_status,
            });
        }
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

        fullRender();
    }

    function handleReadiness(msg) {
        appState.checks = msg.checks || [];
        render();
    }

    function handleStatus(msg) {
        const prev = appState.status;
        appState.status = msg.status;

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
        if (els.koreanPartial) {
            els.koreanPartial.textContent = appState.sourcePartial;
        }
    }

    function handleCaption(msg) {
        const entry = {
            seq: msg.seq,
            sourceText: msg.source_text,
            englishText: msg.english_text,
            segmentKind: msg.segment_kind,
            translationStatus: msg.translation_status,
        };
        appState.captions.push(entry);
        appendCaptionEntry(entry);

        if (appState.autoScroll && els.captionLog) {
            els.captionLog.scrollTop = els.captionLog.scrollHeight;
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
    }

    function handleElapsed(msg) {
        appState.elapsed = msg.seconds || 0;
        if (els.elapsed) {
            els.elapsed.textContent = formatTime(appState.elapsed);
        }
    }

    // ===== 3.4 Render Function =====

    function render() {
        document.body.dataset.state = appState.status;
        renderHeader();
        renderIdlePanel();
        renderRecoveryNotice();
        renderRecoveryFailureWarning();
        renderKoreanPartial();
        renderSummary();
        renderModal();
        renderExportFailureModal();
        renderFooter();
        renderKoreanVisibility();
        renderFontSize();
    }

    function fullRender() {
        render();
        rebuildCaptionLog();
    }

    function renderHeader() {
        const s = appState.status;

        // Status dot
        els.statusDot.className = "status-dot";
        if (s === "idle_ready" || s === "listening") {
            els.statusDot.classList.add("green");
        } else {
            els.statusDot.classList.add("yellow");
        }

        // Status label
        const labels = {
            idle_blocked: "Not ready",
            idle_ready: "Ready",
            listening: "Listening",
            reconnecting: "Reconnecting…",
            session_ended: "Session ended",
        };
        els.statusLabel.textContent = labels[s] || s;

        // Elapsed
        if (s === "session_ended") {
            els.elapsed.textContent = formatTime(appState.elapsed) + " total";
        } else {
            els.elapsed.textContent = formatTime(appState.elapsed);
        }
    }

    function renderIdlePanel() {
        if (appState.status !== "idle_blocked" && appState.status !== "idle_ready") return;

        // Checklist
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

        // Start button — also disabled when a recovery failure is unresolved
        els.startBtn.disabled = appState.status !== "idle_ready" || appState.recoveryFailure !== null;

        // Hint
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

    function renderKoreanPartial() {
        if (els.koreanPartial) {
            els.koreanPartial.textContent = appState.sourcePartial;
        }
    }

    function rebuildCaptionLog() {
        els.captionLog.innerHTML = "";
        for (let i = 0; i < appState.captions.length; i++) {
            appendCaptionEntry(appState.captions[i]);
        }
        els.captionLog.style.setProperty("--caption-font-size", appState.fontSize + "px");

        if (appState.autoScroll) {
            els.captionLog.scrollTop = els.captionLog.scrollHeight;
        }
    }

    function appendCaptionEntry(entry) {
        const div = document.createElement("div");
        div.className = "caption-entry";

        if (entry.segmentKind === "reconnect_fragment") {
            div.classList.add("reconnect-fragment");
            const label = document.createElement("span");
            label.className = "fragment-label";
            label.textContent = "[incomplete fragment]";
            div.appendChild(label);
        }

        const eng = document.createElement("div");
        eng.className = "caption-english";

        if (
            entry.englishText == null ||
            entry.translationStatus === "pending" ||
            entry.translationStatus === "timed_out" ||
            entry.translationStatus === "failed"
        ) {
            eng.textContent = "translation unavailable";
            eng.classList.add("translation-unavailable");
        } else {
            eng.textContent = entry.englishText;
        }
        div.appendChild(eng);

        const kor = document.createElement("div");
        kor.className = "caption-korean";
        kor.textContent = entry.sourceText || "";
        div.appendChild(kor);

        els.captionLog.appendChild(div);
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

        // Clear any previous export error
        const errEl = els.summaryBar.querySelector(".export-error");
        if (errEl && appState.exported) {
            errEl.remove();
        }
    }

    function renderModal() {
        if (appState.modalVisible) {
            els.discardModal.classList.add("visible");
        } else {
            els.discardModal.classList.remove("visible");
        }
    }

    function renderExportFailureModal() {
        if (appState.exportFailureModalVisible && appState.exportFailure) {
            els.exportFailureModal.classList.add("visible");
            els.exportFailureError.textContent = appState.exportFailure.error || "Export failed";
        } else {
            els.exportFailureModal.classList.remove("visible");
        }
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
            els.footerHints.textContent = "F — Fullscreen · Space — Start when ready";
        } else if (s === "session_ended") {
            els.footerHints.textContent = "S — Export · F — Fullscreen";
        } else if (s === "listening" || s === "reconnecting") {
            els.footerHints.textContent = "";
        } else {
            els.footerHints.textContent = "";
        }
    }

    function renderKoreanVisibility() {
        document.body.classList.toggle("korean-hidden", !appState.koreanVisible);

        if (els.koreanToggle) {
            els.koreanToggle.classList.toggle("active", appState.koreanVisible);
        }
    }

    function renderFontSize() {
        if (els.captionLog) {
            els.captionLog.style.setProperty("--caption-font-size", appState.fontSize + "px");
        }
    }

    // ===== 3.5 Auto-Scroll =====

    function setupAutoScroll() {
        els.captionLog.addEventListener("scroll", function () {
            const el = els.captionLog;
            const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 50;
            appState.autoScroll = atBottom;
            if (atBottom) {
                els.jumpLatest.classList.add("hidden");
            } else {
                els.jumpLatest.classList.remove("hidden");
            }
        });

        els.jumpLatest.addEventListener("click", function () {
            els.captionLog.scrollTop = els.captionLog.scrollHeight;
            appState.autoScroll = true;
            els.jumpLatest.classList.add("hidden");
        });
    }

    // ===== 3.6 Controls & Event Listeners =====

    function setupControls() {
        els.startBtn.addEventListener("click", function () {
            appState.recoverySuppressed = true;
            appState.recoveryNotice = null;
            send({ type: "start" });
        });

        els.stopBtn.addEventListener("click", function () {
            send({ type: "stop" });
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
                send({ type: "new_session" });
            }
        });

        els.fullscreenBtn.addEventListener("click", toggleFullscreen);

        els.fontInc.addEventListener("click", function () {
            stepFontSize(1);
        });

        els.fontDec.addEventListener("click", function () {
            stepFontSize(-1);
        });

        els.koreanToggle.addEventListener("click", function () {
            appState.koreanVisible = !appState.koreanVisible;
            renderKoreanVisibility();
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
            send({ type: "new_session" });
            resetSessionPreferences();
            render();
        });

        els.retryExportBtn.addEventListener("click", function () {
            send({ type: "export" });
        });

        els.discardExportBtn.addEventListener("click", function () {
            appState.exportFailureModalVisible = false;
            appState.exportFailure = null;
            send({ type: "new_session" });
        });

        els.retryRecoveryBtn.addEventListener("click", function () {
            send({ type: "retry_recovery" });
        });

        els.discardRecoveryBtn.addEventListener("click", function () {
            send({ type: "discard_recovery" });
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

    function setupKeyboard() {
        document.addEventListener("keydown", function (e) {
            const tag = e.target.tagName.toLowerCase();
            if (tag === "input" || tag === "textarea" || tag === "button") return;
            if (appState.modalVisible) return;

            const s = appState.status;

            if (e.code === "Space") {
                e.preventDefault();
                if (s === "idle_ready") {
                    appState.recoverySuppressed = true;
                    appState.recoveryNotice = null;
                    send({ type: "start" });
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
        });
    }

    // ===== 3.8 Session Preferences Reset =====

    function resetSessionPreferences() {
        appState.fontSize = DEFAULT_FONT_SIZE;
        appState.koreanVisible = true;
        document.body.classList.remove("korean-hidden");
        if (els.captionLog) {
            els.captionLog.style.setProperty("--caption-font-size", DEFAULT_FONT_SIZE + "px");
        }
    }

    // ===== Utility =====

    function formatTime(seconds) {
        const s = Math.max(0, Math.floor(seconds));
        const m = Math.floor(s / 60);
        const sec = s % 60;
        return String(m).padStart(2, "0") + ":" + String(sec).padStart(2, "0");
    }

    // ===== Init =====

    document.addEventListener("DOMContentLoaded", function () {
        cacheDom();
        setupAutoScroll();
        setupControls();
        setupKeyboard();
        connectWebSocket();
    });
})();
