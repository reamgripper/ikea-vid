"""Desktop file-picker UI for assemblyvid: point at a GLB and a leaflet PDF, then
Analyze (write an editable plan.json) or Build (render the video) - no command line needed.
Build first opens a Review step (bill of materials + a keyframe per stage, editable
titles/text) and only renders the video once that's approved.
"""
import io, os, queue, shutil, sys, tempfile, threading, tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from types import SimpleNamespace

from PIL import Image, ImageTk

_DONE = object()
_REVIEW_TAG = "__REVIEW__"


class _QueueWriter:
    def __init__(self, q): self.q = q
    def write(self, s):
        if s: self.q.put(s)
    def flush(self): pass


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("assemblyvid")
        self.minsize(680, 560)

        self.glb_path = tk.StringVar()
        self.pdf_path = tk.StringVar()
        self.plan_path = tk.StringVar()
        self.video_output = tk.StringVar(value=str(Path.cwd() / "assembly.mp4"))
        self.plan_output = tk.StringVar(value=str(Path.cwd() / "plan.json"))
        self.preset = tk.StringVar(value="auto")
        self.max_groups = tk.IntVar(value=14)
        self.fps = tk.IntVar(value=24)
        self.width = tk.IntVar(value=1280)
        self.height = tk.IntVar(value=720)
        self.pace = tk.StringVar()
        self.color = tk.StringVar()
        self.no_pip = tk.BooleanVar(value=False)
        self.frame = tk.StringVar()

        self._q = queue.Queue()
        self._worker = None
        self._review_win = None
        self._build_ui()
        self.after(100, self._drain_log)

    def _browse_row(self, parent, r, label, var, dialog):
        ttk.Label(parent, text=label).grid(row=r, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(parent, textvariable=var).grid(row=r, column=1, sticky="we", padx=6, pady=4)
        ttk.Button(parent, text="Browse…", command=lambda: dialog(var)).grid(row=r, column=2, padx=6, pady=4)

    def _pick_open(self, var, title, filetypes):
        p = filedialog.askopenfilename(title=title, filetypes=filetypes)
        if p: var.set(p)

    def _pick_save(self, var, title, defaultextension, filetypes):
        p = filedialog.asksaveasfilename(title=title, defaultextension=defaultextension, filetypes=filetypes)
        if p: var.set(p)

    def _build_ui(self):
        pad = {"padx": 8, "pady": 6}

        files = ttk.LabelFrame(self, text="Source files")
        files.pack(fill="x", **pad)
        files.columnconfigure(1, weight=1)
        self._browse_row(files, 0, "GLB model (.glb)", self.glb_path,
                          lambda v: self._pick_open(v, "Choose GLB model", [("GLB model", "*.glb"), ("All files", "*.*")]))
        self._browse_row(files, 1, "Leaflet (.pdf, optional)", self.pdf_path,
                          lambda v: self._pick_open(v, "Choose leaflet PDF", [("PDF", "*.pdf"), ("All files", "*.*")]))
        self._browse_row(files, 2, "Plan (.json, optional - reuse an edited plan)", self.plan_path,
                          lambda v: self._pick_open(v, "Choose plan.json", [("JSON", "*.json"), ("All files", "*.*")]))

        opts = ttk.LabelFrame(self, text="Options")
        opts.pack(fill="x", **pad)
        ttk.Label(opts, text="Preset").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Combobox(opts, textvariable=self.preset, values=["auto", "myllra"], width=10, state="readonly").grid(row=0, column=1, sticky="w")
        ttk.Label(opts, text="Max groups").grid(row=0, column=2, sticky="w", padx=6)
        ttk.Spinbox(opts, from_=1, to=64, textvariable=self.max_groups, width=6).grid(row=0, column=3, sticky="w")

        ttk.Label(opts, text="FPS").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        ttk.Spinbox(opts, from_=1, to=60, textvariable=self.fps, width=6).grid(row=1, column=1, sticky="w")
        ttk.Label(opts, text="Width").grid(row=1, column=2, sticky="w", padx=6)
        ttk.Spinbox(opts, from_=160, to=3840, textvariable=self.width, width=8).grid(row=1, column=3, sticky="w")
        ttk.Label(opts, text="Height").grid(row=1, column=4, sticky="w", padx=6)
        ttk.Spinbox(opts, from_=90, to=2160, textvariable=self.height, width=8).grid(row=1, column=5, sticky="w")

        ttk.Label(opts, text="Pace").grid(row=2, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(opts, textvariable=self.pace, width=8).grid(row=2, column=1, sticky="w")
        ttk.Label(opts, text="Color #rrggbb").grid(row=2, column=2, sticky="w", padx=6)
        ttk.Entry(opts, textvariable=self.color, width=10).grid(row=2, column=3, sticky="w")
        ttk.Checkbutton(opts, text="Hide leaflet thumbnail", variable=self.no_pip).grid(row=2, column=4, columnspan=2, sticky="w")

        ttk.Label(opts, text="Single frame at (s, optional)").grid(row=3, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(opts, textvariable=self.frame, width=8).grid(row=3, column=1, sticky="w")

        out = ttk.LabelFrame(self, text="Output")
        out.pack(fill="x", **pad)
        out.columnconfigure(1, weight=1)
        self._browse_row(out, 0, "Video (Build writes here)", self.video_output,
                          lambda v: self._pick_save(v, "Video output", ".mp4", [("MP4 video", "*.mp4"), ("All files", "*.*")]))
        self._browse_row(out, 1, "Plan (Analyze writes here)", self.plan_output,
                          lambda v: self._pick_save(v, "Plan output", ".json", [("JSON", "*.json"), ("All files", "*.*")]))

        btns = ttk.Frame(self)
        btns.pack(fill="x", **pad)
        self.analyze_btn = ttk.Button(btns, text="Analyze → write plan.json", command=self._run_analyze)
        self.analyze_btn.pack(side="left", padx=4)
        self.build_btn = ttk.Button(btns, text="Review & build video…", command=self._run_build)
        self.build_btn.pack(side="left", padx=4)
        self.doctor_btn = ttk.Button(btns, text="Check install", command=self._run_doctor)
        self.doctor_btn.pack(side="left", padx=4)

        log_frame = ttk.LabelFrame(self, text="Log")
        log_frame.pack(fill="both", expand=True, **pad)
        self.log = tk.Text(log_frame, height=16, wrap="word", state="disabled")
        self.log.pack(fill="both", expand=True, side="left")
        sb = ttk.Scrollbar(log_frame, command=self.log.yview)
        sb.pack(fill="y", side="right")
        self.log.configure(yscrollcommand=sb.set)

    def _append_log(self, s):
        self.log.configure(state="normal")
        self.log.insert("end", s)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _drain_log(self):
        try:
            while True:
                item = self._q.get_nowait()
                if item is _DONE:
                    self._set_running(False)
                elif isinstance(item, tuple) and item[0] == _REVIEW_TAG:
                    self._open_review(item[1])
                else:
                    self._append_log(item)
        except queue.Empty:
            pass
        self.after(100, self._drain_log)

    def _set_running(self, running):
        state = "disabled" if running else "normal"
        for b in (self.analyze_btn, self.build_btn, self.doctor_btn):
            b.configure(state=state)

    def _start(self, fn):
        if self._worker and self._worker.is_alive():
            messagebox.showinfo("Busy", "A job is already running.")
            return
        self._append_log("\n")
        self._set_running(True)

        def target():
            old = sys.stdout
            sys.stdout = _QueueWriter(self._q)
            try:
                fn()
            except SystemExit as e:
                self._q.put(f"\n{e}\n")
            except Exception as e:
                self._q.put(f"\nError: {e}\n")
            finally:
                sys.stdout = old
                self._q.put("--- done ---\n")
                self._q.put(_DONE)

        self._worker = threading.Thread(target=target, daemon=True)
        self._worker.start()

    def _args(self, output):
        glb = self.glb_path.get().strip()
        if not glb:
            messagebox.showerror("Missing file", "Choose a GLB model first.")
            return None
        pace = self.pace.get().strip()
        color = self.color.get().strip()
        frame = self.frame.get().strip()
        try:
            pace_v = float(pace) if pace else None
            frame_v = float(frame) if frame else None
        except ValueError:
            messagebox.showerror("Invalid value", "Pace and frame time must be numbers.")
            return None
        return SimpleNamespace(
            glb=glb,
            leaflet=self.pdf_path.get().strip() or None,
            plan=self.plan_path.get().strip() or None,
            output=output,
            preset=self.preset.get(),
            max_groups=self.max_groups.get(),
            fps=self.fps.get(),
            width=self.width.get(),
            height=self.height.get(),
            pace=pace_v,
            color=color or None,
            no_pip=self.no_pip.get(),
            frame=frame_v,
        )

    def _run_analyze(self):
        a = self._args(self.plan_output.get().strip() or "plan.json")
        if a is None: return
        from .cli import cmd_analyze
        self._start(lambda: cmd_analyze(a))

    def _run_build(self):
        a = self._args(self.video_output.get().strip() or "assembly.mp4")
        if a is None: return
        self._start(lambda: self._prepare_review(a))

    def _run_doctor(self):
        from .cli import cmd_doctor
        self._start(lambda: cmd_doctor(None))

    def _prepare_review(self, a):
        """Runs in the worker thread: load model/leaflet, build (or load) the plan,
        then render one keyframe per stage and collect the bill of materials so the
        user can review and edit before any video is rendered."""
        from . import leaflet, model
        from . import plan as P
        from . import render
        from .cli import _name

        print("Loading model ..."); m = model.load_glb(a.glb)
        print(f"  {len(m.comps)} separate components, {len(m.F)} triangles")
        info = None
        if a.leaflet:
            print("Reading leaflet ..."); info = leaflet.parse(a.leaflet)
            print(f"  {len(info['steps'])} numbered steps found")
        if a.plan and os.path.exists(a.plan):
            print(f"Using plan {a.plan}"); pl = P.load(a.plan)
        else:
            pl = P.make_plan(m, info, a.preset, a.max_groups, os.path.basename(a.glb), os.path.basename(a.leaflet) if a.leaflet else "")
            print(f"Auto-grouped into {len(pl['groups'])} parts / {len(pl['stages'])} stages")
        pl.setdefault("settings", {})
        if a.pace: pl["settings"]["pace"] = a.pace
        if a.color: pl["settings"]["color"] = a.color

        print("Rendering keyframe previews for review ...")
        tl = P.timeline(m, pl, a.leaflet, pip=not a.no_pip, width=a.width, height=a.height)
        geoms = P.geometry(m, pl, tl["groups"])
        tmp_dir = tempfile.mkdtemp(prefix="assemblyvid_review_")
        html = render.make_html(tl, geoms, _name(a.glb), tmp_dir)
        n = len(pl["stages"])
        times = [max(0.0, tl["stages"][i]["b"] - 0.05) for i in range(n)]
        pw = max(240, min(480, a.width)); ph = round(pw * a.height / a.width)
        images = render.render_keyframes(html, times, pw, ph)

        bom = []
        if info and info.get("steps"):
            bom = leaflet.hardware_for(info, info["steps"][0], info["steps"][-1])
        print(f"Ready for review: {n} stages.")
        self._q.put((_REVIEW_TAG, dict(args=a, plan=pl, images=images, bom=bom, tmp_dir=tmp_dir)))

    def _open_review(self, data):
        if self._review_win is not None and self._review_win.winfo_exists():
            self._review_win.destroy()

        plan, images, bom, args, tmp_dir = data["plan"], data["images"], data["bom"], data["args"], data["tmp_dir"]
        thumb_refs = []

        win = tk.Toplevel(self)
        self._review_win = win
        win.title("Review plan — approve to render the video")
        win.geometry("760x640")
        win.transient(self)

        def on_cancel():
            shutil.rmtree(tmp_dir, ignore_errors=True)
            win.destroy()
        win.protocol("WM_DELETE_WINDOW", on_cancel)

        bom_frame = ttk.LabelFrame(win, text="Bill of materials (hardware)")
        bom_frame.pack(fill="x", padx=8, pady=6)
        bom_text = ", ".join(bom) if bom else "No leaflet hardware detected (no PDF chosen, or none matched)."
        ttk.Label(bom_frame, text=bom_text, wraplength=720, justify="left").pack(anchor="w", padx=6, pady=4)

        canvas = tk.Canvas(win, borderwidth=0, highlightthickness=0)
        vsb = ttk.Scrollbar(win, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="top", fill="both", expand=True, padx=(8, 0), pady=6)
        scroll_frame = ttk.Frame(canvas)
        canvas_window = canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(canvas_window, width=e.width))

        title_vars, text_widgets = [], []
        for i, st in enumerate(plan["stages"]):
            row = ttk.Frame(scroll_frame, relief="groove", borderwidth=1)
            row.pack(fill="x", padx=4, pady=4)
            row.columnconfigure(1, weight=1)

            photo = ImageTk.PhotoImage(Image.open(io.BytesIO(images[i])))
            thumb_refs.append(photo)
            ttk.Label(row, image=photo).grid(row=0, column=0, rowspan=4, padx=6, pady=6)

            steps = st.get("steps")
            steps_txt = (f"Steps {steps[0]}–{steps[1]}" if steps else f"Stage {i + 1}")
            if st.get("steps_estimated"): steps_txt += " (est.)"
            ttk.Label(row, text=steps_txt, font=("TkDefaultFont", 9, "italic")).grid(row=0, column=1, sticky="w", padx=6, pady=(6, 0))

            tv = tk.StringVar(value=st.get("title", "")); title_vars.append(tv)
            ttk.Entry(row, textvariable=tv).grid(row=1, column=1, sticky="we", padx=6)

            txt = tk.Text(row, height=2, wrap="word"); txt.insert("1.0", st.get("text", ""))
            txt.grid(row=2, column=1, sticky="we", padx=6, pady=(2, 2)); text_widgets.append(txt)

            hw = st.get("hardware") or []
            if hw:
                ttk.Label(row, text="Hardware: " + ", ".join(hw), foreground="#666").grid(row=3, column=1, sticky="w", padx=6, pady=(0, 6))

        # keep the PhotoImage objects alive for the life of the window
        win._thumb_refs = thumb_refs

        def approve():
            for st, tv, txt in zip(plan["stages"], title_vars, text_widgets):
                st["title"] = tv.get().strip() or st["title"]
                st["text"] = txt.get("1.0", "end-1c").strip()
            from . import plan as P
            plan_path = args.plan or str(Path(args.output).with_suffix(".plan.json"))
            P.save(plan, plan_path)
            self._append_log(f"Approved. Saved reviewed plan to {plan_path}\n")
            shutil.rmtree(tmp_dir, ignore_errors=True)
            win.destroy()
            new_args = SimpleNamespace(**vars(args)); new_args.plan = plan_path
            from .cli import cmd_build
            self._start(lambda: cmd_build(new_args))

        btns = ttk.Frame(win)
        btns.pack(fill="x", padx=8, pady=8)
        ttk.Button(btns, text="Cancel", command=on_cancel).pack(side="right", padx=4)
        ttk.Button(btns, text="Approve & render video", command=approve).pack(side="right", padx=4)


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
