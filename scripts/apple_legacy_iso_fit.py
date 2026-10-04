#!/usr/bin/env python3
"""How closely can ISO 21496-1 gain-map metadata restate Apple's legacy HDR gain map?

Apple's legacy curve (the aux-image gain maps of iPhone 12-15 HEICs, headroom H from the
EXIF MakerNote) scales linear light by

    scale = 1 + (H - 1) * sRGB_EOTF(g)            g = stored gain value in [0, 1]

ISO 21496-1 makes the log of the scale linear in a power of the stored value:

    log2(scale) = a + b * g^(1/gamma)              (a = log2 min, b = log2 max - a)

The two have different forms, so ISO metadata over the *same* gain-map pixels can only
approximate Apple's rendition. For each headroom this prints the best minimax fit, first
with the endpoints pinned (min 1, max H) and then with a and b free, plus the error of
re-encoding the gain-map pixels themselves into 8-bit ISO form (half a code step).

Results: benchmarks/apple_legacy_gainmap_iso_fit_2026-10-03.md. numpy only.
"""
import sys

import numpy as np

# Legacy headrooms (stops) of the 24 corpus HEICs and how many files have each, from the
# whitelist-v2 signal probe (_checks/sig_final.tsv, gain_map_headroom).
HEADROOMS = {1.6: 1, 1.626: 1, 1.677: 1, 1.739: 1, 1.776: 1, 1.8: 3,
             2.529: 1, 2.659: 1, 2.663: 1, 3.0: 13}

G = np.arange(256) / 255.0
EOTF = np.where(G <= 0.04045, G / 12.92, ((G + 0.055) / 1.055) ** 2.4)


def minimax_free(target, gamma):
    """Minimax fit of a + b*x to target (Lawson's iteratively reweighted least squares)."""
    x = G ** (1 / gamma)
    A = np.vstack([np.ones_like(x), x]).T
    w = np.ones_like(x)
    for _ in range(60):
        coef, *_ = np.linalg.lstsq(A * np.sqrt(w)[:, None], target * np.sqrt(w), rcond=None)
        r = np.abs(A @ coef - target)
        w = np.maximum(w * r / (np.sum(w * r) + 1e-12), 1e-12)
    return np.abs(A @ coef - target).max()


def main():
    print("headroom_stops\tfiles\tmax_err_pinned\tmax_err_free\tgamma_free\tmax_err_requantized")
    for stops, n in HEADROOMS.items():
        target = np.log2(1 + (2 ** stops - 1) * EOTF)
        pinned = min(np.abs(stops * G ** (1 / g) - target).max() for g in np.linspace(0.3, 1.5, 2401))
        free, gamma = min((minimax_free(target, g), g) for g in np.linspace(0.3, 1.5, 601))
        requant = stops / 255 / 2
        print(f"{stops:.3f}\t{n}\t{pinned:.4f}\t{free:.4f}\t{gamma:.3f}\t{requant:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
