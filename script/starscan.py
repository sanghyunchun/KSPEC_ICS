"""Helpers for the zero-order star scan (runscan) and the MTL-watched path test (pathtest).

Nothing here talks to hardware, except BrokerLink, which only sends what its caller asks for.

Angle conventions (MTL fiber_config ANGLE_SIGN (-1, -1), ANGLE_ZERO (-30, -150); PR #20):
    geometric : fibre = hole + a1 e^{i alpha} + a2 e^{i (alpha + beta)}, degrees, as in the
                planner's .path.txt files; the power-on pose is geometric (30, 150)
    command   : what FBP takes (fbpoffset JSON, loadmotion) and what the MTL trial JSON holds,
                command = -geometric + (alpha_offset_deg, beta_offset_deg) of KSPEC.ini SCIOBS
                (30, 150), so the power-on pose is command (0, 0)

Focal-plane offsets (dx, dy) are in the MTL / planner frame [um]. The planner maps the sky with
East along +x and North along -y (f = 5159.8 mm/rad, 25.0 um/arcsec at the centre).
"""
import datetime as dt
import json
import math
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AXIS_MAP = os.path.join(ROOT, 'Lib', 'positioner_axis_map.json')
KSPEC_INI = os.path.join(ROOT, 'Lib', 'KSPEC.ini')

DESIGN_ARMS = (5.2, 11.6)          # mm, MTL fiber_config.DEFAULT_ARM
UM_PER_ARCSEC = 25.0               # planner scale at the tile centre (fibre core 70 um = 2.80")
FIBRE_CORE_UM = 70.0

# planner names: <project>_2627_<tile>.assign.txt; the example ASPECS_2627.0005 uses a dot
TILE_NAME = re.compile(r'^(?P<project>.+?)_2627[._](?P<tile>\d+)(?P<rest>\..+)$')


# -------------------------------------------------------------- files
def parse_tile_name(filename):
    """(project, tile_id) from '<project>_2627_<tile>...' or '<project>_2627.<tile>...'."""
    m = TILE_NAME.match(os.path.basename(filename))
    if m is None:
        raise ValueError(f'{filename}: not a <project>_2627_<tile> file name')
    return m['project'], int(m['tile'])


def axis_map_positioners(path=AXIS_MAP):
    """The positioners fbpoffset requires (every one of Lib/positioner_axis_map.json)."""
    with open(path, encoding='utf-8') as f:
        return list(json.load(f))


def motion_offsets(path=KSPEC_INI):
    """(alpha_offset_deg, beta_offset_deg) of KSPEC.ini SCIOBS, as loadmotion uses them."""
    with open(path, encoding='utf-8') as f:
        sciobs = json.load(f)['SCIOBS']
    return float(sciobs['alpha_offset_deg']), float(sciobs['beta_offset_deg'])


def read_path(path_file):
    """Planner path file -> (holes, rows); rows[i][hole] = (alpha, beta) geometric [deg].

    Header '<hole>_a,<hole>_b,...', one comma-separated row of absolute angles per step.
    """
    with open(path_file, encoding='utf-8') as f:
        columns = [c.strip() for c in f.readline().strip().split(',') if c.strip()]
        body = [line for line in f if line.strip()]
    holes = []
    for c in columns:
        hole, _, arm = c.rpartition('_')
        if not hole or arm not in ('a', 'b'):
            raise ValueError(f'{path_file}: invalid column {c}')
        if arm == 'a':
            holes.append(hole)
    if columns != [f'{h}_{arm}' for h in holes for arm in ('a', 'b')]:
        raise ValueError(f'{path_file}: columns must be <hole>_a,<hole>_b pairs')
    rows = []
    for n, line in enumerate(body, start=2):
        values = [float(v) for v in line.strip().rstrip(',').split(',')]
        if len(values) != len(columns) or not all(math.isfinite(v) for v in values):
            raise ValueError(f'{path_file}:{n}: expected {len(columns)} finite values')
        rows.append({h: (values[2 * i], values[2 * i + 1]) for i, h in enumerate(holes)})
    if not rows:
        raise ValueError(f'{path_file}: no steps')
    return holes, rows


