import json, os, shutil, subprocess, sys, tempfile, time
from importlib import resources
from pathlib import Path

WEB = Path(__file__).parent / "web"
CHROME_ARGS = ["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist", "--ignore-certificate-errors",
               "--enable-unsafe-swiftshader"]


def ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        exe = shutil.which("ffmpeg")
        if not exe: raise SystemExit("ffmpeg not found. Run: pip install imageio-ffmpeg")
        return exe


def make_html(tl, geoms, title, out_dir):
    tpl = (WEB / "viewer.html").read_text(encoding="utf-8")
    three = (WEB / "three.min.js").read_text(encoding="utf-8")
    data = dict(tl); data["geoms"] = geoms; data["title"] = title
    html = tpl.replace("__THREE__", three).replace("__PLAN__", json.dumps(data))
    p = Path(out_dir) / "viewer.html"; p.write_text(html, encoding="utf-8"); return p


def render_frame(html_path, t, png_path, width, height):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch(args=CHROME_ARGS)
        pg = b.new_page(viewport={"width": width, "height": height})
        pg.goto(html_path.as_uri()); pg.wait_for_function("window.READY===true", timeout=60000)
        pg.evaluate(f"setT({t})"); pg.screenshot(path=str(png_path)); b.close()


def render_video(html_path, out, fps, width, height, dur, quality=20):
    from playwright.sync_api import sync_playwright
    n = int(dur * fps)
    cmd = [ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(fps), "-c:v", "mjpeg", "-i", "-",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", str(quality), "-preset", "medium", "-movflags", "+faststart", str(out)]
    ff = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    t0 = time.time()
    with sync_playwright() as pw:
        b = pw.chromium.launch(args=CHROME_ARGS)
        pg = b.new_page(viewport={"width": width, "height": height})
        pg.goto(html_path.as_uri()); pg.wait_for_function("window.READY===true", timeout=120000)
        for i in range(n + 1):
            pg.evaluate(f"setT({min(i / fps, dur - 0.001)})")
            ff.stdin.write(pg.screenshot(type="jpeg", quality=92))
            if i % 10 == 0 or i == n:
                el = time.time() - t0; eta = el / (i + 1) * (n - i)
                print(f"\rrendering frame {i}/{n}  ({100 * i // n}%)  ETA {int(eta // 60)}m{int(eta % 60):02d}s ", end="", flush=True)
        b.close()
    ff.stdin.close(); ff.wait(); print()
    if ff.returncode: raise SystemExit("ffmpeg failed")
