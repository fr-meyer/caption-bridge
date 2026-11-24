#ifndef CAPTION_CAPTURE_DIAGNOSTIC_H
#define CAPTION_CAPTURE_DIAGNOSTIC_H
/* Failure observations only. No authority, clock extension or closure decision.
 * Portable integer-only helpers; production supplies its own continuous clock.
 */
#include <stdint.h>
#include <stddef.h>
#include <errno.h>
#define CB_CAPTURE_FAILURE_STAGES(X) \
 X(SIGNAL_POLICY) X(STOP_FLAGS) X(TIMEBASE) X(BUDGET) X(STARTUP_DEADLINE) \
 X(PIPE_SETUP) X(PIPE_FLAGS) X(PATH_BOUNDS) X(PRELAUNCH_STOP) X(PARENT_CHANGED) X(STATE_SETUP) \
 X(SPAWN_SETUP) X(GROUP_CUSTODY) X(IDENTITY_VERIFY) X(CAPABILITY) \
 X(READINESS_DEADLINE) X(READINESS_EOF) X(READINESS_ID) X(READINESS_IO) \
 X(FD_CLOSE) X(SPAWN_ACTION_DESTROY) X(SPAWN_ATTR_DESTROY) X(STARTUP_OUTPUT) \
 X(OBSERVE_OWNED) X(CHILD_STATUS) X(ACTIVE_DEADLINE) X(STOP_POLL) \
 X(STOP_READER) X(WALL_EXPIRED) X(LOOP_SLEEP) X(OBSERVATION_INCOMPLETE) \
 X(GROUP_OBSERVE) X(GROUP_SIGNAL) X(REAP_WAIT) X(REAP_SIGNAL) X(REAP_TIMEOUT) \
 X(IDENTITY_VISIBLE) X(IDENTITY_QUERY) X(DIAGNOSTIC_INVALID)
enum cb_capture_failure_stage {
 CB_CAPTURE_FAIL_NONE=0,
#define CB_STAGE_ENUM(name) CB_CAPTURE_FAIL_##name,
 CB_CAPTURE_FAILURE_STAGES(CB_STAGE_ENUM)
#undef CB_STAGE_ENUM
 CB_CAPTURE_FAIL_COUNT
};
static inline const char *cb_capture_failure_name(enum cb_capture_failure_stage stage){
 static const char *const names[]={"NONE",
#define CB_STAGE_NAME(name) #name,
 CB_CAPTURE_FAILURE_STAGES(CB_STAGE_NAME)
#undef CB_STAGE_NAME
 };
 return stage>CB_CAPTURE_FAIL_NONE && stage<CB_CAPTURE_FAIL_COUNT?names[stage]:"DIAGNOSTIC_INVALID";
}
enum cb_capture_event {
 CB_CAPTURE_EVENT_BUDGET=1,CB_CAPTURE_EVENT_PIPES,CB_CAPTURE_EVENT_GUARDIAN_A,
 CB_CAPTURE_EVENT_GUARDIAN_B,CB_CAPTURE_EVENT_HELPER,CB_CAPTURE_EVENT_STARTED,
 CB_CAPTURE_EVENT_ALL_OBSERVED,CB_CAPTURE_EVENT_CLEANUP,CB_CAPTURE_EVENT_GROUP_SIGNAL,
 CB_CAPTURE_EVENT_LIFELINES_CLOSE,CB_CAPTURE_EVENT_REAP_A,CB_CAPTURE_EVENT_REAP_B,
 CB_CAPTURE_EVENT_REAP_HELPER,CB_CAPTURE_EVENT_IDENTITIES_CHECKED
};
enum cb_capture_cleanup_error {
 CB_CAPTURE_CLEANUP_FD=1,CB_CAPTURE_CLEANUP_SPAWN=2,CB_CAPTURE_CLEANUP_GROUP=4,
 CB_CAPTURE_CLEANUP_REAP=8,CB_CAPTURE_CLEANUP_IDENTITY=16
};
static inline unsigned cb_capture_errno_class(int value){
 switch(value){case EINTR:return 1;case EBADF:return 2;case ECHILD:return 3;
 case EPERM:return 4;case ESRCH:return 5;case EINVAL:return 6;default:return 7;}
}
static inline const char *cb_capture_errno_name(unsigned value){
 static const char *const names[]={"NONE","EINTR","EBADF","ECHILD","EPERM","ESRCH","EINVAL","OTHER"};
 return value<8?names[value]:"OTHER";
}
typedef struct {
 enum cb_capture_failure_stage stage;int role;int wait_status[3];
 unsigned cleanup_errors,reader_events,errno_class,event_count,events[16];
 uint64_t start,deadline,when;uint32_t numer,denom;
} cb_capture_diagnostic;
static inline void cb_capture_failure_note(cb_capture_diagnostic *d,
 enum cb_capture_failure_stage stage,int role,uint64_t now,const int *statuses){
 if(d->stage!=CB_CAPTURE_FAIL_NONE)return; /* Preserve the first causal branch. */
 d->stage=stage;d->role=role;d->when=now;
 for(int i=0;i<3;i++)d->wait_status[i]=statuses?statuses[i]:-1;
}
static inline void cb_capture_event_note(cb_capture_diagnostic *d,enum cb_capture_event event){
 if(d->event_count<16)d->events[d->event_count++]=(unsigned)event;
}
static inline int cb_capture_failure_timing(const cb_capture_diagnostic *d,
 uint64_t *elapsed,uint64_t *window){
 *elapsed=0;*window=0;
 if(!d->start || d->deadline<=d->start || d->when<d->start || !d->numer || !d->denom)return 0;
 uint64_t a=d->when-d->start,b=d->deadline-d->start;
 if(a>UINT64_MAX/d->numer || b>UINT64_MAX/d->numer)return 0;
 a=a*d->numer/d->denom;b=b*d->numer/d->denom;
 if(a>10000000000ULL || !b || b>2000000000ULL)return 0;
 *elapsed=a;*window=b;return 1;
}
#endif