def read_assign(assign_file):
    """Assign file -> {hole: {'xp', 'yp', 'mag', 'class', 'flag', 'ra', 'dec'}} (file order)."""
    out = {}
    with open(assign_file, encoding='utf-8') as f:
        for n, line in enumerate(f, start=1):
            p = line.partition('#')[0].split()
            if not p:
                continue
            if len(p) != 8:
                raise ValueError(f'{assign_file}:{n}: expected 8 columns')
            out[p[0]] = dict(xp=float(p[1]), yp=float(p[2]), mag=float(p[3]), cls=int(p[4]),
                             flag=p[5], ra=float(p[6]), dec=float(p[7]))
    return out


def read_angles(json_file):
    with open(json_file, encoding='utf-8') as f:
        return {k: float(v) for k, v in json.load(f).items()}


def write_angles(json_file, angles):
    """Write a command-angle JSON as fbpoffset reads it ({'<hole>_a': deg, '<hole>_b': deg})."""
    os.makedirs(os.path.dirname(os.path.abspath(json_file)), exist_ok=True)
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(angles, f, indent=2, allow_nan=False)
        f.write('\n')
    return json_file


def check_complete(angles, positioners):
    """Raise unless angles hold a finite alpha and beta for exactly these positioners."""
    want = {f'{p}_{arm}' for p in positioners for arm in ('a', 'b')}
    missing, extra = sorted(want - set(angles)), sorted(set(angles) - want)
    if missing or extra:
        raise ValueError(f'fbpoffset needs every positioner of the axis map: '
                         f'missing={missing}, extra={extra}')
    bad = [k for k, v in angles.items() if not math.isfinite(v)]
    if bad:
        raise ValueError(f'non-finite angles: {bad}')


# -------------------------------------------------------------- angles
def to_command(geometric, offsets=(30.0, 150.0)):
    """{hole: (alpha, beta) geometric} -> {'<hole>_a': cmd, '<hole>_b': cmd}."""
    out = {}
    for hole, (a, b) in geometric.items():
        out[f'{hole}_a'] = offsets[0] - a
        out[f'{hole}_b'] = offsets[1] - b
    return out


def to_geometric(command, offsets=(30.0, 150.0)):
    """{'<hole>_a': cmd, ...} -> {hole: (alpha, beta) geometric}."""
    holes = [k[:-2] for k in command if k.endswith('_a')]
    return {h: (offsets[0] - command[f'{h}_a'], offsets[1] - command[f'{h}_b']) for h in holes}


def forward(alpha, beta, arms):
    """Fibre position relative to the hole [mm] for geometric angles [deg]."""
    a1, a2 = arms
    t1, t2 = math.radians(alpha), math.radians(alpha + beta)
    return a1 * math.cos(t1) + a2 * math.cos(t2), a1 * math.sin(t1) + a2 * math.sin(t2)


def _near(angle, reference):
    """angle + k 360 closest to reference."""
    return angle + 360.0 * round((reference - angle) / 360.0)


def inverse(x, y, arms, near):
    """Geometric (alpha, beta) [deg] putting the fibre at (x, y) relative to the hole [mm].

    The elbow stays on the side of `near` (sign of sin beta) and both angles are unwrapped to
    the turn closest to `near`, so a small offset gives a small move.
    """
    a1, a2 = arms
    r2 = x * x + y * y
    c = (r2 - a1 * a1 - a2 * a2) / (2 * a1 * a2)
    if not -1.0 <= c <= 1.0:
        raise ValueError(f'({x:.4f}, {y:.4f}) mm is outside the reach of arms {a1}, {a2} mm')
    side = 1.0 if math.sin(math.radians(near[1])) >= 0 else -1.0
    beta = side * math.degrees(math.acos(c))
    sb, cb = math.sin(math.radians(beta)), c
    alpha = math.degrees(math.atan2(y, x) - math.atan2(a2 * sb, a1 + a2 * cb))
    return _near(alpha, near[0]), _near(beta, near[1])


