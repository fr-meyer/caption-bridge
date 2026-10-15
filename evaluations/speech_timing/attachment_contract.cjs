// Explicit offline composition: one unchanged player/context, four serial B/P/P/B clips.
// Input PCM stays in this process. Output is numeric evidence only; all nodes/clocks are fake.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {createHash}=require('node:crypto');
const probeSource=fs.readFileSync(require.resolve('./browser_probe.cjs'),'utf8');
const attachmentSource=fs.readFileSync(require.resolve('./browser_attachment.cjs'),'utf8');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
assert.equal(input.clips.length,4);
let now=0,timer=0,streaming=false,starts=0,completes=0;
const nodes=[],timers=new Map(),stats=[],reports={};
let scheduled=[];
const sandbox=vm.createContext({URL,structuredClone,Float32Array,Uint8Array,DataView,Map,Set,Number,
  performance:{now:()=>1e6+now},atob:s=>Buffer.from(s,'base64').toString('latin1'),
  setTimeout:f=>{timers.set(++timer,f);return timer;},clearTimeout:id=>timers.delete(id)});
vm.runInContext('window=globalThis;location={origin:"http://127.0.0.1:55555"}',sandbox);
vm.runInContext(probeSource,sandbox,{timeout:500});
vm.runInContext(attachmentSource,sandbox,{timeout:500});
const install=()=>vm.runInContext('CaptionFixtureTiming.installFixtureTiming(window,{baseUrl:"http://127.0.0.1:55555/"})',sandbox);
const bridge=install();assert.throws(install,'one attachment per document');
assert.equal(typeof sandbox.CaptionPcmPlayer,'undefined','installer does not construct a player');
vm.runInContext(fs.readFileSync(process.argv[2],'utf8'),sandbox,{timeout:500});
const native=Object.getPrototypeOf(sandbox.CaptionPcmPlayer);
let contextsUsed=0;
// Existing qualified PLAYER_OBSERVER wraps this same prototype after page load.
const receive=sandbox.CaptionPcmPlayer.prototype.receive;
sandbox.CaptionPcmPlayer.prototype.receive=function(...args){return receive.apply(this,args);};
const audio={get currentTime(){return 700+now/1000;},destination:{},resume:()=>Promise.resolve(),
  createBuffer:(_ch,n,rate)=>{const data=new Float32Array(n);
    return {duration:n/rate,getChannelData:()=>data,data};},
  createBufferSource:()=>{const node={ended:false,buffer:null,connect(){},disconnect(){},stop(){},
    start(at){this.end=(at-700)*1000+this.buffer.duration*1000;
      scheduled.push(Buffer.from(this.buffer.data.buffer));}};nodes.push(node);return node;}};
const player=new sandbox.window.CaptionPcmPlayer({context:()=>{contextsUsed++;return audio;},streaming:()=>streaming,canPlay:()=>true,
  clock:()=>1e6+now,onFirstChunk(){},onStart(){starts++;},onComplete(_msg,s){completes++;stats.push(s);},
  onError(){assert.fail('player error');},onLocked(){assert.fail('player locked');}});
