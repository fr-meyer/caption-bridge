/* Qualification-only app executable. No capture/audio implementation exists. */
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>
static void deadline(int sig) { (void)sig; _exit(72); }
static int number(const char *s, int min, int max) {
    char *end; errno=0; long n=strtol(s,&end,10);
    return errno || !*s || *end || n<min || n>max ? -1 : (int)n;
}
int main(int argc,char **argv) {
    /* The only interfaces are explicitly harmless qualification probes. */
    if(argc==3 && !strcmp(argv[1],"--probe-loopback")) {
        int port=number(argv[2],1,65535); if(port<0) return 64;
        signal(SIGALRM,deadline); alarm(2);
        int fd=socket(AF_INET,SOCK_STREAM,0), result=-1, error=errno;
        if(fd>=0) {
            struct sockaddr_in addr={0}; addr.sin_family=AF_INET;
            addr.sin_port=htons((unsigned short)port);
            addr.sin_addr.s_addr=htonl(INADDR_LOOPBACK);
            result=connect(fd,(struct sockaddr *)&addr,sizeof(addr));
            error=result<0?errno:0; close(fd);
        }
        printf("{\"schema\":1,\"probe\":\"loopback_connect\",\"result\":%d,\"errno\":%d}\n",result,error);
        return result<0 && (error==EPERM || error==EACCES)?0:70;
    }
    if(argc==3 && !strcmp(argv[1],"--probe-file")) {
        signal(SIGALRM,deadline); alarm(2);
        int fd=open(argv[2],O_RDONLY|O_NOFOLLOW), error=fd<0?errno:0;
        if(fd>=0) close(fd); /* Never read file contents. */
        printf("{\"schema\":1,\"probe\":\"file_open_no_read\",\"result\":%d,\"errno\":%d}\n",fd<0?-1:0,error);
        return fd<0 && (error==EPERM || error==EACCES)?0:70;
    }
    if(argc==3 && !strcmp(argv[1],"--probe-lifecycle")) {
        int seconds=number(argv[2],1,5); if(seconds<0) return 64;
        signal(SIGALRM,deadline); alarm((unsigned)seconds);
        struct pollfd fds[3];
        /* Independent controller + two guardian pipe read endpoints. */
        for(int i=0;i<3;i++) {
            if(fcntl(i,F_GETFD)<0) return 64;
            fds[i]=(struct pollfd){.fd=i,.events=POLLIN|POLLHUP|POLLERR};
        }
        for(;;) {
            int n=poll(fds,3,100);
            if(n<0 && errno!=EINTR) return 73;
            for(int i=0;i<3;i++) if(fds[i].revents) return 71;
        }
    }
    return 64; /* Includes --capture: permanently absent, no launch flag. */
}
