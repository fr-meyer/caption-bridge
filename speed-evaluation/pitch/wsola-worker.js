/* Evaluation-only worker. Each worker accepts one bounded PCM job and no text. */
"use strict";
importScripts("wsola.js");
let accepted = false;
self.onmessage = function (event) {
    if (accepted) return;
    const message = event && event.data;
    if (!message || typeof message !== "object" || Array.isArray(message) ||
        !Number.isSafeInteger(message.id) || message.id < 1 ||
        !Number.isSafeInteger(message.epoch) || message.epoch < 0 ||
        !Number.isSafeInteger(message.clipId) || message.clipId < 1) return;
    // Invalid identities are ignored without consuming the worker's one accepted job.
    const identity = {id: message.id, epoch: message.epoch, clipId: message.clipId};
    accepted = true;
    try {
        const fields = ["id", "epoch", "clipId", "rate", "pcm"];
        if (Object.keys(message).length !== fields.length ||
            !Object.keys(message).every(key => fields.includes(key)) ||
            !CaptionSpeedEvaluation.rates.includes(message.rate) ||
            !(message.pcm instanceof Float32Array) ||
            message.pcm.length > CaptionSpeedEvaluation.maxSamples) {
            throw new Error("transform_rejected");
        }
        const pcm = CaptionSpeedEvaluation.stretch(message.pcm, message.rate);
        self.postMessage({...identity, pcm}, [pcm.buffer]);
    } catch (_) {
        self.postMessage({...identity, error: "transform_rejected"});
    }
};
