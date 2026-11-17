#include "input_state.h"
#include <assert.h>
int main(void){
 assert(!cb_capture_admitted());
 for(unsigned mask=0;mask<16;mask++){
 cb_input s={0};assert(!cb_synthetic_input(&s));assert(cb_reserve(&s,10));
 assert(!cb_reserve(&s,10));assert(cb_synthetic_input(&s));assert(!cb_synthetic_input(&s));
 s.muted=false;assert(cb_route_change(&s));assert(s.muted);
 bool good=cb_stop(&s,(mask&8)?11:9,mask&1,mask&2,mask&4);
 assert(good==(mask==7));assert(s.muted);
 assert(s.phase==(good?CB_DISPOSED:CB_HOLD));
 assert(!cb_stop(&s,9,true,true,true));
 assert(s.phase==(good?CB_DISPOSED:CB_HOLD));
 }return 0;
}
