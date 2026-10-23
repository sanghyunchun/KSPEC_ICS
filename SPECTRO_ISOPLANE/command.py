"""ISOPLANE server: the SPEC command set of the main spectrograph, run on the IsoPlane.

Commands and replies follow ``SPECTRO/command.py`` (``inst='SPEC'``, ING progress replies, one
final Done reply per command), so ``speccli.py``, the GUI, and ``scriptcli.py`` need no
IsoPlane-specific code:

    specinitial <night> [experiment]   night directory; optionally load a LightField experiment
    specstatus                         camera, grating, and back-illumination state
    getbias <n> / getflat <t> <n> / getarc <t> <n> / getobj <t> <n>
    illuon / illuoff                   back-illumination stage in + light on / light off + out
    specstop                           emergency stop: stage, then light, then LightField

Replies. The ICS pairs replies with commands by their order, so every command gets exactly one
Done reply, and nothing else is ever sent as Done. Its status is success; fail when the command
was refused and nothing was done (busy, interlock, missing setup); error when the hardware or
LightField failed; or stopped when specstop interrupted it. The specstop reply while a command
runs is ING.

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
"""

import asyncio
import datetime as dt
import json
import os
import re
import shutil

import Lib.mkmessage as mkmsg
from SPECTRO_ISOPLANE.backillum import make_backillum
from SPECTRO_ISOPLANE.fitsio import append_cards, ics_cards
from SPECTRO_ISOPLANE.lightfield import make_lightfield

# func: (file-name tag, shutter closed)
FRAME_TYPES = {
    "getbias": ("bias", True),
    "getflat": ("flat", False),
    "getarc": ("arc", False),
    "getobj": ("obj", False),
}
PROGRESS_EVERY_S = 10


class Refused(RuntimeError):
    """The command was not carried out (reply status fail)."""


class InterlockError(Refused):
    pass


class Isoplane:
    def __init__(self, cfg, lightfield=None, backillum=None):
        self.lf = lightfield if lightfield is not None else make_lightfield(cfg.get("lightfield", {}))
        self.bl = backillum if backillum is not None else make_backillum(cfg.get("backillum"))
        self.datapath = cfg.get("datapath", "../DATA/RAWDATA/")
        self.sharepath = cfg.get("sharepath", "")
        self.night = None
        self.lock = asyncio.Lock()
        self.busy = "idle"
        self.stop_requested = False  # specstop arrived while self.busy ran
        self.lf_status = {}  # last LightField status, served while a command runs
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
        if self.bl is not None:
            await asyncio.to_thread(self.bl.close)  # light off
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
                await self.reply(server, func, msg, status=status)
            finally:
                self.busy = "idle"
                self.stop_requested = False

    async def emergency_stop(self, server):
        """Stage stop, then light off, then LightField stop; does not wait for the lock.

        While a command runs, the reply is ING: that command's own Done (status stopped) is
        the one reply the ICS waits for.
        """
        interrupted = self.busy
        running = interrupted != "idle"
        if running:
            self.stop_requested = True
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
        msg = f"Emergency stop ({'during ' + interrupted if running else 'idle'}): "
        msg += "; ".join(done + failed) + "."
        if self.bl is not None:
            msg += " Stage position unknown: send illuoff to home it."
        await self.reply(server, "specstop", msg, process="ING" if running else "Done",
                         status="error" if failed else "success")

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
        details = {"night": self.night, "busy": self.busy, "lightfield": lf,
                   "lightfield_read_at": self.lf_status_time, "backillum": bl}
        msg = (f"IsoPlane: {'busy (' + self.busy + ')' if busy else 'ready'}, "
               f"night {self.night}, experiment {lf.get('experiment')}, grating "
               f"{lf.get('grating')} at {lf.get('center_nm')} nm"
               f"{' (as of ' + str(self.lf_status_time) + ')' if busy else ''}, back illumination "
               f"{bl['state']}{' light ON' if bl.get('light') else ''}.")
        return msg, details

    async def specinitial(self, server, d):
        night = str(d["dirname"])
        os.makedirs(os.path.join(self.datapath, night), exist_ok=True)
        self.night = night
        experiment = d.get("experiment")
        if experiment:
            await self.require_stage_out("experiment load (may move the grating)")
            await self.reply(server, "specinitial", f"Loading LightField experiment {experiment}.",
                             process="ING")
            await asyncio.to_thread(self.lf.load_experiment, experiment)
            await self.read_lf_status()
        await self.reply(server, "specinitial",
                         f"Initializing of IsoPlane is finished (night {night}"
                         f"{', experiment ' + experiment if experiment else ''}).")

    async def illuon(self, server, d):
        self.require_unit()
        lf = await self.read_lf_status()
        if lf.get("running") or lf.get("updating"):
            raise InterlockError("LightField is acquiring or updating (the grating may move)")
        await self.reply(server, "illuon", "Back illumination: lowering the stage.", process="ING")
        await asyncio.to_thread(self.bl.insert)
        await asyncio.to_thread(self.bl.set_light, True)
        await self.reply(server, "illuon", "Back illumination light on.")

    async def illuoff(self, server, d):
        self.require_unit()
        await self.reply(server, "illuoff", "Back illumination: light off, raising the stage.",
                         process="ING")
        await asyncio.to_thread(self.bl.retract)
        msg = "Back illumination light off, stage OUT."
        if self.bl.last_error:
            msg += f" Warning: {self.bl.last_error}"
        await self.reply(server, "illuoff", msg)

    async def take_frames(self, server, d):
        func = d["func"]
        kind, shutter_closed = FRAME_TYPES[func]
        if self.night is None:
            raise Refused("no night directory: send specinitial <night> first")
        n = int(d["numframe"])
        exptime = 0.0 if func == "getbias" else float(d["time"])
        header = d.get("header") or {}
        await self.require_stage_out(func)
        await self.read_lf_status()  # what specstatus reports during the exposures

        directory = os.path.join(self.datapath, self.night)
        paths = []
        for i in range(n):
            basename = self.next_basename(directory, kind)
            await self.reply(server, func, f"{kind} {i + 1}/{n}: {exptime:g} s exposure started.",
                             process="ING")
            frame = await self.with_progress(
                server, func, exptime, self.lf.expose, exptime, shutter_closed, directory, basename
            )
            expnum = header.get("EXPNUM", "None") if n == 1 else f"{i + 1}/{n}"
            cards = ics_cards(header, frame, func, expnum)
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
        """Run a blocking exposure in a thread, sending the remaining time every 10 s."""
        task = asyncio.ensure_future(asyncio.to_thread(fn, *args))
        remaining = exptime
        while True:
            done, _ = await asyncio.wait({task}, timeout=PROGRESS_EVERY_S)
            if done:
                return task.result()
            remaining -= PROGRESS_EVERY_S
            if remaining > 0:
                await self.reply(server, func, f"Remaining exposure time: {remaining:.0f} seconds.",
                                 process="ING")

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
