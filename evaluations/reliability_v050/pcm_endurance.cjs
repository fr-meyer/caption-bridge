// Finite fake-clock/node cycles through production PCM player and epoch admission.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const pcmSource=fs.readFileSync(process.argv[2],'utf8');
const appSource=fs.readFileSync(process.argv[3],'utf8');
const start=appSource.indexOf('    function acceptTtsMessage(msg)');
const end=appSource.indexOf('    function handleTtsSpeaking(msg)',start);
assert(start>=0 && end>start);
let timerId=0, timerPeak=0, retiredPeak=0, started=0, completed=0, cancelled=0, staleDropped=0;
const timers=new Map();
const context=vm.createContext({window:{},Float32Array,Uint8Array,DataView,Map,Set,Number,
  performance:{now:()=>0},atob:s=>Buffer.from(s,'base64').toString('latin1'),
  setTimeout:fn=>{const id=++timerId;timers.set(id,fn);timerPeak=Math.max(timerPeak,timers.size);return id;},
  clearTimeout:id=>timers.delete(id)});
vm.runInContext(pcmSource,context);
vm.runInContext('var appState={ttsMuted:false,ttsCatchUpPending:false,currentTtsEpoch:0};'+appSource.slice(start,end),context);
const Player=context.window.CaptionPcmPlayer;
let deferred=false, resumeResolve=null;
const nodes=[];
const audio={currentTime:0,destination:{},resume:()=>deferred ? new Promise(r=>resumeResolve=r) : Promise.resolve(),
  createBuffer:(_channels,n)=>{const values=new Float32Array(n);return {getChannelData:()=>values};},
  createBufferSource:()=>{const node={connect(){},start(){},stop(){this.stopped=true;},disconnect(){}};nodes.push(node);return node;}};
const player=new Player({context:()=>audio,streaming:()=>false,canPlay:()=>true,onFirstChunk:()=>{},
  onStart:()=>started++,onComplete:()=>completed++,onError:()=>{throw Error('unexpected_pcm_error');},onLocked:()=>{throw Error('unexpected_lock');}});
const msg=(id,epoch,index,last,data)=>({seq:id,clip_id:id,tts_epoch:epoch,chunk_index:index,is_last:last,data});
const bytes=Buffer.alloc(32);
async function pump(){await Promise.resolve();await Promise.resolve();}
(async()=>{
  for(let i=0;i<512;i++){
    const epoch=Math.floor(i/16), id=i*2+1;
    context.appState.currentTtsEpoch=epoch;
    if(epoch>0){assert(!context.acceptTtsMessage(msg(id,epoch-1,0,true,'')));staleDropped++;}
    deferred=i%7===0;
    const first=msg(id,epoch,0,false,bytes.subarray(0,3).toString('base64'));
    player.receive(first);player.receive(first); // Duplicate chunk contributes no second bytes.
    player.receive(msg(id,epoch,1,true,bytes.subarray(3).toString('base64')));
    await pump();
    if(deferred){
      const before=nodes.length;
      player.cancelAll();deferred=false;resumeResolve();await pump();
      assert.equal(nodes.length,before,'late resume cannot revive cancelled clip');cancelled++;
      player.receive(msg(id+1,epoch,0,true,bytes.toString('base64')));await pump();
    }else if(i%11===0){
      const node=nodes.at(-1), late=node.onended, prior=completed;
      player.cancelAll();late();assert.equal(completed,prior,'late ended cannot complete cancelled epoch');cancelled++;
      player.receive(msg(id+1,epoch,0,true,bytes.toString('base64')));await pump();
    }
    const node=nodes.at(-1);
    assert.equal(typeof node.onended,'function');node.onended();
    const before=started;
    player.receive(msg(id+(i%7===0 || i%11===0 ? 1:0),epoch,0,true,bytes.toString('base64')));await pump();
    assert.equal(started,before,'terminal clip retransmission cannot start twice');
    assert.equal(player.bytes,0);assert.equal(player.clips.size,0);assert.equal(player.queue.length,0);assert.equal(player.active,null);
    assert.equal(timers.size,0);retiredPeak=Math.max(retiredPeak,player.retired.size);assert(retiredPeak<=256);
    nodes.length=0;
  }
  assert.equal(completed,512);assert(timerPeak<=1);
  process.stdout.write(JSON.stringify({passed:true,cycles:512,completed,cancelled,stale_epoch_frames_rejected:staleDropped,
    retired_peak:retiredPeak,pending_timer_peak:timerPeak,remaining_bytes:player.bytes,remaining_clips:player.clips.size,
    fake_clock_and_audio_nodes:true,real_audio:false,browser:false,network:false})+'\n');
})().catch(()=>{process.stderr.write('bounded_pcm_endurance_failed\n');process.exit(1);});
