/* Source-only no-audio controller. No receipt is launch authority. */
#include <Security/Security.h>
#include <CoreFoundation/CoreFoundation.h>
#include <mach/mach_time.h>
#include <spawn.h>
#include <sys/wait.h>
#include <signal.h>
#include <unistd.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <limits.h>
#include "input_state.h"
#ifdef CB_CAPTURE_CONTROLLER
#include "capture_pins.h"
#include "capture_protocol.h"
static cb_capture_options capture_options;
static int capture_stop_fd=-1,capture_pcm_fd=-1,capture_finish_fd=-1;
static int capture_close[2][2]={{-1,-1},{-1,-1}};
static pid_t capture_group=-1;
#else
#include "role_pins.h"
#endif
#include "budget.h"
#include <errno.h>
#include <poll.h>
struct capability { uint64_t deadline; int32_t parent; uint32_t role;
#ifdef CB_CAPTURE_CONTROLLER
 int32_t group;uint32_t reserved;uint64_t expires_unix_ns;
#endif
};
#ifdef CB_CAPTURE_CONTROLLER
_Static_assert(sizeof(struct capability)==sizeof(cb_capture_capability),"controller capability ABI");
#endif
static const char *failure_stage="NONE";
static int failure_role=0,failure_code=0;
static int saved_status[3]={-1,-1,-1},cleanup_killed[3]={0,0,0};
static int reap_owned(pid_t pid,int role) {
 int status=-1;pid_t r=waitpid(pid,&status,WNOHANG);
 if(r==pid){saved_status[role-1]=status;return 1;}
 if(r<0 && errno!=EINTR)return 0;
 if(kill(pid,SIGKILL)<0 && errno!=ESRCH)return 0;
 cleanup_killed[role-1]=1;
 for(int i=0;i<1000;i++){r=waitpid(pid,&status,WNOHANG);if(r==pid){saved_status[role-1]=status;return 1;}if(r<0 && errno!=EINTR)return 0;usleep(1000);}
 return 0;
}
static int verify(pid_t pid,const char *path,int role) {
 CFURLRef url=CFURLCreateFromFileSystemRepresentation(NULL,(const UInt8 *)path,strlen(path),false);
 SecStaticCodeRef disk=NULL;SecCodeRef live=NULL;CFDictionaryRef di=NULL,li=NULL;
 CFNumberRef number=CFNumberCreate(NULL,kCFNumberIntType,&pid);
 if(!url || !number){if(url)CFRelease(url);if(number)CFRelease(number);return 0;}
 const void *k[]={kSecGuestAttributePid},*v[]={number};
 CFDictionaryRef attrs=CFDictionaryCreate(NULL,k,v,1,&kCFTypeDictionaryKeyCallBacks,&kCFTypeDictionaryValueCallBacks);
 int good=0;OSStatus status=0;
 if(!attrs){CFRelease(number);CFRelease(url);return 0;}
 if((status=SecStaticCodeCreateWithPath(url,0,&disk)) || (status=SecStaticCodeCheckValidity(disk,kSecCSStrictValidate,NULL)))goto done;
 if((status=SecCodeCopyGuestWithAttributes(NULL,attrs,0,&live)) || (status=SecCodeCheckValidity(live,kSecCSStrictValidate,NULL)))goto done;
 if((status=SecCodeCopySigningInformation(disk,kSecCSSigningInformation,&di)) || (status=SecCodeCopySigningInformation(live,kSecCSSigningInformation,&li)))goto done;
 CFTypeRef a=CFDictionaryGetValue(di,kSecCodeInfoUnique),b=CFDictionaryGetValue(li,kSecCodeInfoUnique);
 CFTypeRef ai=CFDictionaryGetValue(di,kSecCodeInfoIdentifier),bi=CFDictionaryGetValue(li,kSecCodeInfoIdentifier);
 if(a && b && ai && bi && CFEqual(a,b) && CFEqual(ai,bi) && CFGetTypeID(b)==CFDataGetTypeID() && CFGetTypeID(bi)==CFStringGetTypeID()) {
  char identifier[128];char hash[129]={0};CFIndex count=CFDataGetLength((CFDataRef)b);
  if(count>0 && count<=64 && CFStringGetCString((CFStringRef)bi,identifier,sizeof(identifier),kCFStringEncodingUTF8)) {
   for(CFIndex i=0;i<count;i++)snprintf(hash+2*i,3,"%02x",CFDataGetBytePtr((CFDataRef)b)[i]);
   good=role>=1 && role<=3 && !strcmp(identifier,cb_role_identifiers[role-1]) && !strcmp(hash,cb_role_hashes[role-1]);
  }
 }
done:
 failure_code=good?0:(status?status:-10001);
 if(di)CFRelease(di);if(li)CFRelease(li);if(disk)CFRelease(disk);if(live)CFRelease(live);
 CFRelease(attrs);CFRelease(number);CFRelease(url);return good;
}
static int closure_error=0;
static pid_t owned_identity[3]={-1,-1,-1};
static pid_t retained[3]={-1,-1,-1};
static void close_owned(int *fd){if(*fd>=0){if(close(*fd)<0)closure_error=1;*fd=-1;}}
static pid_t spawn_role(const char *path,int input,int output,int ga,int gb,int role,uint64_t deadline) {
 failure_stage="SPAWN_SETUP";failure_role=role;failure_code=0;errno=0;
 int ready_pipe[2]={-1,-1};int ready_writer=-1;
#ifdef CB_CAPTURE_CONTROLLER
 int stop_copy=-1,pcm_copy=-1,finish_copy=-1,ack_copy[2]={-1,-1};
#endif
 int cap[2]={-1,-1},mapped[5]={-1,-1,-1,-1,-1};pid_t pid=-1;
 posix_spawn_file_actions_t f;posix_spawnattr_t attr;int fi=0,ai=0,ok=0;
 if(pipe(cap) || pipe(ready_pipe))goto done;
 for(int i=0;i<2;i++)if(fcntl(ready_pipe[i],F_SETFD,FD_CLOEXEC)<0)goto done;
 ready_writer=fcntl(ready_pipe[1],F_DUPFD_CLOEXEC,30);if(ready_writer<0)goto done;
 int originals[5]={cap[0],output,input,ga,gb};
 for(int i=0;i<2;i++)if(fcntl(cap[i],F_SETFD,FD_CLOEXEC)<0)goto done;
 for(int i=0;i<5;i++)if(originals[i]>=0){mapped[i]=fcntl(originals[i],F_DUPFD_CLOEXEC,20);if(mapped[i]<0)goto done;}
 if(posix_spawn_file_actions_init(&f))goto done;fi=1;
 if(posix_spawnattr_init(&attr))goto done;ai=1;
 for(int i=0;i<5;i++)if(mapped[i]>=0 && posix_spawn_file_actions_adddup2(&f,mapped[i],3+i))goto done;
 if(posix_spawn_file_actions_adddup2(&f,ready_writer,8))goto done;
#ifdef CB_CAPTURE_CONTROLLER
 stop_copy=fcntl(capture_stop_fd,F_DUPFD_CLOEXEC,40);if(stop_copy<0)goto done;
 if(posix_spawn_file_actions_adddup2(&f,stop_copy,9))goto done;
 if(role==3){
  for(int i=0;i<2;i++){
   ack_copy[i]=fcntl(capture_close[i][1],F_DUPFD_CLOEXEC,40);
   if(ack_copy[i]<0 || posix_spawn_file_actions_adddup2(&f,ack_copy[i],12+i))goto done;
  }
  if(capture_options.flags==CB_CAPTURE_PCM){
   pcm_copy=fcntl(capture_pcm_fd,F_DUPFD_CLOEXEC,40);if(pcm_copy<0)goto done;
   finish_copy=fcntl(capture_finish_fd,F_DUPFD_CLOEXEC,40);if(finish_copy<0)goto done;
   if(posix_spawn_file_actions_adddup2(&f,pcm_copy,10) || posix_spawn_file_actions_adddup2(&f,finish_copy,11))goto done;
  }
 }
#endif
#ifdef CB_CAPTURE_CONTROLLER
 if((role!=1 && capture_group<=1) || posix_spawnattr_setpgroup(&attr,role==1?0:capture_group) ||
    posix_spawnattr_setflags(&attr,POSIX_SPAWN_START_SUSPENDED|POSIX_SPAWN_CLOEXEC_DEFAULT|POSIX_SPAWN_SETPGROUP))goto done;
#else
 if(posix_spawnattr_setflags(&attr,POSIX_SPAWN_START_SUSPENDED|POSIX_SPAWN_CLOEXEC_DEFAULT))goto done;
#endif
 char *args[]={(char *)path,NULL};char *environment[]={NULL};
 if((failure_code=posix_spawn(&pid,path,&f,&attr,args,environment))) {pid=-1;goto done;}
 owned_identity[role-1]=pid;retained[role-1]=pid;
#ifdef CB_CAPTURE_CONTROLLER
 if(role==1)capture_group=pid;
 if(getpgid(pid)!=capture_group)goto done;
#endif
 failure_stage="IDENTITY_VERIFY";failure_code=-10002;
 if(!verify(pid,path,role))goto done;
 failure_stage="CAPABILITY";failure_code=0;errno=0;
#ifdef CB_CAPTURE_CONTROLLER
 struct capability capability={.deadline=deadline,.parent=getpid(),.role=(uint32_t)role};
 capability.group=capture_group;capability.expires_unix_ns=cb_capture_expires_unix_ns;
#else
 struct capability capability={deadline,getpid(),(uint32_t)role};
#endif
 size_t offset=0;
 while(offset<sizeof(capability)){
  ssize_t n=write(cap[1],(const char *)&capability+offset,sizeof(capability)-offset);
  if(n<0 && errno==EINTR)continue;if(n<=0)goto done;offset+=(size_t)n;
 }
#ifdef CB_CAPTURE_CONTROLLER
 if(role==3 && write(cap[1],&capture_options,sizeof(capture_options))!=(ssize_t)sizeof(capture_options))goto done;
#endif
 if(kill(pid,SIGCONT)<0)goto done;
 close_owned(&ready_pipe[1]);
 failure_stage="READY_ACK";failure_code=0;errno=0;
 struct {int32_t pid;uint32_t role;} ready={0};size_t received=0;
 while(received<sizeof(ready) && mach_continuous_time()<deadline){
  struct pollfd fready={.fd=ready_pipe[0],.events=POLLIN|POLLHUP};
  int n=poll(&fready,1,10);if(n<0 && errno==EINTR)continue;if(n<0)goto done;
  if(n>0){ssize_t count=read(ready_pipe[0],(char *)&ready+received,sizeof(ready)-received);if(count<0 && errno==EINTR)continue;if(count<=0){failure_code=count==0?-10007:errno;goto done;}received+=(size_t)count;}
 }
 if(received!=sizeof(ready)){failure_code=-10003;goto done;}
 if(ready.pid!=pid || ready.role!=(uint32_t)role){failure_code=-10004;goto done;}
 ok=1;
done:
 if(!ok && !failure_code)failure_code=errno?errno:-10005;
 if(ok){failure_stage="NONE";failure_role=0;failure_code=0;}
 if(fi && posix_spawn_file_actions_destroy(&f))closure_error=1;
 if(ai && posix_spawnattr_destroy(&attr))closure_error=1;
 for(int i=0;i<2;i++){close_owned(&cap[i]);close_owned(&ready_pipe[i]);}
 for(int i=0;i<5;i++)close_owned(&mapped[i]);close_owned(&ready_writer);
#ifdef CB_CAPTURE_CONTROLLER
 close_owned(&stop_copy);close_owned(&pcm_copy);close_owned(&finish_copy);close_owned(&ack_copy[0]);close_owned(&ack_copy[1]);
#endif
#ifdef CB_CAPTURE_CONTROLLER
 /* Group-leader PID custody must survive failed identity/ready setup too. */
 if(!ok && role==1 && pid>0)return -1;
#endif
 if(!ok && pid>0){if(!reap_owned(pid,role))closure_error=1;else retained[role-1]=-1;pid=-1;}
 return pid;
}
#ifdef CB_CAPTURE_CONTROLLER
static int observe_owned(pid_t pid,int *status){
 siginfo_t info;memset(&info,0,sizeof(info));
 if(waitid(P_PID,(id_t)pid,&info,WEXITED|WNOHANG|WNOWAIT))return errno==EINTR?0:-1;
 if(!info.si_pid)return 0;
 if(info.si_code==CLD_EXITED)*status=info.si_status<<8;
 else if(info.si_code==CLD_KILLED || info.si_code==CLD_DUMPED)*status=info.si_status|(info.si_code==CLD_DUMPED?128:0);
 else return -1;
 return 1;
}
static int kill_capture_group(void){
 /* An owned unreaped leader pins PGID. Never signal after ECHILD/reap. */
 if(capture_group<=1 || retained[0]!=capture_group)return 0;
 int status=-1;if(observe_owned(capture_group,&status)<0)return 0;
 return kill(-capture_group,SIGKILL)==0 || errno==ESRCH;
}
#endif
int main(int argc,char **argv) {
#ifdef CB_CAPTURE_CONTROLLER
 int pcm=argc==8 && !strcmp(argv[1],"--capture-pcm-budget");
 int physical=pcm || (argc==5 && !strcmp(argv[1],"--capture-budget"));
 int noinput=argc==4 && !strcmp(argv[1],"--capture-noinput-budget");
 if(!physical && !noinput)return 64;
 char *after=NULL;errno=0;
 unsigned long device=physical?strtoul(argv[3],&after,10):0;
 if(physical && (errno || !after || *after || !device || device>UINT32_MAX))return 64;
 const char *stoparg=argv[physical?4:3];after=NULL;errno=0;
 long stop_fd=strtol(stoparg,&after,10);
 if(errno || !after || *after || stop_fd<3 || stop_fd>INT_MAX)return 64;
 struct stat stop_stat;int stop_flags=fcntl((int)stop_fd,F_GETFL);
 if(stop_flags<0 || (stop_flags&O_ACCMODE)!=O_RDONLY || fstat((int)stop_fd,&stop_stat) || !S_ISFIFO(stop_stat.st_mode))return 64;
 if(fcntl((int)stop_fd,F_SETFD,FD_CLOEXEC)<0)return 70;
 int32_t launch_parent=getppid();capture_stop_fd=(int)stop_fd;
 capture_options=(cb_capture_options){.magic=CB_CAPTURE_MAGIC,.flags=pcm?CB_CAPTURE_PCM:(physical?CB_CAPTURE_ARMED:0),.device=(uint32_t)device};
 if(pcm){
  long descriptors[2];
  for(int i=0;i<2;i++){
   after=NULL;errno=0;descriptors[i]=strtol(argv[5+i],&after,10);
   if(errno || !after || *after || descriptors[i]<3 || descriptors[i]>INT_MAX || descriptors[i]==stop_fd)return 64;
   struct stat st;int flags=fcntl((int)descriptors[i],F_GETFL);
   if(flags<0 || (flags&O_ACCMODE)!=(i==0?O_WRONLY:O_RDONLY) ||
      (i==0 && (!(flags&O_NONBLOCK) || fpathconf((int)descriptors[i],_PC_PIPE_BUF)<512)) ||
      fstat((int)descriptors[i],&st) || !S_ISFIFO(st.st_mode) ||
      fcntl((int)descriptors[i],F_SETFD,FD_CLOEXEC)<0)return 64;
  }
  if(descriptors[0]==descriptors[1] || strlen(argv[7])!=32)return 64;
  unsigned nonzero=0;
  for(int i=0;i<16;i++){
   unsigned n=0;
   for(int j=0;j<2;j++){
    unsigned char c=(unsigned char)argv[7][i*2+j];
    if(c>='0' && c<='9')n=(n<<4)|(c-'0');
    else if(c>='a' && c<='f')n=(n<<4)|(c-'a'+10);else return 64;
   }
   capture_options.epoch[i]=(unsigned char)n;nonzero|=n;
  }
  if(!nonzero)return 64;
  capture_pcm_fd=(int)descriptors[0];capture_finish_fd=(int)descriptors[1];
 }
 int budget_mode=1;const char *mode="deadline";
#else
 /* Existing qualification-only binary cannot capture. */
 if((argc!=3 && argc!=4) || (strcmp(argv[1],"--noaudio") && strcmp(argv[1],"--noaudio-budget")))return 64;
 int budget_mode=!strcmp(argv[1],"--noaudio-budget");
 if(budget_mode && argc!=3)return 64;
 const char *mode=argc==4?argv[3]:"deadline";
 if(strcmp(mode,"deadline") && strcmp(mode,"guardian_a") && strcmp(mode,"guardian_b") && strcmp(mode,"helper") && strcmp(mode,"suspend") && strcmp(mode,"parent_death"))return 64;
#endif
 char root[PATH_MAX];if(!realpath(argv[2],root))return 64;
 if(signal(SIGPIPE,SIG_IGN)==SIG_ERR)return 70;
#ifdef CB_CAPTURE_CONTROLLER
 struct sigaction child_action;memset(&child_action,0,sizeof(child_action));child_action.sa_handler=SIG_DFL;
 if(sigemptyset(&child_action.sa_mask) || sigaction(SIGCHLD,&child_action,NULL))return 70;
#endif
 mach_timebase_info_data_t tb;if(mach_timebase_info(&tb)!=KERN_SUCCESS || !tb.numer)return 70;
 uint64_t end;
 if(budget_mode){
#ifdef CB_CAPTURE_CONTROLLER
  if(!cb_budget_deadline_for(&end,tb,pcm?"capture_pcm_budget_ready":(physical?"capture_budget_ready":"capture_noinput_budget_ready"),pcm?"CBPC0002":(physical?"CBCA0002":"CBNC0002")))return 70;
#else
  if(!cb_budget_deadline(&end,tb))return 70;
#endif
 }
 else end=mach_continuous_time()+2000000000ULL*tb.denom/tb.numer;
#ifdef CB_CAPTURE_CONTROLLER
 /* Already-impossible startup is rejected before ANY helper can open HAL. */
 if(mach_continuous_time()+500000000ULL*tb.denom/tb.numer>=end)return 70;
#endif
 int lifelines[3][2]={{-1,-1},{-1,-1},{-1,-1}};pid_t children[3]={-1,-1,-1};int result=70;cb_input state={0};int statuses[3]={-1,-1,-1};pid_t identities[3]={-1,-1,-1};
 for(int i=0;i<3;i++){
  if(pipe(lifelines[i]))goto cleanup;
  for(int j=0;j<2;j++)if(fcntl(lifelines[i][j],F_SETFD,FD_CLOEXEC)<0)goto cleanup;
 }
#ifdef CB_CAPTURE_CONTROLLER
 struct pollfd before_spawn={.fd=(int)stop_fd,.events=POLLIN|POLLHUP|POLLERR};
 if(getppid()!=launch_parent || mach_continuous_time()>=end || poll(&before_spawn,1,0)!=0)goto cleanup;
#endif
 if(!cb_reserve(&state,end) || !cb_synthetic_input(&state) || !cb_route_change(&state))goto cleanup;
#ifdef CB_CAPTURE_CONTROLLER
 for(int i=0;i<2;i++){
  if(pipe(capture_close[i]))goto cleanup;
  int f=fcntl(capture_close[i][1],F_GETFL);if(f<0 || fcntl(capture_close[i][1],F_SETFL,f|O_NONBLOCK)<0)goto cleanup;
  for(int j=0;j<2;j++)if(fcntl(capture_close[i][j],F_SETFD,FD_CLOEXEC)<0)goto cleanup;
 }
#endif
 for(int i=0;i<2;i++){
  char path[PATH_MAX];
#ifdef CB_CAPTURE_CONTROLLER
  if(snprintf(path,sizeof(path),"%s/CaptureGuardian%c",root,'A'+i)>=(int)sizeof(path))goto cleanup;
  children[i]=spawn_role(path,lifelines[0][0],lifelines[i+1][1],capture_close[i][0],-1,i+1,end);
#else
  if(snprintf(path,sizeof(path),"%s/Guardian%c",root,'A'+i)>=(int)sizeof(path))goto cleanup;
  children[i]=spawn_role(path,-1,lifelines[i+1][1],-1,-1,i+1,end);
#endif
  close_owned(&lifelines[i+1][1]);
  if(children[i]<0)goto cleanup;
 }
 /* Fixed synthetic helper consumes three read capabilities via a dedicated role image. */
 char path[PATH_MAX];if(snprintf(path,sizeof(path),"%s/SyntheticHelper",root)>=(int)sizeof(path))goto cleanup;
 /* Helper receives role configuration; no actual input opening exists in any image. */
#ifdef CB_CAPTURE_CONTROLLER
 if(snprintf(path,sizeof(path),"%s/CaptureHelper",root)>=(int)sizeof(path))goto cleanup;
#endif
 children[2]=spawn_role(path,lifelines[0][0],lifelines[0][0],lifelines[1][0],lifelines[2][0],3,end);
#ifdef CB_CAPTURE_CONTROLLER
 close_owned(&capture_pcm_fd);close_owned(&capture_finish_fd);
 for(int i=0;i<2;i++)for(int j=0;j<2;j++)close_owned(&capture_close[i][j]);
#endif
 if(children[2]<0)goto cleanup;
 for(int i=0;i<3;i++)identities[i]=children[i];
 if(mach_continuous_time()+500000000ULL*tb.denom/tb.numer>=end)goto cleanup;
 if(printf("{\"event\":\"started\",\"pids\":[%d,%d,%d]}\n",children[0],children[1],children[2])<0 || fflush(stdout))goto cleanup;
 result=0;
 if(!strcmp(mode,"guardian_a") && kill(children[0],SIGKILL)<0)result=70;
 if(!strcmp(mode,"guardian_b") && kill(children[1],SIGKILL)<0)result=70;
 if(!strcmp(mode,"helper") && kill(children[2],SIGKILL)<0)result=70;
 if(!strcmp(mode,"suspend")){if(kill(children[2],SIGSTOP)<0)result=70;if(usleep(2100000)<0 && errno!=EINTR)result=70;if(kill(children[2],SIGCONT)<0)result=70;}
 uint64_t reap_end=end+2000000000ULL*tb.denom/tb.numer;
#ifdef CB_CAPTURE_CONTROLLER
 while(mach_continuous_time()<reap_end){
  int remaining=0;
  for(int i=0;i<3;i++)if(statuses[i]<0){
   int r=observe_owned(children[i],&statuses[i]);if(r<0){result=70;goto cleanup;}
   if(!r)remaining++;
  }
  for(int i=0;i<3;i++)if(statuses[i]>=0 &&
     (!WIFEXITED(statuses[i]) || (i<2?WEXITSTATUS(statuses[i])!=72:(WEXITSTATUS(statuses[i])!=71 && WEXITSTATUS(statuses[i])!=72)))){
   result=70;goto cleanup;
  }
  if(!remaining)break;
  /* The immutable capture deadline is not the reap grace. Stopped roles must
   * enter owned group termination now; forced cleanup remains HOLD. */
  if(mach_continuous_time()>=end){result=70;goto cleanup;}
  struct pollfd stop={.fd=capture_stop_fd,.events=POLLIN|POLLHUP|POLLERR};
  if(poll(&stop,1,0)!=0 || getppid()!=launch_parent || !cb_capture_wall_valid(cb_capture_expires_unix_ns)){result=70;goto cleanup;}
  if(usleep(1000)<0 && errno!=EINTR){result=70;goto cleanup;}
 }
 for(int i=0;i<3;i++)if(statuses[i]<0)result=70;
#else
 while(mach_continuous_time()<reap_end) {
#ifdef CB_CAPTURE_CONTROLLER
  /* Independent of capture/UI callbacks. Only direct, unreaped children are
   * signalled. A forced reap remains HOLD, never closure acceptance. */
  struct pollfd emergency={.fd=(int)stop_fd,.events=POLLIN|POLLHUP|POLLERR};
  int changed=poll(&emergency,1,0);
  if(changed<0 || emergency.revents || getppid()!=launch_parent ||
     mach_continuous_time()>=end || children[0]<0 || children[1]<0) {
   close_owned(&lifelines[0][1]);
   if(children[2]>0){if(!reap_owned(children[2],3))closure_error=1;else {children[2]=-1;retained[2]=-1;}}
   if(changed<0 || emergency.revents || getppid()!=launch_parent)result=70;
  }
#endif
  int remaining=0;
  for(int i=0;i<3;i++)if(children[i]>0){
   pid_t done=waitpid(children[i],&statuses[i],WNOHANG);
   if(done==children[i]){children[i]=-1;retained[i]=-1;}
   else if(done<0 && errno!=EINTR){result=70;goto cleanup;}
   else remaining++;
  }
  if(!remaining)break;
  if(usleep(1000)<0 && errno!=EINTR){result=70;break;}
 }
 for(int i=0;i<3;i++)if(children[i]>0)result=70;
 if(result==0){
  for(int i=0;i<3;i++){
   int injected=(!strcmp(mode,"guardian_a") && i==0)||(!strcmp(mode,"guardian_b") && i==1)||(!strcmp(mode,"helper") && i==2);
   if(injected){if(!WIFSIGNALED(statuses[i]) || WTERMSIG(statuses[i])!=SIGKILL)result=70;}
   else {int expected=(i==2 && (!strcmp(mode,"guardian_a")||!strcmp(mode,"guardian_b")))?71:72;
    if(!WIFEXITED(statuses[i]) || (WEXITSTATUS(statuses[i])!=expected && !(i==2 && expected==72 && WEXITSTATUS(statuses[i])==71)))result=70;}
  }
 }
#endif
cleanup:
#ifdef CB_CAPTURE_CONTROLLER
 close_owned(&capture_pcm_fd);close_owned(&capture_finish_fd);
 for(int i=0;i<2;i++)for(int j=0;j<2;j++)close_owned(&capture_close[i][j]);
 if(capture_group>1 && !kill_capture_group())result=70;
#endif
 for(int i=0;i<3;i++)identities[i]=owned_identity[i];
 for(int i=0;i<3;i++)for(int j=0;j<2;j++)close_owned(&lifelines[i][j]);
 for(int i=0;i<3;i++)if(retained[i]>0){if(!reap_owned(retained[i],i+1))result=70;else retained[i]=-1;}
 for(int i=0;i<3;i++)if(saved_status[i]!=-1)statuses[i]=saved_status[i];
 /* Synthetic only; native stop/drain/dispose proof cannot be asserted by this controller. */
 cb_stop(&state,mach_continuous_time(),false,false,false);
 if(closure_error)result=70;
 for(int i=0;i<3;i++)if(identities[i]>0){errno=0;if(kill(identities[i],0)==0 || errno!=ESRCH)result=70;}
 if(result && !strcmp(failure_stage,"NONE")){failure_stage="OWNED_REAP";failure_code=-10006;}
#ifdef CB_CAPTURE_CONTROLLER
 if(printf("{\"schema\":1,\"capture_exit\":%d,\"capture\":%s,\"terminal\":\"HOLD\",\"pids\":[%d,%d,%d],\"wait_status\":[%d,%d,%d],\"cleanup_killed\":[%d,%d,%d]}\n",result,physical?"true":"false",identities[0],identities[1],identities[2],statuses[0],statuses[1],statuses[2],cleanup_killed[0],cleanup_killed[1],cleanup_killed[2])<0)return 70;
#else
 if(printf("{\"schema\":6,\"noaudio_exit\":%d,\"terminal\":\"HOLD\",\"pids\":[%d,%d,%d],\"wait_status\":[%d,%d,%d],\"failure_stage\":\"%s\",\"failure_role\":%d,\"failure_code\":%d,\"cleanup_killed\":[%d,%d,%d]}\n",result,identities[0],identities[1],identities[2],statuses[0],statuses[1],statuses[2],failure_stage,failure_role,failure_code,cleanup_killed[0],cleanup_killed[1],cleanup_killed[2])<0)return 70;
#endif
 return result;
}
