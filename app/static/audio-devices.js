(function (root) {
    "use strict";
    // Native input tokens and browser sink IDs are deliberately separate, transient namespaces.
    class CaptionAudioDevices {
        constructor(options) {
            this.options = options;
            this.media = options.media || navigator.mediaDevices;
            this.inputs = [];
            this.input = "default";
            this.activeInput = null;
            this.output = "";
            this.outputLabel = "System/browser default";
            this.outputUnavailable = false;
            this.outputs = [];
            this.notice = "";
            this.status = "idle_blocked";
            this.session = null;
            this.revision = 0;
            this.outputBusy = false;
            this.refreshRevision = 0;
        }
        mount(document) {
            this.document = document;
            this.inputSelects = [...document.querySelectorAll("[data-native-input]")];
            this.outputSelects = [...document.querySelectorAll("[data-browser-output]")];
            this.inputSelects.forEach(select => select.addEventListener("change", () => {
                this.input = select.value;
                this.render();
            }));
            this.outputSelects.forEach(select => select.addEventListener("change", () => {
                this.setOutput(select.value);
            }));
            document.querySelectorAll("[data-refresh-audio-devices]").forEach(button => {
                button.addEventListener("click", () => this.refresh());
            });
            document.querySelectorAll("[data-choose-audio-output]").forEach(button => {
                button.hidden = !this.canRoute() || !this.media?.selectAudioOutput;
                button.addEventListener("click", () => this.chooseOutput());
            });
            this.media?.addEventListener?.("devicechange", () => this.refreshOutputs());
            this.render();
            this.refreshOutputs();
        }
        canRoute() {
            return Boolean(this.options.canRoute());
        }
        refresh() {
            this.options.send({type: "refresh_input_devices"});
            return this.refreshOutputs();
        }
        snapshot(data, status, session) {
            const changed = this.session !== null && this.session !== session;
            this.session = session;
            this.status = status;
            this.inputs = data?.available || [];
            this.input = data?.selected || "default";
            this.activeInput = data?.active_label || null;
            if (changed) this.setOutput("");
            this.render();
        }
        inventory(data) {
            this.inputs = data.available || [];
            this.activeInput = data.active_label || null;
            if (data.unavailable) this.notice = "Microphone list unavailable. Refresh devices before Start.";
            this.render();
        }
        updateStatus(status) {
            this.status = status;
            this.render();
        }
        async refreshOutputs() {
            const revision = ++this.refreshRevision;
            if (!this.media?.enumerateDevices) {
                this.notice = "Output list unavailable. Use system/browser audio settings.";
                this.render();
                return;
            }
            try {
                const devices = await this.media.enumerateDevices();
                if (revision !== this.refreshRevision) return;
                this.outputs = devices.filter(device => device.kind === "audiooutput" &&
                    device.deviceId && device.deviceId !== "default");
                if (this.output && !this.outputs.some(device => device.deviceId === this.output)) {
                    this.outputUnavailable = true;
                    this.notice = "Selected speech output is unavailable. Speech is muted; choose an output and unmute.";
                    this.options.unavailable();
                }
            } catch (_) {
                if (revision !== this.refreshRevision) return;
                this.notice = "Output list unavailable. Current route is unchanged; check system/browser settings.";
            }
            this.render();
        }
        async chooseOutput() {
            if (!this.canRoute() || !this.media?.selectAudioOutput || this.outputBusy) return;
            const session = this.session;
            try {
                // This is invoked directly by the chooser button, with user activation.
                const device = await this.media.selectAudioOutput();
                if (session !== this.session) return;
                if (!device?.deviceId) return;
                if (!this.outputs.some(item => item.deviceId === device.deviceId)) this.outputs.push(device);
                await this.setOutput(device.deviceId, device.label);
            } catch (_) {
                this.notice = "Output selection was not granted. Current route is unchanged.";
                this.render();
            }
        }
        async setOutput(id, label) {
            if (!this.canRoute()) {
                this.notice = "This browser uses system/browser default output. Change it in audio settings.";
                this.render();
                return false;
            }
            const context = this.options.context();
            if (!context?.setSinkId) return false;
            const revision = ++this.revision;
            this.outputBusy = true;
            this.render();
            try {
                // Serialize changes so a slow older request cannot override a New Session reset.
                this.sinkQueue = (this.sinkQueue || Promise.resolve()).catch(() => {}).then(() => context.setSinkId(id));
                await this.sinkQueue;
                if (revision !== this.revision) return false;
                this.output = id;
                this.outputUnavailable = false;
                const device = this.outputs.find(item => item.deviceId === id);
                this.outputLabel = id ? label || device?.label || "Selected browser output" : "System/browser default";
                this.notice = "";
                return true;
            } catch (_) {
                this.notice = "Output change failed. Current route is unchanged; check browser/system audio settings.";
                return false;
            } finally {
                if (revision === this.revision) this.outputBusy = false;
                this.render();
            }
        }
        fill(select, items, value, fallback) {
            select.replaceChildren();
            for (const item of items) {
                const option = this.document.createElement("option");
                option.value = item.id;
                option.textContent = item.label;
                select.append(option);
            }
            if (!items.some(item => item.id === value)) {
                const missing = this.document.createElement("option");
                missing.value = value;
                missing.textContent = fallback;
                select.append(missing);
            }
            select.value = value;
        }
        render() {
            if (!this.document) return;
            const idle = ["idle_ready", "idle_blocked"].includes(this.status);
            this.inputSelects.forEach(select => {
                this.fill(select, [{id: "default", label: "System default microphone"}, ...this.inputs],
                    this.input, "Selected microphone unavailable — choose again");
                select.disabled = !idle;
            });
            this.outputSelects.forEach(select => {
                const items = [{id: "", label: "System/browser default output"}, ...this.outputs.map((device, index) =>
                    ({id: device.deviceId, label: device.label || "Permitted audio output " + (index + 1)}))];
                this.fill(select, items, this.output, "Selected output unavailable");
                select.disabled = !this.canRoute() || this.outputBusy;
            });
            this.document.querySelectorAll("[data-audio-device-status]").forEach(element => {
                const input = this.activeInput ? "Capture input: " + this.activeInput + ". " :
                    "Microphone changes apply on Start. ";
                const output = this.outputUnavailable ? "Selected speech output is unavailable. " :
                    this.canRoute() ? "Speech output: " + this.outputLabel + ". " :
                    "Speech uses system/browser default output; this browser cannot select an output here. ";
                element.textContent = input + output + this.notice;
            });
        }
    }
    root.CaptionAudioDevices = CaptionAudioDevices;
    if (typeof module !== "undefined" && module.exports) module.exports = CaptionAudioDevices;
})(typeof window !== "undefined" ? window : globalThis);
