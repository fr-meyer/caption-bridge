/* No-audio only. Three exclusive writer capabilities and absolute continuous deadline. */
#include <mach/mach_time.h>
#include <poll.h>
#include <stdint.h>
#include <stdlib.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
int caption_supervised(const char *arg) {
    char *end; errno=0; unsigned long long deadline=strtoull(arg,&end,10);
    if(errno || !*arg || *end || !deadline) return 64;
    struct pollfd fds[3];
    for(int i=0;i<3;i++) {
        if(fcntl(i,F_GETFD)<0) return 64;
        fds[i]=(struct pollfd){.fd=i,.events=POLLIN|POLLHUP|POLLERR};
    }
    for(;;) {
        /* mach_continuous_time includes sleep. Never do work before checking deadline. */
        if(mach_continuous_time()>=deadline) return 72;
        int result=poll(fds,3,10);
        if(result<0 && errno!=EINTR) return 73;
        for(int i=0;i<3;i++) if(fds[i].revents) return 71;
    }
}
