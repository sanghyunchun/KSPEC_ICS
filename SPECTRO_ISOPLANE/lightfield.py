"""Camera and spectrometer access for the IsoPlane through Teledyne PI LightField.

``LightField`` drives the real application through the LightField Automation API (.NET,
loaded with pythonnet; Windows only). ``FakeLightField`` writes LightField-like FITS files so
the server can be developed and tested anywhere.

The setting names and enum values used here were inferred from the January 2026 headers and
the saved experiments, and all exist in LightField 6.15.2 (probe_lightfield.py on the LightField
laptop, 2026-10-25, no camera attached). Still to check with the camera: that each setting
exists for the PIXIS, and one acquisition with time stamps (``probe_lightfield.py --acquire``).
"""

import atexit
import datetime as dt
import os
import threading
import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from . import netcall


# status key: CameraSettings member, i.e. the .lfe path under Devices/Cameras/Camera.
# The 2026 run used Adc 0.1 MHz / High / LowNoise at -55 C, full sensor;
# from 2026-02-03 the layout read 1330 rows of the 1300-row sensor: the last 30 are overscan.
CAMERA_STATUS = {
    "adc_speed_mhz": "AdcSpeed",
    "adc_gain": "AdcAnalogGain",
    "adc_quality": "AdcQuality",
    "temp_setpoint_c": "SensorTemperatureSetPoint",
    "sensor_temp_c": "SensorTemperatureReading",
    "temp_status": "SensorTemperatureStatus",
    "sensor_cols": "SensorLayoutActiveAreaWidth",
    "sensor_rows": "SensorLayoutActiveAreaHeight",
    "physical_rows": "SensorInformationActiveAreaHeight",
    "roi_selection": "ReadoutControlRegionsOfInterestSelection",
}


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
        """dict with at least ready, running, experiment, grating, center_nm, and the
        CAMERA_STATUS keys (values as strings; "None" when the setting is unknown)."""

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


def check_new_frame(directory, basename):
    """Refuse a frame name already on disk. LightField does not fail on an existing file: it
    writes ``<basename> - (2).fits``, and the server would then read the old file."""
    for ext in (".fits", ".spe"):
        path = os.path.join(directory, basename + ext)
        if os.path.exists(path):
            raise FileExistsError(path)


class FakeLightField(LightFieldBase):
    """Writes small LightField-like FITS frames; the exposure waits exptime * time_scale.

    The last ``overscan_rows`` rows of ``shape`` stand for overscan rows read past the sensor;
    ``camera`` overrides the reported CAMERA_STATUS values.
    """

    def __init__(self, time_scale=1.0, shape=(1, 1300, 1340), grating="[500nm,600][0][0]",
                 center_nm=430.0, overscan_rows=0, camera=None):
        self.scale = time_scale
        self.shape = tuple(shape)
        self.experiment = "fake"
        self.grating = grating
        self.center_nm = center_nm
        self.running = False
        self._stop = threading.Event()
        self.camera = {"adc_speed_mhz": "0.1", "adc_gain": "High", "adc_quality": "LowNoise",
                       "temp_setpoint_c": "-55", "sensor_temp_c": "-55", "temp_status": "Locked",
                       "sensor_cols": str(self.shape[-1]), "sensor_rows": str(self.shape[-2]),
                       "physical_rows": str(self.shape[-2] - overscan_rows),
                       "roi_selection": "FullSensor"}
        self.camera.update({k: str(v) for k, v in (camera or {}).items()})

    def connect(self):
        pass

    def setup(self):
        return {"experiment": self.experiment, "grating": self.grating,
                "center_nm": self.center_nm, **self.camera}

    def status(self):
        return {"ready": not self.running, "running": self.running, "driver": "fake",
                **self.setup()}

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
        check_new_frame(directory, basename)
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
            return Frame(path, _utc(t0), _utc(t1), self.setup())
        finally:
            self.running = False


