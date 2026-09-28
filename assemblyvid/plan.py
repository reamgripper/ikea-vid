"""Build/edit the assembly plan (groups, stages, captions) and turn it into a timed animation description."""
import json, math
import numpy as np
from . import model as M
from . import leaflet as LF
from . import presets


def auto_entry(m, ids):
    mn, mx = M.group_bbox(m, ids); c = (mn + mx) / 2; L = M.TARGET
    d = c - np.array([0.0, 0.5 * L * 0.72, 0.0])
    horiz = np.array([d[0], 0, d[2]]); hn = np.linalg.norm(horiz)
    if hn > 0.22 * L and hn > abs(d[1]) * 0.8:
        v = horiz / hn * 0.8
        return [float(v[0]), 0.15, float(v[2])]
    return [0.0, 0.7 if d[1] >= 0 else -0.5, 0.0]


def _order_key(m, ids):
    mn, mx = M.group_bbox(m, ids); c = (mn + mx) / 2
    return (round(float(mn[1]) / (0.12 * M.TARGET)), float(np.hypot(c[0], c[2])))


def make_plan(m, leaflet_info=None, preset=None, max_groups=14, glb_name="", leaflet_name=""):
    entry = {}
    if preset == "myllra":
        groups, stages, entry = presets.myllra(m)
    else:
        groups = M.auto_group(m, max_groups)
        names = sorted(groups, key=lambda g: _order_key(m, groups[g]))
        stages = [dict(title=f"Add part {i + 1} of {len(names)}", text=f"Position the {g.replace('_', ' ')} part.", steps=None, groups=[g])
                  for i, g in enumerate(names)]
    plan = dict(version=1, glb=glb_name, leaflet=leaflet_name,
                groups={g: dict(components=ids, entry=entry.get(g) or auto_entry(m, ids)) for g, ids in groups.items()},
                stages=stages, settings=dict(pace=1.0))
    if leaflet_info and leaflet_info["steps"]:
        steps = leaflet_info["steps"]; n = len(stages)
        for i, st in enumerate(stages):
            if not st.get("steps"):
                a = steps[int(i * len(steps) / n)]; b = steps[max(int((i + 1) * len(steps) / n) - 1, int(i * len(steps) / n))]
                st["steps"] = [a, b]; st["steps_estimated"] = True
            st["hardware"] = LF.hardware_for(leaflet_info, *st["steps"])
            st["page"] = LF.step_page(leaflet_info, st["steps"][0])
    return plan


def timeline(m, plan, leaflet_pdf=None, pip=True, width=1280, height=720):
    """Return the JSON-able dict consumed by the browser viewer (without geometry)."""
    pace = float(plan.get("settings", {}).get("pace", 1.0)) or 1.0
    L = M.TARGET
    DIS0, DIS1 = 3.5 / pace, 5.0 / pace
    t = 5.2 / pace
    gt, stages_out, bboxes_seen = {}, [], []
    cam = []
    full_mn = np.min([c.bmin for c in m.comps], 0); full_mx = np.max([c.bmax for c in m.comps], 0)
    n_st = len(plan["stages"])
    cam.append([0, 0.75, 1.2, 3.4, 0, 0.42 * L / 1.0 * 0.85, 0])
    for k, st in enumerate(plan["stages"]):
        a0 = t
        ends = []
        stage_boxes = []
        for j, g in enumerate(st["groups"]):
            a = t + 0.4 * j / pace; b = a + 1.9 / pace
            gt[g] = (a, b); ends.append(b)
            ids = plan["groups"][g]["components"]
            mn, mx = M.group_bbox(m, ids); off = np.array(plan["groups"][g]["entry"], dtype=float)
            stage_boxes += [(mn, mx), (mn + off * 0.6, mx + off * 0.6)]
        b0 = max(ends) + 0.5 / pace
        bboxes_seen += stage_boxes
        mn = np.min([b[0] for b in bboxes_seen], 0); mx = np.max([b[1] for b in bboxes_seen], 0)
        c = (mn + mx) / 2; diag = float(np.linalg.norm(mx - mn))
        r = max(2.4, 2.1 * diag + 0.35)
        theta = 0.55 + 1.5 * k / max(1, n_st - 1)
        cam.append([(a0 + b0) / 2, theta, 1.1, r, float(c[0]), float(c[1]), float(c[2])])
        img = None
        if pip and leaflet_pdf and st.get("page") is not None:
            try: img = LF.render_page(leaflet_pdf, st["page"])
            except Exception: img = None
        s = st.get("steps")
        step_txt = (f"STEP {s[0]}" if s and s[0] == s[1] else f"STEPS {s[0]}\u2013{s[1]}") if s else f"STAGE {k + 1} / {n_st}"
        if st.get("steps_estimated"): step_txt += " (est.)"
        stages_out.append(dict(a=a0, b=b0, step=step_txt, title=st["title"], text=st["text"], hw=st.get("hardware") or [], img=img))
        t = b0 + 0.1 / pace
    end_build = t
    stages_out.append(dict(a=end_build + 0.3, b=end_build + 7.5 / pace, step="DONE", title="Assembly complete",
                           text="Your model is fully assembled.", hw=[], img=None))
    dur = end_build + 7.5 / pace
    cam.append([end_build + 0.3, cam[-1][1] + 0.2, 1.1, 3.4, 0, 0.5, 0])
    cam.append([dur, cam[-1][1] + math.pi * 2, 1.1, 3.4, 0, 0.5, 0])
    groups_out = {g: dict(a=gt[g][0], b=gt[g][1], off=plan["groups"][g]["entry"], spin=plan["groups"][g].get("spin", 0)) for g in gt}
    return dict(dur=dur, dis0=DIS0, dis1=DIS1, stages=stages_out, cam=cam, groups=groups_out,
                width=width, height=height, leaflet_name=plan.get("leaflet", ""))


def geometry(m, plan, groups_out):
    import base64
    out = []
    default = "#e6e2d9"
    for g, spec in plan["groups"].items():
        if g not in groups_out: continue
        mask = np.isin(m.fl, spec["components"])
        f = m.F[mask]
        vs, inv = np.unique(f.ravel(), return_inverse=True)
        b = lambda arr: base64.b64encode(arr.tobytes()).decode()
        col = plan.get("settings", {}).get("color", default)
        d = dict(name=g, p=b(m.V[vs].astype(np.float32)), n=b(m.N[vs].astype(np.float32)),
                 i=b(inv.reshape(-1, 3).astype(np.uint32)), color=col)
        d.update(groups_out[g]); out.append(d)
    return out


def save(plan, path):
    with open(path, "w", encoding="utf-8") as f: json.dump(plan, f, indent=1)


def load(path):
    with open(path, encoding="utf-8") as f: return json.load(f)
