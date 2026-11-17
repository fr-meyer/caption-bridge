/* Fixed native guardian image. Only inherited descriptors, no audio/network. */
#include <mach/mach_time.h>
#include <stdint.h>
#include <poll.h>
#include <unistd.h>
#include <stdlib.h>
#include <string.h>
#include <sys/event.h>
#ifndef CAPTION_ROLE
#error fixed role required
#endif
struct capability { uint64_t deadline; int32_t parent; uint32_t role; };
int main(int argc,char **argv) {
 (void)argv;if(argc!=1) return 64;
 struct capability cap;unsigned char *p=(unsigned char *)&cap;size_t left=sizeof(cap);
 while(left) {ssize_t n=read(3,p,left);if(n<=0)return 65;p+=n;left-=(size_t)n;}
 close(3);
 if(cap.role!=CAPTION_ROLE || !cap.deadline || cap.parent!=getppid())return 66;
 int kq=kqueue();if(kq<0)return 67;
 struct kevent change;EV_SET(&change,(uintptr_t)cap.parent,EVFILT_PROC,EV_ADD|EV_ENABLE,NOTE_EXIT|NOTE_EXEC,0,NULL);
 if(kevent(kq,&change,1,NULL,0,NULL)<0)return 68;
 for(;;) {
  if(mach_continuous_time()>=cap.deadline || getppid()!=cap.parent)return 72;
  struct timespec wait={0,10000000};struct kevent event;
  int n=kevent(kq,NULL,0,&event,1,&wait);
  if(n<0)return 69;if(n>0)return 71;
  /* FD4 is sole lifeline writer, closed automatically on any exit. */
  struct pollfd f={.fd=4,.events=POLLERR|POLLHUP};
  if(poll(&f,1,0)>0 && f.revents)return 71;
#if CAPTION_ROLE == 3
  struct pollfd reads[3]={{.fd=5,.events=POLLIN|POLLHUP|POLLERR},{.fd=6,.events=POLLIN|POLLHUP|POLLERR},{.fd=7,.events=POLLIN|POLLHUP|POLLERR}};
  if(poll(reads,3,0)<0)return 69;
  for(int i=0;i<3;i++)if(reads[i].revents)return 71;
#endif
 }
}
