// Explicit public-fixture helper attachment. Never imported by the application.
(function(root){
  'use strict';
  const owners=new WeakMap();
  function installFixtureTiming(scope,{baseUrl}){
    const url=new URL(baseUrl);
    if(url.protocol!=='http:'||url.hostname!=='127.0.0.1'||!url.port||
      url.username||url.password||url.search||url.hash||!['','/'].includes(url.pathname)||
      scope.location.origin!==url.origin||owners.has(scope))throw Error('fixture_attachment_scope');
    const descriptor=Object.getOwnPropertyDescriptor(scope,'CaptionPcmPlayer');
    if(descriptor&&(!descriptor.configurable||descriptor.get||descriptor.set))
      throw Error('fixture_attachment_factory');
    const Probe=scope.ChunkTimingProbe;
    if(typeof Probe!=='function')throw Error('fixture_attachment_probe');
    let native=descriptor?.value,wrapped=native,player=null,current=null,disposed=false,failed=false,rejected=0;
    const reports={};
    function retire(){
      if(!current)return;
      reports[`0:${current.id}`]=current.report();current.detach();current=null;
    }
    function reject(){rejected=Math.min(1e6,rejected+1);failed=true;retire();player=null;}
    function select(candidate,msg){
      if(disposed||failed||msg?.tts_epoch!==0||!Number.isInteger(msg.clip_id)||msg.clip_id<1||msg.clip_id>4)
        return false;
      if(player&&player!==candidate){reject();return false;}
      if(current?.id===msg.clip_id)return false;
      if(reports[`0:${msg.clip_id}`])return false; // Completed retransmission stays retired.
      if((current&&!current.completed)||msg.clip_id!==Object.keys(reports).length+(current?2:1)){
        reject();return false;
      }
      try{
        retire();player=candidate;
        current=new Probe({clipId:msg.clip_id,epoch:0}).attach(candidate);
        return true;
      }catch(_){reject();return false;}
    }
    function wrap(value){
      native=value;
      if(typeof value!=='function'||typeof value.prototype?.receive!=='function'||
        typeof value.prototype?.begin!=='function'){reject();wrapped=value;return;}
      wrapped=class extends value {
        begin(msg){select(this,msg);return super.begin(msg);}
        receive(msg){
          // First receive can precede a speaking notice. Re-enter the newly
          // attached observer once so the first PCM payload is not lost.
          if(select(this,msg))return this.receive(msg);
          return super.receive(msg);
        }
      };
    }
    if(native!==undefined)wrap(native);
    const get=()=>wrapped;
    const set=value=>{
      if(native!==undefined){reject();native=value;wrapped=value;return;}
      wrap(value);
    };
    Object.defineProperty(scope,'CaptionPcmPlayer',{get,set,enumerable:descriptor?.enumerable??true,configurable:true});
    function snapshot(){
      const clips=Object.fromEntries(Object.entries(reports).map(([key,value])=>[key,structuredClone(value)]));
      if(current)clips[`0:${current.id}`]=current.report();
      return {schema_version:1,completed:!failed&&Object.keys(clips).length===4&&
        Object.values(clips).every(r=>r.completed&&r.rejected===0),rejected,clips};
    }
    const controller={snapshot,dispose(){
      if(disposed)return;disposed=true;retire();player=null;
      const actual=Object.getOwnPropertyDescriptor(scope,'CaptionPcmPlayer');
      if(actual?.get===get&&actual?.set===set){
        if(descriptor)Object.defineProperty(scope,'CaptionPcmPlayer',{...descriptor,value:native});
        else if(native===undefined)delete scope.CaptionPcmPlayer;
        else Object.defineProperty(scope,'CaptionPcmPlayer',{value:native,writable:true,enumerable:true,configurable:true});
      }
      if(owners.get(scope)===controller)owners.delete(scope);
    }};
    owners.set(scope,controller);return controller;
  }
  const api={installFixtureTiming};
  if(typeof module==='object'&&module.exports)module.exports=api;
  else root.CaptionFixtureTiming=api;
})(typeof window==='object'?window:globalThis);
