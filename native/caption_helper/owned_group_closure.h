#ifndef CB_OWNED_GROUP_CLOSURE_H
#define CB_OWNED_GROUP_CLOSURE_H
/* Darwin only. Caller serializes custody: no SIGCHLD reaper/other wait thread.
 * Enroll only an already image-verified direct, unreaped, live child. An enrolled
 * PID remains unreaped until this proof and the actual group signal finish.
 */
#include <sys/types.h>
#include <sys/sysctl.h>
#include <sys/proc.h>
#include <sys/wait.h>
#include <libproc.h>
#include <stdint.h>
#include <unistd.h>
#include <string.h>
#define CB_OWNED_GROUP_MEMBERS 3
/* One spare PID is essential: a full/truncated list can NEVER equal 3 entries. */
#define CB_OWNED_GROUP_PID_CAP (CB_OWNED_GROUP_MEMBERS+1)
typedef struct {
 pid_t pid,parent,group;uid_t ruid,euid;
 struct timeval birth;int enrolled;
} cb_owned_group_member;
static inline int cb_owned_group_metadata(pid_t pid,struct kinfo_proc *row){
 int mib[]={CTL_KERN,KERN_PROC,KERN_PROC_PID,pid};size_t bytes=sizeof(*row);
 memset(row,0,sizeof(*row));
 return !sysctl(mib,4,row,&bytes,NULL,0) && bytes==sizeof(*row) && row->kp_proc.p_pid==pid;
}
static inline int cb_owned_group_pin(cb_owned_group_member *pin,pid_t pid,pid_t group){
 memset(pin,0,sizeof(*pin));
 if(pid<=1 || group<=1)return 0;
 siginfo_t info;memset(&info,0,sizeof(info));
 if(waitid(P_PID,(id_t)pid,&info,WEXITED|WNOHANG|WNOWAIT) || info.si_pid)return 0;
 struct kinfo_proc row;
 if(!cb_owned_group_metadata(pid,&row) || row.kp_proc.p_stat==SZOMB ||
    row.kp_eproc.e_ppid!=getpid() || row.kp_eproc.e_pgid!=group ||
    row.kp_eproc.e_pcred.p_ruid!=getuid() || row.kp_eproc.e_ucred.cr_uid!=geteuid() ||
    row.kp_proc.p_starttime.tv_sec<=0 || row.kp_proc.p_starttime.tv_usec<0 ||
    row.kp_proc.p_starttime.tv_usec>=1000000)return 0;
 pin->pid=pid;pin->parent=getpid();pin->group=group;pin->ruid=getuid();pin->euid=geteuid();
 pin->birth=row.kp_proc.p_starttime;pin->enrolled=1;return 1;
}
static inline int cb_owned_group_all_zombies_readback(pid_t group,const cb_owned_group_member *pins,int *snapshot_bytes){
 if(snapshot_bytes)*snapshot_bytes=-1;
 if(group<=1 || group==getpgrp() || !pins || pins[0].pid!=group)return 0;
 /* First establish that each expected identity is an owned immutable zombie.
  * ECHILD, EINTR, missing pins, live/stopped/executing peers all fail closed.
  */
 for(int i=0;i<CB_OWNED_GROUP_MEMBERS;i++){
  const cb_owned_group_member *pin=&pins[i];siginfo_t info;memset(&info,0,sizeof(info));
  if(!pin->enrolled || pin->pid<=1 || pin->parent!=getpid() || pin->group!=group ||
     pin->ruid!=getuid() || pin->euid!=geteuid())return 0;
  for(int j=0;j<i;j++)if(pins[j].pid==pin->pid)return 0;
  if(waitid(P_PID,(id_t)pin->pid,&info,WEXITED|WNOHANG|WNOWAIT) || info.si_pid!=pin->pid ||
     (info.si_code!=CLD_EXITED && info.si_code!=CLD_KILLED && info.si_code!=CLD_DUMPED))return 0;
  struct kinfo_proc row;
  if(!cb_owned_group_metadata(pin->pid,&row) || row.kp_proc.p_stat!=SZOMB ||
     row.kp_eproc.e_ppid!=pin->parent || row.kp_eproc.e_pgid!=group ||
     row.kp_eproc.e_pcred.p_ruid!=pin->ruid || row.kp_eproc.e_ucred.cr_uid!=pin->euid ||
     row.kp_proc.p_starttime.tv_sec!=pin->birth.tv_sec ||
     row.kp_proc.p_starttime.tv_usec!=pin->birth.tv_usec)return 0;
 }
 /* XNU proc_listpids(PROC_PGRP_ONLY) copies BOTH live and zombie PID lists under
  * proc_list_lock, without the sysctl SIDL filter/later callback walk.
  * Require exactly the three pinned zombies in an underfull fixed buffer.
  * Unknown/live/foreign/extra members, truncation/overflow, or denied enumeration
  * cannot be confused with this complete snapshot. No expected zombie can fork
  * or change identity/group after that snapshot; the leader still pins PGID.
  */
 pid_t members[CB_OWNED_GROUP_PID_CAP]={0};
 int bytes=proc_listpids(PROC_PGRP_ONLY,(uint32_t)group,members,(int)sizeof(members));
 if(snapshot_bytes)*snapshot_bytes=bytes;
 if(bytes!=(int)(CB_OWNED_GROUP_MEMBERS*sizeof(pid_t)) || bytes>=(int)sizeof(members))return 0;
 unsigned seen=0;
 for(int n=0;n<CB_OWNED_GROUP_MEMBERS;n++){
  int index=-1;
  for(int i=0;i<CB_OWNED_GROUP_MEMBERS;i++)if(members[n]==pins[i].pid)index=i;
  if(index<0 || (seen&(1U<<index)))return 0;
  seen|=1U<<index;
 }
 return seen==((1U<<CB_OWNED_GROUP_MEMBERS)-1U);
}
static inline int cb_owned_group_all_zombies(pid_t group,const cb_owned_group_member *pins){
 return cb_owned_group_all_zombies_readback(group,pins,NULL);
}
#endif
