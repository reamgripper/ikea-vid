# assemblyvid

Feed it a **3D model (.glb)** and an **IKEA-style assembly leaflet (.pdf)** and it renders an **assembly animation video (.mp4)**:
the finished product comes apart, then rebuilds part by part, with captions, the leaflet step numbers, the hardware
part numbers/quantities read from the leaflet, and a thumbnail of the matching leaflet page.

Everything runs locally. Nothing is uploaded.

## Install (Windows / macOS / Linux)

Requires Python 3.9+.

    python -m venv .venv
    # Windows:  .venv\Scripts\activate      macOS/Linux:  source .venv/bin/activate
    pip install .
    playwright install chromium
    assemblyvid doctor          # checks everything is in place

(`install.sh` / `install.bat` do the same steps.)

## Use

    assemblyvid build model.glb leaflet.pdf -o crib.mp4

Useful options: `--fps 24 --width 1280 --height 720 --pace 1.5 --color "#e8e4da" --no-pip`
Quick look at one moment instead of a whole video: `--frame 30` (writes a PNG).

### GUI

Prefer clicking through files instead of the command line? Run:

    assemblyvid-gui

This opens a desktop window with file pickers for the GLB model and leaflet PDF (and an
optional plan.json), the same options as the CLI, and buttons for **Analyze**, **Review &
build video**, and **Check install** - with the log shown live. Requires Tk (bundled with
the standard python.org installer on Windows/macOS; on Linux install `python3-tk`).

**Review & build video** doesn't render straight away: it first groups the parts, reads the
leaflet, and shows a review window with the aggregated bill of materials plus one keyframe
image per stage. You can edit each stage's title/text right there; the video is only
rendered once you click **Approve & render video** (or **Cancel** to back out without
rendering anything).

## Getting good results: the plan file

A GLB is usually one fused mesh with no part names, and a leaflet is mostly pictures, so the tool has to *guess*
which pieces belong together and in what order. `build` saves that guess next to the video as `<name>.plan.json`.
Edit it and re-run with `--plan`:

    assemblyvid analyze model.glb leaflet.pdf -o plan.json   # just write the plan
    # edit plan.json
    assemblyvid build model.glb leaflet.pdf --plan plan.json -o out.mp4

In `plan.json` you can change: stage `title` / `text`; `steps` (leaflet step range, marked "(est.)" until you set it);
which `groups` appear in which stage (stages play in order); each group's `components` (piece ids) and `entry`
(direction it flies in from, in model units); and `settings` (`pace`, `color`).

`--preset myllra` uses hand-tuned grouping for the IKEA MYLLRA crib (`examples/myllra_plan.json` is its plan).

## Limits (please read)

* Automatic grouping is a heuristic (repeated shapes such as slats are merged, small pieces attach to their nearest
  part, the smallest parts are merged until at most 14 remain). Expect to tweak the plan for a new product.
* Assembly order is estimated bottom-up, not read from the leaflet drawings. The tool reads the leaflet's *text*
  (step numbers, part numbers, quantities); it does not understand the pictures.
* Without a plan, leaflet steps are spread evenly across the stages (marked "est.").
* Fasteners are not animated individually unless they are separate pieces in your GLB.
* Rendering is software-based and slow: roughly 1 s per frame, so a 45 s video at 24 fps takes about 15-20 minutes.
* Your GLB may be Draco-compressed; that is handled. Y-up models (the glTF standard) are assumed.
