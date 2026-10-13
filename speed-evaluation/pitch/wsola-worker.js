/* Evaluation-only worker. Each worker accepts one bounded PCM job and no text. */
"use strict";
importScripts("wsola.js");
let accepted = false;
self.onmessage = function (event) {
    if (accepted) return;
    accepted = true;
    const message = event.data;
    const identity = {id: message.id, epoch: message.epoch, clipId: message.clipId};
    try {
        const pcm = CaptionSpeedEvaluation.stretch(message.pcm, message.rate);
        self.postMessage({...identity, pcm}, [pcm.buffer]);
    } catch (_) {
        self.postMessage({...identity, error: "transform_rejected"});
    }
};
