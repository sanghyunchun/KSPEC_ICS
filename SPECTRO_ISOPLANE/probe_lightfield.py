"""Probe the LightField Automation API from Python (pythonnet) on the LightField PC.

Run this once on the Windows PC before using the IsoPlane server. It checks what the server
assumes and writes everything it finds to a JSON report:

1. pythonnet loads the LightField assemblies (V5 or V4 names).
2. Automation starts LightField and returns the experiment.
3. Devices, saved experiments, and every Camera/Experiment/Spectrometer setting name with its
   current value (this settles the grating, file-name, export and time-stamp setting names).
4. Enum names used by the server (TimeStamps, ShutterTimingMode).
5. Whether a setting can be read from a thread other than the one that created Automation.
6. Optional (--acquire): one exposure with time stamps on, then the SPE time stamps.

The probe never changes the grating or the centre wavelength, and never saves the experiment.
With --acquire it changes the exposure time, time stamps, file name and export settings of the
loaded experiment for that one frame; check the shutter and lamps first.

usage (Windows, from the KSPEC_ICS root):
    python SPECTRO_ISOPLANE/probe_lightfield.py
    python SPECTRO_ISOPLANE/probe_lightfield.py --experiment KSPEC_600_430 --acquire --exptime-ms 100
"""

import argparse
import datetime as dt
import json
import os
import platform
import sys
import threading
import time
import traceback

DEFAULT_ROOT = r"C:\Program Files\Princeton Instruments\LightField"


def step(report, name):
    """Decorator-free helper: run fn, store its result or the traceback under report[name]."""

    def run(fn, *args):
        t0 = time.time()
        try:
            value = fn(*args)
            report[name] = {"ok": True, "value": value}
        except Exception:
            value = None
            report[name] = {"ok": False, "error": traceback.format_exc()}
        report[name]["seconds"] = round(time.time() - t0, 2)
        print(f"[{'ok' if report[name]['ok'] else 'FAIL'}] {name}", flush=True)
        return value

    return run


def load_assemblies(root):
    import clr  # pythonnet

    sys.path.append(root)
    sys.path.append(os.path.join(root, "AddInViews"))
    loaded = {}
    for base, versions in (("PrincetonInstruments.LightFieldView", ("V5", "V4")),
                           ("PrincetonInstruments.LightField.Automation", ("V5", "V4"))):
        for v in versions:
            try:
                clr.AddReference(base + v)
                loaded[base] = base + v
                break
            except Exception:
                continue
        else:
            raise RuntimeError(f"none of {base}{versions} could be loaded from {root}")
    clr.AddReference("PrincetonInstruments.LightFieldAddInSupportServices")
    loaded["support"] = "PrincetonInstruments.LightFieldAddInSupportServices"
    return loaded


def start_automation(visible):
    from PrincetonInstruments.LightField.Automation import Automation
    from System import String
    from System.Collections.Generic import List

    auto = Automation(visible, List[String]())
    return auto, auto.LightFieldApplication.Experiment


def devices(exp):
    def rows(devs):
        return [{"type": str(d.Type), "model": str(d.Model), "serial": str(d.SerialNumber)}
                for d in devs]

    return {"experiment": rows(exp.ExperimentDevices), "available": rows(exp.AvailableDevices)}


def saved_experiments(exp):
    return {"current": str(exp.Name), "saved": [str(n) for n in exp.GetSavedExperiments()]}


def setting_names(cls):
    """Static string properties and fields of a LightField settings class: {member: key}."""
    import clr
    from System.Reflection import BindingFlags

    t = clr.GetClrType(cls)
    flags = BindingFlags.Public | BindingFlags.Static
    out = {}
    for p in t.GetProperties(flags):
        out[str(p.Name)] = str(p.GetValue(None, None))
    for f in t.GetFields(flags):
        out[str(f.Name)] = str(f.GetValue(None))
    return out


def dump_settings(exp):
    from PrincetonInstruments.LightField.AddIns import (CameraSettings, ExperimentSettings,
                                                        SpectrometerSettings)

    out = {}
    for label, cls in (("CameraSettings", CameraSettings),
                       ("ExperimentSettings", ExperimentSettings),
                       ("SpectrometerSettings", SpectrometerSettings)):
        rows = {}
        for member, key in sorted(setting_names(cls).items()):
            row = {"key": key}
            try:
                row["exists"] = bool(exp.Exists(key))
                if row["exists"]:
                    row["value"] = str(exp.GetValue(key))
                    row["read_only"] = bool(exp.IsReadOnly(key))
            except Exception as e:  # some keys throw instead of reporting not-exists
                row["error"] = repr(e)
            rows[member] = row
        out[label] = rows
    return out


def enum_names():
    from PrincetonInstruments.LightField.AddIns import ShutterTimingMode, TimeStamps
    from System import Enum

    out = {}
    for label, e in (("TimeStamps", TimeStamps), ("ShutterTimingMode", ShutterTimingMode)):
        import clr

        out[label] = [str(n) for n in Enum.GetNames(clr.GetClrType(e))]
    return out


