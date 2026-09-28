"""Read an IKEA-style assembly leaflet PDF: step numbers, hardware part numbers + quantities, page images."""
import re, io, base64
from collections import defaultdict

PART = re.compile(r"^\d{5,8}$")
QTY = re.compile(r"^(\d{1,3})x$", re.I)
INT = re.compile(r"^\d{1,2}$")


def _center(w): return ((w["x0"] + w["x1"]) / 2, (w["top"] + w["bottom"]) / 2)


def _words(page):
    """Words with position and font size, restricted to the visible page area (rotated text handled by PDFium)."""
    tp = page.get_textpage()
    W, H = page.get_size()
    n = tp.count_chars()
    words, cur = [], []

    def flush():
        if not cur: return
        txt = "".join(c[0] for c in cur)
        l = min(c[1] for c in cur); b = min(c[2] for c in cur); r = max(c[3] for c in cur); t = max(c[4] for c in cur)
        words.append(dict(text=txt, x0=l, x1=r, top=H - t, bottom=H - b, size=max(c[5] for c in cur)))
        cur.clear()
    for i in range(n):
        ch = tp.get_text_range(i, 1)
        if not ch or ch.isspace():
            flush(); continue
        l, b, r, t = tp.get_charbox(i)
        size = t - b  # glyph box height (font-size metadata is unreliable in some PDFs)
        inside = -2 <= (l + r) / 2 <= W + 2 and -2 <= (b + t) / 2 <= H + 2
        if not inside:
            flush(); continue
        cur.append((ch, l, b, r, t, size))
    flush()
    return words


def parse(path):
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(path)
    pages = []
    for pi in range(len(pdf)):
        words = _words(pdf[pi])
        cand = sorted({int(w["text"]) for w in words if INT.match(w["text"]) and w["size"] >= 22})
        partw = [w for w in words if PART.match(w["text"])]
        qtyw = [w for w in words if QTY.match(w["text"])]
        parts = defaultdict(int)
        for q in qtyw:
            if not partw: break
            qc = _center(q)
            best = min(partw, key=lambda p: (_center(p)[0] - qc[0]) ** 2 + (_center(p)[1] - qc[1]) ** 2)
            bc = _center(best)
            if ((bc[0] - qc[0]) ** 2 + (bc[1] - qc[1]) ** 2) ** 0.5 < 160:
                parts[best["text"]] += int(QTY.match(q["text"]).group(1))
        for p in partw:
            parts.setdefault(p["text"], 0)
        pages.append(dict(index=pi, cand=cand, steps=[], parts=dict(parts), inventory=len({p["text"] for p in partw}) >= 6, appendix=False))
    # main step sequence: strictly increasing; a page whose numbers restart marks the appendix
    last, appendix = 0, False
    for p in pages:
        if appendix:
            p["appendix"] = True; continue
        acc, cur = [], last
        for s_ in p["cand"]:
            if cur < s_ <= cur + 8:
                acc.append(s_); cur = s_
        if p["cand"] and not acc and last >= 5:
            appendix = True; p["appendix"] = True; continue
        p["steps"] = acc
        if acc: last = max(acc)
    main = sorted({s_ for p in pages if not p["appendix"] for s_ in p["steps"]})
    return dict(pages=pages, steps=main, name=path.replace("\\", "/").split("/")[-1])


def step_page(info, step):
    for p in info["pages"]:
        if not p["appendix"] and step in p["steps"]:
            return p["index"]
    return None


def hardware_for(info, a, b):
    """Aggregate hardware (part number, qty) for step range [a,b], skipping inventory pages."""
    tot = defaultdict(int); seen = set()
    for p in info["pages"]:
        if p["appendix"] or p["inventory"]: continue
        if any(a <= s <= b for s in p["steps"]):
            for k, v in p["parts"].items():
                tot[k] += v; seen.add(k)
    out = []
    for k in sorted(tot, key=lambda k: -tot[k]):
        out.append(f"{tot[k]}\u00d7 {k}" if tot[k] else k)
    return out[:6]


def render_page(path, index, height=300, quality=80):
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(path)
    page = pdf[index]
    scale = height / page.get_height()
    img = page.render(scale=scale).to_pil().convert("RGB")
    buf = io.BytesIO(); img.save(buf, "JPEG", quality=quality)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