class LightField(LightFieldBase):
    """The real LightField, through pythonnet. Driver calls are serialised on one Python worker
    thread; every LightField call goes through ``netcall`` so that it never runs while the GIL
    is held (``Automation()`` deadlocked otherwise, see netcall)."""

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
            for v in ("V5", "V4"):  # LightField 6.15 ships V5
                try:
                    clr.AddReference(base + v)
                    break
                except Exception:
                    continue
            else:
                raise RuntimeError(f"cannot load {base}V5/V4 from {self.root}")
        clr.AddReference("PrincetonInstruments.LightFieldAddInSupportServices")
        from PrincetonInstruments.LightField.Automation import Automation

        self._auto = netcall.new(Automation, self.visible, List[String]())
        atexit.register(self._dispose)  # also when the server dies of an exception
        self._app = netcall.get(self._auto, "LightFieldApplication")
        self._exp = netcall.get(self._app, "Experiment")
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
        out = {"ready": bool(netcall.get(exp, "IsReadyToRun")),
               "running": bool(netcall.get(exp, "IsRunning")),
               "updating": bool(netcall.get(exp, "IsUpdating")), "driver": "lightfield",
               "experiment": str(netcall.get(exp, "Name"))}
        names = {"grating": spec.GratingSelected,
                 "center_nm": spec.GratingCenterWavelength}
        names.update({key: getattr(cam, member, None) for key, member in CAMERA_STATUS.items()})
        for key, name in names.items():
            known = name is not None and netcall.call(exp, "Exists", name)
            out[key] = str(netcall.call(exp, "GetValue", name)) if known else "None"
        return out

    def load_experiment(self, name):
        self._call(self._load, name)

    def _load(self, name):
        if not netcall.call(self._exp, "Load", name):
            raise RuntimeError(f"LightField could not load experiment {name!r}")
        while netcall.get(self._exp, "IsUpdating"):  # a grating move happens here
            time.sleep(0.2)

    def stop(self):
        self._stopped.set()
        exp = self._exp  # Stop must not wait behind a running expose() on the worker thread
        if exp is not None and netcall.get(exp, "IsRunning"):
            netcall.call(exp, "Stop")

    def clear_stop(self):
        self._stopped.clear()

    def expose(self, exptime_s, shutter_closed, directory, basename):
        return self._call(self._expose, exptime_s, shutter_closed, directory, basename)

    def _expose(self, exptime_s, shutter_closed, directory, basename):
        from PrincetonInstruments.LightField.AddIns import (ExportFileType, ShutterTimingMode,
                                                            TimeStamps)
        from System import Enum, Int64
        from System.IO import FileAccess

        import clr

        cam, expset, _ = self._settings()
        exp = self._exp
        os.makedirs(directory, exist_ok=True)
        check_new_frame(directory, basename)
        stamps = Enum.ToObject(clr.GetClrType(TimeStamps),
                               int(TimeStamps.ExposureStarted) | int(TimeStamps.ExposureEnded))
        # Everything the frame depends on is set here, not taken from the saved experiment or
        # the LightField window: one frame per Acquire (EXPNUM, time stamps of frame 0), a FITS
        # export with the experiment information (the PI cards the reduction reads), and the SPE.
        for name, value in (
            (cam.ShutterTimingExposureTime, float(exptime_s * 1000.0)),
            (cam.ShutterTimingMode,
             ShutterTimingMode.AlwaysClosed if shutter_closed else ShutterTimingMode.Normal),
            (cam.AcquisitionTimeStampingStamps, stamps),
            (expset.AcquisitionFramesToStore, Int64(1)),
            (expset.FileNameGenerationDirectory, directory),
            (expset.FileNameGenerationBaseFileName, basename),
            (expset.FileNameGenerationAttachDate, False),
            (expset.FileNameGenerationAttachTime, False),
            (expset.FileNameGenerationAttachIncrement, False),
            (expset.OnlineExportEnabled, True),
            (expset.OnlineExportFormat, ExportFileType.Fits),
            (expset.OnlineExportFormatOptionsIncludeExperimentInformation, True),
            (expset.OnlineExportOutputOptionsExportedFilesOnly, False),  # keep the SPE
        ):
            # Exists first: SetValue/GetValue of a missing setting crashes LightField itself
            if not netcall.call(exp, "Exists", name):
                raise RuntimeError(f"LightField has no setting {name}")
            netcall.call(exp, "SetValue", name, value)
        if self._stopped.is_set():
            raise RuntimeError("acquisition stopped")
        if not netcall.get(exp, "IsReadyToRun"):
            raise RuntimeError("LightField is not ready to run")
        netcall.call(exp, "Acquire")
        time.sleep(0.5)
        while netcall.get(exp, "IsRunning"):
            time.sleep(0.1)
        if self._stopped.is_set():
            raise RuntimeError("acquisition stopped")

        fm = netcall.get(self._app, "FileManager")
        files = [str(f) for f in netcall.items(netcall.call(fm, "GetRecentlyAcquiredFileNames"))]
        fits_path = os.path.join(directory, basename + ".fits")
        if not os.path.exists(fits_path):
            raise RuntimeError(f"exported FITS not found: {fits_path} (LightField wrote {files})")
        frame = Frame(fits_path, setup=self._status())
        spe = [f for f in files if f.lower().endswith(".spe")]
        if spe:
            ds = netcall.call(fm, "OpenFile", spe[0], FileAccess.Read)
            try:
                origin = netcall.get(ds, "TimeStampOrigin")
                md = netcall.call(ds, "GetFrameMetaData", 0)
                started = netcall.get(md, "ExposureStarted")
                if origin is not None and started is not None:
                    frame.ut_start = _net_utc(origin, started)
                    frame.ut_end = _net_utc(origin, netcall.get(md, "ExposureEnded"))
            finally:
                netcall.call(fm, "CloseFile", ds)
        return frame

    def _dispose(self):
        """Close LightField. Without it, LightField stays in its AddInProcess.exe, and a host
        left behind (or killed) blocks every later start: IPC "pipe has been ended" or a hang,
        until a reboot (2026-10-24)."""
        auto, self._auto = self._auto, None
        if auto is not None:
            try:
                netcall.call(auto, "Dispose")
            except netcall.NetError:  # LightField already gone (crashed or closed by hand)
                pass

    def close(self):
        self._call(self._dispose)
        self._pool.shutdown()


def _net_utc(origin, span):
    """DateTimeOffset origin + TimeSpan offset -> ISO 8601 UTC string."""
    t = origin.Add(span).ToUniversalTime()
    return t.ToString("yyyy-MM-ddTHH:mm:ss.fff") + "+00:00"


def make_lightfield(cfg):
    """Build the driver from the ``lightfield`` block of isoplane_local.json."""
    if cfg.get("driver", "fake") == "fake":
        return FakeLightField(time_scale=float(cfg.get("time_scale", 1.0)),
                              shape=cfg.get("shape", (1, 1300, 1340)),
                              overscan_rows=int(cfg.get("overscan_rows", 0)))
    return LightField(cfg["root"], visible=bool(cfg.get("visible", True)),
                      experiment=cfg.get("experiment"))
