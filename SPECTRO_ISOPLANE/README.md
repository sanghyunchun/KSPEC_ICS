# SPECTRO_ISOPLANE

ICS server for the backup spectrograph, a Teledyne PI IsoPlane SCT320 run by LightField, and
its back-illumination unit (a flat light on a linear stage lowered into the grating-turret
compartment, driven by an Uno). It accepts the SPEC command set of the main spectrograph, so
the GUI and the observing scripts work unchanged:

| command | IsoPlane action |
|---|---|
| `specinitial <night> [experiment]` | night directory; optionally load a saved LightField experiment (may move the grating) |
| `specstatus` | camera, grating, and stage state |
| `getbias <n>` | n frames, shutter closed, 0 s |
| `getflat <t> <n>`, `getarc <t> <n>`, `getobj <t> <n>` | n frames of t s |
| `illuon` / `illuoff` | stage in + light on / light off + stage out |
| `specstop` | emergency stop: stage, then light, then the acquisition (new command) |

## Replies
The ICS pairs replies with commands by their order, so every command gets exactly one `Done`
reply and nothing else is sent as `Done`. Its `status` is:

| status | meaning |
|---|---|
| `success` | done |
| `fail` | refused, nothing was done: busy, interlock, no `specinitial`, no unit |
| `error` | hardware or LightField failed |
| `stopped` | interrupted by `specstop` |

Progress replies are `ING`. So is the `specstop` reply while a command runs; that command then
answers `Done`/`stopped`.

## Grating and stage interlock
One process owns LightField and the Uno. Every command except `specstatus` takes one lock, so an
exposure, an experiment load, and a stage move never overlap. A command that arrives while
another one runs is refused at once (`<cmd> refused: busy with <running cmd>.`), not queued.
`specstatus` always answers at once; while a command runs, it reports the LightField state read
just before that command ("as of" time in the reply). Before an exposure or an
experiment load, the stage Near switch is read from the hardware; the stage must be OUT and the
light off, otherwise the command is refused. If the server starts with the stage away from
Near, exposures, experiment loads, and `illuon` are refused until `illuoff` brings it home
(`specstatus`, `specstop`, and `specinitial <night>` without an experiment still work).

`specstop` does not wait for the lock. It stops the stage first, then switches the light off,
then stops the LightField acquisition; the running command replies `stopped` and an interrupted
frame is not saved. The stage position is then unknown, so exposures, experiment loads, and
`illuon` are refused until `illuoff` has homed the stage.

Changing the grating by hand in the LightField window bypasses this interlock: do it only with
the stage OUT, or use `specinitial <night> <experiment>`.

If the server process dies, the Uno switches the light off and stops the stage after 60 s
without a command (firmware watchdog). The stage stays where it is: restart the server and send
`illuoff`.

## Files
- `ISOPLANE_server.py`: RabbitMQ consumer on queue `ISOPLANE`.
- `command.py`: the commands, the lock, and the interlock.
- `lightfield.py`: `LightField` (pythonnet, Windows) and `FakeLightField`.
- `backillum.py`: Uno link, stage operations, `FakeUno`.
- `fitsio.py`: adds the ICS cards (OBSTYPE, TILEID, UTSTART/UTEND, ...) to the LightField FITS.
  LightField's own cards are kept byte for byte; its EXPTIME stays in ms and the ICS request
  goes to EXPREQ.
- `probe_lightfield.py`: run once on the LightField PC; reports setting names, devices, and
  whether one acquisition with time stamps works.

Frames are named `<night>_<seq>_<bias|flat|arc|obj>.fits` in `<datapath>/<night>/` and copied
to `<sharepath>/<night>/` when `sharepath` is set; the reply carries the shared path.

## Setup
1. Copy `isoplane_local.example.json` to `isoplane_local.json` (gitignored) and edit it:
   `lightfield.driver` (`fake` or `lightfield`), the LightField `root`, the Uno `port`
   (`fake`, `COM5`, ...), the stage `in_depth_mm` / `in_limit_mm`, `datapath`, `sharepath`.
   Leave out `backillum` (or set it to `null`) when no unit is installed.
2. In `Lib/KSPEC.ini` set `SPEC.queue` to `ISOPLANE` on the ICS side, and the broker
   `RabbitMQ.ip_addr` on the LightField PC.
3. On the LightField PC: `pip install pythonnet pyserial aio-pika astropy numpy`, then
   `python SPECTRO_ISOPLANE/probe_lightfield.py` and check the report.
4. Start the server from the repository root: `python SPECTRO_ISOPLANE/ISOPLANE_server.py`.

Tests with the fakes: `python -m unittest tests.test_isoplane_fake`.
