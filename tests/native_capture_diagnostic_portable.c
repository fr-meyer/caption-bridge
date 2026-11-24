/* Portable synthetic helper unit test only; no macOS/HAL/process capture. */
#include <assert.h>
#include <stdio.h>
#include "native/caption_helper/capture_diagnostic.h"
int main(void){
 cb_capture_diagnostic d={.wait_status={-1,-1,-1}};
 int first[3]={18432,18432,-1},later[3]={18432,18432,18432};
 d.start=100;d.deadline=2000000100ULL;d.numer=1;d.denom=1;
 cb_capture_event_note(&d,CB_CAPTURE_EVENT_BUDGET);
 cb_capture_failure_note(&d,CB_CAPTURE_FAIL_ACTIVE_DEADLINE,0,2000000100ULL,first);
 cb_capture_failure_note(&d,CB_CAPTURE_FAIL_REAP_WAIT,3,3000000100ULL,later);
 assert(d.stage==CB_CAPTURE_FAIL_ACTIVE_DEADLINE && d.role==0);
 assert(d.wait_status[2]==-1 && d.when==2000000100ULL && d.deadline==2000000100ULL);
 uint64_t elapsed=0,window=0;
 assert(cb_capture_failure_timing(&d,&elapsed,&window));
 assert(elapsed==2000000000ULL && window==2000000000ULL);
 for(int i=0;i<100;i++)cb_capture_event_note(&d,CB_CAPTURE_EVENT_CLEANUP);
 assert(d.event_count==16);
 d.when=UINT64_MAX;d.numer=UINT32_MAX;
 assert(!cb_capture_failure_timing(&d,&elapsed,&window) && !elapsed && !window);
 d.numer=1;d.denom=0;
 assert(!cb_capture_failure_timing(&d,&elapsed,&window));
 cb_capture_diagnostic setup={.wait_status={-1,-1,-1}};
 int unspawned[3]={-1,-1,-1};
 cb_capture_failure_note(&setup,CB_CAPTURE_FAIL_STATE_SETUP,0,150,unspawned);
 unspawned[0]=18432; /* The first snapshot must not alias later observations. */
 setup.cleanup_errors|=CB_CAPTURE_CLEANUP_FD;
 cb_capture_failure_note(&setup,CB_CAPTURE_FAIL_FD_CLOSE,3,200,unspawned);
 assert(setup.stage==CB_CAPTURE_FAIL_STATE_SETUP && setup.role==0 && setup.when==150);
 assert(setup.wait_status[0]==-1 && setup.wait_status[1]==-1 && setup.wait_status[2]==-1);
 assert(setup.cleanup_errors==CB_CAPTURE_CLEANUP_FD);
 puts("{\"portable_helper_unit\":true,\"native_capture_executed\":false}");
 return 0;
}
