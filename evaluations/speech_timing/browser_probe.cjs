// Inert evaluation adapter. Attaching observes an existing player; it starts no media or IO.
(function(root){
  'use strict';
  const owners=new WeakMap(), LIMIT=128;
  const numeric=x=>typeof x==='number'&&Number.isFinite(x)&&x>=0&&x<=60000;
  class ChunkTimingProbe {
    constructor({clipId,epoch}){
      if(!Number.isInteger(clipId)||clipId<1||clipId>4||!Number.isInteger(epoch)||epoch<0||epoch>1e6)
        throw Error('public_fixture_identity_required');
      this.id=clipId;this.epoch=epoch;this.chunks=[];this.schedules=[];this.rejected=0;
      this.origin=null;this.ready=null;this.firstSchedule=null;this.previousEnd=null;
      this.lastIndex=-1;this.completed=false;this.attached=false;
      this.currentPayload=null;
      this.used=false;
    }
    matches(msg){return msg&&msg.clip_id===this.id&&msg.tts_epoch===this.epoch;}
    capture(fn){if(!this.attached)return;try{fn();}catch(_){this.rejected=Math.min(1000000,this.rejected+1);}}
    offset(at){const value=at-this.origin;if(!numeric(value))throw Error('invalid_timing');return value;}
    attach(player){
      if(this.used||owners.has(player)||typeof player.clock!=='function')throw Error('probe_attachment');
      const probe=this,receive=player.receive,context=player.o.context,complete=player.o.onComplete;
      this.attached=true;this.used=true;owners.set(player,this);
      const wrappers=new WeakMap();
      function tracedReceive(msg){
        const selected=probe.matches(msg)&&!!msg.data&&Number.isInteger(msg.chunk_index)&&msg.chunk_index>probe.lastIndex;
        let before=null;
        if(selected)probe.capture(()=>{
          before=player.clock();if(probe.origin===null)probe.origin=before;
          if(probe.chunks.length>=LIMIT||msg.chunk_index!==probe.chunks.length)throw Error('trace_limit_or_order');
          probe.offset(before);
        });
        const previousPayload=probe.currentPayload;
        if(selected)probe.currentPayload=msg.chunk_index;
        try {
          const result=receive.call(player,msg);
          if(selected&&before!==null)probe.capture(()=>{
            const after=player.clock(),elapsed=after-before;
            if(!numeric(elapsed)||probe.chunks.length>=LIMIT||msg.chunk_index!==probe.chunks.length)
              throw Error('invalid_timing');
            probe.chunks.push({chunk_index:msg.chunk_index,receive_offset_ms:probe.offset(before),receive_processing_ms:elapsed});
            probe.lastIndex=msg.chunk_index;
          });
          return result;
        } finally {probe.currentPayload=previousPayload;}
      }
      function tracedContext(){
        const audio=context.call(player.o);
        if(wrappers.has(audio))return wrappers.get(audio);
        const wrapper={get currentTime(){return audio.currentTime;},get destination(){return audio.destination;},
          resume(){return audio.resume();},createBuffer(...args){return audio.createBuffer(...args);},
          createBufferSource(){
            const node=audio.createBufferSource();
            probe.capture(()=>{
              const start=node.start;
              node.start=function(...args){
              let at=null,audioNow=null;
              if(probe.matches(player.active?.msg))probe.capture(()=>{at=player.clock();audioNow=audio.currentTime;});
              const result=start.apply(node,args);
              if(probe.matches(player.active?.msg))probe.capture(()=>{
                if(at===null||audioNow===null)throw Error('invalid_timing');
                const scheduled=args[0],duration=node.buffer.duration;
                const offset=probe.offset(at),ahead=(scheduled-audioNow)*1000;
                if(!numeric(ahead)||!numeric(duration*1000)||probe.schedules.length>=LIMIT)throw Error('invalid_schedule');
                const ready=player.active.readyAt;
                if(probe.ready===null&&typeof ready==='number'&&numeric(ready-probe.origin))probe.ready=ready;
                const gap=probe.previousEnd===null?0:Math.max(0,(scheduled-probe.previousEnd)*1000);
                if(!numeric(gap))throw Error('invalid_schedule');
                // EOS has no payload index. A synchronous receive may still be recording its row.
                const payloadCovered=probe.currentPayload===null?probe.lastIndex:probe.currentPayload;
                probe.schedules.push({schedule_index:probe.schedules.length,covered_through_chunk_index:payloadCovered,
                  submitted_offset_ms:offset,scheduled_ahead_ms:ahead,schedule_gap_ms:gap,duration_ms:duration*1000});
                if(probe.firstSchedule===null)probe.firstSchedule=at;
                probe.previousEnd=scheduled+duration;
              });
              return result;
              };
            });
            return node;
          }};
        wrappers.set(audio,wrapper);return wrapper;
      }
      function tracedComplete(msg,stats){
        if(probe.matches(msg))probe.capture(()=>{probe.completed=true;});
        return complete.call(player.o,msg,stats);
      }
      player.receive=tracedReceive;player.o.context=tracedContext;player.o.onComplete=tracedComplete;
      this.detach=()=>{
        if(!probe.attached)return;
        if(player.receive===tracedReceive)player.receive=receive;
        if(player.o.context===tracedContext)player.o.context=context;
        if(player.o.onComplete===tracedComplete)player.o.onComplete=complete;
        if(owners.get(player)===probe)owners.delete(player);
        probe.attached=false;
      };
      return this;
    }
    report(){
      return {schema_version:1,clock_domain:'browser_monotonic_offsets',audio_clock_domain:'audio_schedule_durations',
        completed:this.completed,rejected:this.rejected,chunks:this.chunks.map(x=>({...x})),
        schedules:this.schedules.map(x=>({...x})),
        ready_to_first_schedule_ms:this.ready===null||this.firstSchedule===null?null:this.firstSchedule-this.ready};
    }
  }
  root.ChunkTimingProbe=ChunkTimingProbe;
})(typeof module==='object'?module.exports:globalThis);
