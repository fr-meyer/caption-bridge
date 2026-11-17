#ifndef CAPTION_INPUT_STATE_H
#define CAPTION_INPUT_STATE_H
#include <stdbool.h>
#include <stdint.h>
typedef enum { CB_EMPTY, CB_RESERVED, CB_MUTED, CB_STOPPING, CB_DRAINED, CB_DISPOSED, CB_HOLD } cb_phase;
typedef struct { cb_phase phase; unsigned inputs; bool muted; uint64_t deadline; } cb_input;
/* This phase has no native input opener. No flag or receipt can change admission. */
static inline bool cb_capture_admitted(void) { return false; }
static inline bool cb_reserve(cb_input *s,uint64_t deadline) {
 if(s->phase!=CB_EMPTY || !deadline) return false;
 s->phase=CB_RESERVED;s->deadline=deadline;s->muted=true;return true;
}
static inline bool cb_synthetic_input(cb_input *s) {
 if(s->phase!=CB_RESERVED || s->inputs) return false;
 s->inputs=1;s->phase=CB_MUTED;return true;
}
static inline bool cb_route_change(cb_input *s) {
 s->muted=true; /* Must precede any route decision, including rejected transitions. */
 return s->phase==CB_MUTED;
}
static inline bool cb_stop(cb_input *s,uint64_t now,bool stopped,bool drained,bool disposed) {
 if(s->phase==CB_HOLD || s->phase==CB_DISPOSED || s->phase!=CB_MUTED)return false;
 s->muted=true;s->phase=CB_STOPPING;
 /* Unknown stop/drain/dispose is permanent HOLD, never terminal/refundable. */
 if(now>s->deadline || !stopped || !drained || !disposed) {s->phase=CB_HOLD;return false;}
 s->phase=CB_DRAINED;s->inputs=0;s->phase=CB_DISPOSED;return true;
}
#endif
