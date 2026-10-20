"""Simulates template learning (like the Goodix Windows engine) offline.

usage: learning.py <dataset dir>

The dataset comes from goodix53xd_collect with the labels:
  enrol  presses spread over the finger, the initial template
  usage  natural presses of the same finger, in chronological order
  other labels are impostor fingers

SIGFM scores (patched libsigfm: deduplication fixed, ratio 0.8) of every
pair are computed once with sigfm_tune. Then the usage presses are replayed
in order: a press matches when its best score against the current template
reaches the match threshold, and it is added to the template when it reaches
the learning threshold. Above MAX_TEMPLATES images, the oldest learned image
is replaced, the enrolled ones are kept.
"""

import glob
import os
import subprocess
import sys

import numpy as np

TOOLS = os.path.dirname(os.path.abspath(__file__))
SIGFM = ["1", "0.04", "0.8", "5", "0.05", "0.05"]
MATCH_THRESHOLD = 10
MAX_TEMPLATES = 50


def load(root):
    paths, labels = [], []
    for label in sorted(os.listdir(root)):
        for path in sorted(glob.glob(os.path.join(root, label, "*-image.pgm"))):
            paths.append(path)
            labels.append(label)
    return paths, labels


def scores_of(paths):
    out = subprocess.run([os.path.join(TOOLS, "sigfm_tune")] + SIGFM + paths,
                         check=True, capture_output=True, text=True).stdout
    return np.array([list(map(int, line.split(",")))[1:]
                     for line in out.strip().splitlines()])


def replay(scores, enrolled, usage, learn_threshold, learning=True):
    template = list(enrolled)
    learned = []
    matched = []
    for probe in usage:
        ok = scores[probe, template].max() >= MATCH_THRESHOLD
        matched.append(ok)
        if learning and scores[probe, template].max() >= learn_threshold:
            if len(template) >= MAX_TEMPLATES:
                template.remove(learned.pop(0))
            template.append(probe)
            learned.append(probe)
    return np.array(matched), template


def main():
    paths, labels = load(sys.argv[1])
    enrolled = [i for i, l in enumerate(labels) if l == "enrol"]
    usage = [i for i, l in enumerate(labels) if l == "usage"]
    impostors = [i for i, l in enumerate(labels) if l not in ("enrol", "usage")]
    print(f"{len(enrolled)} enrolled, {len(usage)} usage, "
          f"{len(impostors)} impostor presses")
    scores = scores_of(paths)

    third = max(len(usage) // 3, 1)
    print(f"\n{'mode':32s} {'all':>5s} {'1st third':>9s} {'last third':>10s} "
          f"{'template':>8s} {'impostor max':>12s} {'impostors >= thr':>16s}")
    modes = [("no learning", None, False)]
    for learn in (MATCH_THRESHOLD, MATCH_THRESHOLD * 2, MATCH_THRESHOLD * 4):
        modes.append((f"learning at score >= {learn}", learn, True))
    for name, learn, learning in modes:
        matched, template = replay(scores, enrolled, usage, learn or 0, learning)
        imp = [scores[i, template].max() for i in impostors]
        print(f"{name:32s} {matched.mean():5.0%} {matched[:third].mean():9.0%} "
              f"{matched[-third:].mean():10.0%} {len(template):8d} "
              f"{max(imp):12d} {sum(x >= MATCH_THRESHOLD for x in imp):16d}")

    # Learned images could come from an impostor that got accepted: check
    # whether any impostor would match the enrolled images alone
    imp_enrolled = [scores[i, enrolled].max() for i in impostors]
    print(f"\nimpostors against the enrolled images only: max "
          f"{max(imp_enrolled)}")


if __name__ == "__main__":
    main()
