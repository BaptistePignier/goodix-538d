# AGENTS.md — goodix-538d

Audience: coding agents (Claude Code, Codex, etc.). Dense reference, not prose.
Humans: read `README.md` (English) or `README.fr.md` (French).
The repository owner talks in French; repository files, code comments and
commit messages are in English.

## 1. Project state (as of 2026-10-20)

- Goal: make the Goodix `27c6:538d` match-on-host USB fingerprint reader of a
  Dell Inspiron 3501 usable on Ubuntu 26.04 (no Windows on the machine).
- Status: WORKING with template learning. Real tests: 84–85% of natural
  presses recognized, 18/18 through fprintd, 0/40 real impostor presses
  accepted, 0/80 offline. Results come from same-day sessions only;
  multi-day behavior is unverified.
- Installed on the owner's machine: libfprint + patched fprintd in
  `/opt/fprint-538d`, systemd override
  `/etc/systemd/system/fprintd.service.d/goodix-538d.conf`, print of the right
  index in `/var/lib/fprint/<user>/goodixtls53xd/0/7`. GNOME lock/login screen
  uses it via Ubuntu's `gdm-fingerprint` PAM file. `sudo`/polkit do NOT use it
  (owner declined; Ubuntu's `pam-auth-update` fprintd profile is disabled and
  has `max-tries=1`).

## 2. Hard rules

1. Never write to the sensor flash. Forbidden USB commands: `0xA4` (erase
   app), `0xE0` (write PSK), `0xF0` (write firmware), `0xF4` (check/commit
   firmware). Never run goodix-fp-dump's `run_538d.py` / `driver_53xd.main()`
   (it erases the app if firmware or PSK differ). Read-only state check:
   `check_538d_ro.py` (allowlist `0x00 0xA8 0xE4 0xA6`).
2. Biometric data: never commit or publish images or prints (`*.pgm`,
   `*.variant`, `dataset*/`, `fp-test/`, driver dumps). They are gitignored.
   Delete collected datasets after analysis (they are root-owned: `pkexec rm`).
