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
| `getdark <t> <n>` | n frames of t s, shutter closed (new) |
| `getflat <t> <n>`, `getarc <t> <n>`, `getobj <t> <n>` | n frames of t s |
| `illuon` / `illuoff` | stage in + light on / light off + stage out |
| `illulighton` / `illulightoff` | light only, the stage does not move; on needs the stage IN (new) |
| `specstop` | emergency stop: stage, then light, then the acquisition (new command) |

After a frame command saves all its images, its `Done` reply includes `cmdlog`: observing
night, UT (first frame start), PROJID, TILE ID, OBJTYPE, OBJECT, EXPOSURE (seconds), EXP #
(frames in the command), and Comments (last saved FITS path). Unknown header values are blank.
The ICS receives this reply and appends the row to the `CMDLOG` spreadsheet. Google credentials
are needed on the ICS machine only; a sheet failure does not change the exposure reply.

## Replies
The ICS pairs replies with commands by their order, so every command gets exactly one `Done`
reply and nothing else is sent as `Done`. Its `status` is:

| status | meaning |
|---|---|
| `success` | done |
| `fail` | refused, nothing was done: busy, interlock, no `specinitial`, no unit |
| `error` | hardware or LightField failed (also an exposure past its deadline) |
| `stopped` | interrupted by `specstop` |

Progress replies are `ING`. So are the replies the server sends unasked (light auto-off) and the
`specstop` reply while a command runs; that command then answers `Done`/`stopped`. Replies of the
illumination commands carry `backillum` (`state`, `light`), which the GUI button follows.
Scripts wait with `Lib.reply.wait_reply(queue, inst, func, timeout)`, which skips progress
replies and `Done` replies of other commands (for example a `specstatus` sent from the GUI).

## Metrology (light only between trials)
`runmtl` (script, after `loadtile`) keeps the stage IN for the whole loop and switches only the
light: `fiducialon`, `illuon`, then `mtltrial` with the light on, `illulightoff`, `fbpoffset`,
`illulighton`, ... until the MTL run converges or reaches `max_trial`, then `illuoff` and
`fiducialoff`, also after a failed step. The stage moves twice per tile, not twice per trial.

The light reaches the fibres backwards through the spectrograph and its entrance shutter (Vincent
CS25), which LightField opens only during an exposure. So every light-on first sets the
LightField shutter mode to AlwaysOpen (if that fails, the light stays off and the command fails),
and every light-off (`illulightoff`, `illuoff`, the auto-off, `specstop`, server exit) sets it back
to Normal; a reply warns when that did not work. Exposures set their own mode and are refused
while the stage is not OUT anyway. Checked on the instrument (2026-10-26, shutter opened by hand
in LightField): the light comes out of the fibres.

Every light-on starts a timer: the server switches the light off after
`backillum.light_max_on_s` (default 300 s, 0 disables) and sends an `ING` reply; the stage stays
IN. This covers the ICS script dying with the light on in the turret (the Uno watchdog only
covers this server dying). `backillum.light_settle_s` (default 1 s) is waited after a light-on
before the reply.

## Setups and camera mode
Grating, centre wavelength and camera mode come from saved LightField experiments, one per
setup. `experiments` in `isoplane_local.json` lists the ones `specinitial` may load (`null`:
any). `camera` holds the mode the reduction is calibrated for. Before every exposure the server
reads the camera state and refuses the exposure (`fail`) when a value differs. A mode changed
by hand in the LightField window therefore never reaches the data. `specinitial` and
`specstatus` report the differences (`camera_problems`).

The per-frame settings do not come from the experiment: before every exposure the server sets
the exposure time, shutter, time stamps (exposure started and ended), one frame per
acquisition, the file name, and the FITS export with the experiment information (the PI cards
the reduction reads) next to the SPE. A frame name already on disk is refused (`error`):
LightField would write `<name> - (2).fits` instead, and the old file would be read.

| key | 2026 run | LightField setting (experiment path) |
|---|---|---|
| `adc_speed_mhz` | 0.1 (2 until 2026-01-23) | `Adc/Speed` |
| `adc_gain` / `adc_quality` | High / LowNoise | `Adc/AnalogGain`, `Adc/Quality` |
| `temp_setpoint_c` / `temp_status` | -55 / Locked | `Sensor/Temperature/SetPoint`, `Status` |
| `sensor_rows` / `physical_rows` | 1330 / 1300 (1300 / 1300 until 2026-02-02) | `Sensor/Layout/ActiveArea/Height`, `Sensor/Information/ActiveArea/Height` |
| `roi_selection` | FullSensor | `ReadoutControl/RegionsOfInterest/Selection` |

Overscan: from 2026-02-03 the layout read 1330 rows of the 1300-row sensor. LightField reads
the extra rows last, so they follow the sensor rows.
- **Measured bias rows:** in raw orientation the last sensor row, row 1300, also sits at the
  bias level in every frame, both 1300- and 1330-row readouts. In a 600 s dark of 2026-02-04,
  rows 1295–1299 read 651 ADU, while rows 1300–1330 read 621 ADU with an r.m.s. of 4.1 ADU
  (4.6 e⁻). So a 1330-row readout has 31 bias rows, as the kspecdr commissioning batch assumes.
- **Header cards:** `lightfield.sensor_bias_rows` (1 on this camera) counts such rows at the end
  of the sensor. For a full-sensor readout the server writes `DATASEC = '[1:1340,1:1299]'` and
  `BIASSEC = '[1:1340,1300:1330]'` (raw orientation).
