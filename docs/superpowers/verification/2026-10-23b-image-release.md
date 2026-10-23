# 20261023b image build and offline acceptance

The user requested initial IMU commissioning calibration while standing, then changed delivery from SSH editing to a new image. Earlier regular-release publication preferences are retained. No board login, host-key change, card flash or physical motion occurred.

- File: `microduck-replica-20261023b.img.xz`, 712074020 bytes.
- SHA256: `72742592771652684d9b175e58f77a2b06d746f42fb5f57af099d1d44fe5cf3c`.
- Local distribution: `F:/chengshenzhilu/Robot/Microduck/复刻镜像-20261023b`, six canonical assets including checksum and licensing/model notes.
- Frozen source and release tag target: `320540ed510c0380b1d01b0cb8187f2c1e6d197e`.
- Public release: [20261023b](https://github.com/fanhao375/microduck-replica/releases/tag/microduck-replica-image-20261023b).

The feature was reviewed and integrated locally as fa326a0. The release cherry-picks only that change onto public master dae6684, excluding seven unrelated unpublished training commits and private untracked Studio notes. Software/image and software/studio match the tested feature tree exactly. A clean Git archive supplies the build; no developer key or unconfirmed-file override is enabled.

Inputs remain the previous verified base (SHA256 652dd54e70f49fd3633058d5ed9bbb2f63b435648da2346dfbfa60fcaa4c5bcc) and payload (ad4f5db6eef0f2d5315c2d04376ff12b2fa26d5a66fe1950ff13b1e353fad0ac). robotd remains fork source 4734cbb0aac075335ef206d6557d0b6a3eb9e0a9 and binary ead7f2f8aa5f24cb9883a976f7b23f8184d11ae26aa109afdaf5fe132660c1d1. The pinned runtime explicitly allows verify-imu while holding HOME; no runtime or helper rebuild was needed.

Validation:

- IMU/backend/calibration: 86 passed; helper redo: 21 passed.
- Final release browser regression: all 10 passed, 128.920 seconds, including original unloaded flow, standing capture/solve/verify, motion stance, persistent redo/cancel/recovery and failure rollback.
- Image shell syntax and GPT/MBR partition selftest passed. Actual output SHA256 and xz checks passed; independently decompressed partition and read-only ext4 checks passed.
- Read-only ro,noload inspection matched 337 Studio files, helper 0.7.0 and sudoers ownership/mode, 39 retained runtime/model hashes and 9 configured model references. It confirmed the settled-hold code and instructions in the installed image.
- Factory commissioning mode, 15 uncalibrated zeros, cleared machine identity, absent SSH host/developer keys, no saved WiFi/private state/active redo session and licensing files confirmed; visudo validation passed. Verification mounts and loops were released.
- Windows distribution was copied from the verified output and rechecked; asset sizes and all six hashes are recorded outside Git.

Physical acceptance is pending for this exact image. Commissioning HOME hold requires manual support. The camera remains a test source; actual camera/ToF operation and hardware-based automatic service startup are not established by this build. Prior-image hardware results do not validate the new image.

Published as a regular Latest release: draft=false, prerelease=false, latest API resolves to 20261023b, tag resolves to the frozen 320540ed source. All six uploaded asset sizes and SHA256 digests match the local distribution. Public download HEAD follows a redirect to HTTP 200 with Content-Length 712074020. Prior20261023 and20261021b pages retain their assets/licensing and link to the latest release. Independent release review found no P1/P2 publication blocker.
