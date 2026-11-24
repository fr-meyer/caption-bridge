/* Hosted Darwin diagnostic, real owned processes only. Never capture admission. */
#define _DARWIN_C_SOURCE 1
#include "owned_group_closure.h"
#include <mach/mach_time.h>
#include <signal.h>
#include <fcntl.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#define MEMBERS CB_OWNED_GROUP_MEMBERS
#define OWNED_CAP (MEMBERS+1)
#define CENSUS_CAP 16
static mach_timebase_info_data_t tb;
static uint64_t until_ms(unsigned ms){
 return mach_continuous_time()+(uint64_t)ms*1000000ULL*tb.denom/tb.numer;
}
static int before(uint64_t end){return mach_continuous_time()<end;}
static void close_fd(int *fd){if(*fd>=0){(void)close(*fd);*fd=-1;}}
static int observe(pid_t pid,siginfo_t *info){
 memset(info,0,sizeof(*info));
 if(waitid(P_PID,(id_t)pid,info,WEXITED|WNOHANG|WNOWAIT))return errno==EINTR?0:-1;
 return info->si_pid==pid?1:0;
}
struct ready {pid_t pid,parent,group,session;uid_t uid,euid;};
static void member(pid_t group,int gate,int ready_fd,pid_t parent){
 if(setpgid(0,group))_exit(65);
 struct ready r={getpid(),getppid(),getpgrp(),getsid(0),getuid(),geteuid()};
 if(r.parent!=parent || write(ready_fd,&r,sizeof(r))!=(ssize_t)sizeof(r))_exit(66);
 (void)close(ready_fd);
 char byte;ssize_t n;
 do{n=read(gate,&byte,1);}while(n<0 && errno==EINTR);
 (void)close(gate);_exit(n==0?72:67);
}
static int wait_ready(int fd,struct ready *r,uint64_t end){
 size_t got=0;
 while(before(end)){
  ssize_t n=read(fd,(char *)r+got,sizeof(*r)-got);
  if(n>0){got+=(size_t)n;if(got==sizeof(*r))return 1;}
  else if(n==0 || (errno!=EAGAIN && errno!=EINTR))return 0;
  if(usleep(1000) && errno!=EINTR)return 0;
 }
 return 0;
}
static int spawn_member(int index,pid_t *group,pid_t *pids,int *held,int *gates,uint64_t end){
 int gate[2]={-1,-1},ready_pipe[2]={-1,-1},ok=0;pid_t parent=getpid();
 struct ready r;memset(&r,0,sizeof(r));
 if(pipe(gate) || pipe(ready_pipe))goto done;
 int flags=fcntl(ready_pipe[0],F_GETFL);
 if(flags<0 || fcntl(ready_pipe[0],F_SETFL,flags|O_NONBLOCK))goto done;
 pid_t pid=fork();
 if(pid==0){
  (void)close(gate[1]);(void)close(ready_pipe[0]);
  for(int j=0;j<index;j++)if(gates[j]>=0)(void)close(gates[j]);
  member(*group,gate[0],ready_pipe[1],parent);
 }
 if(pid>0){pids[index]=pid;held[index]=1;gates[index]=gate[1];gate[1]=-1;if(!*group)*group=pid;}
 close_fd(&gate[0]);close_fd(&gate[1]);close_fd(&ready_pipe[1]);
 if(pid<0 || setpgid(pid,*group) || !wait_ready(ready_pipe[0],&r,end))goto done;
 ok=r.pid==pid && r.parent==parent && r.group==*group && r.session==parent &&
    r.uid==getuid() && r.euid==geteuid();
done:
 for(int j=0;j<2;j++){close_fd(&gate[j]);close_fd(&ready_pipe[j]);}
 return ok;
}
/* Diagnostic state projection only. Production closure uses the stronger shared
 * atomic PID enumeration plus enrolled birth/ownership checks, not this walk. */
