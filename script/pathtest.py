"""MTL-watched path test: step slowly through one tile's motion path with no sky, then back.

Checks that the positioners of a star-scan tile do not collide along the planner path and
where the fibre tips really go (MTL image at every visited row), then returns to the start
pose through the same rows in reverse. Run from the KSPEC_ICS root with the ICS Python:

    python script/pathtest.py --path ZOSCAN_2627_0005.coarse.path.txt --dry-run
    python script/pathtest.py --path ZOSCAN_2627_0005.coarse.path.txt \\
        --assign ZOSCAN_2627_0005.assign.txt --backlight --fiducials

Before the first move the positioners must be at the first visited row (row 0 = the power-on
pose, FBP state 'initial'); that row is commanded too (a no-op move) and imaged as the
baseline. Per visited row: <outdir>/<stem>_r<row>.json (absolute command angles of every
positioner of Lib/positioner_axis_map.json), fbpoffset, wait for Done/success, then
[illulighton] mtltest <exptime> <nexp> <stem>_r<row>[_ret] [illulightoff], and one line in
<outdir>/<stem>_pathtest.jsonl.

Rows (--rows): 'A:B' is inclusive and may run backwards (B < A); '--every K' takes every K-th
row of it and always the last one. 'r1,r2,...' visits exactly those rows (no --every). A run
that stopped without returning prints the exact '--rows <list> --no-return' command that
brings the positioners back through the rows they came by.

Stopping: by default every move waits for a prompt (Enter = move + image, m = move without
image, q = stop). Ctrl-C stops going forward after the reply of the current move (a second
Ctrl-C while waiting for that reply aborts without return). After q or Ctrl-C the run returns
to the start pose (prompted too, unless --no-prompt; --no-return skips it). After an FBP
failure nothing moves again: the script prints how to return by hand. MTL or back-light
failures stop the forward part; the return still runs (images are tried, and dropped for the
rest of the return after the first failure there).

Angles: the path file holds geometric angles, FBP takes command = -geometric + (30, 150)
(KSPEC.ini SCIOBS alpha/beta_offset_deg; script/starscan.py).
"""
import argparse
import asyncio
import datetime as dt
import inspect
import json
import os
import queue
import shlex
import signal
import sys
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from script.starscan import (KSPEC_INI, BrokerLink, JsonLog, axis_map_positioners,  # noqa: E402
                             check_complete, motion_offsets, parse_tile_name, read_assign,
                             read_path, to_command, write_angles)
from FBP.fbpcli import fbp_offset  # noqa: E402
from MTL.mtlcli import mtl_test  # noqa: E402
from SPECTRO.speccli import ILLUMINATION_COMMANDS, create_spec_command  # noqa: E402

ILLU_TIMEOUT_S = 120.0     # IsoPlane stage move (~15-20 s) and light switch
MOVE_EPS_DEG = 1e-3        # an axis turning less than this does not count as moving
SKIP_WARN_DEG = 0.5        # warn when skipped rows leave a straight move by more than this
INTERRUPTS = (KeyboardInterrupt, asyncio.CancelledError)


class FbpFailed(Exception):
    """fbpoffset did not reply success: nothing may move again without the user."""


class Abort(Exception):
    """Second Ctrl-C while waiting for the FBP reply of a move: stop without return."""


class AuxFailed(Exception):
    """MTL image or back illumination failed (info dict for the record)."""

    def __init__(self, info):
        super().__init__(info.get('message'))
        self.info = info


def _uncancel():
    """Drop a cancellation that was caught, so later timeouts work as usual."""
    try:
        task = asyncio.current_task()
    except RuntimeError:
        task = None
    if task is not None and task.cancelling():
        task.uncancel()


# -------------------------------------------------------------- plan
def select_rows(nrows, every=1, rows=None):
    """Visited row indices: 'A:B' (inclusive, backwards if B < A, empty = first / last) with
    every K-th row and always the last; or an explicit 'r1,r2,...' list (every must be 1)."""
    if every < 1:
        raise ValueError('--every must be >= 1')
    spec = '0:' if rows is None else rows.strip()
    if ':' in spec:
        a, _, b = spec.partition(':')
        a = int(a) if a.strip() else 0
        b = int(b) if b.strip() else nrows - 1
        d = 1 if b >= a else -1
        out = list(range(a, b + d, d * every))
        if out[-1] != b:
            out.append(b)
    else:
        if every != 1:
            raise ValueError('--every does not apply to a row list')
        out = [int(r) for r in spec.split(',') if r.strip()]
    if not out:
        raise ValueError(f'--rows {rows}: no rows')
    bad = [r for r in out if not 0 <= r < nrows]
    if bad:
        raise ValueError(f'rows {bad} are outside the path (0..{nrows - 1})')
    if any(r == s for r, s in zip(out, out[1:])):
        raise ValueError(f'rows {out}: the same row twice in a row')
    return out


