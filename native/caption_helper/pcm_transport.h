#ifndef CAPTION_PCM_TRANSPORT_H
#define CAPTION_PCM_TRANSPORT_H
/* Private pipe only. One nonblocking atomic write, never wait/drop/retry audio.
 * <=496 bytes is below the POSIX minimum PIPE_BUF (512). No stderr/stdout PCM.
 */
#include <stdint.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/stat.h>
#define CB_PCM_PAYLOAD 448U
#define CB_PCM_HEADER 48U
static inline void cb_pcm_be(unsigned char *p,uint64_t n,unsigned bytes){
 for(unsigned i=0;i<bytes;i++){p[bytes-i-1]=(unsigned char)n;n>>=8;}
}
static inline int cb_pcm_pipe(int fd){
 struct stat st;int f=fcntl(fd,F_GETFL);
 return f>=0 && (f&O_ACCMODE)==O_WRONLY && (f&O_NONBLOCK) &&
  !fstat(fd,&st) && S_ISFIFO(st.st_mode) && fpathconf(fd,_PC_PIPE_BUF)>=512;
}
static inline int cb_pcm_packet(int fd,const unsigned char epoch[16],uint64_t sequence,
 uint32_t rate,uint16_t channels,uint16_t flags,uint32_t frames,const void *pcm){
 unsigned char packet[CB_PCM_HEADER+CB_PCM_PAYLOAD];
 uint32_t size=frames*(uint32_t)channels*2;
 if(channels<1 || channels>2 || rate<8000 || rate>192000 || flags>1 ||
    frames>CB_PCM_PAYLOAD/(channels*2U) || (flags?(frames!=0):(frames==0)) ||
    (size && !pcm))return -1;
 memcpy(packet,"CBPCM001",8);memcpy(packet+8,epoch,16);
 cb_pcm_be(packet+24,sequence,8);cb_pcm_be(packet+32,rate,4);
 cb_pcm_be(packet+36,channels,2);cb_pcm_be(packet+38,flags,2);
 cb_pcm_be(packet+40,frames,4);cb_pcm_be(packet+44,size,4);
 if(size)memcpy(packet+CB_PCM_HEADER,pcm,size);
 ssize_t n=write(fd,packet,CB_PCM_HEADER+size);
 /* EINTR, EAGAIN, partial writes and closed reader all fail closed. */
 memset(packet,0,sizeof(packet));
 return n==(ssize_t)(CB_PCM_HEADER+size)?0:-1;
}
#endif
