# 20261023 image release plan

> Execute this existing image pipeline locally. The user explicitly requested a new image and update/push after local Studio completion. No board connection or card flash is part of this release run.

**Goal:** Build a new downloadable image containing the committed Studio changes, validate the compressed deliverable, push the corresponding source, and publish a GitHub release marked Latest with accurate acceptance status.

**Inputs:** Pinned release branch from studio-dev `cc628b6`; existing known R1 base on F:; verified previous public payload `/root/microduck-build11/payload.tgz` in Ubuntu-22.04. Review runtime compatibility before selecting the final payload. WSL root filesystem is backed by E: with98GiB free, so use a fresh ext4 output directory, never an existing user build directory.

- [x] Integrate current remote master without losing Studio/training changes. Record exact committed source versions, input hashes, runtime provenance and release compatibility.
- [x] Run root image tests and shell syntax/selftest. Fix any real packaging incompatibility with a regression test before changing scripts.
- [x] Build with `IMAGE_TAG=20261023`, explicit committed `STUDIO_VERSION` and `IMAGE_VERSION`, no developer SSH key and no unconfirmed-file override. Use `/root/microduck-build-20261023/out`.
- [x] Test the delivered xz, decompress it independently, run read-only filesystem checks/mount inspection; verify installed Studio/helper/sudoers, runtime/model hashes, commissioning config, removed identities and credentials, licenses and no private notes/tests/dev caches.
- [x] Save distributable image/checksum/manifest/license/model notes under a new local `复刻镜像-20261023` folder. Record software/offline acceptance separately from pending physical board acceptance.
- [x] Push source without force; create new release tag only after validation. Publish a regular release marked Latest with the6 canonical assets and license notice, and verify uploaded sizes/digests/links. Preserve existing releases and their assets.
- [x] Integrate release records back to studio-dev and clean only this task's clean worktrees. Report actual image path, release link, checksum and pending hardware acceptance.

The user explicitly requested promotion from prerelease to a regular latest release. GitHub release classification and current download entries were updated; the image bytes and hardware acceptance evidence are unchanged.