def path_stem(path_file, tag=None):
    """'ZOSCAN_2627_0005.coarse.path.txt' -> 'ZOSCAN_2627_0005_coarse' (+ '_<tag>')."""
    name = os.path.basename(path_file)
    for suffix in ('.path.txt', '.txt'):
        if name.endswith(suffix):
            name = name[:-len(suffix)]
            break
    name = name.replace('.', '_').replace(' ', '_')
    return f'{name}_{tag}' if tag else name


def motion_summary(prev, cmd, lit=()):
    """Which positioners move between two command-angle dicts, and by how much."""
    delta = {k: cmd[k] - prev[k] for k in cmd}
    key = max(delta, key=lambda k: abs(delta[k]))
    holes = sorted({k[:-2] for k in cmd})
    movers = [h for h in holes
              if max(abs(delta[f'{h}_a']), abs(delta[f'{h}_b'])) > MOVE_EPS_DEG]
    return dict(max_dangle_deg=round(abs(delta[key]), 4), max_axis=key, n_move=len(movers),
                n_lit_move=sum(h in lit for h in movers), movers=movers)


def skip_deviation(commands, i, j):
    """Largest distance [deg] of the path rows strictly between i and j from the straight
    (linear in command angle) move i -> j; 0 for consecutive rows."""
    if abs(j - i) < 2:
        return 0.0
    a, b = commands[i], commands[j]
    d = 1 if j > i else -1
    worst = 0.0
    for k in range(i + d, j, d):
        f = (k - i) / (j - i)
        worst = max(worst, max(abs(commands[k][x] - (a[x] + f * (b[x] - a[x]))) for x in a))
    return round(worst, 4)


def make_plan(path_file, rows, outdir, stem, positioners, offsets=(30.0, 150.0)):
    """Command angles of every path row and one checked JSON per visited row.

    Raises before anything is sent when a row misses a positioner of the axis map.
    Returns (commands, {row: json_file}).
    """
    _, geo = read_path(path_file)
    commands = [to_command(r, offsets) for r in geo]
    files = {}
    for row in dict.fromkeys(rows):
        check_complete(commands[row], positioners)
        files[row] = write_angles(os.path.join(outdir, f'{stem}_r{row:03d}.json'),
                                  commands[row])
    return commands, files


def describe(key, body):
    """routing key, func and the key fields of a message (not the 146 angles)."""
    d = json.loads(body)
    func = d.get('func')
    if func == 'fbpoffset':
        extra = f"{d.get('source_name')} ({len(d.get('offsets', {}))} angles)"
    elif func == 'mtltest':
        extra = f"exptime {float(d['time']) / 1e6:g} s x {d.get('nexposure')}, file {d.get('file')}"
    else:
        extra = ''
    return f'{key} {func} {extra}'.rstrip()


# -------------------------------------------------------------- links
class DryLink:
    """Sends nothing; every request gets an immediate success Done."""

    def __init__(self):
        self.last = {}

    async def send(self, key, body):
        d = json.loads(body)
        self.last[d.get('func')] = d

    async def wait_done(self, inst, func, timeout, match=None):
        reply = {'inst': inst, 'func': func, 'process': 'Done', 'status': 'success',
                 'message': 'dry run', 'dry_run': True}
        if func == 'mtltest':
            d = self.last.get(func, {})
            reply['images'] = [f"{d.get('file')}_{i}.fits"
                               for i in range(int(d.get('nexposure') or 1))]
        return reply


