/* Exact role-3 input custodian. No-input mode traverses the same custody/lifelines
 * but MUST NOT call an AudioUnit function. No receipt here releases Journal HOLD.
 */
#include <mach/mach_time.h>
#include <stdint.h>
#include <poll.h>
#include <unistd.h>
#include <errno.h>
#include <stdbool.h>
#include <sys/stat.h>
#include <fcntl.h>
#include "capture_protocol.h"
#include "capture_input.h"
#include "pcm_transport.h"
#include <signal.h>
struct capability {uint64_t deadline;int32_t parent;uint32_t role;};
static int read_exact(int fd,void *out,size_t length) {
 size_t offset=0;while(offset<length){ssize_t n=read(fd,(char *)out+offset,length-offset);if(n<0 && errno==EINTR)continue;if(n<=0)return 0;offset+=(size_t)n;}return 1;
}
static int reader_pipe(int fd){struct stat s;int f=fcntl(fd,F_GETFL);return f>=0 && (f&O_ACCMODE)==O_RDONLY && !fstat(fd,&s) && S_ISFIFO(s.st_mode);}
int main(int argc,char **argv){
 (void)argv;if(argc!=1)return 64;
 struct capability cap;cb_capture_options options;
 if(!reader_pipe(3) || !read_exact(3,&cap,sizeof(cap)) || !read_exact(3,&options,sizeof(options)) || close(3))return 65;
 if(cap.role!=3 || cap.parent!=getppid() || !cap.deadline || mach_continuous_time()>=cap.deadline ||
    options.magic!=CB_CAPTURE_MAGIC || options.reserved || options.flags>CB_CAPTURE_PCM ||
    (options.flags?options.device==0:options.device!=0))return 66;
 for(int fd=5;fd<=7;fd++)if(!reader_pipe(fd))return 66;
 if(!reader_pipe(9))return 66;
 int pcm=options.flags==CB_CAPTURE_PCM;
 if(pcm && (!cb_pcm_pipe(10) || !reader_pipe(11) || signal(SIGPIPE,SIG_IGN)==SIG_ERR))return 66;
 mach_timebase_info_data_t tb;if(mach_timebase_info(&tb)!=KERN_SUCCESS || !tb.numer || !tb.denom)return 66;
 uint64_t margin=100000000ULL*tb.denom/tb.numer;
 if(cap.deadline<=margin || mach_continuous_time()>=cap.deadline-margin)return 66;
 uint64_t stop_at=cap.deadline-margin;
 struct {int32_t pid;uint32_t role;} ready={getpid(),3};
 if(write(8,&ready,sizeof(ready))!=(ssize_t)sizeof(ready) || close(8))return 65;
 /* Startup ACK is not proof of a successful opener or closure. */
 cb_capture_input input={0};int result=72,opened=0;
 if(options.flags==CB_CAPTURE_ARMED || options.flags==CB_CAPTURE_PCM){
  struct pollfd preflight[4]={{.fd=5,.events=POLLIN|POLLHUP|POLLERR},{.fd=6,.events=POLLIN|POLLHUP|POLLERR},{.fd=7,.events=POLLIN|POLLHUP|POLLERR},{.fd=9,.events=POLLIN|POLLHUP|POLLERR}};
  if(getppid()!=cap.parent || poll(preflight,4,0)!=0){result=71;goto cleanup;}
  if(cb_capture_open(&input,options.device,stop_at,pcm?10:-1,options.epoch)){result=70;goto cleanup;}opened=1;
 }
 for(;;){
  if(getppid()!=cap.parent){result=71;break;}
  if(mach_continuous_time()>=stop_at)break;
  if(pcm){struct pollfd finish={.fd=11,.events=POLLIN|POLLHUP|POLLERR};
   if(poll(&finish,1,0)!=0){result=71;break;}}
  if(opened && atomic_load_explicit(&input.fault,memory_order_acquire)){result=70;break;}
  struct pollfd p[4]={{.fd=5,.events=POLLIN|POLLHUP|POLLERR},{.fd=6,.events=POLLIN|POLLHUP|POLLERR},{.fd=7,.events=POLLIN|POLLHUP|POLLERR},{.fd=9,.events=POLLIN|POLLHUP|POLLERR}};
  int n=poll(p,4,5);if(n<0 && errno!=EINTR){result=70;break;}
  for(int i=0;i<4;i++)if(p[i].revents){result=71;goto cleanup;}
 }
cleanup:
 /* No-input qualification calls neither open nor close (the latter uses AudioUnit). */
 if((options.flags==CB_CAPTURE_ARMED || options.flags==CB_CAPTURE_PCM) && cb_capture_close(&input,cap.deadline))result=70;
 /* END follows checked local close only. It never releases journal HOLD. */
 if(pcm){
  if(!opened || result==70 || atomic_load_explicit(&input.fault,memory_order_acquire) ||
     cb_pcm_packet(10,options.epoch,input.pcm_sequence,input.pcm_rate,input.pcm_channels,1,0,NULL))result=70;
  int pcm_closed=close(10),finish_closed=close(11);
  if(pcm_closed || finish_closed)result=70;
 }
 return result;
}
