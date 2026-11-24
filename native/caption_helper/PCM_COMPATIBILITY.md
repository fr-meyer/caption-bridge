# Native PCM conversion compatibility

The declared Python range stays >=3.11, <3.14. Python 3.11/3.12 use their stdlib
audioop; Python 3.13 installs the exactly locked audioop-lts 0.2.2 port via a
Python-version dependency marker. The port exports the original audioop API and
retains the PSF license. It has no runtime dependencies. The dependency is not
installed on Python versions that still contain the stdlib module.

The conversion contract is unchanged: little-endian signed 16-bit PCM, explicit
native format, equal-weight stereo-to-mono and stateful ratecv to the existing
16 kHz mono ASR rate. There is no new DSP, resampler, model/default change, or
missing-converter fallback. Unsupported/missing conversion remains fail-closed.

Synthetic regression vectors fix byte lengths, SHA256s and ratecv state from the
previous CPython 3.11 implementation at seven input rates, for mono and stereo.
Whole-buffer, unequal frame-aligned chunks and cleared-state conversion must
agree. These are software semantics tests, not device or physical acceptance.

The lock change adds only this exact marked dependency, its verified registry
artifacts and the necessary Python 3.13 resolution split; existing package
versions/artifacts and the declared Python range are preserved. The package's
published source/license and tomono/ratecv implementation are reviewed as a
compatibility port, not represented as a new independently audited DSP library.
Actual Python 3.13 execution remains a hosted qualification requirement wherever
that runtime is not locally available; 3.11 parity alone does not prove it.