- The 8-pixel left and right margins of the sensor are not read.

## Deadlines
An exposure still running `lightfield.expose_timeout_s` (default 120 s) after its exposure time
is stopped and fails with `error`; an experiment load fails after `lightfield.load_timeout_s`
(default 300 s). A hung LightField therefore still produces a `Done` reply.

## Header cards
Every frame gets these cards after LightField's own (`fitsio.ics_cards`). They come from the
header dict of the frame command (`Lib/make_spec_header.set_header_info`) and from the server.
A value the ICS does not know (None) leaves its card out, so a card that is present is
meaningful. Numbers are written as numbers.

| card | type | source | meaning |
|---|---|---|---|
| `OBSTYPE` | str | header `OBSTYPE` | `Bias`, `Dark`, `Flat`, `Arc`, `Object`; without one, the frame type of the command |
| `ICSFUNC` | str | command | `getbias`, `getdark`, `getflat`, `getarc`, `getobj` |
| `OBSDATE` | str | header | observing night (directory name) |
| `PROJID`, `TILEID`, `OBJECT` | str | header | project, tile, object name |
| `TILERA`, `TILEDEC` | str | header `RA`, `DEC` | planned tile centre (sexagesimal), not the telescope position |
| `EXPREQ` | float | header `EXPTIME` | [s] requested exposure time (LightField `EXPTIME` stays, in ms) |
| `EXPNUM` | int | header `EXPNUM` + frame | number of this frame in the sequence: header `EXPNUM` (first frame, default 1) + its index in the command |
| `NEXP` | int | header `NEXP` | frames in the sequence (default: frames of this command) |
| `FWHM` | float | header | [arcsec] GFA seeing; left out when unknown (the scripts' 9.99) |
| `OBSERVAT`, `SITELAT`, `SITELONG`, `SITEELEV` | str, float | `KSPEC.ini` `SITE` | observatory; [deg] latitude (N +), longitude (E +); [m] elevation |
| `UTSTART`, `UTEND` | str | SPE time stamps | exposure start and end, ISO 8601 UTC (ms); left out when LightField gives no stamp |
| `SPECBACK`, `LFEXPER` | str | server | `ISOPLANE`; LightField experiment (= setup) |
| `DATASEC`, `BIASSEC` | str | camera layout | see above |
| `BILLUM` | str | back illumination | stage state |

Other subsystems (TCS, lamps, tile configuration) add cards through the header dict's `CARDS`
list, `[[key, value, comment], ...]` (`set_header_info(extra_cards=...)`). Each key must be a
FITS keyword that neither LightField nor the cards above use. Values must be str, int, float or
bool. The server checks them before the exposure and refuses the command (`fail`) when a card is
invalid, so a bad card never costs a frame.

LightField's own cards are untouched; note that its `DATE-OBS` is the end of the exposure.

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
- `netcall.py`: runs every LightField call on a .NET thread while Python waits without the GIL.
  A direct call can deadlock: `Automation()` never returned (LightField 6.15, pythonnet 3.2).
- `backillum.py`: Uno link, stage operations, `FakeUno`.
- `fitsio.py`: adds the ICS cards ("Header cards" above) to the LightField FITS. LightField's
  own cards are kept byte for byte; its EXPTIME stays in ms and the ICS request goes to EXPREQ.
- `probe_lightfield.py`: run once on the LightField PC; reports setting names, devices, and
  whether one acquisition with time stamps works.

Frames are named `<night>_<seq>_<bias|dark|flat|arc|obj>.fits` in `<datapath>/<night>/` and copied
to `<sharepath>/<night>/` when `sharepath` is set; the reply carries the shared path.

## Setup
1. Copy `isoplane_local.example.json` to `isoplane_local.json` (gitignored) and edit it:
   `lightfield.driver` (`fake` or `lightfield`), the LightField `root`, the Uno `port`
   (`fake`, `COM5`, ...), the stage `in_depth_mm` / `in_limit_mm`, `datapath`, `sharepath`,
   the `camera` mode and `experiments` list, and optionally the timeouts and light settings
   above. `lightfield.shape` and `overscan_rows` shape the fake frames only.
   Leave out `backillum` (or set it to `null`) when no unit is installed.
2. In `Lib/KSPEC.ini` set `SPEC.queue` to `ISOPLANE` on the ICS side, and the broker
   `RabbitMQ.ip_addr` on the LightField PC.
3. On the LightField PC: `pip install pythonnet pyserial aio-pika astropy numpy`, then
   `python SPECTRO_ISOPLANE/probe_lightfield.py` and check the report.
   LightField runs in a child `AddInProcess.exe`. If the server or the probe is killed while
   LightField starts, that child can stay behind and break every later start (IPC "pipe has
   been ended", or a hang); end it, or reboot when it cannot be ended.
   Read or set a LightField setting only after `Exists`: `GetValue`/`SetValue` of a missing
   setting crashes LightField itself ("LightField has stopped working"; answer Cancel).
   Saved experiments are looked up in `<LightField working directory>\Experiments`
   (LightField Options): keep the working directory fixed rather than per night.
4. Start the server from the repository root: `python SPECTRO_ISOPLANE/ISOPLANE_server.py`.

Tests with the fakes: `python -m unittest tests.test_isoplane_fake`.
