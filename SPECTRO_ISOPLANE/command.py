"""ISOPLANE server: the SPEC command set of the main spectrograph, run on the IsoPlane.

Commands and replies follow ``SPECTRO/command.py`` (``inst='SPEC'``, ING progress replies, one
final Done reply per command), so ``speccli.py``, the GUI, and ``scriptcli.py`` need no
IsoPlane-specific code:

    specinitial <night> [experiment]   night directory; optionally load a LightField experiment
    specstatus                         camera, grating, and back-illumination state
    getbias <n> / getdark <t> <n> / getflat <t> <n> / getarc <t> <n> / getobj <t> <n>
    illuon / illuoff                   back-illumination stage in + light on / light off + out
    illulighton / illulightoff         light only; the stage does not move (on needs it IN)
    specstop                           emergency stop: stage, then light, then LightField

Replies. The ICS pairs replies with commands by their order, so every command gets exactly one
Done reply, and nothing else is ever sent as Done. Its status is success; fail when the command
was refused and nothing was done (busy, interlock, missing setup); error when the hardware or
LightField failed; or stopped when specstop interrupted it. Messages the server sends on its
own (light auto-off) and the specstop reply while a command runs are ING.

One process owns both LightField and the back-illumination Uno, because the stage is lowered
into the grating-turret compartment. Every command except specstatus and specstop holds one
lock, so an exposure, an experiment load (which may move the grating), and a stage move never
overlap. A command that arrives while another one runs is refused at once, not queued. Before
anything that may move the grating or open the shutter, the Near switch is read from the
hardware: the stage must be OUT and the light off.

specstatus never waits: while a command runs, it reports the LightField state read before that
command (LightField serves one call at a time, so asking it would wait for the exposure).

specstop never waits either. It stops the stage, switches the light off, and stops the
acquisition; the running command then replies stopped. The stage position is unknown
afterwards, so exposures, experiment loads, and illuon stay refused until illuoff has homed the
stage.

Light auto-off: every light-on (illuon, illulighton) starts a timer, and the server switches
the light off after ``backillum.light_max_on_s`` (default 300 s; 0 disables it) unless the light
is switched on again. The stage stays where it is. The Uno's own 60 s watchdog only covers this
server dying; the timer covers the ICS script dying with the light on in the turret.

Deadlines: an exposure still running ``lightfield.expose_timeout_s`` (default 120 s) after its
exposure time is stopped and fails; an experiment load fails after ``lightfield.load_timeout_s``
(default 300 s). A hung LightField then still produces a Done reply.

Setups: ``experiments`` (a list of saved LightField experiments) limits what specinitial may
load; without it any experiment loads. ``camera`` holds the camera mode the reduction is
calibrated for (ADC speed, gain and quality, temperature lock, readout rows, ROI): every
exposure reads the camera state first and is refused when any value differs, so a mode changed
by hand in the LightField window never reaches the data. specinitial and specstatus report the
differences.
"""

import asyncio
import datetime as dt
import json
import os
import re
import shutil
import time

import Lib.mkmessage as mkmsg
from SPECTRO_ISOPLANE.backillum import make_backillum
from SPECTRO_ISOPLANE.fitsio import append_cards, extra_cards, ics_cards
from SPECTRO_ISOPLANE.lightfield import make_lightfield

# func: (file-name tag, shutter closed)
FRAME_TYPES = {
    "getbias": ("bias", True),
    "getdark": ("dark", True),
    "getflat": ("flat", False),
    "getarc": ("arc", False),
    "getobj": ("obj", False),
}
PROGRESS_EVERY_S = 10
AUTO_OFF = "light auto-off"  # self.busy while the timer switches the light off


class Refused(RuntimeError):
    """The command was not carried out (reply status fail)."""


class InterlockError(Refused):
    pass


def setup_summary(lf):
    """One line for the message log: the setup the next frames will be taken with."""
    return (f"experiment {lf.get('experiment')}, grating {lf.get('grating')} at "
            f"{lf.get('center_nm')} nm, ADC {lf.get('adc_speed_mhz')} MHz "
            f"{lf.get('adc_gain')}/{lf.get('adc_quality')}, {lf.get('sensor_temp_c')} C "
            f"{lf.get('temp_status')}")


