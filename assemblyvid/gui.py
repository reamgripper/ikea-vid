"""Desktop file-picker UI for assemblyvid: point at a GLB and a leaflet PDF, then
Analyze (write an editable plan.json) or Build (render the video) - no command line needed.
"""
import queue, sys, threading, tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from types import SimpleNamespace

_DONE = object()


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
        self.build_btn = ttk.Button(btns, text="Build video", command=self._run_build)
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
        from .cli import cmd_build
        self._start(lambda: cmd_build(a))

    def _run_doctor(self):
        from .cli import cmd_doctor
        self._start(lambda: cmd_doctor(None))


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
