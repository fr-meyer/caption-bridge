"""Exception-safe ownership for harmless qualification children and descriptors."""
import errno
import os
import signal
import subprocess
import time


class OwnedResources:
    def __init__(self):
        self.fds = set()
        self.roles = []
        self.children = []

    def __enter__(self):
        return self

    def pipe(self):
        pair = os.pipe()
        self.fds.update(pair)
        for fd in pair:
            os.set_inheritable(fd, False)
        return pair

    def close(self, fd):
        if fd not in self.fds:
            return
        try:
            os.close(fd)
        except OSError as exc:
            if exc.errno != errno.EBADF:
                raise
        self.fds.discard(fd)

    def own_role(self, pid):
        if pid <= 0:
            raise ValueError('only a successfully forked direct child can be owned')
        self.roles.append(pid)
        return pid

    def spawn(self, *args, **kwargs):
        child = subprocess.Popen(*args, **kwargs)
        self.children.append(child)
        return child

    @staticmethod
    def _reap_role(pid):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + 1
        while True:
            try:
                reaped, _ = os.waitpid(pid, os.WNOHANG)
                if reaped == pid:
                    return
            except ChildProcessError:
                return
            except InterruptedError:
                pass
            if time.monotonic() >= deadline:
                raise TimeoutError('owned role could not be reaped')
            time.sleep(.005)

    def __exit__(self, exc_type, exc, tb):
        errors = []
        # Closing lifelines first permits natural shutdown, but never replaces reaping.
        for fd in tuple(self.fds):
            try:
                self.close(fd)
            except OSError as error:
                errors.append(type(error).__name__)
        for child in self.children:
            try:
                if child.poll() is None:
                    child.kill()
                child.wait(timeout=1)
            except (OSError, subprocess.TimeoutExpired) as error:
                errors.append(type(error).__name__)
        for pid in self.roles:
            try:
                self._reap_role(pid)
            except (OSError, TimeoutError) as error:
                errors.append(type(error).__name__)
        if errors:
            raise RuntimeError('qualification cleanup unverified: ' + ','.join(errors)) from exc
        return False
