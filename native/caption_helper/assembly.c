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
#include "role_pins.h"
#include <errno.h>
#include <poll.h>
struct capability { uint64_t deadline; int32_t parent; uint32_t role; };
static int reap_owned(pid_t pid) {
 if(kill(pid,SIGKILL)<0 && errno!=ESRCH)return 0;
 for(int i=0;i<1000;i++){pid_t r=waitpid(pid,NULL,WNOHANG);if(r==pid)return 1;if(r<0 && errno!=EINTR)return 0;usleep(1000);}
 return 0;
}
static int verify(pid_t pid,const char *path,int role) {
 CFURLRef url=CFURLCreateFromFileSystemRepresentation(NULL,(const UInt8 *)path,strlen(path),false);
 SecStaticCodeRef disk=NULL;SecCodeRef live=NULL;CFDictionaryRef di=NULL,li=NULL;
 CFNumberRef number=CFNumberCreate(NULL,kCFNumberIntType,&pid);
 if(!url || !number){if(url)CFRelease(url);if(number)CFRelease(number);return 0;}
 const void *k[]={kSecGuestAttributePid},*v[]={number};
 CFDictionaryRef attrs=CFDictionaryCreate(NULL,k,v,1,&kCFTypeDictionaryKeyCallBacks,&kCFTypeDictionaryValueCallBacks);
 int good=0;
 if(!attrs){CFRelease(number);CFRelease(url);return 0;}
 if(SecStaticCodeCreateWithPath(url,0,&disk) || SecStaticCodeCheckValidity(disk,kSecCSStrictValidate,NULL))goto done;
 if(SecCodeCopyGuestWithAttributes(NULL,attrs,0,&live) || SecCodeCheckValidity(live,kSecCSStrictValidate,NULL))goto done;
 if(SecCodeCopySigningInformation(disk,kSecCSSigningInformation,&di) || SecCodeCopySigningInformation(live,kSecCSSigningInformation,&li))goto done;
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
 if(di)CFRelease(di);if(li)CFRelease(li);if(disk)CFRelease(disk);if(live)CFRelease(live);
 CFRelease(attrs);CFRelease(number);CFRelease(url);return good;
}
static int closure_error=0;
static pid_t owned_identity[3]={-1,-1,-1};
static pid_t retained[3]={-1,-1,-1};
static void close_owned(int *fd){if(*fd>=0){if(close(*fd)<0)closure_error=1;*fd=-1;}}
static pid_t spawn_role(const char *path,int input,int output,int ga,int gb,int role,uint64_t deadline) {
 int ready_pipe[2]={-1,-1};int ready_writer=-1;
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
 if(posix_spawnattr_setflags(&attr,POSIX_SPAWN_START_SUSPENDED|POSIX_SPAWN_CLOEXEC_DEFAULT))goto done;
 char *args[]={(char *)path,NULL};char *environment[]={NULL};
 if(posix_spawn(&pid,path,&f,&attr,args,environment)) {pid=-1;goto done;}
 owned_identity[role-1]=pid;retained[role-1]=pid;
 if(!verify(pid,path,role))goto done;
 struct capability capability={deadline,getpid(),(uint32_t)role};
 size_t offset=0;
 while(offset<sizeof(capability)){
  ssize_t n=write(cap[1],(const char *)&capability+offset,sizeof(capability)-offset);
  if(n<0 && errno==EINTR)continue;if(n<=0)goto done;offset+=(size_t)n;
 }
 if(kill(pid,SIGCONT)<0)goto done;
 close_owned(&ready_pipe[1]);
 struct {int32_t pid;uint32_t role;} ready={0};size_t received=0;
 while(received<sizeof(ready) && mach_continuous_time()<deadline){
  struct pollfd fready={.fd=ready_pipe[0],.events=POLLIN|POLLHUP};
  int n=poll(&fready,1,10);if(n<0 && errno==EINTR)continue;if(n<0)goto done;
  if(n>0){ssize_t count=read(ready_pipe[0],(char *)&ready+received,sizeof(ready)-received);if(count<0 && errno==EINTR)continue;if(count<=0)goto done;received+=(size_t)count;}
 }
 if(received!=sizeof(ready) || ready.pid!=pid || ready.role!=(uint32_t)role)goto done;
 ok=1;
done:
 if(fi && posix_spawn_file_actions_destroy(&f))closure_error=1;
 if(ai && posix_spawnattr_destroy(&attr))closure_error=1;
 for(int i=0;i<2;i++){close_owned(&cap[i]);close_owned(&ready_pipe[i]);}
 for(int i=0;i<5;i++)close_owned(&mapped[i]);close_owned(&ready_writer);
 if(!ok && pid>0){if(!reap_owned(pid))closure_error=1;else retained[role-1]=-1;pid=-1;}
 return pid;
}
int main(int argc,char **argv) {
 /* Explicit noaudio mode only. Capture admission is compile-time false. */
 if((argc!=3 && argc!=4) || strcmp(argv[1],"--noaudio"))return 64;
 const char *mode=argc==4?argv[3]:"deadline";
 if(strcmp(mode,"deadline") && strcmp(mode,"guardian_a") && strcmp(mode,"guardian_b") && strcmp(mode,"helper") && strcmp(mode,"suspend") && strcmp(mode,"parent_death"))return 64;
 char root[PATH_MAX];if(!realpath(argv[2],root))return 64;
 if(signal(SIGPIPE,SIG_IGN)==SIG_ERR)return 70;
 mach_timebase_info_data_t tb;if(mach_timebase_info(&tb)!=KERN_SUCCESS || !tb.numer)return 70;
 uint64_t end=mach_continuous_time()+2000000000ULL*tb.denom/tb.numer;
 int lifelines[3][2]={{-1,-1},{-1,-1},{-1,-1}};pid_t children[3]={-1,-1,-1};int result=70;cb_input state={0};int statuses[3]={-1,-1,-1};pid_t identities[3]={-1,-1,-1};
 for(int i=0;i<3;i++){
  if(pipe(lifelines[i]))goto cleanup;
  for(int j=0;j<2;j++)if(fcntl(lifelines[i][j],F_SETFD,FD_CLOEXEC)<0)goto cleanup;
 }
 if(!cb_reserve(&state,end) || !cb_synthetic_input(&state) || !cb_route_change(&state))goto cleanup;
 for(int i=0;i<2;i++){
  char path[PATH_MAX];if(snprintf(path,sizeof(path),"%s/Guardian%c",root,'A'+i)>=(int)sizeof(path))goto cleanup;
  children[i]=spawn_role(path,-1,lifelines[i+1][1],-1,-1,i+1,end);
  close_owned(&lifelines[i+1][1]);
  if(children[i]<0)goto cleanup;
 }
 /* Fixed synthetic helper consumes three read capabilities via a dedicated role image. */
 char path[PATH_MAX];if(snprintf(path,sizeof(path),"%s/SyntheticHelper",root)>=(int)sizeof(path))goto cleanup;
 /* Helper receives role configuration; no actual input opening exists in any image. */
 children[2]=spawn_role(path,lifelines[0][0],lifelines[0][0],lifelines[1][0],lifelines[2][0],3,end);
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
 while(mach_continuous_time()<reap_end) {
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
cleanup:
 for(int i=0;i<3;i++)identities[i]=owned_identity[i];
 for(int i=0;i<3;i++)for(int j=0;j<2;j++)close_owned(&lifelines[i][j]);
 for(int i=0;i<3;i++)if(retained[i]>0){if(!reap_owned(retained[i]))result=70;else retained[i]=-1;}
 /* Synthetic only; native stop/drain/dispose proof cannot be asserted by this controller. */
 cb_stop(&state,mach_continuous_time(),false,false,false);
 if(closure_error)result=70;
 for(int i=0;i<3;i++)if(identities[i]>0){errno=0;if(kill(identities[i],0)==0 || errno!=ESRCH)result=70;}
 if(printf("{\"schema\":5,\"noaudio_exit\":%d,\"terminal\":\"HOLD\",\"pids\":[%d,%d,%d],\"wait_status\":[%d,%d,%d]}\n",result,identities[0],identities[1],identities[2],statuses[0],statuses[1],statuses[2])<0)return 70;
 return result;
}
