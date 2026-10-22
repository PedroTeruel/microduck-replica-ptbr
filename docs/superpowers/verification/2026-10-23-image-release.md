# 20261023 image: build and offline acceptance

User explicitly requested a new image and update/push. Built locally in Ubuntu-22.04 WSL, using a clean source archive at `03136c9a9b5149d1f66b7c4a62e82feb3e9be490`. No board connection or card flash occurred.

## Deliverable

- File: `microduck-replica-20261023.img.xz`
- Size: **712183896 bytes**
- SHA256: **2532dbffa46f087ccbc9dcb6fbe76663713ddf4bcf2510212809d5c8908dabab**
- Local distribution: `F:/chengshenzhilu/Robot/Microduck/复刻镜像-20261023`
- Release: [20261023 release](https://github.com/fanhao375/microduck-replica/releases/tag/microduck-replica-image-20261023)
- Six canonical assets: image, checksum, manifest, licenses, third-party components and model notes.

## Pinned inputs and source

- Base SHA256: `652dd54e70f49fd3633058d5ed9bbb2f63b435648da2346dfbfa60fcaa4c5bcc`.
- Payload SHA256: `ad4f5db6eef0f2d5315c2d04376ff12b2fa26d5a66fe1950ff13b1e353fad0ac`, identical to public20261021b; all71 internal file hashes checked.
- robotd SHA256: `ead7f2f8aa5f24cb9883a976f7b23f8184d11ae26aa109afdaf5fe132660c1d1`; fork source `4734cbb0aac075335ef206d6557d0b6a3eb9e0a9`, freshly confirmed on its public branch.
- Source includes the Studio changes, concurrent committed training work and current public servo tooling. No private untracked Studio notes are included.
- Initial archive build was correctly stopped by the CRLF guard. `run.py` lacked an explicit LF attribute under Windows archive conversion. Commit03136c9 adds that rule; the rebuilt archive's entrypoint byte check passes. No guard bypass was used.

## Verification

- Studio regression:1009 tests,4 skipped, remaining tests passed. Final IMU/helper targeted tests:165 passed, including destination integration. All9 original/redo browser scenarios passed.
- Image pipeline under WSL root:117 passed, plus shell syntax and GPT/MBR partition selftests.
- Public servo tooling after merging remote master:119 passed using isolated test dependencies.
- Delivered xz passes its checksum and `xz -t`; its independently decompressed image passes `sfdisk --verify` and read-only `e2fsck -fn`.
- Read-only `ro,noload` mount verifies337 installed Studio files against the frozen source, helper0.7.0 and sudoers,39 retained payload file hashes,9 configured model references, default commissioning mode and15 uncalibrated servo zeros.
- Empty machine identity; no SSH host/developer keys, saved WiFi profiles, private Studio state or active IMU recovery session. Sudoers passes `visudo -cf`.
- Final build sanitation scan passed without `DEV_AUTHORIZED_KEY` or `ALLOW_UNCONFIRMED`; required model attribution remains in the model-license notes.
- Independent read-only artifact review found no P1/P2 blocker;36 payload metadata text files showed no detected secrets or personal identity paths.
- Runtime/source and all10 model contracts were inspected for Studio API compatibility. This is not ARM inference or hardware acceptance.

## Acceptance limits

Published as a regular release and marked Latest at the user’s explicit request. This exact new image has not completed a fresh-card physical setup/standing/walking test. Camera source is `test`; the base contains a ToF service unit, which does not establish working hardware. Hardware-based automatic camera/ToF service startup remains unfinished. Existing20261021b physical results do not validate this image's new features.

Published as a regular public release at the link above. GitHub reports all six assets `uploaded`; every remote asset size and SHA256 digest matches the local distribution. Release tag targets exact build source03136c9. Public-text review found no publishing blocker. Existing20261021b assets and release remain intact.

Unauthenticated HEAD requests to the release page and image download both return200; image Content-Length is712183896. Public master and local studio-dev include release documentationd34919a. This task's two clean implementation/release worktrees were removed; concurrent training checkouts and private untracked Studio notes were preserved.

Promotion verification: GitHub reports draft=false, prerelease=false, and the latest-release API resolves to microduck-replica-image-20261023. All six asset IDs, sizes and digests are unchanged. The old20261021b page links to the new latest version.
