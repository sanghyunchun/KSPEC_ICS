"""Camera and spectrometer access for the IsoPlane through Teledyne PI LightField.

``LightField`` drives the real application through the LightField Automation API (.NET,
loaded with pythonnet; Windows only). ``FakeLightField`` writes LightField-like FITS files so
the server can be developed and tested anywhere.

Setting names marked "confirm with probe" are inferred from the January 2026 headers (a header
key ``PI CAMERA SHUTTERTIMING EXPOSURETIME`` is the setting ``CameraSettings.
ShutterTimingExposureTime``). ``probe_lightfield.py`` lists the real names on the LightField PC.
"""

import datetime as dt
import os
import threading
import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field


@dataclass
class Frame:
    path: str  # exported FITS on the local disk
    ut_start: str = "None"  # ISO 8601 UTC from the SPE time stamps
    ut_end: str = "None"
    setup: dict = field(default_factory=dict)  # grating, centre wavelength, experiment


class LightFieldBase(ABC):
    @abstractmethod
    def connect(self):
        """Start or attach to LightField; load the default experiment if one is configured."""

    @abstractmethod
    def status(self):
        """dict with at least ready, running, experiment, grating, center_nm."""

    @abstractmethod
    def load_experiment(self, name):
        """Load a saved experiment. This MAY MOVE THE GRATING: call it only with the
        back-illumination stage verified OUT."""

    @abstractmethod
    def expose(self, exptime_s, shutter_closed, directory, basename):
        """Take one frame, export it as ``directory/basename.fits``, and return a Frame.
        Blocks until the file is written."""

    def stop(self):
        """Abort a running acquisition (best effort, from any thread); expose() then raises
        until clear_stop()."""

    def clear_stop(self):
        pass

    def close(self):
        pass


def _utc(t):
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).isoformat(timespec="milliseconds")


class FakeLightField(LightFieldBase):
    """Writes small LightField-like FITS frames; the exposure waits exptime * time_scale."""

    def __init__(self, time_scale=1.0, shape=(1, 1300, 1340), grating="[500nm,600][0][0]",
                 center_nm=430.0):
        self.scale = time_scale
        self.shape = tuple(shape)
        self.experiment = "fake"
        self.grating = grating
        self.center_nm = center_nm
        self.running = False
        self._stop = threading.Event()

    def connect(self):
        pass

    def status(self):
        return {"ready": not self.running, "running": self.running, "driver": "fake",
                "experiment": self.experiment, "grating": self.grating,
                "center_nm": self.center_nm}

    def load_experiment(self, name):
        self.experiment = name

    def stop(self):
        self._stop.set()

    def clear_stop(self):
        self._stop.clear()

    def expose(self, exptime_s, shutter_closed, directory, basename):
        import numpy as np
        from astropy.io import fits

        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, basename + ".fits")
        if os.path.exists(path):
            raise FileExistsError(path)
        if self._stop.is_set():
            raise RuntimeError("acquisition stopped")
        self.running = True
        try:
            t0 = time.time()
            if self._stop.wait(exptime_s * self.scale):
                raise RuntimeError("acquisition stopped")
            t1 = t0 + exptime_s
            hdr = fits.Header()
            hdr["DATE-OBS"] = (_utc(t1)[:19], "Date of data acquisition")
            hdr["EXPTIME"] = (f"{round(exptime_s * 1000)}", "Exposure time")
            hdr["HIERARCH PI CAMERA SHUTTERTIMING EXPOSURETIME"] = f"{round(exptime_s * 1000)}"
            hdr["HIERARCH PI CAMERA SHUTTERTIMING MODE"] = (
                "AlwaysClosed" if shutter_closed else "Normal")
            hdr["HIERARCH PI SPECTROMETER GRATING SELECTED"] = self.grating
            hdr["HIERARCH PI SPECTROMETER GRATING CENTERWAVELENGTH"] = f"{self.center_nm:g}"
            data = np.full(self.shape, 600, dtype=np.uint16)
            fits.PrimaryHDU(data, hdr).writeto(path)
            return Frame(path, _utc(t0), _utc(t1),
                         {"experiment": self.experiment, "grating": self.grating,
                          "center_nm": self.center_nm})
        finally:
            self.running = False


