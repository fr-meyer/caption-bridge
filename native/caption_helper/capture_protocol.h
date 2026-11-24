#ifndef CAPTION_CAPTURE_PROTOCOL_H
#define CAPTION_CAPTURE_PROTOCOL_H
#include <stdint.h>
#include <time.h>
#define CB_CAPTURE_MIN_NS 1000000000ULL
#define CB_CAPTURE_CLOSED 0x4342434cU
typedef struct { uint64_t deadline; int32_t parent; uint32_t role; int32_t group; uint32_t reserved; uint64_t expires_unix_ns; } cb_capture_capability;
_Static_assert(sizeof(cb_capture_capability)==32,"capture capability ABI");
static inline int cb_capture_wall_valid(uint64_t expires){
 if(!expires)return 1;
 struct timespec now;if(clock_gettime(CLOCK_REALTIME,&now) || now.tv_sec<0 || now.tv_nsec<0)return 0;
 uint64_t seconds=(uint64_t)now.tv_sec;if(seconds>UINT64_MAX/1000000000ULL)return 0;
 return seconds*1000000000ULL+(uint64_t)now.tv_nsec<expires;
}
#define CB_CAPTURE_MAGIC 0x43424331U
#define CB_CAPTURE_ARMED 1U
#define CB_CAPTURE_PCM 2U
/* Additional private role-3 capability, never argv authority. */
typedef struct { uint32_t magic, flags, device, reserved; unsigned char epoch[16]; } cb_capture_options;
#endif
