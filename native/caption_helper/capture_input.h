#ifndef CAPTION_CAPTURE_INPUT_H
#define CAPTION_CAPTURE_INPUT_H
#include <AudioUnit/AudioUnit.h>
#include <stdatomic.h>
#include <stdint.h>
/* One HAL input, no output/render-to-speaker path. PCM is discard-only unless an explicit private PCM pipe is admitted. */
typedef struct {
 AudioUnit unit;
 AudioBufferList *buffers;
 void *scratch;
 UInt32 buffer_count, bytes_per_frame, buffer_bytes, channels_per_buffer;
 atomic_bool accepting;
 atomic_uint callbacks;
 atomic_int fault;
 uint64_t stop_at;
 unsigned attempted;
 int initialized, started;
 int pcm_fd; uint32_t pcm_rate; uint16_t pcm_channels;
 unsigned char epoch[16]; uint64_t pcm_sequence, pcm_frames, pcm_frame_limit;
} cb_capture_input;
int cb_capture_open(cb_capture_input *, uint32_t device, uint64_t stop_at, int pcm_fd, const unsigned char epoch[16]);
/* Return OSStatus (zero only for checked stop, callback drain, uninitialize/dispose). */
int cb_capture_close(cb_capture_input *, uint64_t deadline);
#endif