def quantise(angle, quantum):
    return angle if not quantum else quantum * round(angle / quantum)


def offset_command(centre, holes, dx_um, dy_um, arms, *, offsets=(30.0, 150.0), quantum=0.0,
                   min_sin_beta=0.3, max_delta_deg=3.0):
    """Command angles moving `holes` by (dx, dy) um from the centre pose; others stay.

    centre : complete command-angle dict (all positioners), e.g. the converged MTL trial JSON
    arms   : {hole: (a1, a2)} or one (a1, a2) for all
    Returns (angles, achieved) with achieved[hole] = (dx, dy) um the model gives for the
    (quantised) angles. Raises when a positioner is near the singular stretched / folded pose
    (|sin beta| < min_sin_beta) or when an axis would turn more than max_delta_deg.
    """
    angles = dict(centre)
    achieved = {}
    geo = to_geometric(centre, offsets)
    for hole in holes:
        arm = arms.get(hole, DESIGN_ARMS) if isinstance(arms, dict) else arms
        a0, b0 = geo[hole]
        if abs(math.sin(math.radians(b0))) < min_sin_beta:
            raise ValueError(f'{hole}: beta {b0:.2f} deg is near the stretched/folded pose '
                             f'(|sin beta| < {min_sin_beta}); offsets there are unreliable')
        x0, y0 = forward(a0, b0, arm)
        a, b = inverse(x0 + dx_um / 1e3, y0 + dy_um / 1e3, arm, near=(a0, b0))
        cmd_a = quantise(offsets[0] - a, quantum)
        cmd_b = quantise(offsets[1] - b, quantum)
        for key, new in ((f'{hole}_a', cmd_a), (f'{hole}_b', cmd_b)):
            if abs(new - centre[key]) > max_delta_deg:
                raise ValueError(f'{key}: {new - centre[key]:+.3f} deg exceeds max_delta_deg '
                                 f'{max_delta_deg}')
        angles[f'{hole}_a'], angles[f'{hole}_b'] = cmd_a, cmd_b
        x, y = forward(offsets[0] - cmd_a, offsets[1] - cmd_b, arm)
        achieved[hole] = ((x - x0) * 1e3, (y - y0) * 1e3)
    return angles, achieved


def mtl_arms(holes):
    """{hole: (a1, a2)} from kspec_metrology (measured arms where known), or None if it does
    not import (then the caller uses DESIGN_ARMS)."""
    try:
        from kspec_metrology.analysis import fiber_config as cfg
    except Exception:          # not installed here (e.g. the LightField laptop)
        return None
    a1, a2 = cfg.arm_lengths()
    table = dict(zip(cfg.fiber_ids(), zip(a1.tolist(), a2.tolist())))
    return {h: table.get(h, DESIGN_ARMS) for h in holes}