3. Do not overwrite Ubuntu package files. Install under `/opt/fprint-538d`;
   fprintd's `meson install` also writes `/usr/share/dbus-1/*` and
   `/usr/share/polkit-1/*`: do not copy those (Ubuntu's are compatible).
4. PAM / authentication changes require explicit owner approval, a rollback
   plan, and an open root shell during the test.
5. Ask before installing packages system-wide or changing systemd/PAM.

## 3. Hardware facts (this unit)

| Item | Value |
|---|---|
| USB | `27c6:538d`, interface 0, EP IN `0x83`, EP OUT `0x01`, bus 1 |
| Firmware | `GF5298_GM168SEC_APP_13016` (required by the driver) |
| Bootloader (IAP) name | `MILAN_GM168SEC_IAP_10007` (expected by goodix-fp-dump) |
| PSK | 32 zero bytes; PSK hash read with flags `0xbb020001` = `sha256(0^32)` = `66687aad…5f2925` |
| TLS | TLS-PSK with the zero key: transport is not confidential |
| Raw frame | 7680 bytes → 64×80 pixels, 12 bit (6 bytes per 4 pixels), `decode_frame()` |
| Final image | 60×76, 8 bit (2-pixel border cropped) |
| Image read payload | `{0x41, 0x03, dac0, dac1, dac2, dac3}`, LE16 each; dac = `otp[26]`, `otp[26]-6`, `otp[45]`, `otp[45]-4`, plus the current DAC offset |
| Before each read | FDT mode cmd `0x36` (OTP bytes `otp[33], otp[41..43]` at payload indexes 2,4,6,8), then register `0x022c` = `0x0305` (bytes `05 03`) |
| DAC response | linear, uniform: −72.9 counts per DAC step (72.2–73.4 per pixel) |
| Finger-free level | OTP DAC (offset 0): saturated 4095; +20: median ~3770; +40: ~2320; +60: ~860; +80: 0 |
| Finger contact gap | mean abs diff vs finger-free frame at +20: ~2600–2900 for a full press |
| USB power | runtime autosuspend after 2 s (`/usr/lib/udev/hwdb.d/60-autosuspend-libfprint-2.hwdb` lists `538D`) |
| Ridge content | 4–5 nearly parallel ridges per image; SIFT keypoints ~25–90 per image |

## 4. Repositories and layout

Expected local layout (owner's machine: `~/dev/goodix-538d`):

```
goodix-538d/          this repo (docs, patches, tools)  main
  goodix-fp-dump/     clone of goodix-fp-linux-dev/goodix-fp-dump (ignored)
  libfprint-53xd/     infinytum/libfprint, branch goodix53xd (ignored)
  libfprint-sigfm/    goodix-fp-linux-dev/libfprint sigfm + work, branch goodix53xd (ignored)
  fprintd/            fprintd v1.94.5 + patch, branch goodix53xd-learning (ignored)
  .venv/              python venv: pyusb, numpy, opencv-python-headless (ignored)
```

| Repo | Branch | Base | Head |
|---|---|---|---|
| github.com/BaptistePignier/goodix-538d | `main` | — | docs/tools |
| github.com/BaptistePignier/libfprint (fork of goodix-fp-linux-dev/libfprint) | `goodix53xd-sigfm` | `07306bb` (sigfm, libfprint 1.94.5) | `d2a29e2` — CURRENT WORK |
| same | `goodix53xd-infinytum` | `5e14af7` (infinytum unstable, 2021) | `6f54d7e` — superseded, no calibration |
| gitlab.freedesktop.org/libfprint/fprintd | local branch `goodix53xd-learning` | tag `v1.94.5` | patch in `patches/fprintd/` |

Local remote names: in `libfprint-sigfm` and `libfprint-53xd`, `github` =
owner's fork. Push: `git -C libfprint-sigfm push github goodix53xd:goodix53xd-sigfm`.
After changing those branches, regenerate `patches/` with
`git format-patch -o ../patches/libfprint-sigfm 07306bb..goodix53xd`
(and `v1.94.5..goodix53xd-learning` for fprintd).

## 5. Code map (libfprint-sigfm)

| File | What |
|---|---|
| `libfprint/drivers/goodixtls/goodix53xd.c` | the driver (all changes below) |
| `libfprint/drivers/goodixtls/goodix53xd.h` | IDs, firmware string, PSK hash, MCU config blob |
| `libfprint/drivers/goodixtls/goodix.c` | protocol/TLS helpers from infinytum (legacy, needs `-Wno-incompatible-pointer-types`) |
| `libfprint/sigfm/sigfm.cpp` | SIGFM: SIFT extract + match score (fixed `match::operator<`, ratio 0.8) |
| `libfprint/fp-print.c` | print serialization (fixed SIGFM `GPtrArray` release) |
| `libfprint/fpi-print.c` | `fpi_print_sigfm_learn()` (template learning) |
| `libfprint/fpi-image-device.c` | `fp_image_device_maybe_learn()`; min-keypoints retry in `fpi_image_device_minutiae_detected()` |
| `libfprint/fpi-image-device.h` | class fields `sigfm_learn_max`, `sigfm_min_keypoints` |
| `libfprint/fp-device.h`, `fpi-device.c` | `FP_DEVICE_RETRY_TOO_FAST` (needed by fprintd 1.94.5) |
| `examples/verify.c` | saves the matched (learned) print to `test-storage.variant` |
| fprintd `src/device.c` `match_cb()` | saves the matched print when the device has `FP_DEVICE_FEATURE_UPDATE_PRINT` and not `FP_DEVICE_FEATURE_STORAGE` |

### Driver flow (`goodix53xd.c`)

1. `dev_init`: claim interface, `drain_input()` (read until 100 ms timeout,
   max 64 reads) to drop stale replies of a killed process.
2. `dev_activate`: states `READ_AND_NOP, ENABLE_CHIP, NOP, CHECK_FW_VER,
   CHECK_PSK, RESET, OTP, SET_MCU_IDLE, SET_MCU_CONFIG`, then TLS handshake.
   On `G_IO_ERROR_TIMED_OUT`: retry after 200 ms, 3 attempts (autosuspend).
3. Scan state machine `SCAN_STAGE_{CALIBRATE, WAIT, SWITCH_TO_FDT_MODE,
   GET_IMG}`; each read = FDT mode → register `0x022c` → image read.
   Capture modes:
   - `BACKGROUND`: frame at DAC +20 (`detect_img`), frame at +40
     (`calib_img`); `calibration_is_empty()` (≥50% of pixels of `detect_img`
     ≥ 2500 and <5% zeros in `calib_img`) else restart calibration;
     background at finger DAC = `detect + (detect − calib) × 20/20`
     (`extrapolate_background()`); third frame at +20 → noise →
     `finger_threshold = max(4×noise, noise+16)`.
   - `WAIT_FINGER_ON`: poll every 100 ms at +20, mean abs diff vs `detect_img`.
   - `SETTLE`: poll until delta changes ≤5% or 8 polls; lifted → retry
     `TOO_SHORT`; delta < 1900 → retry `CENTER_FINGER`.
   - `PRESS`: 3 frames at finger DAC (offset 0) → average → `frame + 0x2000 −
     background` → `signal_amplitude()` (std, cropped) → `squash_frame_rows()`
     (row mean removal, 2 px crop, 2–98 percentile stretch) → 60×76 image.
     In VERIFY/IDENTIFY, amplitude > 230 → retry `REMOVE_FINGER`, else
     `fpi_image_device_image_captured()`.
   - `WAIT_FINGER_OFF`: poll until delta ≤ threshold, then
     `fpi_ssm_mark_completed()` BEFORE reporting finger off (reporting first
     starts the next scan and caused a double free).
4. libfprint core: SIGFM extraction (hard minimum 25 keypoints in
   `fp-image.c`), then class minimum 33 → retry `CENTER_FINGER`; match
   threshold `bz3_threshold = 10`; on match `fpi_print_sigfm_learn(template,
   print, nr_enroll_stages=20, sigfm_learn_max=50)` (enrolled images
   protected, oldest learned replaced).
5. `dev_deactivate`: cancels a pending poll; `temp_hot_seconds = -1`
   (libfprint's simulated overheating model disabled).

### Tunables

| Constant | Value | Why / evidence |
|---|---|---|
| `GOODIX53XD_DETECT_DAC_STEP` / `CALIB_DAC_STEP` | 20 / 40 | first offsets without saturation |
| `GOODIX53XD_CAP_FRAMES` | 3 | frames averaged per press |
| `GOODIX53XD_MIN_CONTACT_DELTA` | 1900 | light presses blurry; env `GOODIX53XD_MIN_CONTACT` |
| `GOODIX53XD_SETTLE_PERCENT` / `MAX_POLLS` | 5 / 8 | finger landing gives partial images |
| `GOODIX53XD_ENROLL_STAGES` | 20 | coverage; Windows uses up to 50 |
| `GOODIX53XD_TEMPLATE_MAX` | 50 | Windows `maxTempNum:50`; >50 gave no offline gain |
| `GOODIX53XD_MIN_KEYPOINTS` | 33 | below: 8/22 failures, 0/38 matches (offline) |
| `GOODIX53XD_MAX_AMPLITUDE` | 230 | above: ~half of failures, 1/38 matches; env override |
| `bz3_threshold` (SIGFM score) | 10 | impostors ≤3 after calibration; 6–10 equivalent |
| SIGFM `distance_match` | 0.8 | 0.75 loses matches, 0.85 lets impostors score |

Debug env vars: `GOODIX53XD_DUMP_DIR` (per press: `*-background.pgm`
extrapolated 16-bit, `*-detect.pgm`, `*-calibration.pgm`, `*-frame{0,1,2}.pgm`
raw 16-bit maxval 65535, `*-image.pgm` 8-bit, `*-info.txt` with delta,
settle_polls, finger_threshold, amplitude; plus `*-empty-detect.pgm` at each
calibration), `GOODIX53XD_DAC_OFFSET` (finger DAC offset, read per scan).

## 6. Build / test commands

```sh
# deps: meson ninja-build gcc libglib2.0-dev libgusb-dev libssl-dev libopencv-dev doctest-dev
cd libfprint-sigfm
meson setup build -Ddrivers=goodixtls53xd -Dintrospection=false -Ddoc=false \
  -Dgtk-examples=false -Dudev_rules=disabled -Dudev_hwdb=disabled
ninja -C build            # only warnings expected: pre-existing unused functions
build/libfprint/fprint-list-supported-devices | grep 538d
```

Interactive tests need the owner's finger and root. From an agent session,
`sudo` has no TTY: use `pkexec` (GUI password prompt), or ask the owner to
run commands in their own terminal. Tell the owner what to do BEFORE
launching (no finger during the first ~1 s: calibration), and wrap with
`timeout`.

```sh
# capture one image (prints debug to STDOUT, GLib default handler)
pkexec env G_MESSAGES_DEBUG=all GOODIX53XD_DUMP_DIR=/tmp/dump timeout 60 \
  "$PWD"/build/examples/img-capture /tmp/dump/capture.pgm > log 2>&1
# enroll / verify (examples prompt: "update existing print?" → n, finger 6 = right index)
printf '\n6\n' | pkexec sh -c "cd DIR && exec build/examples/enroll"   # DIR: print storage
(echo 6; yes) | sudo G_MESSAGES_DEBUG=none build/examples/verify 2>&1 | grep -E "MATCH!|retry error"
# through the installed fprintd
fprintd-enroll -f right-index-finger; fprintd-verify -f right-index-finger
journalctl -u fprintd
```

Notes: `img-capture` always exits 1 (example bug). The examples set
`G_MESSAGES_DEBUG=all` unless already set: use `none` for humans. Examples
store prints in `./test-storage.variant`. Without a finger, a scan never
completes: cancel or timeout.

Decode a stored print (system python has `gi`; the venv does not):

```python
from gi.repository import GLib
d = open('test-storage.variant','rb').read()   # fprintd: the file itself is one print
v = GLib.Variant.new_from_bytes(GLib.VariantType('a{sv}'), GLib.Bytes.new(d), False)
raw = bytes(v['goodixtls53xd/0/7'])            # "FP3" header + GVariant
p = GLib.Variant.new_from_bytes(GLib.VariantType('(issbymsmsia{sv}v)'), GLib.Bytes.new(raw[3:]), False)
# p[0]: type (2 NBIS, 3 SIGFM); p[9].get_variant()[0]: list of images
```

## 7. Offline evaluation workflow

1. Build tools: `tools/goodix53xd_collect` (gcc, see file header, rpath to
   `libfprint-sigfm/build/libfprint`), `tools/sigfm_tune`, `tools/sigfm_matrix`
   (g++, OpenCV, `libsigfm.a`).
2. Owner runs, in their terminal: `sudo tools/goodix53xd_collect DIR label:N ...`
   (one sub-directory per label, resumes if interrupted).
3. Analyze with `.venv/bin/python -I tools/<script>.py DIR`:
   - `analyze.py`: genuine label `index`, others impostors; processing variants.
   - `tune.py CONFIG...`: SIGFM parameter sweep (`scale,contrast,ratio,min_match,length_tol,angle_tol[,bug]`).
   - `learning.py`: labels `enrol`, `usage` (chronological), others impostors.
   - `quality.py`: quality indicators vs failures (same labels).
   - `sigfm_tune` with `SIGFM_ROW_BUG=1` reproduces original libsigfm exactly.
4. Metric conventions: threshold = lowest score rejecting all impostors
   ("FAR=0" on the set); report genuine acceptance at that threshold and at 10.
   Caveats: impostor sets are small (≤40); same-session data is optimistic.
5. Delete the dataset after analysis (`pkexec rm -rf DIR`).

## 8. Dead ends (measured; do not retry without new information)

| Idea | Result |
|---|---|
| NBIS/bozorth3 | 1–2 minutiae per image, score 0 |
| Hardware FDT finger detection | thresholds are per-sensor; computing bases from a manual FDT reply: reply was all zeros |
| Upscaling ×2/×3 before SIFT | no gain once fixed pattern removed; earlier it only matched sensor noise |
| Band-pass, CLAHE, statistical fixed-pattern removal | no gain / worse |
| Pixel correlation (rotation + phase correlation) | impostor up to 0.62, genuine median 0.21 |
| SIFT + RANSAC (`estimateAffinePartial2D`) | +0–10 points but impostor margin 1–2 points |
| Mosaic of enrollment images | consecutive presses do not register (corr 0.20 vs 0.15 impostor) |
| Stricter learning threshold (score ≥ 12–40) | lower acceptance, no safety gain |
| Classic quality gates (coherence, contrast low, contact low) | failures are the opposite: clean, regular, strong images |

## 9. Open leads

1. Multi-day field use; check recognition drift and impostor behavior
   (`journalctl -u fprintd`, print size growth).
2. Per-pixel gain calibration (Windows `kr[]`), method unknown.
3. Observe the Windows driver in a VM (Goodix debug logs via
   `goodix-fp-dump/log/goodix_enable_logs.reg`, USB captures). Do not
   decompile Goodix binaries.
4. Optional PAM profile for `sudo` with `max-tries=3 timeout=10` (owner
   declined for now).
5. Report the two SIGFM bugs to goodix-fp-linux-dev.

## 10. Rollback of the installed system

```sh
sudo rm /etc/systemd/system/fprintd.service.d/goodix-538d.conf
sudo systemctl daemon-reload && sudo systemctl restart fprintd
sudo rm -rf /opt/fprint-538d
```

`apt-mark manual` was applied to `libopencv-{core,features2d,flann,imgproc}410`
(runtime libs of `/opt/fprint-538d`); revert with `apt-mark auto` if removed.
