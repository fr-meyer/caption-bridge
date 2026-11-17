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
extern char **environ;
struct capability { uint64_t deadline; int32_t parent; uint32_t role; };
static int verify(pid_t pid,const char *path) {
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
 good=a && b && ai && bi && CFEqual(a,b) && CFEqual(ai,bi);
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
 if(!verify(pid,path)){kill(pid,SIGKILL);waitpid(pid,NULL,0);close(cap[1]);return -1;}
 struct capability capability={deadline,getpid(),(uint32_t)role};
 ssize_t n=write(cap[1],&capability,sizeof(capability));close(cap[1]);
 if(n!=(ssize_t)sizeof(capability)){kill(pid,SIGKILL);waitpid(pid,NULL,0);return -1;}
 kill(pid,SIGCONT);return pid;
}
int main(int argc,char **argv) {
 /* Explicit noaudio mode only. Capture admission is compile-time false. */
 if(argc!=3 || strcmp(argv[1],"--noaudio"))return 64;
 char root[PATH_MAX];if(!realpath(argv[2],root))return 64;
 signal(SIGPIPE,SIG_IGN);
 mach_timebase_info_data_t tb;mach_timebase_info(&tb);
 uint64_t end=mach_continuous_time()+1000000000ULL*tb.denom/tb.numer;
 int lifelines[3][2]={{-1,-1},{-1,-1},{-1,-1}};pid_t children[3]={-1,-1,-1};int result=70;cb_input state={0};
 for(int i=0;i<3;i++){
  if(pipe(lifelines[i]))goto cleanup;
  for(int j=0;j<2;j++)fcntl(lifelines[i][j],F_SETFD,FD_CLOEXEC);
 }
 if(!cb_reserve(&state,end))goto cleanup;
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
 while(mach_continuous_time()<end) {
  int status;pid_t done=waitpid(children[2],&status,WNOHANG);
  if(done==children[2]){children[2]=-1;break;}
  usleep(1000);
 }
cleanup:
 for(int i=0;i<3;i++)for(int j=0;j<2;j++)if(lifelines[i][j]>=0)close(lifelines[i][j]);
 for(int i=0;i<3;i++)if(children[i]>0){kill(children[i],SIGKILL);if(waitpid(children[i],NULL,0)<0)result=70;}
 /* Synthetic only; native stop/drain/dispose proof cannot be asserted by this controller. */
 cb_stop(&state,mach_continuous_time(),false,false,false);
 printf("{\"schema\":3,\"noaudio_exit\":%d,\"terminal\":\"HOLD\"}\n",result);
 return result;
}
