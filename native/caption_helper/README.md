# Native sandbox qualification helper

Qualification-only macOS APPL bundle with no capture implementation, microphone entitlement,
provider client, playback or admission switch. Every unknown invocation including --capture exits 64.
Build using existing tools: sh scripts/build_caption_helper.sh /absolute/new/output
Ad-hoc signing is local development evidence, not Developer ID distribution/notarization.

Supported mechanism: Apple's App Sandbox entitlement in a signed APPL bundle, not custom SBPL.
Official references consulted 2026-11-17:
- https://developer.apple.com/documentation/security/app-sandbox
- https://developer.apple.com/documentation/xcode/embedding-a-helper-tool-in-a-sandboxed-app
- https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.security.app-sandbox

This executable is the sandboxed app itself, not a helper inheriting an unsandboxed parent's sandbox.
No com.apple.security.inherit entitlement is used.

## Qualification API v1

--probe-loopback PORT: 127.0.0.1 only, JSON result/errno, exit 0 only for EPERM/EACCES.
Host first proves an owned listener accepts its control connection, then checks sandbox connection
was not accepted. No external network probe.

--probe-file PATH: O_RDONLY|O_NOFOLLOW open only, never reads content. Only use owned harmless
scratch canary outside app container. Exit 0 only for EPERM/EACCES.

--probe-lifecycle SECONDS: 1..5 second alarm. FD0 controller, FD1 guardian A, FD2 guardian B
must be independent pipe read ends. Any EOF/data/error exits 71; alarm exits 72.
No stdout/stderr output in this mode. Caller must close duplicate endpoints and reap children.

Budget lane contract: qualification facts only, never admission. Bind host/node, image SHA256,
source SHA256, extracted signed entitlements and CodeDirectory hash, probe arguments, actual
return/errno/timing, PID-reap checks, and listener closure. Naked booleans or receipt hashes
are not capture readiness. There is no spending interface.

## Residual gates

App Sandbox supplies standard OS/container allowances, not an exact per-file allowlist.
One denied canary does not prove all filesystem paths denied. EOF tests establish closure
mechanics, not death of independently identified controllers/guardians with descriptor custody.
Alarm is a process timer, not an external monotonic absolute-deadline guardian or suspend proof.
Production capture/audio closure, trusted guardians, fixed-role image/receipt trust, independent
review and later human readiness/capture authority remain unimplemented gates. Existing attended
preflight is deliberately untouched. No receipt from this helper grants launch authority.
