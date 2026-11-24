#ifndef CAPTION_CAPTURE_PROTOCOL_H
#define CAPTION_CAPTURE_PROTOCOL_H
#include <stdint.h>
#define CB_CAPTURE_MAGIC 0x43424331U
#define CB_CAPTURE_ARMED 1U
/* Additional private role-3 capability, never argv authority. */
typedef struct { uint32_t magic, flags, device, reserved; } cb_capture_options;
#endif
