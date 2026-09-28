import argparse, os, sys, tempfile
from pathlib import Path


def _name(p): return Path(p).stem.replace("_", " ").replace("-", " ") if p else "Model"


def _prepare(a):
    from . import model, leaflet, plan as P
    print("Loading model ..."); m = model.load_glb(a.glb)
    print(f"  {len(m.comps)} separate components, {len(m.F)} triangles")
    info = None
    if getattr(a, "leaflet", None):
        print("Reading leaflet ..."); info = leaflet.parse(a.leaflet)
        print(f"  {len(info['steps'])} numbered steps found ({info['steps'][0] if info['steps'] else '-'}\u2013{info['steps'][-1] if info['steps'] else '-'})")
    if getattr(a, "plan", None) and os.path.exists(a.plan):
        print(f"Using plan {a.plan}"); pl = P.load(a.plan)
    else:
        pl = P.make_plan(m, info, a.preset, a.max_groups, os.path.basename(a.glb), os.path.basename(a.leaflet) if a.leaflet else "")
        print(f"Auto-grouped into {len(pl['groups'])} parts / {len(pl['stages'])} stages")
    return m, info, pl


def cmd_analyze(a):
    from . import plan as P
    m, info, pl = _prepare(a)
    out = a.output or "plan.json"; P.save(pl, out)
    print(f"\nWrote {out}. Edit it (stage titles, order, which parts belong together, entry directions),")
    print("then run:  assemblyvid build MODEL.glb LEAFLET.pdf --plan", out)


def cmd_build(a):
    from . import plan as P, render
    m, info, pl = _prepare(a)
    if a.pace: pl.setdefault("settings", {})["pace"] = a.pace
    if a.color: pl.setdefault("settings", {})["color"] = a.color
    if not (a.plan and os.path.exists(a.plan)):
        side = Path(a.output).with_suffix(".plan.json"); P.save(pl, side); print(f"Saved editable plan: {side}")
    w, h = a.width, a.height
    tl = P.timeline(m, pl, a.leaflet, pip=not a.no_pip, width=w, height=h)
    geoms = P.geometry(m, pl, tl["groups"])
    with tempfile.TemporaryDirectory() as d:
        html = render.make_html(tl, geoms, _name(a.glb), d)
        if a.frame is not None:
            out = Path(a.output).with_suffix(".png"); render.render_frame(html, a.frame, out, w, h); print("Wrote", out); return
        print(f"Video: {tl['dur']:.1f}s at {a.fps} fps, {w}x{h}")
        render.render_video(html, a.output, a.fps, w, h, tl["dur"])
    print("Done:", a.output)


def cmd_doctor(a):
    ok = True
    for mod in ["numpy", "scipy", "trimesh", "DracoPy", "pypdfium2", "PIL", "playwright", "imageio_ffmpeg"]:
        try: __import__(mod); print("ok     ", mod)
        except Exception as e: ok = False; print("MISSING", mod, "-", e)
    try:
        from playwright.sync_api import sync_playwright
        from .render import CHROME_ARGS
        with sync_playwright() as pw: pw.chromium.launch(args=CHROME_ARGS).close()
        print("ok      chromium (playwright)")
    except Exception as e:
        ok = False; print("MISSING chromium - run: playwright install chromium\n", str(e)[:200])
    print("\nAll good." if ok else "\nFix the items above and re-run.")


def main():
    ap = argparse.ArgumentParser(prog="assemblyvid", description="GLB model + assembly leaflet PDF -> assembly animation video")
    sub = ap.add_subparsers(dest="cmd", required=True)
    def common(p):
        p.add_argument("glb"); p.add_argument("leaflet", nargs="?", help="assembly leaflet PDF (optional but recommended)")
        p.add_argument("--plan", help="edited plan.json to use instead of auto-grouping")
        p.add_argument("--preset", choices=["auto", "myllra"], default="auto", help="'myllra' = hand-tuned grouping for the IKEA MYLLRA crib")
        p.add_argument("--max-groups", type=int, default=14)
    p1 = sub.add_parser("analyze", help="write an editable plan.json"); common(p1); p1.add_argument("-o", "--output"); p1.set_defaults(fn=cmd_analyze)
    p2 = sub.add_parser("build", help="render the video"); common(p2)
    p2.add_argument("-o", "--output", default="assembly.mp4"); p2.add_argument("--fps", type=int, default=24)
    p2.add_argument("--width", type=int, default=1280); p2.add_argument("--height", type=int, default=720)
    p2.add_argument("--pace", type=float, help="animation speed multiplier (2 = twice as fast)")
    p2.add_argument("--color", help="model colour as #rrggbb (default light off-white)")
    p2.add_argument("--no-pip", action="store_true", help="don't show the leaflet page thumbnail")
    p2.add_argument("--frame", type=float, help="render a single PNG at this time (seconds) instead of a video")
    p2.set_defaults(fn=cmd_build)
    p3 = sub.add_parser("doctor", help="check the installation"); p3.set_defaults(fn=cmd_doctor)
    a = ap.parse_args(); a.fn(a)


if __name__ == "__main__":
    main()
