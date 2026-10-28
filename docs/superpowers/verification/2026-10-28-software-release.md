# Software 2026.10.28 release verification

This release supplies the existing-card software update and an explicitly
confirmed optional native update. No new SD image, physical deployment, motor
operation, Qinmo hardware acceptance or walking acceptance was performed.

## Frozen artifacts and source

- Software tag: `microduck-software-v2026.10.28`, frozen commit
  `53c0dc96dbbdd127deeb2322cc6e551e5fd8f61d`.
- Approved product implementation: `280fed1371d18d3464a4d3e18cd84f29dc852fd3`.
  Upstream documentation was merged without discarding other writers' changes.
- Native source: `fanhao375/Microduck-kissqy`, public branch
  `hd1910-v167-qinmo-20261027`, commit
  `bdf494ab3fd74898b5159419fbffe87113b4097c`.
- Native AArch64 ELF: 5,564,672 bytes,
  SHA256 `febf44e2e5d4e573f4513f25a1ae6480b976c3988dd3d5e7cdfcf84d2a2d5063`.
- Standalone signed software package: 8,069,120 bytes,
  SHA256 `f6bd4dfb45e3307b588ca58a9ecc3a4ba7e586bc83fa28c3d86a8a456602d85f`.
- Bootstrap: 60,200,730 bytes,
  SHA256 `6fd12f50137c8ec3b77a21c9f7480c890302818d3f3b6bcdaeb9737a182de324`.

Independent final artifact review compared all 352 whitelisted runtime files
against frozen Git and the approved product. All match byte for byte. All 354
suite hashes, including the two fixed native payload files, match. Outer and
suite source revisions both identify the frozen commit. Both minisign signatures
verify with the previous release public key; the trust root was not replaced.

The bootstrap contains the exact standalone package, original ARM updater and
original public key. Its 320 regular files all match its inventory, with exactly
304 pinned external resource files. Inspection found no publisher private key,
SSH identity or private account files.

## Compatibility and execution boundaries

The actual 20261027 ARM updater was executed under QEMU with the actual previous
bootstrap and signed package, then this final package. Dry run, wrong-hash and
wrong-signature rejection, install, rollback, health-failure automatic rollback,
and durable recovery after process death pass. The real installed helper's
root-owned managed-release hash-bound module loader also accepts the native
module and fixed payload. Stage 1 restarts only Studio and voice and leaves the
native target unchanged. These are filesystem/service fixtures, not robot tests.

Actual systemd 249 condition evaluation permits controllers only when the
persistent guard is absent or the matching boot-local restoration permit is
present; the interrupted guarded state refuses controller startup. No live
service was started by that check.

The frozen native ARM binary passed all five read-only PTY cases: live, frozen,
not-ready, invalid quaternion and invalid checksum. The peer implements the
documented Qinmo protocol 1.2; it is not vendor MCU firmware. All motor writes
were prohibited. Qinmo remains a manual profile and does not alter default
identification of existing boards.

## Test results and test maintenance

Task 1 native/helper scope: Windows 281 tests, 6 platform skips, pass; Linux 281,
no skips, pass. Task 2 Studio scope: Windows 522 tests, 7 platform skips, pass;
Linux 342, no skips, pass. Voice discovery: Windows 160, 18 platform skips, pass;
Linux 160, no skips, pass. Canonical checkout update/Qinmo smoke: 57 tests,
2 platform skips, pass. The logs contain existing Windows AF_UNIX background
errors and ResourceWarnings; this is not a warning-free claim.

The first broad Studio discovery ran 1,332 tests with 11 skips and one failure:
the WebSocket test assumed the command acknowledgment preceded an independently
published servo snapshot. Commit `fe0eb4a` waits for both under the original
timeout. A forced real-WebSocket snapshot-before-acknowledgment ordering fails
the old predicate and passes the new predicate; the focused tests in both
classes, 60 repetitions and Linux focused checks pass. Root's fresh four focused
tests also pass.

