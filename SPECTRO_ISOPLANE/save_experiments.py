"""Save one LightField experiment per IsoPlane setup (grating and centre wavelength).

Run on the LightField PC, with the LightField window closed, from the KSPEC_ICS root:

    python SPECTRO_ISOPLANE/save_experiments.py 150_620 300_450 300_490 600_450 600_680

Each setup ``<lines>_<centre nm>`` is saved as ``KSPEC_<lines>_<centre>`` in
``<LightField working directory>\\Experiments``, starting from ``--base`` (default
``Experiment_overscan``, the camera mode of the 2026 run). The script

1. reads the back-illumination Near switch and stops unless the stage is OUT: loading the base
   experiment and every setup MOVE THE GRATING;
2. loads the base experiment and stops if its camera mode differs from ``camera`` in
   isoplane_local.json;
3. per setup, sets the grating and the centre wavelength, waits for the move, reads both back,
   sets the export the server uses (FITS with the experiment information, SPE kept, time stamps,
   one frame), and saves the experiment.

Then list the names in ``experiments`` of isoplane_local.json.
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from SPECTRO_ISOPLANE import netcall  # noqa: E402
from SPECTRO_ISOPLANE.backillum import UnoLink, rd  # noqa: E402
from SPECTRO_ISOPLANE.command import camera_problems  # noqa: E402
from SPECTRO_ISOPLANE.lightfield import LightField  # noqa: E402

# grating lines/mm -> LightField grating name on the K-SPEC IsoPlane turret (January 2026 headers)
GRATINGS = {150: "[500nm,150][2][0]", 300: "[500nm,300][1][0]", 600: "[500nm,600][0][0]"}
MOVE_TIMEOUT_S = 120.0


def stage_out(port):
    """True when the back-illumination Near switch reads pressed (read only, no motion)."""
    if port == "fake":
        return True
    link = UnoLink(port)
    try:
        r = link.cmd("MB " + rd(0x2E).hex().upper())
        if not r.startswith("OK"):
            raise RuntimeError(f"Uno replied {r!r}")
        return not int(r.split()[1][6:10], 16) & 1
    finally:
        link.close()


def wait_updated(exp, t0):
    """Wait until LightField is no longer updating; seconds since t0. SetValue of the grating
    already blocks during the move (2 s for the centre, 40 s for a turret change)."""
    time.sleep(0.5)
    while netcall.get(exp, "IsUpdating"):
        if time.time() - t0 > MOVE_TIMEOUT_S:
            raise RuntimeError(f"LightField still updating after {MOVE_TIMEOUT_S:g} s")
        time.sleep(0.2)
    return time.time() - t0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("setups", nargs="+", help="<lines>_<centre nm>, e.g. 600_450")
    ap.add_argument("--base", default="Experiment_overscan", help="saved experiment to start from")
    ap.add_argument("--config", default="SPECTRO_ISOPLANE/isoplane_local.json")
    a = ap.parse_args()

    setups = []
    for s in a.setups:
        lines, centre = (int(x) for x in s.split("_"))
        if lines not in GRATINGS:
            sys.exit(f"{s}: no {lines} l/mm grating (have {sorted(GRATINGS)})")
        setups.append((f"KSPEC_{lines}_{centre}", GRATINGS[lines], float(centre)))

    with open(a.config, encoding="utf-8") as f:
        cfg = json.load(f)
    bl = cfg.get("backillum")
    if bl and not stage_out(bl["port"]):
        sys.exit("back-illumination stage is not at Near: send illuoff first (grating moves)")
    print("back-illumination stage OUT" if bl else "no back-illumination unit configured")

    lf_cfg = cfg["lightfield"]
    lf = LightField(lf_cfg["root"], visible=bool(lf_cfg.get("visible", True)))
    lf.connect()
    try:
        print(f"loading {a.base} ...", flush=True)
        lf.load_experiment(a.base)
        problems = camera_problems(cfg.get("camera", {}), lf.status())
        if problems:
            sys.exit(f"{a.base} camera mode differs from isoplane_local.json: {problems}")

        from PrincetonInstruments.LightField.AddIns import (CameraSettings, ExperimentSettings,
                                                            ExportFileType, SpectrometerSettings,
                                                            TimeStamps)
        from System import Enum, Int64

        import clr

        exp = lf._exp
        stamps = Enum.ToObject(clr.GetClrType(TimeStamps),
                               int(TimeStamps.ExposureStarted) | int(TimeStamps.ExposureEnded))
        export = (
            (CameraSettings.AcquisitionTimeStampingStamps, stamps),
            (ExperimentSettings.AcquisitionFramesToStore, Int64(1)),
            (ExperimentSettings.OnlineExportEnabled, True),
            (ExperimentSettings.OnlineExportFormat, ExportFileType.Fits),
            (ExperimentSettings.OnlineExportFormatOptionsIncludeExperimentInformation, True),
            (ExperimentSettings.OnlineExportOutputOptionsExportedFilesOnly, False),
        )
        for name, grating, centre in setups:
            t0 = time.time()
            netcall.call(exp, "SetValue", SpectrometerSettings.GratingSelected, grating)
            netcall.call(exp, "SetValue", SpectrometerSettings.GratingCenterWavelength, centre)
            took = wait_updated(exp, t0)
            got_g = str(netcall.call(exp, "GetValue", SpectrometerSettings.GratingSelected))
            got_c = float(str(netcall.call(exp, "GetValue",
                                           SpectrometerSettings.GratingCenterWavelength)))
            if got_g != grating or abs(got_c - centre) > 0.05:
                raise RuntimeError(f"{name}: spectrometer at {got_g} {got_c} nm after the move")
            for key, value in export:
                if netcall.call(exp, "Exists", key):  # a missing setting would crash LightField
                    netcall.call(exp, "SetValue", key, value)
            netcall.call(exp, "SaveAs", name)
            print(f"saved {name}: {got_g} at {got_c:.3f} nm (move {took:.1f} s)", flush=True)
        saved = [str(n) for n in netcall.items(netcall.call(exp, "GetSavedExperiments"))]
        print("saved experiments:", saved)
    finally:
        lf.close()


if __name__ == "__main__":
    main()
