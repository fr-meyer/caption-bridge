/* Provider-free physical opener. Only the fixed signed CaptureHelper links this file.
 * No default-device query/change, output, file retention, sockets or provider SDKs.
 * This source is NOT physical qualification. Do not invoke without admitted custody.
 */
#include "capture_input.h"
#include "pcm_transport.h"
#include <CoreAudio/CoreAudio.h>
#include <mach/mach_time.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <poll.h>
#include <math.h>
#define CB_MAX_FRAMES 4096U
#define CB_CAPTURE_ERROR (-10100)
static int live(uint64_t stop_at) {
 struct pollfd p[4]={{.fd=5,.events=POLLIN|POLLHUP|POLLERR},{.fd=6,.events=POLLIN|POLLHUP|POLLERR},{.fd=7,.events=POLLIN|POLLHUP|POLLERR},{.fd=9,.events=POLLIN|POLLHUP|POLLERR}};
 return mach_continuous_time()<stop_at && poll(p,4,0)==0;
}
static OSStatus receive(void *context, AudioUnitRenderActionFlags *flags,
 const AudioTimeStamp *when, UInt32 bus, UInt32 frames, AudioBufferList *unused) {
 (void)bus;(void)unused;
 cb_capture_input *s=context;
 if(atomic_fetch_add_explicit(&s->callbacks,1,memory_order_acq_rel)!=0){
  atomic_store_explicit(&s->fault,CB_CAPTURE_ERROR,memory_order_release);
  atomic_fetch_sub_explicit(&s->callbacks,1,memory_order_acq_rel);return CB_CAPTURE_ERROR;
 }
 OSStatus result=noErr;
 if(atomic_load_explicit(&s->accepting,memory_order_acquire)) {
  if(frames==0 || frames>CB_MAX_FRAMES || mach_continuous_time()>=s->stop_at ||
     (s->pcm_fd>=0 && (s->pcm_frames>s->pcm_frame_limit || frames>s->pcm_frame_limit-s->pcm_frames)))result=CB_CAPTURE_ERROR;
  else {
   s->buffers->mNumberBuffers=s->buffer_count;
   for(UInt32 i=0;i<s->buffer_count;i++){
    s->buffers->mBuffers[i].mNumberChannels=s->channels_per_buffer;
    s->buffers->mBuffers[i].mData=(char *)s->scratch+i*s->buffer_bytes;
    s->buffers->mBuffers[i].mDataByteSize=frames*s->bytes_per_frame;
   }
   result=AudioUnitRender(s->unit,flags,when,1,frames,s->buffers);
   if(result==noErr && s->pcm_fd>=0){
    UInt32 offset=0,maximum=CB_PCM_PAYLOAD/(s->pcm_channels*2U);
    while(offset<frames){
     UInt32 count=frames-offset;if(count>maximum)count=maximum;
     if(!live(s->stop_at) || cb_pcm_packet(s->pcm_fd,s->epoch,s->pcm_sequence,
        s->pcm_rate,s->pcm_channels,0,count,(char *)s->scratch+offset*s->bytes_per_frame)){
      result=CB_CAPTURE_ERROR;break;
     }
     s->pcm_sequence++;s->pcm_frames+=count;offset+=count;
    }
   }
   /* Bounded callback scratch is cleared after the one private-pipe handoff. */
   memset(s->scratch,0,(size_t)s->buffer_count*s->buffer_bytes);
  }
  if(result!=noErr){
   atomic_store_explicit(&s->fault,(int)result,memory_order_release);
   atomic_store_explicit(&s->accepting,false,memory_order_release);
  }
 }
 atomic_fetch_sub_explicit(&s->callbacks,1,memory_order_acq_rel);
 return result;
}
int cb_capture_open(cb_capture_input *s,uint32_t device,uint64_t stop_at,int pcm_fd,const unsigned char epoch[16]) {
 if(s->attempted || !device || !stop_at || !live(stop_at))return CB_CAPTURE_ERROR;
 s->attempted=1;s->stop_at=stop_at;s->pcm_fd=pcm_fd;
 if(pcm_fd>=0){if(!epoch || !cb_pcm_pipe(pcm_fd))return CB_CAPTURE_ERROR;memcpy(s->epoch,epoch,16);}
 atomic_init(&s->accepting,false);atomic_init(&s->callbacks,0);atomic_init(&s->fault,0);
 AudioObjectPropertyAddress alive={kAudioDevicePropertyDeviceIsAlive,kAudioObjectPropertyScopeGlobal,kAudioObjectPropertyElementMain};
 UInt32 present=0,size=sizeof(present);OSStatus e=AudioObjectGetPropertyData(device,&alive,0,NULL,&size,&present);
 if(e || size!=sizeof(present) || !present)return e?e:CB_CAPTURE_ERROR;
 AudioComponentDescription d={kAudioUnitType_Output,kAudioUnitSubType_HALOutput,kAudioUnitManufacturer_Apple,0,0};
 AudioComponent component=AudioComponentFindNext(NULL,&d);if(!component)return CB_CAPTURE_ERROR;
 if((e=AudioComponentInstanceNew(component,&s->unit)))return e;
 UInt32 yes=1,no=0,maximum=CB_MAX_FRAMES;
 /* Disable output and choose EXACT explicit HAL id BEFORE initialization/open. */
 if((e=AudioUnitSetProperty(s->unit,kAudioOutputUnitProperty_EnableIO,kAudioUnitScope_Output,0,&no,sizeof(no))) ||
    (e=AudioUnitSetProperty(s->unit,kAudioOutputUnitProperty_EnableIO,kAudioUnitScope_Input,1,&yes,sizeof(yes))) ||
    (e=AudioUnitSetProperty(s->unit,kAudioOutputUnitProperty_CurrentDevice,kAudioUnitScope_Global,0,&device,sizeof(device))) ||
    (e=AudioUnitSetProperty(s->unit,kAudioUnitProperty_MaximumFramesPerSlice,kAudioUnitScope_Global,0,&maximum,sizeof(maximum))))return e;
 /* Query the exact selected device's existing client format. Do NOT change
  * hardware/default rates or assume an ASR mono format is a native device format.
  * Provider-free qualification discards samples, so conversion is not needed. */
 AudioStreamBasicDescription format={0};UInt32 format_size=sizeof(format);
 if((e=AudioUnitGetProperty(s->unit,kAudioUnitProperty_StreamFormat,kAudioUnitScope_Output,1,&format,&format_size)))return e;
 if(format_size!=sizeof(format) || format.mFormatID!=kAudioFormatLinearPCM ||
    !isfinite(format.mSampleRate) || format.mSampleRate<8000 || format.mSampleRate>192000 ||
    !format.mChannelsPerFrame || format.mChannelsPerFrame>32 || !format.mBytesPerFrame ||
    format.mBytesPerFrame>256 || format.mFramesPerPacket!=1 ||
    format.mBytesPerPacket!=format.mBytesPerFrame || !format.mBitsPerChannel || format.mBitsPerChannel>64)return CB_CAPTURE_ERROR;
 if(pcm_fd>=0){
  /* Client-side PCM conversion only. Never set device nominal/default rate.
   * Preserve selected native rate, support mono/stereo only, fail on any refusal.
   * Stateful ASR-rate conversion happens downstream, once per capture epoch. */
  if(format.mChannelsPerFrame>2 || floor(format.mSampleRate)!=format.mSampleRate)return CB_CAPTURE_ERROR;
  AudioStreamBasicDescription client={0};client.mSampleRate=format.mSampleRate;
  client.mFormatID=kAudioFormatLinearPCM;client.mFormatFlags=kAudioFormatFlagIsSignedInteger|kAudioFormatFlagIsPacked;
  client.mChannelsPerFrame=format.mChannelsPerFrame;client.mBitsPerChannel=16;
  client.mFramesPerPacket=1;client.mBytesPerFrame=2*client.mChannelsPerFrame;client.mBytesPerPacket=client.mBytesPerFrame;
  if((e=AudioUnitSetProperty(s->unit,kAudioUnitProperty_StreamFormat,kAudioUnitScope_Output,1,&client,sizeof(client))))return e;
  format_size=sizeof(format);
  if((e=AudioUnitGetProperty(s->unit,kAudioUnitProperty_StreamFormat,kAudioUnitScope_Output,1,&format,&format_size)))return e;
  if(format_size!=sizeof(format) || format.mFormatID!=client.mFormatID ||
     format.mFormatFlags!=client.mFormatFlags || format.mSampleRate!=client.mSampleRate ||
     format.mChannelsPerFrame!=client.mChannelsPerFrame || format.mBitsPerChannel!=16 ||
     format.mBytesPerFrame!=client.mBytesPerFrame || format.mFramesPerPacket!=1 ||
     format.mBytesPerPacket!=client.mBytesPerPacket)return CB_CAPTURE_ERROR;
  s->pcm_rate=(uint32_t)format.mSampleRate;s->pcm_channels=(uint16_t)format.mChannelsPerFrame;
  mach_timebase_info_data_t tb;if(mach_timebase_info(&tb)!=KERN_SUCCESS || !tb.numer || !tb.denom)return CB_CAPTURE_ERROR;
  uint64_t now=mach_continuous_time();if(now>=stop_at)return CB_CAPTURE_ERROR;
  s->pcm_frame_limit=(uint64_t)((long double)(stop_at-now)*tb.numer*s->pcm_rate/(tb.denom*1000000000.0L));
  if(!s->pcm_frame_limit || s->pcm_frame_limit>(uint64_t)s->pcm_rate*2)return CB_CAPTURE_ERROR;
 }
 s->buffer_count=(format.mFormatFlags&kAudioFormatFlagIsNonInterleaved)?format.mChannelsPerFrame:1;
 s->channels_per_buffer=s->buffer_count>1?1:format.mChannelsPerFrame;
 s->bytes_per_frame=format.mBytesPerFrame;s->buffer_bytes=CB_MAX_FRAMES*s->bytes_per_frame;
 if((uint64_t)s->buffer_count*s->buffer_bytes>1048576)return CB_CAPTURE_ERROR;
 s->buffers=calloc(1,sizeof(AudioBufferList)+(s->buffer_count-1)*sizeof(AudioBuffer));
 s->scratch=calloc(s->buffer_count,s->buffer_bytes);
 if(!s->buffers || !s->scratch)return CB_CAPTURE_ERROR;
 s->buffers->mNumberBuffers=s->buffer_count;
 for(UInt32 i=0;i<s->buffer_count;i++){
  s->buffers->mBuffers[i].mNumberChannels=s->channels_per_buffer;
  s->buffers->mBuffers[i].mDataByteSize=s->buffer_bytes;
  s->buffers->mBuffers[i].mData=(char *)s->scratch+i*s->buffer_bytes;
 }
 AURenderCallbackStruct callback={receive,s};
 if((e=AudioUnitSetProperty(s->unit,kAudioOutputUnitProperty_SetInputCallback,kAudioUnitScope_Global,0,&callback,sizeof(callback))))return e;
 if(!live(stop_at))return CB_CAPTURE_ERROR;
 if((e=AudioUnitInitialize(s->unit)))return e;s->initialized=1;
 if(!live(stop_at))return CB_CAPTURE_ERROR;
 atomic_store_explicit(&s->accepting,true,memory_order_release);
 s->started=1; /* Even a failed start gets an explicit checked Stop attempt. */
 if((e=AudioOutputUnitStart(s->unit)))return e;
 return noErr;
}
int cb_capture_close(cb_capture_input *s,uint64_t deadline) {
 atomic_store_explicit(&s->accepting,false,memory_order_release);
 int good=1;
 if(s->unit && s->started){if(AudioOutputUnitStop(s->unit)!=noErr)good=0;else s->started=0;}
 while(atomic_load_explicit(&s->callbacks,memory_order_acquire)){
  if(mach_continuous_time()>=deadline){good=0;break;}usleep(1000);
 }
 if(s->unit && s->initialized){if(AudioUnitUninitialize(s->unit)!=noErr)good=0;else s->initialized=0;}
 /* Never free callback context/storage while disposal is unknown. Process exit
  * retires the resource, but is NOT independent closure evidence to the journal. */
 if(s->unit){if(AudioComponentInstanceDispose(s->unit)!=noErr)good=0;else s->unit=NULL;}
 if(!s->unit && !atomic_load_explicit(&s->callbacks,memory_order_acquire)){
  if(s->scratch)memset(s->scratch,0,(size_t)s->buffer_count*s->buffer_bytes);
  free(s->scratch);s->scratch=NULL;free(s->buffers);s->buffers=NULL;
 }
 if(mach_continuous_time()>=deadline)good=0;
 return good?0:CB_CAPTURE_ERROR;
}
