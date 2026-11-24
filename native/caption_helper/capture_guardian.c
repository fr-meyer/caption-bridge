/* Capture-only independent group guardian; no HAL, network or playback code.
 * Both guardians and helper share an isolated, pinned-image process group. A live
 * guardian signals its OWN group only: no borrowed/recycled numeric PID custody.
 * Controller retains its owned group-leader child unreaped until group cleanup.
 */
#include <mach/mach_time.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <poll.h>
#include <unistd.h>
#include <fcntl.h>
#include <signal.h>
#include <errno.h>
#include <string.h>
#include "capture_protocol.h"
#ifndef CAPTION_ROLE
#error fixed capture guardian role required
#endif
static int reader(int fd){
 struct stat st;int f=fcntl(fd,F_GETFL);
 return f>=0 && (f&O_ACCMODE)==O_RDONLY && !fstat(fd,&st) && S_ISFIFO(st.st_mode);
}
static int force_close(void){
 /* The current executing process itself pins its group identity. Never kill a
  * reported helper PID or signal a stale controller-supplied numeric target. */
 if(getpgrp()<=1)_exit(70);
 if(kill(0,SIGKILL))_exit(70);
 _exit(70);
}
int main(void){
 cb_capture_capability cap={0};
 if(signal(SIGPIPE,SIG_IGN)==SIG_ERR || read(3,&cap,sizeof(cap))!=(ssize_t)sizeof(cap))return 65;
 if(close(3))return 65;
 if(cap.role!=CAPTION_ROLE || cap.reserved || cap.parent<=1 || cap.parent!=getppid() ||
    cap.group<=1 || cap.group==cap.parent || cap.group!=getpgrp() || getpgid(cap.parent)==cap.group || (CAPTION_ROLE==1 && cap.group!=getpid()))return 66;
 struct stat lifeline;int out_flags=fcntl(4,F_GETFL);
 if(out_flags<0 || (out_flags&O_ACCMODE)!=O_WRONLY || fstat(4,&lifeline) || !S_ISFIFO(lifeline.st_mode) ||
    !reader(5) || !reader(6) || !reader(9))return force_close();
 int flags=fcntl(6,F_GETFL);
 if(flags<0 || fcntl(6,F_SETFL,flags|O_NONBLOCK)<0)return force_close();
 struct {int32_t pid;uint32_t role;} ready={getpid(),CAPTION_ROLE};
 if(write(8,&ready,sizeof(ready))!=(ssize_t)sizeof(ready) || close(8))return force_close();
 unsigned char token[sizeof(uint32_t)+1];size_t size=0;
 for(;;){
  if(getppid()!=cap.parent || mach_continuous_time()>=cap.deadline ||
     !cb_capture_wall_valid(cap.expires_unix_ns))return force_close();
  struct pollfd p[3]={{.fd=5,.events=POLLIN|POLLHUP|POLLERR},
                     {.fd=6,.events=POLLIN|POLLHUP|POLLERR},
                     {.fd=9,.events=POLLIN|POLLHUP|POLLERR}};
  int n=poll(p,3,5);if(n<0){if(errno==EINTR)continue;return force_close();}
  if(p[0].revents || p[2].revents)return force_close();
  if(p[1].revents){
   ssize_t count=read(6,token+size,sizeof(token)-size);
   if(count<0){if(errno==EINTR || errno==EAGAIN)continue;return force_close();}
   if(count==0){
    uint32_t closed=0;if(size==sizeof(closed))memcpy(&closed,token,sizeof(closed));
    if(closed!=CB_CAPTURE_CLOSED)return force_close();
    /* Local checked close only. Never claim independent physical acceptance. */
    if(close(6))return force_close();
    return 72;
   }
   size+=(size_t)count;if(size>sizeof(uint32_t))return force_close();
  }
 }
}
