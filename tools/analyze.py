"""Offline evaluation of goodix53xd image processing and SIGFM matching.

usage: analyze.py <dataset dir> <work dir> [variant...]

The dataset comes from goodix53xd_collect: one sub directory per finger,
"index" is the genuine finger, every other one is an impostor. Each press
has raw 12 bit frames, the background, and the image built by the driver.

For each variant (image processing) and scale, images are written to the
work dir, scored pairwise with sigfm_matrix, then evaluated like libfprint
verify: a probe matches when its best score against the enrolled images
reaches the threshold.
"""

import glob
import os
import subprocess
import sys

import cv2
import numpy as np

TOOLS = os.path.dirname(os.path.abspath(__file__))
GENUINE = "index"
PROBES = 15  # last genuine presses used as probes
TEMPLATE_COUNTS = (5, 10, 15)
BORDER = 2


def load_dataset(root):
    presses = []
    for label in sorted(os.listdir(root)):
        for image in sorted(glob.glob(os.path.join(root, label, "*-image.pgm"))):
            prefix = image[: -len("image.pgm")]
            frames = [
                cv2.imread(f, cv2.IMREAD_UNCHANGED).astype(np.float64)
                for f in sorted(glob.glob(prefix + "frame*.pgm"))
            ]
            background = cv2.imread(prefix + "background.pgm",
                                    cv2.IMREAD_UNCHANGED).astype(np.float64)
            driver = cv2.imread(image, cv2.IMREAD_GRAYSCALE)
            presses.append({"label": label, "frames": frames,
                            "background": background, "driver": driver})
    return presses


def stretch(img, percentile=2):
    low, high = np.percentile(img, [percentile, 100 - percentile])
    return np.clip((img - low) * 255 / max(high - low, 1e-9), 0, 255).astype(np.uint8)


def signal(press):
    """Background subtracted average of the press frames, border cropped."""
    diff = np.mean(press["frames"], axis=0) - press["background"]
    return diff[BORDER:-BORDER, BORDER:-BORDER]


def variant_driver(press):
    return press["driver"]


def variant_rows(press):
    img = signal(press)
    return stretch(img - img.mean(axis=1, keepdims=True))


def variant_rows_cols(press):
    img = signal(press)
    img = img - img.mean(axis=1, keepdims=True)
    return stretch(img - img.mean(axis=0, keepdims=True))


def variant_bandpass(press):
    """Keeps the ridge frequencies: removes the slow background and the
    pixel noise with a difference of gaussians."""
    img = signal(press)
    img = img - img.mean(axis=1, keepdims=True)
    fine = cv2.GaussianBlur(img, (0, 0), 0.8)
    coarse = cv2.GaussianBlur(img, (0, 0), 6)
    return stretch(fine - coarse)


def variant_clahe(press):
    img = variant_bandpass(press)
    return cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4)).apply(img)


def bandpass(img):
    fine = cv2.GaussianBlur(img, (0, 0), 0.8)
    coarse = cv2.GaussianBlur(img, (0, 0), 6)
    return fine - coarse


def flatfield_signals(presses):
    """Signals with the sensor fixed pattern removed. The pattern of a press
    is the mean of all the other presses, so it never contains that press."""
    sig = np.array([signal(p) for p in presses])
    sig -= sig.mean(axis=2, keepdims=True)
    total = sig.sum(axis=0)
    return [s - (total - s) / (len(sig) - 1) for s in sig]


def per_press(variant):
    return lambda presses: [variant(p) for p in presses]


VARIANTS = {
    "driver": per_press(variant_driver),
    "rows": per_press(variant_rows),
    "rows_cols": per_press(variant_rows_cols),
    "bandpass": per_press(variant_bandpass),
    "clahe": per_press(variant_clahe),
    "flatfield": lambda presses: [stretch(s) for s in flatfield_signals(presses)],
    "flatfield_bandpass":
        lambda presses: [stretch(bandpass(s)) for s in flatfield_signals(presses)],
}


def score_matrix(images, work_dir, scale):
    os.makedirs(work_dir, exist_ok=True)
    paths = []
    for i, img in enumerate(images):
        path = os.path.join(work_dir, f"{i:03d}.pgm")
        cv2.imwrite(path, img)
        paths.append(path)
    out = subprocess.run([os.path.join(TOOLS, "sigfm_matrix"), str(scale)] + paths,
                         check=True, capture_output=True, text=True).stdout
    rows = [list(map(int, line.split(","))) for line in out.strip().splitlines()]
    keypoints = np.array([r[0] for r in rows])
    return keypoints, np.array([r[1:] for r in rows])


def evaluate(presses, scores):
    genuine = [i for i, p in enumerate(presses) if p["label"] == GENUINE]
    impostors = [i for i, p in enumerate(presses) if p["label"] != GENUINE]
    probes = genuine[-PROBES:]
    results = []
    for count in TEMPLATE_COUNTS:
        templates = genuine[:count]
        best_genuine = np.array([scores[p, templates].max() for p in probes])
        best_impostor = np.array([scores[p, templates].max() for p in impostors])
        # Lowest threshold rejecting every impostor
        threshold = max(int(best_impostor.max()) + 1, 1)
        frr = np.mean(best_genuine < threshold)
        frr24 = np.mean(best_genuine < 24)
        far24 = np.mean(best_impostor >= 24)
        results.append((count, threshold, frr, frr24, far24,
                        np.median(best_genuine), best_impostor.max()))
    return results


def main():
    root, work = sys.argv[1], sys.argv[2]
    names = sys.argv[3:] or list(VARIANTS)
    presses = load_dataset(root)
    labels = {p["label"] for p in presses}
    print(f"{len(presses)} presses: " + ", ".join(
        f"{l} {sum(p['label'] == l for p in presses)}" for l in sorted(labels)))

    for name in names:
        images = VARIANTS[name](presses)
        for scale in (1, 2):
            keypoints, scores = score_matrix(images, os.path.join(work, name), scale)
            print(f"\n== {name} x{scale}: keypoints min {keypoints.min()} "
                  f"median {int(np.median(keypoints))}")
            print("  templates | threshold FAR=0 | rejected index | "
                  "at 24: rejected index, accepted impostors | median index | max impostor")
            for count, thr, frr, frr24, far24, med, imax in evaluate(presses, scores):
                print(f"  {count:9d} | {thr:15d} | {frr:14.0%} | "
                      f"{frr24:21.0%} {far24:19.0%} | {med:12.0f} | {imax:12d}")


if __name__ == "__main__":
    main()