# -------------------------------------------------------------- run
class PathTest:
    """One path test. link: send(key, body) / wait_done(inst, func, timeout); ask(prompt) ->
    str (or awaitable); lamp(cmd) async (fiducialon / fiducialoff)."""

    def __init__(self, path_file, rows, *, link, ask, lamp, outdir, positioners,
                 offsets=(30.0, 150.0), assign_file=None, tag=None, mtl=True, mtl_exptime=0.5,
                 mtl_nexp=1, backlight=False, fiducials=False, prompt=True, do_return=True,
                 dry_run=False, spec_key='ISOPLANE', fbp_timeout=600.0, mtl_timeout=300.0,
                 illu_timeout=ILLU_TIMEOUT_S, every=1, out=print):
        self.path_file, self.rows = os.path.abspath(path_file), list(rows)
        self.link, self.ask, self.lamp, self.out = link, ask, lamp, out
        self.outdir = os.path.abspath(outdir)
        self.mtl, self.mtl_exptime, self.mtl_nexp = mtl, mtl_exptime, mtl_nexp
        self.backlight = backlight and mtl
        self.fiducials, self.prompt, self.do_return = fiducials, prompt, do_return
        self.dry, self.spec_key = dry_run, spec_key
        self.fbp_timeout, self.mtl_timeout, self.illu_timeout = fbp_timeout, mtl_timeout, illu_timeout
        self.every, self.tag = every, tag
        self.stem = path_stem(path_file, tag)
        try:
            self.tile = parse_tile_name(path_file)
        except ValueError:
            self.tile = None
        self.lit = set()
        if assign_file:
            self.lit = {h for h, a in read_assign(assign_file).items() if a['cls'] == 1}
        self.commands, self.files = make_plan(path_file, self.rows, self.outdir, self.stem,
                                              positioners, offsets)
        self.log = JsonLog(os.path.join(self.outdir, f'{self.stem}_pathtest.jsonl'))
        self.track = []          # forward rows reached; the pose is track[-1]
        self.light = False       # back light possibly on
        self.stage_in = self.fid_on = False
        self.cleaning = False
        self.return_mtl = mtl

    # ---------------------------------------------------- messages
    async def _send(self, key, body):
        self.out(f"{'[dry-run] would send' if self.dry else '->'} {describe(key, body)}")
        await self.link.send(key, body)

    async def _illu(self, cmd):
        """One IsoPlane back-illumination command; AuxFailed unless Done/success."""
        if cmd == 'illuon':
            self.stage_in = True
        if cmd in ('illuon', 'illulighton'):
            self.light = True
        await self._send(self.spec_key, create_spec_command(cmd, message=ILLUMINATION_COMMANDS[cmd]))
        reply = await self.link.wait_done('SPEC', cmd, self.illu_timeout)
        ok = reply.get('status') == 'success'
        if ok and cmd in ('illuoff', 'illulightoff'):
            self.light = False
        if not ok:
            raise AuxFailed({'illumination': cmd, 'message': f"{cmd} failed: {reply.get('message')}"})

    async def _lamp(self, cmd):
        if self.dry:
            self.out(f'[dry-run] would switch LAMP {cmd} (WebRelay HTTP)')
            return
        self.out(f'-> LAMP {cmd}')
        await self.lamp(cmd)

    async def _fbp(self, row):
        """fbpoffset to a row; (reply, interrupted). A Ctrl-C while the move runs waits for
        its Done; a second one raises Abort."""
        try:
            await self._send('FBP', fbp_offset(self.files[row]))
            return await self.link.wait_done('FBP', 'fbpoffset', self.fbp_timeout), False
        except INTERRUPTS:
            _uncancel()
            self.out('Ctrl-C: this move was sent; waiting for its FBP reply before stopping '
                     '(Ctrl-C again = abort, no return).')
        try:
            return await self.link.wait_done('FBP', 'fbpoffset', self.fbp_timeout), True
        except INTERRUPTS:
            _uncancel()
            raise Abort(f'second Ctrl-C while the move to row {row} ran') from None

    async def _image(self, row, phase):
        """[illulighton] mtltest [illulightoff]; the record fields, AuxFailed on failure."""
        name = f'{self.stem}_r{row:03d}' + ('_ret' if phase == 'return' else '')
        info = {'mtl_file': name}
        try:
            if self.backlight:
                await self._illu('illulighton')
            await self._send('MTL', mtl_test(self.mtl_exptime, self.mtl_nexp, name))
            reply = await self.link.wait_done(
                'MTL', 'mtltest', self.mtl_timeout,
                match=lambda d: any(os.path.basename(str(i)).startswith(name + '_')
                                    for i in d.get('images') or []) or d.get('status') != 'success')
        finally:
            if self.backlight and self.light:
                try:
                    await self._illu('illulightoff')
                except Exception as error:
                    self.out(f'WARNING: {error}')
        info.update(mtl_status=reply.get('status'), mtl_images=reply.get('images'),
                    mtl_message=reply.get('message'))
        if reply.get('status') != 'success':
            raise AuxFailed(dict(info, message=f"mtltest failed: {reply.get('message')}"))
        return info

    # ---------------------------------------------------- steps
    def _step_text(self, phase, n, total, row, prev):
        m = motion_summary(self.commands[prev], self.commands[row], self.lit)
        text = (f"[{'fwd' if phase == 'forward' else 'ret'} {n}/{total}] row {row:03d} <- "
                f"{prev:03d}: {m['n_move']} move" + (f" ({m['n_lit_move']} lit)" if self.lit else '')
                + (f", max {m['max_dangle_deg']:.2f} deg {m['max_axis']}" if m['n_move'] else ''))
        dev = skip_deviation(self.commands, prev, row)
        if dev > SKIP_WARN_DEG:
            text += f'; WARNING: skipped rows leave this straight move by up to {dev:.2f} deg'
        return text, m, dev

    async def _confirm(self, prompt):
        """'' (move + image), 'm' (move only) or 'q'; asks again on anything else."""
        while True:
            ans = self.ask(prompt)
            if inspect.isawaitable(ans):
                ans = await ans
            ans = (ans or '').strip().lower()
            if ans in ('', 'm', 'q'):
                return ans
            self.out("  Enter = move + image, m = move without image, q = stop")

    async def _step(self, phase, n, total, row, prev, image):
        """Move to row (and image it); returns None or 'interrupt' / 'aux' to stop."""
        text, m, dev = self._step_text(phase, n, total, row, prev)
        rec = dict(event='step', phase=phase, row=row, from_row=prev, json=self.files[row],
                   max_dangle_deg=m['max_dangle_deg'], max_axis=m['max_axis'],
                   n_move=m['n_move'], n_lit_move=m['n_lit_move'], movers=m['movers'],
                   skip_dev_deg=dev, dry_run=self.dry)
        if self.backlight and self.light:          # light off while the positioners move
            try:
                await self._illu('illulightoff')
            except AuxFailed as error:
                self.out(f'WARNING: {error}; moving with the back light on')
        reply, interrupted = await self._fbp(row)
        rec.update(fbp_status=reply.get('status'), fbp_message=reply.get('message'))
        if reply.get('status') != 'success':
            rec['result'] = 'fbp_failed'
            self.log.write(**rec)
            self.out(f"{text}; FBP {reply.get('status')}: {reply.get('message')}")
            raise FbpFailed(f"fbpoffset to row {row} (from row {prev}): {reply.get('status')}: "
                            f"{reply.get('message')}")
        stop = 'interrupt' if interrupted else None
        if image and not interrupted:
            try:
                rec.update(await self._image(row, phase))
            except INTERRUPTS:
                _uncancel()
                rec['mtl_status'] = 'interrupted'
                stop = 'interrupt'
            except AuxFailed as error:
                rec.update(error.info)
                stop = 'aux'
        rec['result'] = stop or 'ok'
        self.log.write(**rec)
        mtl = ''
        if 'mtl_status' in rec:
            mtl = '; MTL ' + ' '.join(x for x in (rec.get('mtl_file'), rec['mtl_status']) if x)
            if rec.get('mtl_images'):
                mtl += f" ({len(rec['mtl_images'])} image{'s' * (len(rec['mtl_images']) > 1)})"
        self.out(f"{text}; FBP {reply.get('status')}{mtl}")
        return stop

    async def _setup(self):
        if self.fiducials:
            self.fid_on = True
            await self._lamp('fiducialon')
        if self.backlight:
            await self._illu('illuon')          # stage in + light on; off while moving
            await self._illu('illulightoff')

    async def _forward(self):
        """Forward rows; returns 'done', 'quit', 'interrupt' or 'aux'."""
        total = len(self.rows)
        for n, row in enumerate(self.rows, start=1):
            prev = self.track[-1] if self.track else self.rows[0]
            image = self.mtl
            try:
                if self.prompt:
                    text, _, _ = self._step_text('forward', n, total, row, prev)
                    ans = await self._confirm(f'{text}\n  Enter = move + image, m = move only, '
                                              f'q = stop > ' if self.mtl else
                                              f'{text}\n  Enter = move, q = stop > ')
                    if ans == 'q':
                        self.out('Stopped going forward (q).')
                        return 'quit'
                    image = image and ans != 'm'
                stop = await self._step('forward', n, total, row, prev, image)
            except INTERRUPTS:
                _uncancel()
                self.out('Ctrl-C: stopped going forward.')
                return 'interrupt'
            self.track.append(row)
            if stop == 'interrupt':
                self.out('Ctrl-C: stopped going forward.')
                return stop
            if stop == 'aux':
                self.out('MTL / back light failed: stopped going forward.')
                return stop
        return 'done'

    async def _return(self):
        """Back through the reached rows; 'done', 'quit' or 'interrupt'."""
        total = len(self.track) - 1
        n = 0
        while len(self.track) > 1:
            n += 1
            prev, row = self.track[-1], self.track[-2]
            image = self.return_mtl
            try:
                if self.prompt:
                    text, _, _ = self._step_text('return', n, total, row, prev)
                    ans = await self._confirm(f'{text}\n  Enter = move + image, m = move only, '
                                              f'q = stop returning > ' if image else
                                              f'{text}\n  Enter = move, q = stop returning > ')
                    if ans == 'q':
                        self.out('Stopped returning (q).')
                        return 'quit'
                    image = image and ans != 'm'
                stop = await self._step('return', n, total, row, prev, image)
            except INTERRUPTS:
                _uncancel()
                self.out('Ctrl-C: stopped returning.')
                return 'interrupt'
            self.track.pop()
            if stop == 'interrupt':
                self.out('Ctrl-C: stopped returning.')
                return stop
            if stop == 'aux':
                self.out('MTL / back light failed: returning without images.')
                self.return_mtl = False
        return 'done'

    def return_command(self, rows):
        """CLI that visits rows (the first = where the positioners are) and stops there."""
        cmd = ['python', 'script/pathtest.py', '--path', self.path_file,
               '--rows', ','.join(str(r) for r in rows), '--no-return', '--outdir', self.outdir]
        if self.backlight:
            cmd.append('--backlight')
        if self.fiducials:
            cmd.append('--fiducials')
        return ' '.join(shlex.quote(c) for c in cmd)

    def _banner(self):
        lines = ['=' * 78]
        if self.dry:
            lines += ['DRY RUN: nothing is sent to the broker or the lamps; no positioner moves.']
        else:
            lines += ['LIVE RUN: FBP WILL MOVE THE POSITIONERS. Watch them; Ctrl-C stops after '
                      'the current move.']
        lines += [f'path   {self.path_file}' + (f'  ({self.tile[0]} tile {self.tile[1]})'
                                                if self.tile else ''),
                  f'rows   {len(self.rows)}: {self.rows}',
                  f"MTL    {'mtltest %g s x %d per row' % (self.mtl_exptime, self.mtl_nexp) if self.mtl else 'off'}"
                  f"; back light {'on (IsoPlane stage)' if self.backlight else 'off'}"
                  f"; fiducials {'on' if self.fiducials else 'off'}",
                  f"return {'yes' if self.do_return else 'no'}; prompts "
                  f"{'yes' if self.prompt and not self.dry else 'no'}; lit (class 1) "
                  f'{len(self.lit) if self.lit else "-"}',
                  f'outdir {self.outdir}']
        first = self.rows[0]
        if all(abs(v) < 1e-9 for v in self.commands[first].values()):
            lines += [f'Before the first move the positioners must be at row {first}: the '
                      "power-on pose (command 0 for all, FBP state 'initial')."]
        else:
            lines += [f'Before the first move the positioners must be at row {first} of the '
                      f'path ({self.files[first]}), NOT the power-on pose.']
        worst = max([skip_deviation(self.commands, a, b)
                     for a, b in zip(self.rows, self.rows[1:])], default=0.0)
        if worst > SKIP_WARN_DEG:
            lines += [f'WARNING: the path rows skipped between visited rows leave the direct '
                      f'moves by up to {worst:.2f} deg: those moves are NOT the planner-checked '
                      'path (--every 1 follows it row by row).']
        lines += ['=' * 78]
        return '\n'.join(lines)

    async def run(self):
        """Forward, return, cleanup. Returns the outcome string (also in the jsonl)."""
        self.out(self._banner())
        self.log.write(event='start', path=self.path_file, rows=self.rows, every=self.every,
                       stem=self.stem, mtl=self.mtl, mtl_exptime=self.mtl_exptime,
                       mtl_nexp=self.mtl_nexp, backlight=self.backlight,
                       fiducials=self.fiducials, prompt=self.prompt, do_return=self.do_return,
                       dry_run=self.dry, lit=sorted(self.lit))
        outcome = 'setup_failed'
        try:
            try:
                await self._setup()
            except Exception as error:
                self.out(f'Setup failed ({error}); nothing moved.')
                return outcome
            except INTERRUPTS:
                _uncancel()
                self.out('Ctrl-C during setup; nothing moved.')
                return outcome
            try:
                outcome = await self._forward()
                if self.track and self.do_return and len(self.track) > 1:
                    self.out(f'Returning to row {self.track[0]} through {self.track[-2::-1]}.')
                    back = await self._return()
                    outcome = f'{outcome}, returned' if back == 'done' else f'{outcome}, return {back}'
            except FbpFailed as error:
                outcome = 'fbp_failed'
                self.out(f'FBP FAILURE: {error}\nNothing will move again from this run. '
                         'Check the positioners (fbpstatus, an MTL image) before any move.')
                if self.track:
                    self.out(f'If they are still at row {self.track[-1]}, return with:\n  '
                             f'{self.return_command(self.track[::-1])}')
            except Abort as error:
                outcome = 'aborted'
                self.out(f'ABORTED: {error}. Nothing will move again from this run; check the '
                         'FBP state before any move.')
            return outcome
        finally:
            await self._cleanup()
            pose = self.track[-1] if self.track else None
            if outcome not in ('fbp_failed', 'aborted') and len(self.track) > 1:
                self.out(f'Positioners are at row {pose}, not at the start row {self.track[0]}. '
                         f'Return later with:\n  {self.return_command(self.track[::-1])}')
            elif pose is not None and outcome not in ('fbp_failed', 'aborted'):
                self.out(f'Positioners are at row {pose} (the start row).')
            self.log.write(event='end', outcome=outcome, pose_row=pose, dry_run=self.dry)
            self.out(f"Outcome{' (DRY RUN)' if self.dry else ''}: {outcome}. "
                     f'Records: {self.log.path}')

    async def _cleanup(self):
        """illuoff (light off, stage out) and fiducialoff, whatever happened."""
        self.cleaning = True
        if self.stage_in:
            try:
                await self._illu('illuoff')
            except (Exception, KeyboardInterrupt, asyncio.CancelledError) as error:
                _uncancel()
                self.out(f'WARNING: illuoff failed ({error!r}): switch the back light off and '
                         'take the stage out by hand (illuoff).')
        if self.fid_on:
            try:
                await self._lamp('fiducialoff')
            except (Exception, KeyboardInterrupt, asyncio.CancelledError) as error:
                _uncancel()
                self.out(f'WARNING: fiducialoff failed ({error!r}).')
        self.cleaning = False



