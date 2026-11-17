/* Fixed noaudio roles. No device calls, no network. */
#include <mach/mach_time.h>
#include <stdint.h>
#include <poll.h>
#include <unistd.h>
#include <errno.h>
#ifndef CAPTION_ROLE
#error fixed role required
#endif
struct capability {uint64_t deadline;int32_t parent;uint32_t role;};
int main(int argc,char **argv){
 (void)argv;if(argc!=1)return 64;
 struct capability cap;size_t offset=0;
 while(offset<sizeof(cap)){ssize_t n=read(3,(char *)&cap+offset,sizeof(cap)-offset);if(n<0 && errno==EINTR)continue;if(n<=0)return 65;offset+=(size_t)n;}
 if(close(3)<0)return 65;
 if(cap.role!=CAPTION_ROLE || !cap.deadline || cap.parent!=getppid())return 66;
 struct {int32_t pid;uint32_t role;} ready={getpid(),CAPTION_ROLE};
 size_t sent=0;while(sent<sizeof(ready)){ssize_t n=write(8,(char *)&ready+sent,sizeof(ready)-sent);if(n<0 && errno==EINTR)continue;if(n<=0)return 65;sent+=(size_t)n;}
 if(close(8)<0)return 65;
 for(;;){
  if(getppid()!=cap.parent)return 71;
  if(mach_continuous_time()>=cap.deadline)return 72;
#if CAPTION_ROLE == 3
  struct pollfd reads[3]={{.fd=5,.events=POLLIN|POLLHUP|POLLERR},{.fd=6,.events=POLLIN|POLLHUP|POLLERR},{.fd=7,.events=POLLIN|POLLHUP|POLLERR}};
  int n=poll(reads,3,10);if(n<0 && errno!=EINTR)return 69;
  for(int i=0;i<3;i++)if(reads[i].revents)return 71;
#else
  /* Guardian retains sole writer until parent death or absolute deadline. */
  int n=poll(NULL,0,10);if(n<0 && errno!=EINTR)return 69;
#endif
 }
}
