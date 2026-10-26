"""Run IsoPlane server commands on the real hardware without RabbitMQ (bench tests).

Run on the LightField PC, with the LightField window closed, from the KSPEC_ICS root. The
commands go through the server's own handler (``command.Isoplane.handle``) with the settings of
isoplane_local.json, one after the other; every reply is printed. The run stops at the first
command that does not succeed (``--keep-going`` continues), and always ends with the server's
close (light off, LightField disposed).

    python SPECTRO_ISOPLANE/bench.py "specinitial 20261025 KSPEC_600_680" specstatus \\
        "getbias 1" "getdark 5 1"

Commands: ``specinitial <night> [experiment]``, ``specstatus``, ``getbias <n>``,
``getdark|getflat|getarc|getobj <t> <n>``, ``illuon``, ``illuoff``, ``illulighton``,
``illulightoff``, ``specstop``, ``wait <s>`` (bench only: sleep, the server keeps running,
e.g. for the light auto-off) and ``waitlock <s>`` (bench only: poll the camera every 30 s until
its temperature is Locked, at most <s> s; a camera just powered on takes 15-20 min). Frame commands carry the header dict of
``Lib/make_spec_header.set_header_info`` (OBJECT ``bench``), as the ICS sends it.
"""

import argparse
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Lib.make_spec_header import set_header_info  # noqa: E402
from SPECTRO_ISOPLANE.command import FRAME_TYPES, Isoplane  # noqa: E402

OBSTYPE = {"getbias": "Bias", "getdark": "Dark", "getflat": "Flat", "getarc": "Arc",
           "getobj": "Object"}
SHOWN = ("filename", "filenames", "camera_problems", "backillum")


class PrintServer:
    """Stands in for the AMQ client: prints each reply and keeps it."""

    def __init__(self):
        self.sent = []

    async def send_message(self, key, message):
        d = json.loads(message)
        self.sent.append(d)
        extra = {k: d[k] for k in SHOWN if k in d}
        print(f"  <- {d.get('func')} {d.get('process')}/{d.get('status')}: {d.get('message')}"
              + (f"  {extra}" if extra else ""), flush=True)


def message(words, night):
    """The ICS message dict for one bench command (``words`` = command and arguments)."""
    func, args = words[0], words[1:]
    d = {"inst": "SPEC", "func": func, "message": " ".join(words)}
    if func == "specinitial":
        d["dirname"] = args[0]
        if len(args) > 1:
            d["experiment"] = args[1]
    elif func in FRAME_TYPES:
        n = int(args[-1])
        t = 0.0 if func == "getbias" else float(args[0])
        d.update(numframe=n, time=t)
        d["header"] = set_header_info(obstype=OBSTYPE[func], obsdate=night, exptime=t,
                                      expnum=n, object_name="bench")
    return d


async def run(cfg, commands, keep_going):
    iso = Isoplane(cfg)
    server = PrintServer()
    night = "bench"
    try:
        await iso.start()
        print(f"started: {iso.lf_status.get('experiment')} "
              f"{iso.lf_status.get('grating')} {iso.lf_status.get('center_nm')} nm", flush=True)
        for cmd in commands:
            words = cmd.split()
            if words[0] == "wait":
                print(f"-> wait {words[1]} s", flush=True)
                await asyncio.sleep(float(words[1]))
                continue
            if words[0] == "waitlock":
                print(f"-> waitlock (at most {words[1]} s)", flush=True)
                t_end = time.monotonic() + float(words[1])
                while True:
                    st = await iso.read_lf_status()
                    print(f"  camera {st.get('sensor_temp_c')} C {st.get('temp_status')}",
                          flush=True)
                    if str(st.get("temp_status")).lower() == "locked":
                        break
                    if time.monotonic() > t_end:
                        print("stopping: the camera did not lock", flush=True)
                        return 1
                    await asyncio.sleep(30)
                continue
            if words[0] == "specinitial":
                night = words[1]
            print(f"-> {cmd}", flush=True)
            n = len(server.sent)
            await iso.handle(server, json.dumps(message(words, night)))
            done = [d for d in server.sent[n:] if d.get("process") == "Done"]
            if not keep_going and (not done or done[-1].get("status") != "success"):
                print("stopping: the command did not succeed", flush=True)
                return 1
        return 0
    finally:
        await iso.close()
        print("closed", flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("commands", nargs="+", help='e.g. "getdark 5 1" (quote each command)')
    ap.add_argument("--config", default="SPECTRO_ISOPLANE/isoplane_local.json")
    ap.add_argument("--keep-going", action="store_true")
    a = ap.parse_args()
    with open(a.config, encoding="utf-8") as f:
        cfg = json.load(f)
    sys.exit(asyncio.run(run(cfg, a.commands, a.keep_going)))


if __name__ == "__main__":
    main()
