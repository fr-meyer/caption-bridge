/* Parent-side direct-child identity check. No network/audio. */
#include <Security/Security.h>
#include <CoreFoundation/CoreFoundation.h>
#include <sys/sysctl.h>
#include <sys/types.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <string.h>
static void hex(CFDataRef d) {
    for(CFIndex i=0;i<CFDataGetLength(d);i++) printf("%02x",CFDataGetBytePtr(d)[i]);
}
int main(int argc,char **argv) {
    if(argc!=3) return 64;
    pid_t pid=(pid_t)strtol(argv[1],NULL,10);
    struct kinfo_proc a={0},b={0}; size_t size=sizeof(a);
    int mib[4]={CTL_KERN,KERN_PROC,KERN_PROC_PID,pid};
    if(sysctl(mib,4,&a,&size,NULL,0)||size!=sizeof(a)) return 65;
    CFNumberRef number=CFNumberCreate(NULL,kCFNumberIntType,&pid);
    const void *keys[]={kSecGuestAttributePid};const void *values[]={number};
    CFDictionaryRef attrs=CFDictionaryCreate(NULL,keys,values,1,&kCFTypeDictionaryKeyCallBacks,&kCFTypeDictionaryValueCallBacks);
    SecCodeRef code=NULL;CFDictionaryRef info=NULL;
    OSStatus status=SecCodeCopyGuestWithAttributes(NULL,attrs,kSecCSDefaultFlags,&code);
    if(!status) status=SecCodeCheckValidity(code,kSecCSStrictValidate,NULL);
    if(!status) status=SecCodeCopySigningInformation(code,kSecCSSigningInformation,&info);
    printf("pid=%d security_status=%d ",pid,(int)status);
    if(status) return 66;
    CFDataRef unique=CFDictionaryGetValue(info,kSecCodeInfoUnique);
    CFURLRef url=CFDictionaryGetValue(info,kSecCodeInfoMainExecutable);
    UInt8 path[4096];
    if(!unique || !url || !CFURLGetFileSystemRepresentation(url,true,path,sizeof(path))) return 67;
    printf("cdhash=");hex(unique);
    printf(" birth=%lld.%06d ppid=%d path_equal=%d\n",(long long)a.kp_proc.p_starttime.tv_sec,(int)a.kp_proc.p_starttime.tv_usec,a.kp_eproc.e_ppid,!strcmp((char *)path,argv[2]));
    size=sizeof(b);
    if(sysctl(mib,4,&b,&size,NULL,0)||size!=sizeof(b) || memcmp(&a.kp_proc.p_starttime,&b.kp_proc.p_starttime,sizeof(a.kp_proc.p_starttime))) return 68;
    return strcmp((char *)path,argv[2])?69:0;
}