def cross_thread_read(exp):
    """Read the exposure time from a plain Python thread (the server uses one worker thread)."""
    from PrincetonInstruments.LightField.AddIns import CameraSettings

    result = {}

    def worker():
        try:
            result["value"] = str(exp.GetValue(CameraSettings.ShutterTimingExposureTime))
        except Exception:
            result["error"] = traceback.format_exc()

    t = threading.Thread(target=worker)
    t.start()
    t.join(30)
    result["finished"] = not t.is_alive()
    return result


def flags(enum_type, *members):
    """OR together .NET flag-enum members (pythonnet 3 enums are not Python ints)."""
    import clr
    from System import Enum

    value = 0
    for m in members:
        value |= int(m)
    return Enum.ToObject(clr.GetClrType(enum_type), value)


def acquire_one(app, exp, exptime_ms, outdir):
    from PrincetonInstruments.LightField.AddIns import (CameraSettings, ExperimentSettings,
                                                        TimeStamps)
    from System.IO import FileAccess

    os.makedirs(outdir, exist_ok=True)
    base = "probe_" + dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    exp.SetValue(CameraSettings.ShutterTimingExposureTime, float(exptime_ms))
    exp.SetValue(CameraSettings.AcquisitionTimeStampingStamps,
                 flags(TimeStamps, TimeStamps.ExposureStarted, TimeStamps.ExposureEnded))
    exp.SetValue(ExperimentSettings.FileNameGenerationDirectory, outdir)
    exp.SetValue(ExperimentSettings.FileNameGenerationBaseFileName, base)
    exp.SetValue(ExperimentSettings.FileNameGenerationAttachDate, False)
    exp.SetValue(ExperimentSettings.FileNameGenerationAttachTime, False)
    exp.SetValue(ExperimentSettings.FileNameGenerationAttachIncrement, False)
    exp.SetValue(ExperimentSettings.OnlineExportEnabled, True)
    exp.SetValue(ExperimentSettings.OnlineExportOutputOptionsExportedFilesOnly, False)

    if not exp.IsReadyToRun:
        raise RuntimeError("experiment is not ready to run")
    t_call = dt.datetime.now(dt.timezone.utc)
    exp.Acquire()
    time.sleep(0.5)
    while exp.IsRunning:
        time.sleep(0.1)
    t_done = dt.datetime.now(dt.timezone.utc)

    files = [str(f) for f in app.FileManager.GetRecentlyAcquiredFileNames()]
    out = {"pc_utc_call": t_call.isoformat(), "pc_utc_done": t_done.isoformat(), "files": files}
    spe = [f for f in files if f.lower().endswith(".spe")]
    if spe:
        ds = app.FileManager.OpenFile(spe[0], FileAccess.Read)
        try:
            origin = ds.TimeStampOrigin
            md = ds.GetFrameMetadata(0)
            out["time_stamp_origin"] = str(origin)
            out["exposure_started"] = str(md.ExposureStarted)
            out["exposure_ended"] = str(md.ExposureEnded)
        finally:
            app.FileManager.CloseFile(ds)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", default=os.environ.get("LIGHTFIELD_ROOT", DEFAULT_ROOT),
                    help="LightField install directory (default: $LIGHTFIELD_ROOT)")
    ap.add_argument("--experiment", help="saved experiment to load first (may move the grating "
                    "if it was saved with another one: only with the back illumination OUT)")
    ap.add_argument("--hidden", action="store_true", help="run LightField without its window")
    ap.add_argument("--acquire", action="store_true", help="take one frame (see the warning)")
    ap.add_argument("--exptime-ms", type=float, default=100.0)
    ap.add_argument("--outdir", default=os.path.join(os.getcwd(), "probe_out"))
    ap.add_argument("--report", default="lightfield_probe.json")
    a = ap.parse_args()

    report = {"started": dt.datetime.now(dt.timezone.utc).isoformat(),
              "python": sys.version, "platform": platform.platform(), "root": a.root}
    try:
        import clr  # noqa: F401
        import pythonnet

        report["pythonnet"] = getattr(pythonnet, "__version__", "unknown")
    except Exception:
        report["pythonnet"] = "import failed: " + traceback.format_exc()

    if step(report, "assemblies")(load_assemblies, a.root) is None:
        return finish(report, a.report)
    started = step(report, "automation")(start_automation, not a.hidden)
    if started is None:
        return finish(report, a.report)
    auto, exp = started
    app = auto.LightFieldApplication

    if a.experiment:
        step(report, "load_experiment")(exp.Load, a.experiment)
    step(report, "devices")(devices, exp)
    step(report, "experiments")(saved_experiments, exp)
    step(report, "settings")(dump_settings, exp)
    step(report, "enums")(enum_names)
    step(report, "cross_thread_read")(cross_thread_read, exp)
    if a.acquire:
        step(report, "acquire")(acquire_one, app, exp, a.exptime_ms, a.outdir)
    finish(report, a.report)
    auto.Dispose()


def finish(report, path):
    report["finished"] = dt.datetime.now(dt.timezone.utc).isoformat()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    print(f"report written to {path}", flush=True)


if __name__ == "__main__":
    main()
