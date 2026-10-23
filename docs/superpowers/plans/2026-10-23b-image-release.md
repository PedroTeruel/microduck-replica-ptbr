# 20261023b image release

The user changed delivery from live SSH editing to rebuilding the image with the initial IMU commissioning stance fix. Retain the prior request for regular releases and preserve earlier image assets.

- [x] Complete focused IMU/helper and browser regression, then commit and integrate only this change.
- [x] Freeze committed software/image and software/studio in a clean Git archive. Build tag 20261023b using the previous verified base and payload, without keys or validation bypasses.
- [x] Verify the actual compressed image, independently decode and inspect the read-only filesystem; compare Studio/runtime/model files and confirm factory defaults, cleared identities and attribution.
- [x] Copy six distributable assets to a new local 复刻镜像-20261023b directory, with SHA256 and accurate acceptance notes.
- [x] Push source and publish the new regular image release after validation; update the latest download entry and preserve existing assets.
- [x] Verify publication and record exact source, image hash and acceptance limits. No board connection, host-key changes, flashing or physical motion.
