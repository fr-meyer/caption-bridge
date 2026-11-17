"""POSIX offline programme journal. No native admission profile exists."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from scripts.attended_acceptance import CAP_MS, hex_id


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode() + b'\n'


class Journal:
    """Exclusive inode lock held for the entire reservation and child lifetime.

    Directory must be coordinator-owned, local, private and never replaced/deleted.
    Missing journals are never auto-created during admission. Tampering/rollback is
    outside this local lock's trust boundary; retain an independent ledger anchor.
    """

    @staticmethod
    def initialize(path, programme):
        if not hex_id(programme, 64):
            raise ValueError('programme_id')
        path = Path(path)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            data = encoded({'programme': programme, 'schema': 1})
            if os.write(fd, data) != len(data):
                raise RuntimeError('journal_short_write')
            os.fsync(fd)
        finally:
            os.close(fd)
        parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)

    def __init__(self, path, programme):
        import fcntl
        import stat

        self.fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            st = os.fstat(self.fd)
            if (not stat.S_ISREG(st.st_mode) or st.st_nlink != 1
                    or st.st_mode & 0o077 or st.st_uid != os.geteuid()):
                raise RuntimeError('journal_permissions')
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.path = Path(path)
            self.identity = (st.st_dev, st.st_ino)
            self.programme = programme
            self.poisoned = False
            self._read()
        except BaseException:
            os.close(self.fd)
            raise

    def _read(self):
        os.lseek(self.fd, 0, os.SEEK_SET)
        raw = os.read(self.fd, 2_000_001)
        if len(raw) > 2_000_000 or not raw.endswith(b'\n'):
            raise RuntimeError('journal_incomplete')
        rows = [json.loads(line) for line in raw.splitlines()]
        if not rows or rows[0] != {'programme': self.programme, 'schema': 1}:
            raise RuntimeError('programme_mismatch')
        self.charged = 0
        self.active = None
        self.count = 0
        self.tail = hashlib.sha256(encoded(rows[0])).hexdigest()
        for row in rows[1:]:
            if not isinstance(row, dict) or row.get('previous') != self.tail:
                raise RuntimeError('journal_chain')
            if row.get('event') == 'reserve':
                if (self.active is not None or set(row) != {
                        'event', 'previous', 'sequence', 'ms', 'candidate', 'proof'}
                        or type(row['ms']) is not int or not 0 < row['ms'] <= CAP_MS
                        or type(row['sequence']) is not int
                        or row['sequence'] != self.count + 1
                        or not hex_id(row['candidate'], 40) or not hex_id(row['proof'], 64)):
                    raise RuntimeError('journal_reservation')
                self.active = row
                self.count += 1
                self.charged += row['ms']
            elif row.get('event') == 'close':
                if (self.active is None or set(row) != {
                        'event', 'previous', 'sequence', 'outcome'}
                        or row['sequence'] != self.active['sequence']
                        or row['outcome'] not in ('exit', 'stop', 'deadline', 'controller_eof',
                                                  'error')):
                    raise RuntimeError('journal_close')
                self.active = None
            else:
                raise RuntimeError('journal_event')
            self.tail = hashlib.sha256(encoded(row)).hexdigest()
        if self.charged > CAP_MS:
            raise RuntimeError('programme_cap')

    def _append(self, row):
        if self.poisoned:
            raise RuntimeError('journal_uncertain_write')
        self.poisoned = True
        st = os.stat(self.path, follow_symlinks=False)
        if (st.st_dev, st.st_ino) != self.identity:
            raise RuntimeError('journal_replaced')
        # Advisory locks cannot stop an accidental same-user writer. Detect
        # edits/rollback against this live coordinator's in-memory tail anchor.
        expected_tail = self.tail
        self._read()
        if self.tail != expected_tail:
            raise RuntimeError('journal_anchor_changed')
        row['previous'] = self.tail
        data = encoded(row)
        os.lseek(self.fd, 0, os.SEEK_END)
        if os.write(self.fd, data) != len(data):
            raise RuntimeError('journal_short_write')
        os.fsync(self.fd)
        self._read()
        self.poisoned = False

    def reserve(self, ms, candidate, proof):
        if self.active is not None:
            raise RuntimeError('unclosed_reservation')
        if (type(ms) is not int or not 0 < ms <= CAP_MS - self.charged
                or not hex_id(candidate, 40) or not hex_id(proof, 64)):
            raise ValueError('reservation_invalid')
        self._append({'event': 'reserve', 'sequence': self.count + 1,
                      'ms': ms, 'candidate': candidate, 'proof': proof})

    def finish(self, outcome):
        if self.active is None:
            raise RuntimeError('no_reservation')
        self._append({'event': 'close', 'sequence': self.active['sequence'], 'outcome': outcome})

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