def camera_problems(expected, lf):
    """['<key> <value> (expected <value>)', ...] for every configured camera value that differs."""
    out = []
    for key, want in expected.items():
        got = lf.get(key, "None")
        try:
            same = float(got) == float(want)
        except (TypeError, ValueError):
            same = str(got).strip().lower() == str(want).strip().lower()
        if not same:
            out.append(f"{key} {got} (expected {want})")
    return out


class Isoplane:
    def __init__(self, cfg, lightfield=None, backillum=None):
        lf_cfg = cfg.get("lightfield", {})
        bl_cfg = cfg.get("backillum") or {}
        self.lf = lightfield if lightfield is not None else make_lightfield(lf_cfg)
        self.bl = backillum if backillum is not None else make_backillum(cfg.get("backillum"))
        self.datapath = cfg.get("datapath", "../DATA/RAWDATA/")
        self.sharepath = cfg.get("sharepath", "")
        self.expose_timeout_s = float(lf_cfg.get("expose_timeout_s", 120.0))
        self.load_timeout_s = float(lf_cfg.get("load_timeout_s", 300.0))
        self.stop_grace_s = 30.0  # wait for LightField after stopping a late exposure
        self.sensor_bias_rows = int(lf_cfg.get("sensor_bias_rows", 0))  # see fitsio.overscan_cards
        self.light_settle_s = float(bl_cfg.get("light_settle_s", 1.0))
        self.light_max_on_s = float(bl_cfg.get("light_max_on_s", 300.0))
        self.camera = dict(cfg.get("camera") or {})  # expected camera mode; empty: no check
        self.experiments = cfg.get("experiments")  # allowed experiments; None: any
        self.night = None
        self.lock = asyncio.Lock()
        self.busy = "idle"
        self.stop_requested = False  # specstop arrived while self.busy ran
        self.light_timer = None
        self.light_off_at = None  # time.monotonic() of the next auto-off
        self.lf_status = {}  # last LightField status, served while a command runs
        self.shutter_open = False  # entrance shutter set AlwaysOpen for the back illumination
        self.shutter_timeout_s = 10.0
        self.lf_status_time = None

    # -------------------------------------------------- lifecycle
    async def start(self):
        await asyncio.to_thread(self.lf.connect)
        await self.read_lf_status()
        if self.bl is None:
            print("\033[33m[ISOPLANE] no back-illumination unit configured\033[0m", flush=True)
            return
        state = await asyncio.to_thread(self.bl.connect)
        if state != "OUT":
            print("\033[31m[ISOPLANE] back-illumination stage is not at Near: exposures and "
                  "experiment loads are blocked until illuoff\033[0m", flush=True)

    async def close(self):
        self.cancel_light_timer()
        if self.bl is not None:
            await asyncio.to_thread(self.bl.close)  # light off
        await self.close_shutter()
        await asyncio.to_thread(self.lf.close)

    # -------------------------------------------------- messaging
    async def reply(self, server, func, message, process="Done", status="success", **extra):
        data = mkmsg.specmsg()
        data.update(func=func, message=message, process=process, status=status, **extra)
        color = "\033[32m" if status == "success" else "\033[31m"
        print(f"{color}[ISOPLANE] {message}\033[0m", flush=True)
        await server.send_message("ICS", json.dumps(data))

    async def handle(self, server, body):
        d = json.loads(body)
        func = d.get("func")
        if func == "specstatus":
            msg, details = await self.status()
            await self.reply(server, func, msg, isoplane=details)
            return
        if func == "specstop":
            await self.emergency_stop(server)
            return
        handlers = {
            "specinitial": self.specinitial,
            "illuon": self.illuon,
            "illuoff": self.illuoff,
            "illulighton": self.illulighton,
            "illulightoff": self.illulightoff,
            **{f: self.take_frames for f in FRAME_TYPES},
        }
        if func not in handlers:
            await self.reply(server, str(func), f"Unknown command for ISOPLANE: {func}",
                             status="error")
            return
        if self.lock.locked():  # no await since the check: the lock cannot change hands here
            await self.reply(server, func, f"{func} refused: busy with {self.busy}.",
                             status="fail")
            return
        async with self.lock:
            self.busy = func
            self.stop_requested = False
            if self.bl is not None:  # a specstop holds until the next command starts
                self.bl.clear_stop()
            self.lf.clear_stop()
            try:
                await handlers[func](server, d)
            except Exception as e:
                if self.stop_requested:
                    status, msg = "stopped", f"{func} stopped by specstop: {e}"
                elif isinstance(e, Refused):
                    status, msg = "fail", f"{func} refused: {e}"
                else:
                    status, msg = "error", f"{func} failed: {e}"
                extra = {"backillum": self.bl.status()} if self.bl is not None else {}
                await self.reply(server, func, msg, status=status, **extra)
            finally:
                self.busy = "idle"
                self.stop_requested = False

    async def emergency_stop(self, server):
        """Stage stop, then light off, then LightField stop; does not wait for the lock.

        While a command runs, the reply is ING: that command's own Done (status stopped) is
        the one reply the ICS waits for.
        """
        interrupted = self.busy
        running = interrupted not in ("idle", AUTO_OFF)
        if running:
            self.stop_requested = True
        self.cancel_light_timer()
        done, failed = [], []
        if self.bl is not None:
            try:
                await asyncio.to_thread(self.bl.emergency_stop)
                done.append("stage stopped, light off")
            except Exception as e:
                failed.append(f"back illumination: {e}")
        try:
            await asyncio.to_thread(self.lf.stop)
            done.append("acquisition stopped")
        except Exception as e:
            failed.append(f"LightField: {e}")
        if self.shutter_open:
            warning = await self.close_shutter()
            (failed if warning else done).append(warning.strip() or "shutter back to Normal")
        msg = f"Emergency stop ({'during ' + interrupted if running else 'idle'}): "
        msg += "; ".join(done + failed) + "."
        if self.bl is not None:
            msg += " Stage position unknown: send illuoff to home it."
        extra = {"backillum": self.bl.status()} if self.bl is not None else {}
        await self.reply(server, "specstop", msg, process="ING" if running else "Done",
                         status="error" if failed else "success", **extra)

    def check_stop(self):
        if self.stop_requested:
            raise RuntimeError("stopped by specstop")

    # -------------------------------------------------- interlock
    def require_unit(self):
        if self.bl is None:
            raise Refused("no back-illumination unit configured")

    async def require_stage_out(self, what):
        """Raise unless the stage reads OUT at the Near switch now and the light is off."""
        if self.bl is None:
            return
        near = await asyncio.to_thread(self.bl.at_near)
        if not near or self.bl.light:
            raise InterlockError(
                f"{what}: back-illumination stage is not OUT "
                f"(state {self.bl.state}, light {self.bl.light}); send illuoff first"
            )
        self.bl.state = "OUT"

    # -------------------------------------------------- entrance shutter
    async def set_shutter(self, is_open):
        """Entrance shutter AlwaysOpen while the back illumination is on (its light reaches the
        fibres only through that shutter), Normal otherwise."""
        await asyncio.to_thread(self.lf.set_shutter_open, is_open)
        self.shutter_open = is_open

    async def close_shutter(self):
        """Shutter back to Normal after a light-off: '' or a warning for the reply."""
        if not self.shutter_open:
            return ""
        try:
            await asyncio.wait_for(self.set_shutter(False), self.shutter_timeout_s)
            return ""
        except Exception as e:
            return f" Warning: entrance shutter not set back to Normal ({type(e).__name__}: {e})."

    # -------------------------------------------------- light auto-off
    def lease_note(self):
        return f", auto-off in {self.light_max_on_s:g} s" if self.light_max_on_s > 0 else ""

    def arm_light_timer(self, server):
        self.cancel_light_timer()
        if self.light_max_on_s > 0:
            self.light_off_at = time.monotonic() + self.light_max_on_s
            self.light_timer = asyncio.ensure_future(
                self.light_auto_off(server, self.light_max_on_s))

    def cancel_light_timer(self):
        timer, self.light_timer, self.light_off_at = self.light_timer, None, None
        if timer is not None and timer is not asyncio.current_task() and not timer.done():
            timer.cancel()

    async def light_auto_off(self, server, after):
        await asyncio.sleep(after)
        async with self.lock:  # a command holding the lock cancels or re-arms this timer
            if self.light_timer is not asyncio.current_task():
                return
            self.light_timer = self.light_off_at = None
            if self.bl is None or not self.bl.light:
                return
            self.busy = AUTO_OFF
            try:
                await asyncio.to_thread(self.bl.set_light, False)
                warning = await self.close_shutter()
                await self.reply(server, "illulightoff",
                                 f"Back illumination light switched off after {after:g} s on "
                                 f"(light_max_on_s); stage stays {self.bl.state}.{warning}",
                                 process="ING", backillum=self.bl.status())
            except Exception as e:
                await self.reply(server, "illulightoff",
                                 f"Back illumination light auto-off failed: {e}",
                                 process="ING", status="error", backillum=self.bl.status())
            finally:
                self.busy = "idle"

    async def light_on(self, server):
        await self.set_shutter(True)  # first: if it fails, the light stays off
        await asyncio.to_thread(self.bl.set_light, True)
        self.arm_light_timer(server)
        await asyncio.sleep(self.light_settle_s)
        self.check_stop()

    # -------------------------------------------------- commands
    async def read_lf_status(self):
        self.lf_status = await asyncio.to_thread(self.lf.status)
        self.lf_status_time = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        return self.lf_status

    async def status(self):
        """Never waits on a running command: while busy, LightField is reported from cache."""
        busy = self.busy != "idle"
        lf = dict(self.lf_status) if busy else await self.read_lf_status()
        bl = self.bl.status() if self.bl is not None else {"state": "NONE"}
        if self.light_off_at is not None:
            bl["auto_off_in_s"] = round(max(0.0, self.light_off_at - time.monotonic()))
        problems = camera_problems(self.camera, lf)
        details = {"night": self.night, "busy": self.busy, "lightfield": lf,
                   "lightfield_read_at": self.lf_status_time, "backillum": bl,
                   "camera_problems": problems}
        msg = (f"IsoPlane: {'busy (' + self.busy + ')' if busy else 'ready'}, "
               f"night {self.night}, {setup_summary(lf)}"
               f"{' (as of ' + str(self.lf_status_time) + ')' if busy else ''}, back illumination "
               f"{bl['state']}{' light ON' if bl.get('light') else ''}.")
        if problems:
            msg += " Camera not in the configured mode: " + "; ".join(problems) + "."
        return msg, details

    async def specinitial(self, server, d):
        night = str(d["dirname"])
        os.makedirs(os.path.join(self.datapath, night), exist_ok=True)
        self.night = night
        experiment = d.get("experiment")
        if experiment and self.experiments is not None and experiment not in self.experiments:
            raise Refused(f"experiment {experiment} is not one of the configured setups "
                          f"({', '.join(self.experiments) or 'none'})")
        if experiment:
            await self.require_stage_out("experiment load (may move the grating)")
            await self.reply(server, "specinitial", f"Loading LightField experiment {experiment}.",
                             process="ING")
            try:
                await asyncio.wait_for(asyncio.to_thread(self.lf.load_experiment, experiment),
                                       self.load_timeout_s)
            except asyncio.TimeoutError:
                raise TimeoutError(f"LightField did not load {experiment} within "
                                   f"{self.load_timeout_s:g} s") from None
        lf = await self.read_lf_status()
        problems = camera_problems(self.camera, lf)
        msg = f"Initializing of IsoPlane is finished (night {night}). Setup: {setup_summary(lf)}."
        if problems:
            msg += (" Warning: exposures will be refused, camera not in the configured mode: "
                    + "; ".join(problems) + ".")
        await self.reply(server, "specinitial", msg, camera_problems=problems)

    async def illuon(self, server, d):
        self.require_unit()
        lf = await self.read_lf_status()
        if lf.get("running") or lf.get("updating"):
            raise InterlockError("LightField is acquiring or updating (the grating may move)")
        await self.reply(server, "illuon", "Back illumination: lowering the stage.", process="ING")
        await asyncio.to_thread(self.bl.insert)
        await self.light_on(server)
        await self.reply(server, "illuon", f"Back illumination stage IN, light on{self.lease_note()}.",
                         backillum=self.bl.status())

    async def illuoff(self, server, d):
        self.require_unit()
        self.cancel_light_timer()
        await self.reply(server, "illuoff", "Back illumination: light off, raising the stage.",
                         process="ING")
        try:
            await asyncio.to_thread(self.bl.retract)
        finally:
            warning = await self.close_shutter()
        msg = "Back illumination light off, stage OUT."
        if self.bl.last_error:
            msg += f" Warning: {self.bl.last_error}"
        msg += warning
        await self.reply(server, "illuoff", msg, backillum=self.bl.status())

    async def illulighton(self, server, d):
        """Light on without moving the stage, e.g. between metrology trials."""
        self.require_unit()
        if self.bl.state != "IN":
            raise InterlockError(f"the stage is {self.bl.state}, not IN: send illuon to lower it")
        await self.light_on(server)
        await self.reply(server, "illulighton",
                         f"Back illumination light on, stage IN{self.lease_note()}.",
                         backillum=self.bl.status())

    async def illulightoff(self, server, d):
        """Light off without moving the stage."""
        self.require_unit()
        self.cancel_light_timer()
        await asyncio.to_thread(self.bl.set_light, False)
        warning = await self.close_shutter()
        await self.reply(server, "illulightoff",
                         f"Back illumination light off, stage {self.bl.state}.{warning}",
                         backillum=self.bl.status())

    async def take_frames(self, server, d):
        func = d["func"]
        kind, shutter_closed = FRAME_TYPES[func]
        if self.night is None:
            raise Refused("no night directory: send specinitial <night> first")
        n = int(d["numframe"])
        exptime = 0.0 if func == "getbias" else float(d["time"])
        header = d.get("header") or {}
        try:
            extra_cards(header)  # an invalid card must not cost the exposure
        except ValueError as e:
            raise Refused(f"header: {e}") from None
        await self.require_stage_out(func)
        lf = await self.read_lf_status()  # also what specstatus reports during the exposures
        problems = camera_problems(self.camera, lf)
        if problems:
            raise Refused("camera is not in the configured mode: " + "; ".join(problems))

        directory = os.path.join(self.datapath, self.night)
        paths = []
        for i in range(n):
            basename = self.next_basename(directory, kind)
            await self.reply(server, func, f"{kind} {i + 1}/{n}: {exptime:g} s exposure started.",
                             process="ING")
            frame = await self.with_progress(
                server, func, exptime, self.lf.expose, exptime, shutter_closed, directory, basename
            )
            cards = ics_cards(header, frame, func, i, n, self.sensor_bias_rows)
            cards.append(("BILLUM", self.bl.state if self.bl else "NONE",
                          "back-illumination stage state"))
            await asyncio.to_thread(append_cards, frame.path, cards)
            paths.append(await asyncio.to_thread(self.publish, frame.path))
            await self.reply(server, func, f"{kind} {i + 1}/{n} saved: {paths[-1]}",
                             process="ING")
        await self.reply(server, func, f"{n} {kind} frame(s) obtained.", filename=paths[-1],
                         filenames=paths)

    # -------------------------------------------------- helpers
    async def with_progress(self, server, func, exptime, fn, *args):
        """Run a blocking exposure in a thread, sending the remaining time every 10 s.

        An exposure still running expose_timeout_s after its exposure time is stopped; it then
        fails, also when LightField does not return within stop_grace_s of the stop.
        """
        loop = asyncio.get_running_loop()
        task = asyncio.ensure_future(asyncio.to_thread(fn, *args))
        t0 = loop.time()
        deadline = t0 + exptime + self.expose_timeout_s
        while True:
            wait = min(PROGRESS_EVERY_S, max(0.0, deadline - loop.time()))
            done, _ = await asyncio.wait({task}, timeout=wait)
            if done:
                return task.result()
            if loop.time() >= deadline:
                break
            remaining = exptime - (loop.time() - t0)
            if remaining > 0:
                await self.reply(server, func, f"Remaining exposure time: {remaining:.0f} seconds.",
                                 process="ING")
        await asyncio.to_thread(self.lf.stop)
        done, _ = await asyncio.wait({task}, timeout=self.stop_grace_s)
        task.add_done_callback(lambda t: t.cancelled() or t.exception())  # result is dropped
        raise TimeoutError(
            f"LightField did not finish the {exptime:g} s exposure within "
            f"{self.expose_timeout_s:g} s of its end; acquisition stopped"
            f"{'' if done else ' (LightField still not responding)'}"
        )

    def next_basename(self, directory, kind):
        """<night>_<seq>_<kind>, seq one above the highest in the night directory."""
        pat = re.compile(rf"^{re.escape(self.night)}_(\d{{4}})_")
        seqs = [int(m.group(1)) for f in os.listdir(directory) if (m := pat.match(f))]
        return f"{self.night}_{max(seqs, default=0) + 1:04d}_{kind}"

    def publish(self, path):
        """Copy to the shared storage (if configured) and return the path the ICS should use."""
        if not self.sharepath:
            return path
        dst_dir = os.path.join(self.sharepath, self.night)
        os.makedirs(dst_dir, exist_ok=True)
        dst = os.path.join(dst_dir, os.path.basename(path))
        shutil.copy2(path, dst + ".part")
        if os.path.getsize(dst + ".part") != os.path.getsize(path):
            raise OSError(f"copy to {dst} is incomplete")
        os.replace(dst + ".part", dst)
        return dst
