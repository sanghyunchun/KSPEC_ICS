"""Send one IsoPlane command through RabbitMQ and print the server's replies until its Done.

For tests on the LightField PC while the server runs (unlike bench.py, which owns LightField
itself). Run from the KSPEC_ICS root with the ICS Python:

    python SPECTRO_ISOPLANE/sendcmd.py "specinitial 20261027 KSPEC_150_0"
    python SPECTRO_ISOPLANE/sendcmd.py "getobj 100 1" --save reply.json

Frame commands carry the header dict of ``Lib/make_spec_header.set_header_info`` (``--night``,
``--object``). Replies are read from a temporary auto-delete queue bound to routing key ICS on
ics.ex, so the ICS's own ICS_queue still gets every reply (nothing is taken from it); the ICS
then sees Done replies of commands it did not send, which ``wait_reply`` skips.
"""

import argparse
import asyncio
import json
import sys

import aio_pika

sys.path.insert(0, ".")
from Lib.make_spec_header import set_header_info  # noqa: E402
from SPECTRO_ISOPLANE.specisocli import make_speciso_command  # noqa: E402

OBSTYPE = {"getbias": "Bias", "getdark": "Dark", "getflat": "Flat", "getarc": "Arc",
           "getobj": "Object"}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command")
    ap.add_argument("--timeout", type=float, default=600)
    ap.add_argument("--save", help="write the Done reply here (JSON)")
    ap.add_argument("--object", default="zero-order test")
    ap.add_argument("--night", default="20261027")
    a = ap.parse_args()
    ini = json.load(open("Lib/KSPEC.ini"))["RabbitMQ"]
    words = a.command.split()
    func = words[0]
    header = None
    if func in OBSTYPE:
        t = 0.0 if func == "getbias" else float(words[1])
        header = set_header_info(obstype=OBSTYPE[func], obsdate=a.night, exptime=t,
                                 expnum=int(words[-1]), object_name=a.object)
    msg = make_speciso_command(a.command, header)

    conn = await aio_pika.connect_robust(host=ini["ip_addr"], login=ini["idname"],
                                         password=ini["pwd"])
    async with conn:
        ch = await conn.channel()
        ex = await ch.declare_exchange("ics.ex", aio_pika.ExchangeType.DIRECT)
        q = await ch.declare_queue("", exclusive=True, auto_delete=True)
        await q.bind(ex, routing_key="ICS")
        await ex.publish(aio_pika.Message(body=msg.encode()), routing_key="ISOPLANE")
        print(f"-> {a.command}", flush=True)
        try:
            async with asyncio.timeout(a.timeout):
                async with q.iterator() as it:
                    async for m in it:
                        async with m.process():
                            d = json.loads(m.body)
                        if d.get("inst") not in (None, "SPEC") or d.get("func") != func:
                            continue
                        extra = {k: d[k] for k in ("filename", "camera_problems", "backillum")
                                 if k in d}
                        print(f"<- {d.get('process')}/{d.get('status')}: {d.get('message')}"
                              + (f"  {extra}" if extra else ""), flush=True)
                        if "zoflux" in d:
                            z = d["zoflux"]
                            print("   zoflux:", {k: z.get(k) for k in
                                                 ("ok", "nfib", "ndet", "method", "pitch",
                                                  "error")}, flush=True)
                        if d.get("process") == "Done":
                            if a.save:
                                json.dump(d, open(a.save, "w"), indent=1)
                            return 0 if d.get("status") == "success" else 1
        except TimeoutError:
            print(f"no Done reply within {a.timeout:g} s", flush=True)
            return 2


sys.exit(asyncio.run(main()))
