# File-only preparation receipt, 2026-11-17

Executed with narrowly authorized private-temp-only Mac file processing.
No device/browser/controller/port/playback/capture/provider operation. Meeting
checkout and fallback unchanged. Capture consumption remains 0/600 seconds.

macOS 27.2 build 26B123; ffmpeg 7.1.1; Node 24.18.0. Existing Eddy English (US)
and Korean (South Korea) voices. Voice-specific asset versions not independently
exposed; record names plus OS build, do not invent versions. Recipe uses say -o,
170 words/minute, fixed public synthetic sentences; no voice installation.
ffmpeg file,pipe protocol whitelist, -nostdin, single threads, mono 24kHz f32le.

Private local files: /private/tmp/caption-offline-fixtures-freyq00t . Directory
0700. Synthetic binaries are NOT distributed or committed: reuse/redistribution
rights were not demonstrated. Keep use local pending license determination.
Only recipe, fixed text, aggregate measurements and hashes are in source.

PCM validation checked bounded size, finite [-1,1] samples and non-silent peak:
- English synthetic: 200460 samples, 8.3525s, peak .72663909,
  SHA256 9514bf87dab8f2447b77a6a8193c85e394ac7e22b8a8740878bd6863b1073736.
- Korean synthetic: 262776 samples, 10.949s, peak .59365833,
  SHA256 0168ba6cad49e54b8381cd80fd6bdfaa1ed64f26dae54262ca97de3d71a7278b.
- Public Korean greeting: original pinned 10376-byte Ogg hash verified before
  decoding. 40898 samples, 1.704083s, peak .26966527,
  PCM SHA256 d964a0f0e971d024d00c0d6016e1a82f47e6b9eff3e61270ee2b33a76a05395a.
  Original HappyMidnight CC BY-SA4.0 attribution applies to decoded derivative.

Existing WSOLA benchmark, 30 runs/rate/fixture, offline native Node only:
processing p50/p95 milliseconds at rates 1, 1.15, 1.3 respectively:
- English: .462/.942; 15.768/18.945; 12.312/14.701.
- Korean synthetic: .598/1.407; 17.378/21.544; 16.459/17.760.
- Public Korean: .107/.197; 2.250/4.418; 1.919/3.317.
No browser startup, acoustic latency, pitch/clarity or human-quality claim.
No English Commons retries after parent reported 429. Public English remains
unprovisioned; local synthetic English unblocks local-only processing, not a
public redistributable human corpus. Native browser/human tests still pending.

Longer synthetic clips improve sentence/pause preparation but cannot fit full
clip recording into the 2-second onset budget. Onset-only versus full-clip
continuity evidence must remain distinct; no new capture authority or reduced
acceptance. Actual runtime budget preflight remains mandatory.