The subsequent core discovery ran 1,334 tests in 311.240 seconds with 81 skips
and one different failure in the unchanged stale-motion-frame test. That test
expected its worker to reach a rate-limit wait although the wait applies only
inside a 40 ms interval. Advancing the fixture source clock by 50 ms reproduces
the failure. Post-freeze test-only commit
`32e1285bbd0a23859c578ee8c72bbf4610e3f4a5` freezes the PadOps fixture clock before
seeding the frame and guarantees worker release/join and exception checks. Both
normal and delayed-source-clock repetitions pass 100/100, and the full motion
module passes 86/86. The production code, immutable release tag and package were
not changed by this test maintenance. The test is excluded by the runtime
whitelist, so the reviewed 352 runtime files remain identical.

Final core rerun on test-maintenance revision `32e1285`: 1,334 tests in
316.089 seconds, 81 platform/browser skips, **pass**. This used `STUDIO_E2E=0`;
it does not claim all automatic browser tests were repeated. Root's fresh
targeted browser run is recorded separately below.

Fresh Edge update and IMU tests pass, 2 tests in 36.147 seconds. All 20 update
behavior flags are true; browser exceptions are empty and widths 1440, 390 and
320 have no horizontal overflow. The browser exercises the real coordinator
with the old signed 20261027 fixture and explicit fake privileged services;
actual ARM execution is checked separately above. Native confirmations,
reconnect, failure/recovery and absent/unsupported payload are exercised. Merely
viewing the page makes no native mutation, and Space retains the actual relax
path. Fresh desktop and mobile screenshots were inspected.

For the separate hotspot question, firstboot tests on Linux pass 35/35 and
network-guard tests on Windows pass 28/28. Windows firstboot tests could not run
six shell-dependent cases without sh; the Linux run covers all 35. Hotspot
startup has no servo-ID dependency. This does not establish Zero 3E image or
external Wi-Fi adapter compatibility.

## Publication and local preservation

The formal release has exactly 11 expected assets. Every GitHub server size and
SHA256 digest matches the final local inventory. The frozen old client downloads
the public package anonymously, checks its outer source revision and verifies
both signatures with the old public key. The old image remains Latest.

The initial anonymous catalog request returned GitHub HTTP 403 with
`X-RateLimit-Remaining: 0` and reset Unix time `1793151514`. The initial report
separately records a real-public-catalog parser check through the connected
maintainer CLI and a successful anonymous package download; it does not present
that parser fallback as anonymous catalog success.

After the reset, the fresh end-to-end check completed at 2026-10-28 10:38:53 JST:
the frozen 20261027 client anonymously fetched the actual public catalog,
selected `2026.10.28`, downloaded the complete package, checked its SHA256 and
source revision, and verified both signatures with its original public key.
The final report confirms all 11 server asset digests and the old image's
Latest status. No catalog fallback was needed in that final run. The documented
offline upload path remains available during GitHub rate limits or outages.

Local private documents and the existing training tree are preserved. The
canonical checkout is integrated separately so its private training ancestry
is not pushed into the public release branch.

Local evidence is under `artifacts/software-release-20261028/`, including
`frozen-build.json`, `publication-assets.json`,
`independent-final-package-review.json`, `delivery-inspection.json`,
`legacy-engine-final.json`, `systemd-controller-final.json`,
`root-final-e2e.log`, `root-final-e2e/`, `root-full-studio-280fed.log`,
`root-final-core.log`, `root-final-core-32e1285.log`, `root-ws-final.log`,
`motion-wait-*.log`, `canonical-integration.json`,
`public-publication-first-rate-limited.json` and
`public-publication-verification.json`.

Physical old-card upgrade, power-loss restoration, Qinmo board and walking
acceptance remain pending. Music following and free-form spoken AI conversation
are not delivered by this release. User steps are in
[the existing-card guide](../../软件更新与Qinmo使用说明-20261028.md).
