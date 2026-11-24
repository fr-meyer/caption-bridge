#ifndef CAPTION_BUDGET_H
#define CAPTION_BUDGET_H
/* No-audio debit-to-native-deadline seam. Never capture admission.
 * FD0 must be a private inherited pipe with one parent-owned writer. The
 * challenge binds this reply to this live launch, not to trusted peer identity.
 * The anchor precedes publication AND parent debit. Startup/IPC/fsync latency
 * consumes, never extends, the granted duration. Continuous time includes sleep.
 */
#include <sys/stat.h>
#include <fcntl.h>
#include <poll.h>
#include <errno.h>
#include <unistd.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <mach/mach_time.h>
#define CB_BUDGET_FD 0
#define CB_BUDGET_NS 2000000000ULL
#ifdef CB_CAPTURE_CONTROLLER
#include "capture_protocol.h"
#define CB_BUDGET_BYTES 72
static uint64_t cb_capture_expires_unix_ns;
#else
#define CB_BUDGET_BYTES 56
#endif
static uint64_t cb_be64(const unsigned char *p) {
 uint64_t n=0;for(int i=0;i<8;i++)n=(n<<8)|p[i];return n;
}
static int cb_budget_deadline_for(uint64_t *deadline,mach_timebase_info_data_t tb,const char *event,const char *magic) {
 int fd=CB_BUDGET_FD,ok=0;struct stat st;unsigned char challenge[32],wire[CB_BUDGET_BYTES+1];
 size_t received=0;int flags=fcntl(fd,F_GETFL);
 if(!tb.numer || !tb.denom || flags<0 || (flags&O_ACCMODE)!=O_RDONLY ||
    fstat(fd,&st)<0 || !S_ISFIFO(st.st_mode))goto done;
 if(fcntl(fd,F_SETFD,FD_CLOEXEC)<0 || fcntl(fd,F_SETFL,flags|O_NONBLOCK)<0)goto done;
 uint64_t anchor=mach_continuous_time();
 uint64_t ceiling_ticks=(CB_BUDGET_NS*tb.denom)/tb.numer;
 if(!ceiling_ticks || anchor>UINT64_MAX-ceiling_ticks)goto done;
 uint64_t timeout=anchor+ceiling_ticks;
 arc4random_buf(challenge,sizeof(challenge));
 char hex[65];for(int i=0;i<32;i++)snprintf(hex+2*i,3,"%02x",challenge[i]);
#ifdef CB_CAPTURE_CONTROLLER
 if(printf("{\"event\":\"%s\",\"challenge\":\"%s\",\"ceiling_ms\":2000,\"anchor_continuous_ticks\":%llu,\"timebase_numer\":%u,\"timebase_denom\":%u}\n",event,hex,(unsigned long long)anchor,tb.numer,tb.denom)<0 || fflush(stdout))goto done;
#else
 if(printf("{\"event\":\"%s\",\"challenge\":\"%s\",\"ceiling_ms\":2000}\n",event,hex)<0 || fflush(stdout))goto done;
#endif
 /* Require exact fixed message followed by EOF. No blocking read, no reconnect. */
 while(mach_continuous_time()<timeout){
  struct pollfd p={.fd=fd,.events=POLLIN|POLLHUP|POLLERR};
  int n=poll(&p,1,10);if(n<0 && errno==EINTR)continue;if(n<0)goto done;
  if(!n)continue;
  ssize_t count=read(fd,wire+received,sizeof(wire)-received);
  if(count<0 && (errno==EINTR || errno==EAGAIN))continue;
  if(count<0)goto done;
  if(count==0){if(received!=CB_BUDGET_BYTES)goto done;break;}
  received+=(size_t)count;if(received>CB_BUDGET_BYTES)goto done;
 }
 if(received!=CB_BUDGET_BYTES || mach_continuous_time()>=timeout)goto done;
 if(memcmp(wire,magic,8) || memcmp(wire+8,challenge,32))goto done;
#ifndef CB_CAPTURE_CONTROLLER
 /* Existing binary always hard-pins its original noaudio wire domain. */
 if(memcmp(wire,"CBNA0001",8))goto done;
#endif
 uint64_t ns=cb_be64(wire+40),sequence=cb_be64(wire+48);
 if(!ns || ns>CB_BUDGET_NS || !sequence)goto done;
 /* Product bounded by 2e9 * uint32 max; floor rounding cannot extend budget. */
 uint64_t ticks=(ns*tb.denom)/tb.numer;
 if(!ticks || anchor>UINT64_MAX-ticks)goto done;
 *deadline=anchor+ticks;
#ifdef CB_CAPTURE_CONTROLLER
 if(ns<CB_CAPTURE_MIN_NS)goto done;
 uint64_t validity=cb_be64(wire+56);cb_capture_expires_unix_ns=cb_be64(wire+64);
 if(validity<=anchor || !validity)goto done;
 if(!memcmp(magic,"CBNC0002",8)){
  if(cb_capture_expires_unix_ns)goto done;
 }else if(!cb_capture_expires_unix_ns || !cb_capture_wall_valid(cb_capture_expires_unix_ns))goto done;
 if(validity<*deadline)*deadline=validity;
#endif
 if(mach_continuous_time()>=*deadline)goto done;
 ok=1;
done:
 if(close(fd)<0)ok=0;
 return ok;
}
#ifndef CB_CAPTURE_CONTROLLER
static int cb_budget_deadline(uint64_t *deadline,mach_timebase_info_data_t tb) {
 return cb_budget_deadline_for(deadline,tb,"noaudio_budget_ready","CBNA0001");
}
#endif
#endif
