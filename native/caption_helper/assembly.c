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
extern char **environ;
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
 const void *k[]={kSecGuestAttributePid},*v[]={number};
 CFDictionaryRef attrs=CFDictionaryCreate(NULL,k,v,1,&kCFTypeDictionaryKeyCallBacks,&kCFTypeDictionaryValueCallBacks);
 int good=0;
 if(SecStaticCodeCreateWithPath(url,0,&disk) || SecStaticCodeCheckValidity(disk,kSecCSStrictValidate,NULL))goto done;
 if(SecCodeCopyGuestWithAttributes(NULL,attrs,0,&live) || SecCodeCheckValidity(live,kSecCSStrictValidate,NULL))goto done;
 if(SecCodeCopySigningInformation(disk,kSecCSSigningInformation,&di) || SecCodeCopySigningInformation(live,kSecCSSigningInformation,&li))goto done;
 CFTypeRef a=CFDictionaryGetValue(di,kSecCodeInfoUnique),b=CFDictionaryGetValue(li,kSecCodeInfoUnique);
 CFTypeRef ai=CFDictionaryGetValue(di,kSecCodeInfoIdentifier),bi=CFDictionaryGetValue(li,kSecCodeInfoIdentifier);
 if(a && b && ai && bi && CFEqual(a,b) && CFEqual(ai,bi) && CFGetTypeID(b)==CFDataGetTypeID()) {
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
static pid_t spawn_role(const char *path,int input,int output,int ga,int gb,int role,uint64_t deadline) {
 int cap[2];if(pipe(cap))return -1;
 int originals[5]={cap[0],output,input,ga,gb};int mapped[5]={-1,-1,-1,-1,-1};
 for(int i=0;i<5;i++)if(originals[i]>=0){mapped[i]=fcntl(originals[i],F_DUPFD_CLOEXEC,20);if(mapped[i]<0){for(int j=0;j<i;j++)if(mapped[j]>=0)close(mapped[j]);close(cap[0]);close(cap[1]);return -1;}}
 for(int i=0;i<2;i++)fcntl(cap[i],F_SETFD,FD_CLOEXEC);
 posix_spawn_file_actions_t f;posix_spawnattr_t attr;
 posix_spawn_file_actions_init(&f);posix_spawnattr_init(&attr);
 posix_spawn_file_actions_adddup2(&f,mapped[0],3);
 posix_spawn_file_actions_adddup2(&f,mapped[1],4);
 if(input>=0)posix_spawn_file_actions_adddup2(&f,mapped[2],5);
 if(ga>=0)posix_spawn_file_actions_adddup2(&f,mapped[3],6);
 if(gb>=0)posix_spawn_file_actions_adddup2(&f,mapped[4],7);
 posix_spawnattr_setflags(&attr,POSIX_SPAWN_START_SUSPENDED|POSIX_SPAWN_CLOEXEC_DEFAULT);
 char *args[]={(char *)path,NULL};pid_t pid=-1;
 int error=posix_spawn(&pid,path,&f,&attr,args,environ);
 posix_spawn_file_actions_destroy(&f);posix_spawnattr_destroy(&attr);close(cap[0]);
 for(int i=0;i<5;i++)if(mapped[i]>=0)close(mapped[i]);
 if(error){close(cap[1]);return -1;}
 /* Owned suspended child cannot exec itself or recycle PID before wait. */
 if(!verify(pid,path,role)){reap_owned(pid);close(cap[1]);return -1;}
 struct capability capability={deadline,getpid(),(uint32_t)role};
 ssize_t n=write(cap[1],&capability,sizeof(capability));close(cap[1]);
 if(n!=(ssize_t)sizeof(capability)){reap_owned(pid);return -1;}
 if(kill(pid,SIGCONT)<0){reap_owned(pid);return -1;}return pid;
}
int main(int argc,char **argv) {
 /* Explicit noaudio mode only. Capture admission is compile-time false. */
 if((argc!=3 && argc!=4) || strcmp(argv[1],"--noaudio"))return 64;
 const char *mode=argc==4?argv[3]:"deadline";
 if(strcmp(mode,"deadline") && strcmp(mode,"guardian_a") && strcmp(mode,"guardian_b") && strcmp(mode,"helper") && strcmp(mode,"suspend"))return 64;
 char root[PATH_MAX];if(!realpath(argv[2],root))return 64;
 if(signal(SIGPIPE,SIG_IGN)==SIG_ERR)return 70;
 mach_timebase_info_data_t tb;if(mach_timebase_info(&tb)!=KERN_SUCCESS || !tb.numer)return 70;
 uint64_t end=mach_continuous_time()+1000000000ULL*tb.denom/tb.numer;
 int lifelines[3][2]={{-1,-1},{-1,-1},{-1,-1}};pid_t children[3]={-1,-1,-1};int result=70;cb_input state={0};
 for(int i=0;i<3;i++){
  if(pipe(lifelines[i]))goto cleanup;
  for(int j=0;j<2;j++)if(fcntl(lifelines[i][j],F_SETFD,FD_CLOEXEC)<0)goto cleanup;
 }
 if(!cb_reserve(&state,end) || !cb_synthetic_input(&state) || !cb_route_change(&state))goto cleanup;
 for(int i=0;i<2;i++){
  char path[PATH_MAX];if(snprintf(path,sizeof(path),"%s/Guardian%c",root,'A'+i)>=(int)sizeof(path))goto cleanup;
  children[i]=spawn_role(path,-1,lifelines[i+1][1],-1,-1,i+1,end);
  close(lifelines[i+1][1]);lifelines[i+1][1]=-1;
  if(children[i]<0)goto cleanup;
 }
 /* Fixed synthetic helper consumes three read capabilities via a dedicated role image. */
 char path[PATH_MAX];if(snprintf(path,sizeof(path),"%s/SyntheticHelper",root)>=(int)sizeof(path))goto cleanup;
 /* Helper receives role configuration; no actual input opening exists in any image. */
 children[2]=spawn_role(path,lifelines[0][0],lifelines[0][0],lifelines[1][0],lifelines[2][0],3,end);
 if(children[2]<0)goto cleanup;
 result=0;
 if(!strcmp(mode,"guardian_a") && kill(children[0],SIGKILL)<0)result=70;
 if(!strcmp(mode,"guardian_b") && kill(children[1],SIGKILL)<0)result=70;
 if(!strcmp(mode,"helper") && kill(children[2],SIGKILL)<0)result=70;
 if(!strcmp(mode,"suspend")){if(kill(children[2],SIGSTOP)<0)result=70;usleep(1100000);if(kill(children[2],SIGCONT)<0)result=70;}
 while(mach_continuous_time()<end) {
  int status;pid_t done=waitpid(children[2],&status,WNOHANG);
  if(done==children[2]){children[2]=-1;break;}
  usleep(1000);
 }
cleanup:
 for(int i=0;i<3;i++)for(int j=0;j<2;j++)if(lifelines[i][j]>=0)close(lifelines[i][j]);
 for(int i=0;i<3;i++)if(children[i]>0){if(!reap_owned(children[i]))result=70;}
 /* Synthetic only; native stop/drain/dispose proof cannot be asserted by this controller. */
 cb_stop(&state,mach_continuous_time(),false,false,false);
 printf("{\"schema\":3,\"noaudio_exit\":%d,\"terminal\":\"HOLD\"}\n",result);
 return result;
}