class LightField(LightFieldBase):
    """The real LightField, through pythonnet. Every .NET call runs on one dedicated thread,
    the thread that created the Automation object."""

    def __init__(self, root, visible=True, experiment=None):
        self.root = root
        self.visible = visible
        self.default_experiment = experiment
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lightfield")
        self._auto = self._app = self._exp = None
        self._stopped = threading.Event()

    def _call(self, fn, *args):
        return self._pool.submit(fn, *args).result()

    def connect(self):
        self._call(self._connect)

    def _connect(self):
        import sys

        import clr
        from System import String
        from System.Collections.Generic import List

        sys.path.append(self.root)
        sys.path.append(os.path.join(self.root, "AddInViews"))
        for base in ("PrincetonInstruments.LightFieldView",
                     "PrincetonInstruments.LightField.Automation"):
            for v in ("V5", "V4"):  # confirm with probe
                try:
                    clr.AddReference(base + v)
                    break
                except Exception:
                    continue
            else:
                raise RuntimeError(f"cannot load {base}V5/V4 from {self.root}")
        clr.AddReference("PrincetonInstruments.LightFieldAddInSupportServices")
        from PrincetonInstruments.LightField.Automation import Automation

        self._auto = Automation(self.visible, List[String]())
        self._app = self._auto.LightFieldApplication
        self._exp = self._app.Experiment
        if self.default_experiment:
            self._load(self.default_experiment)

    def _settings(self):
        from PrincetonInstruments.LightField.AddIns import (CameraSettings, ExperimentSettings,
                                                            SpectrometerSettings)

        return CameraSettings, ExperimentSettings, SpectrometerSettings

    def status(self):
        return self._call(self._status)

    def _status(self):
        cam, _, spec = self._settings()
        exp = self._exp
        out = {"ready": bool(exp.IsReadyToRun), "running": bool(exp.IsRunning),
               "updating": bool(exp.IsUpdating), "driver": "lightfield",
               "experiment": str(exp.Name)}
        for key, name in (("grating", spec.GratingSelected),  # confirm with probe
                          ("center_nm", spec.GratingCenterWavelength),
                          ("sensor_temp_c", cam.SensorTemperatureReading)):
            out[key] = str(exp.GetValue(name)) if exp.Exists(name) else "None"
        return out

    def load_experiment(self, name):
        self._call(self._load, name)

    def _load(self, name):
        if not self._exp.Load(name):
            raise RuntimeError(f"LightField could not load experiment {name!r}")
        while self._exp.IsUpdating:  # a grating move happens here
            time.sleep(0.2)

    def stop(self):
        self._stopped.set()
        exp = self._exp  # Stop must not wait behind a running expose() on the worker thread
        if exp is not None and exp.IsRunning:
            exp.Stop()  # called off the worker thread: confirm with probe (cross_thread_read)

    def clear_stop(self):
        self._stopped.clear()

    def expose(self, exptime_s, shutter_closed, directory, basename):
        return self._call(self._expose, exptime_s, shutter_closed, directory, basename)

    def _expose(self, exptime_s, shutter_closed, directory, basename):
        from PrincetonInstruments.LightField.AddIns import ShutterTimingMode, TimeStamps
        from System import Enum
        from System.IO import FileAccess

        import clr

        cam, expset, _ = self._settings()
        exp = self._exp
        os.makedirs(directory, exist_ok=True)
        stamps = Enum.ToObject(clr.GetClrType(TimeStamps),
                               int(TimeStamps.ExposureStarted) | int(TimeStamps.ExposureEnded))
        for name, value in (
            (cam.ShutterTimingExposureTime, float(exptime_s * 1000.0)),
            (cam.ShutterTimingMode,  # confirm with probe
             ShutterTimingMode.AlwaysClosed if shutter_closed else ShutterTimingMode.Normal),
            (cam.AcquisitionTimeStampingStamps, stamps),
            (expset.FileNameGenerationDirectory, directory),  # confirm with probe (all below)
            (expset.FileNameGenerationBaseFileName, basename),
            (expset.FileNameGenerationAttachDate, False),
            (expset.FileNameGenerationAttachTime, False),
            (expset.FileNameGenerationAttachIncrement, False),
            (expset.OnlineExportEnabled, True),
            (expset.OnlineExportOutputOptionsExportedFilesOnly, False),  # keep the SPE
        ):
            exp.SetValue(name, value)
        if self._stopped.is_set():
            raise RuntimeError("acquisition stopped")
        if not exp.IsReadyToRun:
            raise RuntimeError("LightField is not ready to run")
        exp.Acquire()
        time.sleep(0.5)
        while exp.IsRunning:
            time.sleep(0.1)
        if self._stopped.is_set():
            raise RuntimeError("acquisition stopped")

        files = [str(f) for f in self._app.FileManager.GetRecentlyAcquiredFileNames()]
        fits_path = os.path.join(directory, basename + ".fits")
        if not os.path.exists(fits_path):
            raise RuntimeError(f"exported FITS not found: {fits_path} (LightField wrote {files})")
        frame = Frame(fits_path, setup=self._status())
        spe = [f for f in files if f.lower().endswith(".spe")]
        if spe:
            ds = self._app.FileManager.OpenFile(spe[0], FileAccess.Read)
            try:
                origin, md = ds.TimeStampOrigin, ds.GetFrameMetadata(0)
                if origin is not None and md.ExposureStarted is not None:
                    frame.ut_start = _net_utc(origin, md.ExposureStarted)
                    frame.ut_end = _net_utc(origin, md.ExposureEnded)
            finally:
                self._app.FileManager.CloseFile(ds)
        return frame

    def close(self):
        if self._auto is not None:
            self._call(self._auto.Dispose)
        self._pool.shutdown()


def _net_utc(origin, span):
    """DateTimeOffset origin + TimeSpan offset -> ISO 8601 UTC string."""
    t = origin.Add(span).ToUniversalTime()
    return t.ToString("yyyy-MM-ddTHH:mm:ss.fff") + "+00:00"


def make_lightfield(cfg):
    """Build the driver from the ``lightfield`` block of isoplane_local.json."""
    if cfg.get("driver", "fake") == "fake":
        return FakeLightField(time_scale=float(cfg.get("time_scale", 1.0)),
                              shape=cfg.get("shape", (1, 1300, 1340)))
    return LightField(cfg["root"], visible=bool(cfg.get("visible", True)),
                      experiment=cfg.get("experiment"))