# -------------------------------------------------------------- scan pattern
def scan_pattern(kind='grid', step_um=35.0, npts=5, centre_repeats=True):
    """Offsets [(dx, dy) um] of a scan, with 'centre' flags.

    grid  : npts x npts, centred (npts odd), rows of increasing y, each row from -x to +x
            (one approach direction per row; the move back to the row start is one fbpoffset)
    cross : the centre, then npts points along x, then along y (npts odd)
    line-x / line-y : npts points along one axis
    centre_repeats adds the centre at the start, the middle and the end (guiding and
    transparency drift), unless the pattern already has it there.
    Returns a list of dicts {'dx', 'dy', 'centre'}.
    """
    if npts < 1 or npts % 2 == 0:
        raise ValueError('npts must be odd and positive (the pattern is centred)')
    k = (npts - 1) // 2
    ticks = [step_um * i for i in range(-k, k + 1)]
    if kind == 'grid':
        pts = [(x, y) for y in ticks for x in ticks]
    elif kind == 'cross':
        pts = [(x, 0.0) for x in ticks] + [(0.0, y) for y in ticks if y != 0]
    elif kind == 'line-x':
        pts = [(x, 0.0) for x in ticks]
    elif kind == 'line-y':
        pts = [(0.0, y) for y in ticks]
    else:
        raise ValueError(f'unknown pattern {kind}: grid, cross, line-x, line-y')
    steps = [dict(dx=x, dy=y, centre=False) for x, y in pts]
    if centre_repeats:
        c = dict(dx=0.0, dy=0.0, centre=True)
        steps = [dict(c)] + steps[:len(steps) // 2] + [dict(c)] + steps[len(steps) // 2:] + [dict(c)]
    out = []
    for s in steps:
        s['centre'] = s['centre'] or (s['dx'] == 0 and s['dy'] == 0)
        if not (s['centre'] and out and out[-1]['centre']):     # no centre twice in a row
            out.append(s)
    return out


def sky_offset(dx_um, dy_um, um_per_arcsec=UM_PER_ARCSEC):
    """(dE, dN) arcsec of a focal-plane offset, planner convention (East +x, North -y)."""
    return dx_um / um_per_arcsec + 0.0, -dy_um / um_per_arcsec + 0.0     # no -0.0


# -------------------------------------------------------------- records
def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')


class JsonLog:
    """One JSON object per line; every record gets 'time_utc'."""

    def __init__(self, path):
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    def write(self, **record):
        record = {'time_utc': utc_now(), **record}
        with open(self.path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + '\n')
        return record


# -------------------------------------------------------------- broker
class BrokerLink:
    """Send ICS messages on ics.ex and read replies from a private queue bound to 'ICS'.

    As SPECTRO_ISOPLANE/sendcmd.py: the ICS's own queue still gets every reply (a running
    KSPECRUN skips Done replies it did not ask for). Used by pathtest only; runscan runs inside
    the ICS and uses its client.
    """

    def __init__(self, ini=KSPEC_INI):
        with open(ini, encoding='utf-8') as f:
            self.cfg = json.load(f)['RabbitMQ']
        self.conn = self.exchange = self.queue = None

    async def connect(self):
        import aio_pika
        self._aio_pika = aio_pika
        self.conn = await aio_pika.connect_robust(host=self.cfg['ip_addr'],
                                                  login=self.cfg['idname'],
                                                  password=self.cfg['pwd'])
        ch = await self.conn.channel()
        self.exchange = await ch.declare_exchange('ics.ex', aio_pika.ExchangeType.DIRECT)
        self.queue = await ch.declare_queue('', exclusive=True, auto_delete=True)
        await self.queue.bind(self.exchange, routing_key='ICS')

    async def close(self):
        if self.conn is not None:
            await self.conn.close()

    async def send(self, routing_key, body):
        await self.exchange.publish(self._aio_pika.Message(body=body.encode()),
                                    routing_key=routing_key)

    async def wait_done(self, inst, func, timeout, on_reply=None, match=None):
        """The Done reply of inst/func (and match(reply), if given); {'status': 'error', ...}
        after timeout. match lets a caller skip the late Done of an abandoned earlier request
        of the same func (e.g. mtltest by its image names)."""
        import asyncio
        try:
            async with asyncio.timeout(timeout):
                async with self.queue.iterator() as it:
                    async for m in it:
                        async with m.process():
                            d = json.loads(m.body)
                        if d.get('inst') != inst or d.get('func') != func:
                            continue
                        if on_reply is not None:
                            on_reply(d)
                        if d.get('process') == 'Done' and (match is None or match(d)):
                            return d
        except TimeoutError:
            return {'inst': inst, 'func': func, 'process': 'Done', 'status': 'error',
                    'message': f'No reply from {inst} to {func} within {timeout:g} s.'}