# -------------------------------------------------------------- console
class Console:
    """Prompts read stdin in a thread, so the event loop (broker heartbeats) keeps running
    while a prompt waits; Ctrl-C cancels the wait. Lines typed ahead are dropped."""

    def __init__(self):
        self.lines = queue.Queue()
        self.thread = None

    def _read(self):
        while True:
            line = sys.stdin.readline()
            self.lines.put(line)
            if line == '':
                return

    async def ask(self, prompt):
        while True:                              # no typed-ahead Enter confirms a move
            try:
                self.lines.get_nowait()
            except queue.Empty:
                break
        if self.thread is None or not self.thread.is_alive():
            self.thread = threading.Thread(target=self._read, daemon=True)
            self.thread.start()
        print(prompt, end='', flush=True)
        while True:
            try:
                line = self.lines.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.1)
                continue
            return 'q' if line == '' else line.strip()   # EOF = stop


def spec_queue_of(ini=KSPEC_INI):
    with open(ini, encoding='utf-8') as f:
        return json.load(f)['SPEC'].get('queue', 'SPEC')


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog='pathtest', description='MTL-watched, prompted run of a tile motion path with no '
        'sky, then back to the start pose (see the module docstring).')
    p.add_argument('--path', required=True, help='planner .path.txt (geometric angles)')
    p.add_argument('--assign', help='assign file of the tile (class 1 = lit, for the summary)')
    p.add_argument('--every', type=int, default=1, help='every K-th row, always the last')
    p.add_argument('--rows', help="'A:B' inclusive (B < A runs backwards) or 'r1,r2,...'")
    p.add_argument('--mtl-exptime', type=float, default=0.5, help='mtltest exposure [s]')
    p.add_argument('--mtl-nexp', type=int, default=1, help='mtltest images per row')
    p.add_argument('--no-mtl', dest='mtl', action='store_false', help='no MTL images')
    p.add_argument('--backlight', action='store_true',
                   help='IsoPlane back illumination: illuon first, light on only while MTL '
                   'exposes, illuoff at the end')
    p.add_argument('--fiducials', action='store_true', help='fiducialon first, fiducialoff at the end')
    p.add_argument('--no-prompt', dest='prompt', action='store_false',
                   help='no prompt before each move (Ctrl-C still stops)')
    p.add_argument('--no-return', dest='do_return', action='store_false',
                   help='stay at the last row (prints the command that returns)')
    p.add_argument('--tag', help='appended to the file stem (keeps MTL images of reruns apart)')
    p.add_argument('--dry-run', action='store_true',
                   help='send nothing; print the messages, write the JSON files and the jsonl')
    p.add_argument('--outdir', help='records (default ../DATA/STARSCAN/pathtest/<UTC date>)')
    p.add_argument('--fbp-timeout', type=float, default=600.0)
    p.add_argument('--mtl-timeout', type=float, default=300.0)
    return p.parse_args(argv)


