"""Load a GLB, split it into components, normalise, and auto-group components into assembly parts."""
from dataclasses import dataclass
import numpy as np
import trimesh
import scipy.sparse as sp
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

TARGET = 1.4  # longest model dimension after normalisation


@dataclass
class Comp:
    id: int
    name: str
    faces: int
    bmin: np.ndarray
    bmax: np.ndarray
    vs: np.ndarray  # vertex indices

    @property
    def cen(self): return (self.bmin + self.bmax) / 2
    @property
    def ext(self): return self.bmax - self.bmin


class Model:
    pass


def load_glb(path):
    scene = trimesh.load(path, force="scene")
    insts = []
    for node in scene.graph.nodes_geometry:
        T, gname = scene.graph[node]
        g = scene.geometry[gname].copy()
        g.apply_transform(T)
        insts.append((node, g))
    if not insts:
        raise SystemExit("No mesh geometry found in GLB.")
    color = None
    try:
        mc = insts[0][1].visual.material.main_color
        color = [int(v) for v in mc[:3]]
    except Exception:
        pass

    Vs, Fs, Ns, labels, names = [], [], [], [], []
    off = 0
    use_instances = len(insts) >= 6
    for k, (node, g) in enumerate(insts):
        V = np.asarray(g.vertices, dtype=np.float64)
        F = np.asarray(g.faces)
        N = np.asarray(g.vertex_normals, dtype=np.float64)
        Vs.append(V); Ns.append(N); Fs.append(F + off)
        if use_instances:
            labels.append(np.full(len(F), k)); names.append(str(node))
        off += len(V)
    V = np.vstack(Vs); F = np.vstack(Fs); N = np.vstack(Ns)

    if use_instances:
        fl = np.concatenate(labels)
    else:
        ext = V.max(0) - V.min(0)
        key = np.round((V - V.min(0)) / (ext.max() * 1e-5)).astype(np.int64)
        _, inv = np.unique(key, axis=0, return_inverse=True)
        inv = inv.ravel(); nn = inv.max() + 1
        Fw = inv[F]
        a = sp.coo_matrix((np.ones(len(F) * 3),
                           (np.r_[Fw[:, 0], Fw[:, 1], Fw[:, 2]], np.r_[Fw[:, 1], Fw[:, 2], Fw[:, 0]])),
                          shape=(nn, nn))
        _, lab = connected_components(a, directed=False)
        fl = lab[Fw[:, 0]]
        names = [f"c{i}" for i in range(fl.max() + 1)]

    raw_min, raw_max = V.min(0), V.max(0)
    s = TARGET / (raw_max - raw_min).max()
    V = (V - np.array([(raw_min[0] + raw_max[0]) / 2, raw_min[1], (raw_min[2] + raw_max[2]) / 2])) * s

    comps = []
    for c in range(fl.max() + 1):
        idx = np.where(fl == c)[0]
        if len(idx) == 0:
            continue
        vs = np.unique(F[idx].ravel())
        P = V[vs]
        comps.append(Comp(len(comps), names[c] if c < len(names) else f"c{c}", len(idx), P.min(0), P.max(0), vs))
        fl[idx] = len(comps) - 1
    m = Model()
    m.V, m.F, m.N, m.fl, m.comps, m.scale, m.color = V, F, N, fl, comps, s, color
    m.raw_min, m.raw_max = raw_min, raw_max
    return m


def _gap(a_min, a_max, b_min, b_max):
    d = np.maximum(0, np.maximum(a_min - b_max, b_min - a_max))
    return float(np.linalg.norm(d))


def auto_group(m, max_groups=14):
    """Generic heuristic grouping. Returns {name: [component ids]}."""
    C = m.comps; L = TARGET
    tiny = [c for c in C if c.ext.max() < 0.03 * L and c.faces < 60]
    tiny_ids = {c.id for c in tiny}
    big = [c for c in C if c.id not in tiny_ids]
    if not big:
        big, tiny, tiny_ids = C, [], set()
    groups = []
    used = set()
    # 1) sets of repeated shapes (slats, screws...) that are spatially connected
    sig = {}
    for c in big:
        e = np.sort(c.ext)[::-1]
        key = (tuple(np.round(e / L * 50).astype(int)), int(np.argmax(c.ext)))
        sig.setdefault(key, []).append(c)
    for cs in sig.values():
        if len(cs) < 3:
            continue
        cens = np.array([c.cen for c in cs])
        tree = cKDTree(cens)
        d, _ = tree.query(cens, k=2)
        eps = 3.0 * np.median(d[:, 1])
        pairs = tree.query_pairs(eps, output_type="ndarray")
        n = len(cs)
        if len(pairs) == 0:
            continue
        a = sp.coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(n, n))
        k, lab = connected_components(a, directed=False)
        for j in range(k):
            mem = [cs[i] for i in np.where(lab == j)[0]]
            if len(mem) >= 3:
                groups.append([c.id for c in mem]); used.update(c.id for c in mem)
    # 2) every remaining big component alone
    for c in big:
        if c.id not in used:
            groups.append([c.id])
    # 3) tiny pieces join nearest big group
    comp2g = {cid: gi for gi, g in enumerate(groups) for cid in g}
    if tiny:
        pts, own = [], []
        for c in big:
            P = m.V[c.vs]; pts.append(P); own += [c.id] * len(P)
        tree = cKDTree(np.vstack(pts)); own = np.array(own)
        for c in tiny:
            _, i = tree.query(c.cen)
            groups[comp2g[own[i]]].append(c.id)

    def bbox(g):
        return (np.min([C[i].bmin for i in g], 0), np.max([C[i].bmax for i in g], 0))
    # 4) merge smallest group into its nearest neighbour until <= max_groups
    while len(groups) > max_groups:
        vol = [np.prod(np.maximum(bbox(g)[1] - bbox(g)[0], 1e-3)) for g in groups]
        i = int(np.argmin(vol)); bi = bbox(groups[i])
        best, bj = None, None
        for j, g in enumerate(groups):
            if j == i: continue
            bj_ = bbox(g)
            score = (_gap(*bi, *bj_), float(np.linalg.norm((bi[0] + bi[1]) / 2 - (bj_[0] + bj_[1]) / 2)))
            if best is None or score < best:
                best, bj = score, j
        groups[bj] += groups[i]; del groups[i]

    out = {}
    for g in groups:
        mn, mx = bbox(g); cen = (mn + mx) / 2
        v = "low" if cen[1] < 0.3 * L else ("mid" if cen[1] < 0.65 * L else "high")
        h = "left" if cen[0] < -0.25 * L else ("right" if cen[0] > 0.25 * L else "centre")
        z = "back" if cen[2] < -0.12 * L else ("front" if cen[2] > 0.12 * L else "mid")
        base = f"{v}_{h}_{z}"; name = base; k = 2
        while name in out:
            name = f"{base}_{k}"; k += 1
        out[name] = sorted(g)
    return out


def group_bbox(m, ids):
    return (np.min([m.comps[i].bmin for i in ids], 0), np.max([m.comps[i].bmax for i in ids], 0))