static int census(pid_t group,const pid_t *pids,const int *held,int *states){
 struct kinfo_proc rows[CENSUS_CAP];size_t bytes=sizeof(rows);
 int mib[]={CTL_KERN,KERN_PROC,KERN_PROC_PGRP,group};
 if(sysctl(mib,4,rows,&bytes,NULL,0) || bytes>sizeof(rows) || bytes%sizeof(rows[0]) ||
    bytes/sizeof(rows[0])!=MEMBERS)return 0;
 unsigned seen=0;
 for(size_t n=0;n<bytes/sizeof(rows[0]);n++){
  struct kinfo_proc *p=&rows[n];int index=-1;
  for(int i=0;i<MEMBERS;i++)if(held[i] && p->kp_proc.p_pid==pids[i])index=i;
  if(index<0 || (seen&(1U<<index)) || p->kp_eproc.e_ppid!=getpid() ||
     p->kp_eproc.e_pgid!=group || p->kp_eproc.e_pcred.p_ruid!=getuid() ||
     p->kp_eproc.e_ucred.cr_uid!=geteuid())return 0;
  siginfo_t info;if(observe(pids[index],&info)<0)return 0;
  states[index]=p->kp_proc.p_stat;seen|=1U<<index;
 }
 return seen==7;
}
static int cleanup(const pid_t *pids,int *held,int *statuses,int *forced){
 int ok=1;uint64_t end=until_ms(2000),grace=until_ms(1000);
 while(before(grace)){
  int pending=0;
  for(int i=0;i<OWNED_CAP;i++)if(held[i]){
   siginfo_t info;int r=observe(pids[i],&info);
   if(r<0)ok=0;else if(!r)pending++;
  }
  if(!pending)break;
  if(usleep(1000) && errno!=EINTR){ok=0;break;}
 }
 /* One common cleanup budget, including the real adverse fourth child. */
 for(int i=0;i<OWNED_CAP;i++)if(held[i]){
  siginfo_t info;int r=observe(pids[i],&info);
  if(r<0){ok=0;continue;}
  if(!r){if(kill(pids[i],SIGKILL) && errno!=ESRCH)ok=0;else forced[i]=1;}
 }
 for(int i=0;i<OWNED_CAP;i++)while(held[i] && before(end)){
  pid_t done=waitpid(pids[i],&statuses[i],WNOHANG);
  if(done==pids[i]){held[i]=0;break;}
  if(done<0 && errno!=EINTR){ok=0;break;}
  if(usleep(1000) && errno!=EINTR){ok=0;break;}
 }
 for(int i=0;i<OWNED_CAP;i++)if(held[i])ok=0;
 return ok;
}
static const char *maybe_bool(int value){return value<0?"null":value?"true":"false";}
static int run_case(int exited){
 pid_t pids[OWNED_CAP]={0};int held[OWNED_CAP]={0};
 int gates[OWNED_CAP]={-1,-1,-1,-1},statuses[OWNED_CAP]={-1,-1,-1,-1};
 int forced[OWNED_CAP]={0},states[MEMBERS]={0},observed[MEMBERS]={0};
 cb_owned_group_member pins[MEMBERS];memset(pins,0,sizeof(pins));
 int ok=1,complete=0,census_ok=0,zero_rc=-2,zero_errno=0,kill_rc=-2,kill_errno=0;
 int closure=-1,extra_live=-1,extra_zombie=-1;
 int closure_bytes=-1,extra_live_bytes=-1,extra_zombie_bytes=-1;
 pid_t group=0;uint64_t end=until_ms(3000);
 for(int i=0;i<MEMBERS;i++){
  if(!spawn_member(i,&group,pids,held,gates,end) ||
     !cb_owned_group_pin(&pins[i],pids[i],group)){ok=0;goto done;}
 }
 for(int i=0;i<exited;i++)close_fd(&gates[i]);
 for(;;){
  int pending=0;
  for(int i=0;i<MEMBERS;i++){
   siginfo_t info;int r=observe(pids[i],&info);
   if(r<0){ok=0;goto done;}
   if(i<exited){
    if(!r){pending++;continue;}
    if(info.si_code!=CLD_EXITED || info.si_status!=72){ok=0;goto done;}
    observed[i]=info.si_status;
   }else if(r){ok=0;goto done;}
  }
  if(!pending)break;
  if(!before(end) || (usleep(1000) && errno!=EINTR)){ok=0;goto done;}
 }
 /* Exactly the predicate compiled into CaptureController, on real OS state. */
 closure=cb_owned_group_all_zombies_readback(group,pins,&closure_bytes);
 if(closure!=(exited==MEMBERS)){ok=0;goto done;}
 if(exited==MEMBERS){
  /* Deliberately omit a genuinely owned fourth member from expected identities.
   * Both a live outsider and an unreaped zombie outsider must prevent closure.
   * No group signal occurs while the extra member is present. */
  if(!spawn_member(MEMBERS,&group,pids,held,gates,end)){ok=0;goto done;}
  extra_live=!cb_owned_group_all_zombies_readback(group,pins,&extra_live_bytes);
  if(!extra_live || extra_live_bytes!=(int)(OWNED_CAP*sizeof(pid_t))){ok=0;goto done;}
  close_fd(&gates[MEMBERS]);
  for(;;){
   siginfo_t info;int r=observe(pids[MEMBERS],&info);
   if(r<0){ok=0;goto done;}
   if(r){if(info.si_code!=CLD_EXITED || info.si_status!=72){ok=0;goto done;}break;}
   if(!before(end) || (usleep(1000) && errno!=EINTR)){ok=0;goto done;}
  }
  extra_zombie=!cb_owned_group_all_zombies_readback(group,pins,&extra_zombie_bytes);
  if(!extra_zombie || extra_zombie_bytes!=(int)(OWNED_CAP*sizeof(pid_t))){ok=0;goto done;}
  while(before(end)){
   pid_t done=waitpid(pids[MEMBERS],&statuses[MEMBERS],WNOHANG);
   if(done==pids[MEMBERS]){held[MEMBERS]=0;break;}
   if(done<0 && errno!=EINTR){ok=0;goto done;}
   if(usleep(1000) && errno!=EINTR){ok=0;goto done;}
  }
  if(held[MEMBERS] || !WIFEXITED(statuses[MEMBERS]) || WEXITSTATUS(statuses[MEMBERS])!=72 ||
     !cb_owned_group_all_zombies(group,pins)){ok=0;goto done;}
 }
 census_ok=census(group,pids,held,states);
 if(!census_ok || group<=1 || group==getpgrp()){ok=0;goto done;}
 for(int i=0;i<MEMBERS;i++)if((states[i]==SZOMB)!=(i<exited)){ok=0;goto done;}
 errno=0;zero_rc=kill(-group,0);zero_errno=zero_rc<0?errno:0;
 if(!census(group,pids,held,states)){ok=0;goto done;}
 errno=0;kill_rc=kill(-group,SIGKILL);kill_errno=kill_rc<0?errno:0;
 complete=1;
 if(exited<MEMBERS && (zero_rc || kill_rc))ok=0;
done:
 for(int i=0;i<OWNED_CAP;i++)close_fd(&gates[i]);
 if(!cleanup(pids,held,statuses,forced))ok=0;
 for(int i=0;i<OWNED_CAP;i++)if(forced[i])ok=0;
 if(complete)for(int i=0;i<MEMBERS;i++){
  if(i<exited){if(!WIFEXITED(statuses[i]) || WEXITSTATUS(statuses[i])!=72)ok=0;}
  else if(!WIFSIGNALED(statuses[i]) || WTERMSIG(statuses[i])!=SIGKILL)ok=0;
 }
 printf("{\"schema\":2,\"kind\":\"DARWIN_OWNED_GROUP_SIGNAL_OBSERVATION\","
        "\"natural_exits\":%d,\"observation_complete\":%s,\"mechanism_complete\":%s,"
        "\"group\":%d,\"uid\":%u,\"euid\":%u,\"private_session\":%d,"
        "\"pids\":[%d,%d,%d],\"census_complete\":%s,\"states\":[%d,%d,%d],"
        "\"waitid_exits\":[%d,%d,%d],\"signal_zero\":{\"rc\":%d,\"errno\":%d},"
        "\"signal_kill\":{\"rc\":%d,\"errno\":%d},\"reaped_status\":[%d,%d,%d],"
        "\"cleanup_forced\":[%d,%d,%d],\"remaining_owned\":[%d,%d,%d],"
        "\"all_owned_zombies\":%s,\"closure_snapshot_bytes\":%d,\"adverse\":{\"live_extra_rejected\":%s,"
        "\"zombie_extra_rejected\":%s,\"live_extra_snapshot_bytes\":%d,\"zombie_extra_snapshot_bytes\":%d,\"extra_reaped_status\":%d,"
        "\"cleanup_forced\":%d,\"remaining_owned\":%d},"
        "\"darwin_unix03\":%d,\"capture\":false,\"native_admission\":false}\n",
        exited,complete?"true":"false",ok?"true":"false",group,(unsigned)getuid(),
        (unsigned)geteuid(),getsid(0),pids[0],pids[1],pids[2],census_ok?"true":"false",
        states[0],states[1],states[2],observed[0],observed[1],observed[2],zero_rc,zero_errno,
        kill_rc,kill_errno,statuses[0],statuses[1],statuses[2],forced[0],forced[1],forced[2],
        held[0],held[1],held[2],maybe_bool(closure),closure_bytes,maybe_bool(extra_live),maybe_bool(extra_zombie),
        extra_live_bytes,extra_zombie_bytes,statuses[MEMBERS],forced[MEMBERS],held[MEMBERS],__DARWIN_UNIX03);
 return ok;
}
int main(int argc,char **argv){
 (void)argv;if(argc!=1)return 64;
 struct sigaction action;memset(&action,0,sizeof(action));action.sa_handler=SIG_DFL;
 if(sigemptyset(&action.sa_mask) || sigaction(SIGCHLD,&action,NULL) ||
    signal(SIGPIPE,SIG_IGN)==SIG_ERR || mach_timebase_info(&tb)!=KERN_SUCCESS ||
    !tb.numer || !tb.denom)return 70;
 if(setsid()!=getpid() || getsid(0)!=getpid())return 70;
 if(!run_case(0) || !run_case(1) || !run_case(3))return 70;
 return fflush(stdout)?70:0;
}
