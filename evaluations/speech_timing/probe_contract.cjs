// Finite generated-silence scheduling through the unchanged production PCM player.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const {ChunkTimingProbe}=require('./browser_probe.cjs');
const playerSource=fs.readFileSync(process.argv[2],'utf8');
const fixtures=JSON.parse(fs.readFileSync(process.argv[3],'utf8'));
const results=[];
async function model(source,{trace=true,resumeDelay=0,busyIndex=-1,observerFailure=false,readonlyStart=false}={}){
  let now=0,timer=0,resume=null,processing=0,starts=0,completes=0;
  const timers=new Map(),nodes=[],errors=[],stats=[];
  const context=vm.createContext({window:{},Float32Array,Uint8Array,DataView,Map,Set,Number,
    performance:{now:()=>1e6+now},
    atob:s=>{now+=processing;return Buffer.from(s,'base64').toString('latin1');},
    setTimeout:f=>{const id=++timer;timers.set(id,f);return id;},clearTimeout:id=>timers.delete(id)});
  vm.runInContext(playerSource,context,{timeout:500});
  const audio={get currentTime(){return 700+now/1000;},destination:{},
    resume:()=>resumeDelay?new Promise(resolve=>{resume={resolve,due:now+resumeDelay};}):Promise.resolve(),
    createBuffer:(_ch,n,rate)=>{const data=new Float32Array(n);return {duration:n/rate,getChannelData:()=>data};},
    createBufferSource:()=>{const node={ended:false,stopped:false,buffer:null,connect(){},disconnect(){},
      start(at){this.end=(at-700)*1000+this.buffer.duration*1000;},stop(){this.stopped=true;}};
      if(readonlyStart)Object.defineProperty(node,'start',{value:node.start,writable:false,configurable:false});
      nodes.push(node);return node;}};
  const player=new context.window.CaptionPcmPlayer({context:()=>audio,streaming:()=>true,canPlay:()=>true,
    clock:()=>1e6+now,onFirstChunk(){},onStart(){starts++;},onComplete(_msg,s){completes++;stats.push(s);},
    onError(_msg,e){errors.push(e);},onLocked(){errors.push('locked');}});
  const original={receive:player.receive,context:player.o.context,complete:player.o.onComplete};
  const probe=new ChunkTimingProbe({clipId:1,epoch:0});
  assert.equal(probe.origin,null,'construction performs no sampling');
  if(trace){probe.attach(player);assert.throws(()=>new ChunkTimingProbe({clipId:1,epoch:0}).attach(player));}
  if(observerFailure)probe.offset=()=>{throw Error('NEVER-COPY-PRIVATE-ERROR');};
  async function flush(){await Promise.resolve();await Promise.resolve();await Promise.resolve();}
  async function advance(target){
    assert(target>=now);
    for(let count=0;count<1000;count++){
      const live=nodes.filter(n=>!n.ended&&!n.stopped&&n.end<=target).sort((a,b)=>a.end-b.end);
      const node=live[0];
      if(resume&&resume.due<=target&&(!node||resume.due<=node.end)){
        now=Math.max(now,resume.due);const pending=resume;resume=null;pending.resolve();await flush();continue;
      }
      if(!node)break;
      now=Math.max(now,node.end);node.ended=true;if(node.onended)node.onended();await flush();
      assert(count<999);
    }
    now=target;await flush();
  }
  for(const row of source.chunks){
    await advance(Math.max(now,row.yield_offset_ms));
    processing=row.chunk_index===busyIndex?120:0;
    player.receive({seq:'NEVER-COPY-PRIVATE-SEQ',private_note:'NEVER-COPY-PRIVATE-TEXT',clip_id:1,tts_epoch:0,
      chunk_index:row.chunk_index,is_last:false,data:Buffer.alloc(row.samples*4).toString('base64')});
    processing=0;await flush();
  }
  const duration=source.chunks.reduce((n,r)=>n+r.samples/24,0);
  await advance(Math.max(now,duration));
  player.receive({seq:'NEVER-COPY-PRIVATE-SEQ',clip_id:1,tts_epoch:0,chunk_index:source.chunks.length,is_last:true,data:''});
  await flush();await advance(Math.max(now,...nodes.map(n=>n.end||0))+1);
  assert.equal(starts,1);assert.equal(completes,1);assert.equal(errors.length,0);
  assert.equal(player.bytes,0);assert.equal(player.clips.size,0);assert.equal(timers.size,0);
  const report=probe.report();
  assert(!JSON.stringify(report).includes('NEVER-COPY'));
  assert(report.chunks.length<=128&&report.schedules.length<=128);
  if(trace){
    probe.detach();assert.equal(player.receive,original.receive);assert.equal(player.o.context,original.context);
    assert.equal(player.o.onComplete,original.complete);
  }
  return {browser:report,production_stats:stats[0],starts,completes,remaining_bytes:player.bytes};
}
(async()=>{
  const idle={clock:()=>0,receive(){},o:{context(){throw Error('no context admission');},onComplete(){}}};
  const first=new ChunkTimingProbe({clipId:1,epoch:0}).attach(idle);first.detach();
  const second=new ChunkTimingProbe({clipId:2,epoch:0}).attach(idle);first.detach();
  assert.throws(()=>new ChunkTimingProbe({clipId:3,epoch:0}).attach(idle),'stale detach cannot erase current owner');
  second.detach();second.detach();
  assert.throws(()=>first.attach(idle),'probe instances cannot restart with stale trace state');
  for(const [name,source,settings] of [
    ['anchored',fixtures.normal,{}],['controller_stall',fixtures.stalled,{}],
    ['resume_delay',fixtures.normal,{resumeDelay:250}],['receive_work',fixtures.normal,{busyIndex:31}],
    ['EOS_short_tail',fixtures.short,{}],['observer_failure',fixtures.normal,{observerFailure:true}],
    ['readonly_start',fixtures.normal,{readonlyStart:true}],
  ]){
    const observed=await model(source,settings),without=await model(source,{...settings,trace:false,observerFailure:false});
    assert.deepEqual(JSON.parse(JSON.stringify(observed.production_stats)),
      JSON.parse(JSON.stringify(without.production_stats)),'instrumentation preserves production scheduling');
    assert.equal(observed.starts,without.starts);assert.equal(observed.completes,without.completes);
    if(!['observer_failure','readonly_start'].includes(name)){
      assert(observed.browser.completed);assert.equal(observed.browser.rejected,0);
      assert.equal(observed.browser.chunks.length,source.chunks.length);
      assert(observed.browser.schedules.every(s=>s.covered_through_chunk_index<source.chunks.length));
    }else assert(observed.browser.rejected>0);
    results.push({case:name,source,...observed,equivalent_without_probe:true});
  }
  console.log(JSON.stringify({passed:true,cases:results,attachment_lifecycle_checks:3,device:false,provider:false,network:false,
    real_browser:false,real_audio:false,clock_origins:'source arbitrary; browser1e6ms; audio700s'}));
})().catch(e=>{console.error(e.stack);process.exitCode=1;});
