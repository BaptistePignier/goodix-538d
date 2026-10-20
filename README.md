# Goodix 27c6:538d on Linux

*English · [Français](README.fr.md)*

Report of an attempt to get the Goodix `27c6:538d` fingerprint reader of a
Dell Inspiron 3501 working on Ubuntu 26.04, without Windows.

**Conclusion.** The libfprint driver fixed here talks to the sensor
reliably, calibrates it properly, detects the finger and captures sharp
images. With **template learning** (section 9), like the Goodix Windows
engine, **84 to 85% of natural presses are recognized** after about twenty
uses, and **no other finger was accepted** (0 out of 40 real presses, 0 out
of 80 offline). These figures come from sessions of a few hours: only use
over several days will tell whether they hold. Installed with an fprintd
patched to keep the learning (section 11), the reader recognized 18 presses
out of 18 and unlocks the GNOME screen.

Without learning, only 25 to 35% of presses were recognized. The sensor only
sees 4 or 5 nearly parallel ridges: on such a pattern, the position of one
image relative to another is undetermined (the "aperture problem" of image
registration). Every matching method tried hits that ceiling; accumulating
images over time is what gets around it.

## Contents

1. [Audit of `run_538d.py`](#1-audit-of-run_538dpy)
2. [Read-only check](#2-read-only-check)
3. [Community libfprint driver](#3-community-libfprint-driver)
4. [First driver fixes](#4-first-driver-fixes)
5. [NBIS, then SIGFM](#5-nbis-then-sigfm)
6. [Sensor calibration](#6-sensor-calibration)
7. [Captures, robustness and enrollment](#7-captures-robustness-and-enrollment)
8. [Fingerprint matching](#8-fingerprint-matching)
9. [Template learning](#9-template-learning)
10. [Results](#10-results)
11. [Installation with fprintd](#11-installation-with-fprintd)
12. [Reproducing](#12-reproducing)
13. [Repository contents](#13-repository-contents)

## 1. Audit of `run_538d.py`

[`goodix-fp-dump`](https://github.com/goodix-fp-linux-dev/goodix-fp-dump)
provides `run_538d.py`, which reflashes the sensor before capturing images.
Before running it as root, the script and all the code it calls
(`driver_53xd.py`, `goodix.py`, `protocol.py`, `tool.py`) were audited.

**Behavior depending on the sensor state:**

| Firmware version | PSK | Action |
|---|---|---|
| `GF5298_GM168SEC_APP_13016` | zero | image capture, nothing written to flash |
| `GF5298_GM168SEC_APP_13016` | other | **application erased**, then flashed |
| `GF5298_GM168SEC_APP_130xx` (other) | — | **application erased**, then flashed |
| `MILAN_GM168SEC_IAP_10007` (bootloader) | — | PSK written, firmware 13016 flashed |
| other | — | stops with "Invalid firmware", nothing written |

**USB commands writing to flash:** `0xA4` (erase the application), `0xE0`
(write the PSK), `0xF0` (write the firmware, 95 blocks of 256 bytes). The
bootloader is never rewritten, which makes most failures recoverable by
running the script again.

**What gets installed:** the `GF5298_GM168SEC_APP_13016.bin` firmware
(24,268 bytes) and a PSK of 32 zero bytes. The script checks no checksum of
the file, and since the zero key is public, the TLS link between the PC and
the sensor no longer protects anything.

**Points of no return:**
1. Erasing the original firmware, with no prior backup.
2. Overwriting the original PSK, which cannot be read beforehand.
3. Flashing firmware 13016.

**Risks found:**
- The erase happens *before* the script sees the bootloader version: if it
  is not `10007`, the sensor is left without an application.
- A Ctrl+C during the flash is not caught (`KeyboardInterrupt` does not
  inherit from `Exception`): neither erase nor check follows.
- During capture, `openssl s_server` listens as root on port 4433, on all
  interfaces, with the zero key.
- `fingerprint.pgm` is written unencrypted in the current directory.

## 2. Read-only check

[`check_538d_ro.py`](check_538d_ro.py) reuses `goodix.Device` unchanged, but
replaces the USB write with an allowlist: only `0x00` (nop), `0xA8`
(version), `0xE4` (PSK hash read) and `0xA6` (OTP read) can reach the
sensor. It prints what `run_538d.py` would do.

On this sensor, the firmware was already `GF5298_GM168SEC_APP_13016` with
the zero key (hash `sha256(0^32)`): it had already been flashed with this
tool, and **no flashing was needed** afterwards.

## 3. Community libfprint driver

Neither Ubuntu's libfprint nor Dell's proprietary
`libfprint-2-tod1-goodix` driver supports `538d`. The only existing driver
is `goodixtls53xd`, in the `unstable` branch of
[infinytum/libfprint](https://github.com/infinytum/libfprint) (last commit
in November 2021, packaged on Arch as `libfprint-goodix-521d`). It requires
exactly firmware 13016 and the zero key, and never writes to flash.

As is, it talks to the sensor fine (checks, TLS handshake, image reads) but
the image it produces is unusable.

## 4. First driver fixes

Branch `goodix53xd-infinytum` ([patches](patches/libfprint-infinytum)):

| Problem | Fix |
|---|---|
| The images of a press are stitched as for a swipe sensor | average of 3 images of the same press |
| No subtraction of the finger-free image (disabled and wrong code) | finger-free image captured at the start of each scan |
| Horizontal bands, border with extreme values | mean of each row removed, 2-pixel border cropped, contrast stretched between the 2nd and 98th percentiles; final image 60×76 |
| Register `0x022c` receives `05 00` instead of `05 03` | value `0x0305` |
| Hardware finger detection (FDT) firing without a finger: its thresholds come from the author's sensor | image-based detection, compared with the finger-free image every 100 ms |
| `double free` on close | state machine completed before reporting the finger lifted |
| Build fails with GCC 14 | `-Wno-incompatible-pointer-types` |

This branch does not include the calibration of section 6; the rest of the
work is in `goodix53xd-sigfm`.

## 5. NBIS, then SIGFM

**NBIS**, libfprint's default algorithm, compares minutiae (ridge endings
and bifurcations) with bozorth3. It only finds **1 or 2 per image**: no
verification succeeds (score 0/24).

**SIGFM** compares SIFT keypoints (OpenCV); the Goodix community wrote it
for small sensors. It lives in the `sigfm` branch of
[goodix-fp-linux-dev/libfprint](https://github.com/goodix-fp-linux-dev/libfprint),
which has no goodixtls driver: the driver was transplanted there (branch
`goodix53xd-sigfm`, [patches](patches/libfprint-sigfm)).

Two bugs in SIGFM itself were fixed:
- `fp_print_serialize` released a `GPtrArray` with `g_clear_object`: the
  enrolled print was not saved.
- `match::operator<` only compares `p1.y` (its second clause can never be
  true), so the `std::set` of matches keeps **only one per image row** and
  drops most of the good ones.

With the images of section 4, SIGFM accepted other fingers as soon as the
image was upscaled: a middle finger scored 2954 against the index, more
than any pair of the right finger. The cause is explained below.

## 6. Sensor calibration

The raw data (12-bit images recorded by the driver) showed that **the
finger-free image was 100% saturated**: every pixel at 4095. The
"finger-free image subtraction" therefore removed a constant, and the
sensor's fixed pattern (sensitivity differences, mostly per column) stayed
in every image. From one finger to another, images correlated at 0.32 on
average; SIGFM matched that common pattern.

The DAC values (signal offset sent with each image read, taken from the
OTP) put the finger-free sensor above 4095. A finger-free sweep
([`goodix53xd_dacsweep`](tools/goodix53xd_dacsweep.c)) gives:

| DAC offset | Finger-free level (median) | Saturation |
|---|---|---|
| 0 (OTP) | 4095 | 100% |
| +20 | 3771 | 0% |
| +40 | 2321 | 0% |
| +60 | 856 | 0% |
| +80 | 0 | 100% at 0 |

The response is **linear and identical for every pixel**: −72.9 per step
(72.2 to 73.4 depending on the pixel), with no zones. The driver:
- captures two finger-free images, at +20 and +40;
- **extrapolates the finger-free image at the finger offset** (0), pixel by
  pixel: `2 × calib(+20) − calib(+40)`;
- detects the finger at +20, against the matching finger-free image;
- captures the finger at offset 0 (signal centered around 2000) and
  subtracts the real finger-free image from it.

Result: no more saturation, a much weaker fixed pattern, and **no other
finger accepted anymore** (see section 10).

## 7. Captures, robustness and enrollment

| Problem | Fix |
|---|---|
| Image captured while the finger lands (partial contact, blur) | wait for the gap to the finger-free image to settle (less than 5% change) |
| Presses that are too light | rejected, retry requested below a gap of 1900 |
| An image only covers a small part of the finger | 20 images at enrollment |
| Finger still on the sensor during calibration: it becomes the finger-free image and lifting it looks like a press | calibration check (median at +20 above 2500, less than 5% of pixels at 0 at +40), otherwise calibrate again |
| "Device disabled to prevent overheating": libfprint's simulated temperature model runs out because of image-based detection | model disabled, as for the goodixmoc driver |
| The reader goes into USB autosuspend after 2 s (hwdb `60-autosuspend-libfprint-2`) and the first command after waking up is lost | up to 3 activation attempts |
| Data left by an interrupted program | read until timeout when opening, like `empty_buffer()` in goodix-fp-dump |
| TLS error during activation never reported (hang) | error passed on to libfprint |

Debugging environment variables: `GOODIX53XD_DUMP_DIR` (raw images,
calibration, final image and contact gap of each press),
`GOODIX53XD_DAC_OFFSET`, `GOODIX53XD_MIN_CONTACT`,
`GOODIX53XD_MAX_AMPLITUDE`.

## 8. Fingerprint matching

Every variant was evaluated offline on the same images, with the tools in
[`tools/`](tools):

| Method | Result |
|---|---|
| Original SIGFM | no other finger, but few right presses recognized |
| Fixed SIGFM, ratio 0.8 (instead of 0.75), threshold 10 | kept: other fingers score 3 at most, a few points gained |
| Images upscaled ×2 or ×3 | more SIFT keypoints, but no gain once the fixed pattern is removed |
| Image filters (band-pass, CLAHE, estimated fixed pattern) | no gain |
| Pixel correlation with rotation and translation search | worse: another finger reaches 0.62, like real presses |
| SIFT + RANSAC (rotation and translation, number of consistent keypoints) | 25 to 35% like SIGFM, but a margin of only 1 or 2 points against other fingers: not kept |
| Mosaic: stitching the enrollment images | impossible: two consecutive, barely shifted presses do not register (correlation 0.20 versus 0.15 between different fingers) |

## 9. Template learning

The Windows driver logs captured by the community
([`goodix-fp-dump/log/ENGINE.log`](https://github.com/goodix-fp-linux-dev/goodix-fp-dump/tree/master/log),
Goodix "Milan" engine, 5110 sensor with the same resolution) show how
Windows copes:

| Goodix engine (Windows) | This repository |
|---|---|
| Template of at most 50 images (`maxTempNum:50`) | 50 images |
| Every successful match adds the image to the template (`gx_templateStudy`) | same, `fpi_print_sigfm_learn()` |
| Quality (25) and coverage (65%) thresholds | retry requested for undistinctive images |
| Per-pixel gain and offset calibration (`kr[]`, `b[]`) | offset only |

**Learning.** When a verification succeeds, the image joins the template;
above 50 images, the oldest learned image is replaced, the 20 enrollment
images stay. The caller saves the enriched template (the `verify` example
does; fprintd has to be patched).

**Retry rather than failure.** Failed presses are not blurry images but very
regular parallel ridges: fewer SIFT keypoints, stronger and more coherent
signal ([`tools/quality.py`](tools/quality.py)). The driver asks to place
the finger again when an image has fewer than 33 SIFT keypoints, or, during
verification, when its signal exceeds 230. A retry request does not use up
an attempt in fprintd.

## 10. Results

Five sets of presses were collected
([`goodix53xd_collect`](tools/goodix53xd_collect.c)), then deleted after
the analysis.

**Before and after calibration** (30 varied index presses, 25 from other
fingers; the first 15 index presses are the reference):

| | Without calibration | With calibration |
|---|---|---|
| Other finger, best score (images ×2) | 4504 | 3 |
| Saturated pixels in finger images | 2.7% | 0% |

**Recognition depending on the number of reference images** (fixed SIGFM,
threshold 10, varied presses, 300 draws): 45% with 15 images, 59% with 25.

**Real conditions** (libfprint `enroll` and `verify`, 20 enrollment
images): 3 presses recognized out of 9.

**Realistic offline scenario** (30 enrollment images while shifting the
finger little by little, 20 natural presses to verify, 40 presses from
other fingers):

| Method | Threshold | Other fingers (max) | Natural presses recognized |
|---|---|---|---|
| Fixed SIGFM | 10 | 0 | 25% |
| SIFT + RANSAC | 6 | 4 | 25% |
| SIFT + RANSAC | 5 | 4 | 35% |

**Learning, offline simulation**
([`tools/learning.py`](tools/learning.py): 20 enrollment images, 60
natural presses replayed in order, 40 presses from other fingers):

| | Without learning | With learning |
|---|---|---|
| Presses recognized | 28% | 63% |
| Unlock within at most 3 attempts | — | 90% |
| Other fingers, best score (threshold 10) | 1 | 1 |

Retry requests turn 12 of the 22 failures into "place your finger again"
while asking only 1 recognized press out of 38 again: 77% of the presses
the driver answers are recognized.

**Learning, real conditions** (`enroll`, then `verify` in a loop):

| Run | Right index recognized | Other fingers accepted |
|---|---|---|
| Right after enrollment | 34/40 (85%): 5/10, 9/10, 10/10, 10/10 | 0/30 |
| One hour later, with retries | 26/31 (84%), 2 retries | 0/10 |

Going further: use over several days, per-pixel gain calibration, or
observing the Windows driver (logs and USB traffic in a virtual machine) to
learn its capture settings.

## 11. Installation with fprintd

fprintd, the service used by GNOME and PAM, never writes a print back after
a verification: the learning would be lost every time the print is loaded.
The [fprintd patch](patches/fprintd), on version 1.94.5 shipped with
Ubuntu 26.04, saves the print after each successful verification, for
image readers without their own storage. It also accepts libfprint 1.94.5,
on which the SIGFM branch is based.

Everything is installed in `/opt/fprint-538d`, without touching Ubuntu's
packages. Extra dependency: `libpolkit-gobject-1-dev`.

```sh
P=/opt/fprint-538d
git clone https://github.com/BaptistePignier/goodix-538d.git
git clone -b goodix53xd-sigfm https://github.com/BaptistePignier/libfprint.git
git clone -b v1.94.5 https://gitlab.freedesktop.org/libfprint/fprintd.git
git -C fprintd am "$PWD"/goodix-538d/patches/fprintd/*.patch

meson setup libfprint/build-opt libfprint --prefix=$P -Ddrivers=goodixtls53xd \
    -Dintrospection=false -Ddoc=false -Dgtk-examples=false \
    -Dudev_rules=disabled -Dudev_hwdb=disabled
ninja -C libfprint/build-opt
PKG_CONFIG_PATH="$PWD"/libfprint/build-opt/meson-uninstalled \
    meson setup fprintd/build fprintd --prefix=$P -Dpam=false -Dman=false \
    -Dsystemd=false -Dgtk_doc=false -Dc_link_args=-Wl,-rpath,$P/lib/x86_64-linux-gnu
ninja -C fprintd/build

meson install -C libfprint/build-opt --destdir "$PWD"/stage
meson install -C fprintd/build --destdir "$PWD"/stage
sudo sh goodix-538d/tools/install-fprintd-538d.sh "$PWD"/stage
```

[`install-fprintd-538d.sh`](tools/install-fprintd-538d.sh):
- copies only `/opt/fprint-538d`. Installing fprintd would also write its
  D-Bus and polkit files in `/usr/share`, over those of the Ubuntu package:
  they are identical except for two translations, and Ubuntu's are kept;
- creates `/etc/systemd/system/fprintd.service.d/goodix-538d.conf`, which
  starts our fprintd instead of `/usr/libexec/fprintd`. Ubuntu's systemd
  sandbox is kept, and the D-Bus service file already delegates to systemd;
- marks the OpenCV libraries in use as manually installed, so that cleaning
  up the development packages does not remove them.

Then:

```sh
fprintd-enroll -f right-index-finger    # 20 presses spread over the finger
fprintd-verify -f right-index-finger
```

The GNOME lock and login screens then offer the fingerprint (Ubuntu's
`gdm-fingerprint` PAM file). `sudo` and administration dialogs do not use
it: Ubuntu's `pam-auth-update` profile only allows one attempt
(`max-tries=1`), and this repository does not enable it.

**Result**: 18 index presses recognized out of 18 with `fprintd-verify`,
one retry request, 2 presses from another finger rejected; the print saved
by fprintd grew from about 460 KB to 1.2 MB (learned images).

**Going back to Ubuntu's fprintd:**

```sh
sudo rm /etc/systemd/system/fprintd.service.d/goodix-538d.conf
sudo systemctl daemon-reload && sudo systemctl restart fprintd
sudo rm -rf /opt/fprint-538d
```

The prints stay in `/var/lib/fprint`; Ubuntu's fprintd does not handle this
reader. Reminder: the sensor's PSK is public (section 1), so an attacker
with physical access could in theory inject images.

## 12. Reproducing

Dependencies (Ubuntu 26.04): `meson`, `ninja-build`, `gcc`,
`libglib2.0-dev`, `libgusb-dev`, `libssl-dev`, `libopencv-dev`,
`doctest-dev`.

```sh
git clone -b goodix53xd-sigfm https://github.com/BaptistePignier/libfprint.git
cd libfprint
meson setup build -Ddrivers=goodixtls53xd -Dintrospection=false -Ddoc=false \
    -Dgtk-examples=false -Dudev_rules=disabled -Dudev_hwdb=disabled
ninja -C build
sudo G_MESSAGES_DEBUG=none build/examples/enroll   # 20 presses
(echo 6; yes) | sudo G_MESSAGES_DEBUG=none build/examples/verify 2>&1 | grep -E "MATCH!|retry error"
```

The examples use the library just built, without touching the system's
libfprint. Lift the finger clearly between two presses: the driver waits
for the sensor to be empty before calibrating.

Collecting presses for offline analysis (build the tool as described at the
top of [`goodix53xd_collect.c`](tools/goodix53xd_collect.c)):

```sh
sudo tools/goodix53xd_collect dataset index:30 middle:15 ring:10
.venv/bin/python tools/analyze.py dataset work
```

Read-only check of the sensor state:

```sh
git clone https://github.com/goodix-fp-linux-dev/goodix-fp-dump.git
python3 -m venv .venv && .venv/bin/pip install pyusb python-periphery spidev
sudo .venv/bin/python check_538d_ro.py
```

## 13. Repository contents

| Path | Purpose |
|---|---|
| `check_538d_ro.py` | read-only sensor state, next to a `goodix-fp-dump` clone |
| `patches/libfprint-infinytum/` | first fixes on `infinytum/libfprint` (`unstable`) |
| `patches/libfprint-sigfm/` | complete driver and SIGFM fixes on `goodix-fp-linux-dev/libfprint` (`sigfm`) |
| `patches/fprintd/` | saving the print after a successful verification, on fprintd 1.94.5 |
| `tools/install-fprintd-538d.sh` | installation in `/opt/fprint-538d` and systemd override |
| `tools/goodix53xd_collect.c` | guided collection of presses, finger by finger |
| `tools/goodix53xd_dacsweep.c` | finger-free images for several DAC offsets |
| `tools/analyze.py`, `tools/sigfm_matrix.cpp` | image processing variants evaluated with libsigfm |
| `tools/sigfm_tune.cpp`, `tools/tune.py` | SIGFM with tunable parameters, and a sweep |
| `tools/correlation.py`, `tools/ransac.py` | correlation and SIFT + RANSAC matching prototypes |
| `tools/learning.py` | template learning simulation |
| `tools/quality.py` | quality indicators of failed presses |
| `tools/sigfm_bench.cpp` | first SIGFM test bench |
| `AGENTS.md` | the same project, written for coding agents (LLMs) |

Both driver branches are published in
[BaptistePignier/libfprint](https://github.com/BaptistePignier/libfprint):
`goodix53xd-infinytum` (section 4) and `goodix53xd-sigfm` (sections 5
to 9).

No biometric data is included. libfprint is under LGPL 2.1, goodix-fp-dump
under the MIT license; the Goodix firmware is not redistributed here.