async def amain(opts):
    night = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d')
    outdir = opts.outdir or os.path.normpath(os.path.join(ROOT, '..', 'DATA', 'STARSCAN',
                                                          'pathtest', night))
    try:
        _, geo = read_path(opts.path)
        rows = select_rows(len(geo), opts.every, opts.rows)
        spec_key = spec_queue_of()
        if opts.backlight and opts.mtl and spec_key != 'ISOPLANE':
            raise ValueError(f'KSPEC.ini SPEC.queue is {spec_key!r}: --backlight drives only '
                             'the IsoPlane stage (queue ISOPLANE)')
        if opts.backlight and not opts.mtl:
            print('Note: --backlight is ignored with --no-mtl.')
        console = Console()
        link = DryLink() if opts.dry_run else BrokerLink()
        if opts.dry_run:
            async def lamp(cmd):
                raise RuntimeError('no lamp in a dry run')
        else:
            from LAMP.lampcli import handle_lamp

            async def lamp(cmd):
                return await handle_lamp(cmd, None)
        test = PathTest(opts.path, rows, link=link, ask=console.ask, lamp=lamp, outdir=outdir,
                        positioners=axis_map_positioners(), offsets=motion_offsets(),
                        assign_file=opts.assign, tag=opts.tag, mtl=opts.mtl,
                        mtl_exptime=opts.mtl_exptime, mtl_nexp=opts.mtl_nexp,
                        backlight=opts.backlight, fiducials=opts.fiducials,
                        prompt=opts.prompt and not opts.dry_run, do_return=opts.do_return,
                        dry_run=opts.dry_run, spec_key=spec_key, fbp_timeout=opts.fbp_timeout,
                        mtl_timeout=opts.mtl_timeout, every=opts.every)
    except (OSError, ValueError) as error:
        print(f'pathtest: {error}; nothing sent.')
        return 2

    if not opts.dry_run:
        try:
            await link.connect()
        except Exception as error:
            print(f'pathtest: cannot connect to RabbitMQ ({error}); nothing sent.')
            return 2
    task, loop = asyncio.current_task(), asyncio.get_running_loop()

    def on_sigint(signum, frame):
        if test.cleaning:
            print('\nCtrl-C ignored while the lamps switch off; wait for it.', flush=True)
            return
        loop.call_soon_threadsafe(task.cancel)

    previous = signal.signal(signal.SIGINT, on_sigint)
    try:
        outcome = await test.run()
    finally:
        signal.signal(signal.SIGINT, previous)
        if not opts.dry_run:
            await link.close()
    return 0 if outcome == 'done' or outcome.endswith(', returned') else 1


def main(argv=None):
    return asyncio.run(amain(parse_args(argv)))


if __name__ == '__main__':
    sys.exit(main())
