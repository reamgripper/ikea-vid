"""Hand-tuned grouping for the IKEA MYLLRA crib with drawer (GLB 'MYLLRA_Babybett_mit_Schubfach')."""
import numpy as np


def myllra(m):
    """Returns (groups, stages). Coordinates are read from the *raw* (un-normalised) model in metres."""
    C = m.comps
    s = m.scale
    off = np.array([(m.raw_min[0] + m.raw_max[0]) / 2, m.raw_min[1], (m.raw_min[2] + m.raw_max[2]) / 2])
    def raw(c): return c.bmin / s + off, c.bmax / s + off
    groups = {}
    tiny = []
    from scipy.spatial import cKDTree

    def classify(c):
        mn, mx = raw(c); ce = (mn + mx) / 2; ext = mx - mn; cx, cy, cz = ce
        if cx < -0.6: return "end_left"
        if cx > 0.6: return "end_right"
        if mx[1] <= 0.08 and 0.5 < abs(cx) < 0.6: return "feet"
        if mx[1] > 0.34 and abs(cz) > 0.3: return "slat_side_front" if cz > 0 else "slat_side_back"
        if (mx[1] - mn[1]) < 0.005 and 0.32 < cy < 0.335 and abs(cz) > 0.345 and ext[0] > 1.0:
            return "slat_side_front" if cz > 0 else "slat_side_back"
        if mx[1] > 0.34: return "slat_side_front" if cz > 0 else "slat_side_back"
        if mn[2] > 0.36: return "drawer_pulls"
        if 0.27 <= cy <= 0.345 and abs(cz) < 0.375: return "mattress_base"
        if mn[2] >= 0.344 and cy < 0.3: return "drawer_front"
        if abs(cx) > 0.535 and cy < 0.155 and 0.0 < cz < 0.33 and mn[1] > 0.11: return "runners"
        if abs(cx) < 0.5585 and -0.19 < mn[2] and mx[2] < 0.362 and 0.115 <= cy < 0.29 and mx[1] < 0.29: return "drawer_box"
        if cy < 0.1: return "base_floor"
        if cz < -0.37: return "base_back"
        return "base_walls"
    lab = {}
    for c in C:
        if c.faces < 20 and c.ext.max() < 0.03 * 1.4:
            tiny.append(c); continue
        lab[c.id] = classify(c)
    pts, own = [], []
    for c in C:
        if c.id in lab:
            P = m.V[c.vs]; pts.append(P); own += [lab[c.id]] * len(P)
    tree = cKDTree(np.vstack(pts)); own = np.array(own)
    for c in tiny:
        _, i = tree.query(c.cen); lab[c.id] = own[i]
    for cid, g in lab.items():
        groups.setdefault(g, []).append(cid)
    groups = {k: sorted(v) for k, v in groups.items()}
    stages = [
        dict(title="Build the base frame", text="Fit dowels and studs, then lock the base boards together with cam locks and add the two metal drawer runners.",
             steps=[1, 14], groups=["base_floor", "base_walls", "runners", "base_back"]),
        dict(title="Screw in the four feet", text="Turn each foot into its threaded socket until it sits tight against the base.",
             steps=[23, 23], groups=["feet"]),
        dict(title="Stand the two end panels", text="Position the head and foot panels against the base, one at each end.",
             steps=[36, 36], groups=["end_left", "end_right"]),
        dict(title="Build and slide in the drawer", text="Assemble the drawer box, fit the front panel and pulls, then push the drawer onto its runners.",
             steps=[33, 37], groups=["drawer_box", "drawer_front", "drawer_pulls"]),
        dict(title="Lower in the mattress base", text="Drop the slatted base between the end panels and bolt it down with the Allen key.",
             steps=[38, 40], groups=["mattress_base"]),
        dict(title="Hang the two slat sides", text="Fit the back side first, then the front side, and tighten the bolts through the end panels.",
             steps=[41, 44], groups=["slat_side_back", "slat_side_front"]),
    ]
    entry = {"end_left": [-0.8, 0, 0], "end_right": [0.8, 0, 0], "slat_side_back": [0, 0.25, -0.95],
             "slat_side_front": [0, 0.25, 0.95], "drawer_box": [0, 0.1, 0.9], "drawer_front": [0, 0.1, 0.9],
             "drawer_pulls": [0, 0.1, 0.9], "base_floor": [0, -0.55, 0], "base_walls": [0, 0.55, 0],
             "runners": [0, 0.5, 0], "base_back": [0, 0.1, -0.9], "feet": [0, -0.4, 0], "mattress_base": [0, 0.8, 0]}
    return groups, stages, entry