assert.equal(contextsUsed,0,'construction samples no audio context');
async function flush(){await Promise.resolve();await Promise.resolve();await Promise.resolve();}
async function advance(target){
  assert(target>=now);
  for(let count=0;count<1000;count++){
    const node=nodes.filter(n=>!n.ended&&n.end<=target).sort((a,b)=>a.end-b.end)[0];
    if(!node)break;
    now=Math.max(now,node.end);node.ended=true;if(node.onended)node.onended();await flush();
    assert(count<999);
  }
  now=target;await flush();
}
(async()=>{
  for(const [index,clip] of input.clips.entries()){
    scheduled=[];
    assert.equal(clip.chunks.length,clip.source.chunks.length);
    assert(clip.chunks.length>0&&clip.chunks.length<=128);
    streaming=index===1||index===2;
    const anchor=now;
    if(index!==1)player.begin({seq:'excluded-caption',clip_id:index+1,tts_epoch:0});
    for(const [chunkIndex,data] of clip.chunks.entries()){
      const row=clip.source.chunks[chunkIndex];
      assert.equal(Buffer.from(data,'base64').length,row.samples*4);
      await advance(anchor+row.yield_offset_ms);
      player.receive({seq:'excluded-caption',clip_id:index+1,tts_epoch:0,chunk_index:chunkIndex,is_last:false,data});
      await flush();
    }
    const duration=clip.source.chunks.reduce((n,r)=>n+r.samples/24,0);
    await advance(anchor+duration);
    player.receive({seq:'excluded-caption',clip_id:index+1,tts_epoch:0,chunk_index:clip.chunks.length,is_last:true,data:''});
    await flush();await advance(Math.max(now,...nodes.map(n=>n.end||0))+1);
    assert.equal(starts,index+1);assert.equal(completes,index+1);
    assert.equal(player.bytes,0);assert.equal(player.clips.size,0);assert.equal(timers.size,0);
    const expected=Buffer.concat(clip.chunks.map(data=>Buffer.from(data,'base64')));
    assert.equal(createHash('sha256').update(Buffer.concat(scheduled)).digest('hex'),
      createHash('sha256').update(expected).digest('hex'),'scheduled buffers preserve fixture samples');
    const snapshot=bridge.snapshot(),report=snapshot.clips[`0:${index+1}`];
    assert(report.completed);assert.equal(report.rejected,0);
    assert.equal(report.chunks.length,clip.chunks.length,'first receive is included without speaking notice');
    reports[`0:${index+1}`]=report;
  }
  assert(bridge.snapshot().completed);bridge.dispose();bridge.dispose();
  assert.equal(sandbox.CaptionPcmPlayer,native,'dispose preserves the native factory');
  const later=install();bridge.dispose();assert.throws(install,'old dispose cannot release new owner');later.dispose();
  const idleOptions={context:()=>{throw Error('no audio admission');},canPlay:()=>false,streaming:()=>false,
    clock:()=>1e6+now,onFirstChunk(){},onStart(){},onComplete(){},onError(){},onLocked(){}};
  const order=install(),outOfOrder=new sandbox.CaptionPcmPlayer(idleOptions);
  outOfOrder.begin({seq:'excluded-caption',clip_id:2,tts_epoch:0});
  assert.equal(order.snapshot().rejected,1);
  assert(outOfOrder.clips.has('0:2'),'evidence refusal must not cancel application clips');
  outOfOrder.cancelAll();order.dispose();
  const multiple=install(),one=new sandbox.CaptionPcmPlayer(idleOptions),two=new sandbox.CaptionPcmPlayer(idleOptions);
  one.begin({clip_id:1,tts_epoch:0});two.begin({clip_id:1,tts_epoch:0});
  assert.equal(multiple.snapshot().rejected,1);
  assert(one.clips.has('0:1')&&two.clips.has('0:1'));
  one.cancelAll();two.cancelAll();multiple.dispose();
  const replaced=install(),replacement=class {};
  Object.defineProperty(sandbox,'CaptionPcmPlayer',{value:replacement,writable:true,configurable:true});
  replaced.dispose();assert.equal(sandbox.CaptionPcmPlayer,replacement,'dispose preserves a newer factory owner');
  Object.defineProperty(sandbox,'CaptionPcmPlayer',{value:native,writable:true,configurable:true});
  assert.equal(timers.size,0);
  for(const order of [[input.init_script,input.disable_script],[input.disable_script,input.init_script]]){
    const next=vm.createContext({URL,structuredClone});
    vm.runInContext('window=globalThis;location={origin:"http://127.0.0.1:55555"}',next);
    for(const script of order)vm.runInContext(script,next,{timeout:500});
    assert.equal(next.__fixtureTimingDisabled,true);
    assert.equal(Object.getOwnPropertyDescriptor(next,'CaptionPcmPlayer'),undefined,
      'cleanup keeps a later document unobserved in either init-script order');
    if(next.__fixtureChunkTiming)assert.equal(next.__fixtureChunkTiming.snapshot().completed,false);
  }
  assert(!JSON.stringify(reports).includes('excluded-caption'));
  console.log(JSON.stringify({clips:reports,starts,completes,context_count:1,
    modes:stats.map(s=>s.mode),remaining_bytes:player.bytes,
    lifecycle_negative_contracts:3,refresh_retirement_orders:2,
    real_audio:false,real_browser:false,provider:false,network:false}));
})().catch(e=>{console.error(e.stack);process.exitCode=1;});
