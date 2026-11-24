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
#include <errno.h>
#include <unistd.h>
#include <string.h>
#define CB_OWNED_GROUP_MEMBERS 3
/* One spare PID is essential: a full/truncated list can NEVER equal 3 entries. */
#define CB_OWNED_GROUP_PID_CAP (CB_OWNED_GROUP_MEMBERS+1)
typedef struct {
 pid_t pid,parent,group;uid_t ruid,euid;
 struct timeval birth;int enrolled;
} cb_owned_group_member;
/* Diagnostic-only distinctions. No failed predicate is relaxed or retried. */
enum cb_owned_group_pin_result {
 CB_PIN_OK=0,CB_PIN_ARGUMENT,CB_PIN_WAIT,CB_PIN_TERMINAL,
 CB_PIN_METADATA_QUERY,CB_PIN_METADATA_SIZE,CB_PIN_METADATA_PID,CB_PIN_ZOMBIE,
 CB_PIN_PARENT,CB_PIN_GROUP,CB_PIN_RUID,CB_PIN_EUID,CB_PIN_BIRTH_SEC,CB_PIN_BIRTH_USEC
};
static inline enum cb_owned_group_pin_result cb_owned_group_metadata_detail(
 pid_t pid,struct kinfo_proc *row,int *system_errno){
 int mib[]={CTL_KERN,KERN_PROC,KERN_PROC_PID,pid};size_t bytes=sizeof(*row);
 if(system_errno)*system_errno=0;
 memset(row,0,sizeof(*row));
 if(sysctl(mib,4,row,&bytes,NULL,0)){
  if(system_errno)*system_errno=errno;
  return CB_PIN_METADATA_QUERY;
 }
 if(bytes!=sizeof(*row))return CB_PIN_METADATA_SIZE;
 if(row->kp_proc.p_pid!=pid)return CB_PIN_METADATA_PID;
 return CB_PIN_OK;
}
static inline int cb_owned_group_metadata(pid_t pid,struct kinfo_proc *row){
 return cb_owned_group_metadata_detail(pid,row,NULL)==CB_PIN_OK;
}
static inline enum cb_owned_group_pin_result cb_owned_group_pin_detail(
 cb_owned_group_member *pin,pid_t pid,pid_t group,int *system_errno){
 if(system_errno)*system_errno=0;
 if(!pin)return CB_PIN_ARGUMENT;
 memset(pin,0,sizeof(*pin));
 if(pid<=1 || group<=1)return CB_PIN_ARGUMENT;
 siginfo_t info;memset(&info,0,sizeof(info));
 if(waitid(P_PID,(id_t)pid,&info,WEXITED|WNOHANG|WNOWAIT)){
  if(system_errno)*system_errno=errno;
  return CB_PIN_WAIT;
 }
 if(info.si_pid)return CB_PIN_TERMINAL;
 struct kinfo_proc row;
 enum cb_owned_group_pin_result result=cb_owned_group_metadata_detail(pid,&row,system_errno);
 if(result!=CB_PIN_OK)return result;
 if(row.kp_proc.p_stat==SZOMB)return CB_PIN_ZOMBIE;
 if(row.kp_eproc.e_ppid!=getpid())return CB_PIN_PARENT;
 if(row.kp_eproc.e_pgid!=group)return CB_PIN_GROUP;
 if(row.kp_eproc.e_pcred.p_ruid!=getuid())return CB_PIN_RUID;
 if(row.kp_eproc.e_ucred.cr_uid!=geteuid())return CB_PIN_EUID;
 if(row.kp_proc.p_starttime.tv_sec<=0)return CB_PIN_BIRTH_SEC;
 if(row.kp_proc.p_starttime.tv_usec<0 || row.kp_proc.p_starttime.tv_usec>=1000000)return CB_PIN_BIRTH_USEC;
 pin->pid=pid;pin->parent=getpid();pin->group=group;pin->ruid=getuid();pin->euid=geteuid();
 pin->birth=row.kp_proc.p_starttime;pin->enrolled=1;return CB_PIN_OK;
}
static inline int cb_owned_group_pin(cb_owned_group_member *pin,pid_t pid,pid_t group){
 return cb_owned_group_pin_detail(pin,pid,group,NULL)==CB_PIN_OK;
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
