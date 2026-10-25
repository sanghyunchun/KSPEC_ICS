"""Back-illumination unit of the IsoPlane: a flat light on a linear stage that is lowered into
the grating-turret compartment, driven by an Uno (USB serial) -> MAX485 -> SBC-11R4 stepper
driver (Modbus RTU, slave 1).

The stage shares the turret compartment with the gratings, so it must be OUT (at the Near limit
switch) whenever the grating may move. The caller (``command.Isoplane``) enforces that with
``at_near()``, which reads the switch from the hardware every time.

Operating rules (ported from kspec-backlight ``elec/host/bl_cycle.py``):
- Moves are bounded relative 0x002B moves. A move is never resent: on a failed reply the stage
  is stopped and its position is unknown until it is homed again.
- The IN soft limit is counted in steps from the Near switch.
- The return to Near ends with a slow approach that checks for lost steps, then a 0.3 mm seat past
  the trip point with the limits off (stopped on the trip point, the switch chatters).
- The motor is released at rest (the lead screw is not back-drivable).
- The Uno switches the light off (and sends a stop frame) if no command arrives for 60 s, so the
  host pings it from a keep-alive thread.
- ``emergency_stop`` (from any thread) stops the stage first, then switches the light off, and
  blocks every further motion or light-on until ``clear_stop``.
"""

import threading
import time

SLAVE = 1
STEPS_PER_MM = 1600
STAGE_TRAVEL_MM = 148.0  # hard cap from the stage itself (Near -> Far switch is 151 mm)
MAX_SPEED = 16000  # step/s; 19200 is the highest verified, 24000 loses steps
HOME_SPEED = 3200  # step/s (2 mm/s)
SLOW_SPEED = 1600  # step/s (1 mm/s), final approach to Near
HOME_TRAVEL_MM = 155.0  # full stroke + margin for a bounded home
APPROACH_MM = 2.0  # the fast return stops this far short of Near
APPROACH_TOL_MM = 0.3  # Near must trip within APPROACH_MM +- this, else steps were lost
SEAT_MM = 0.3  # the IR1 stop leaves the lever on its trip point, where it chatters: seat it this
# much further up (Near trips ~2 mm below the top hard stop)
WATCHDOG_S = 60
PING_EVERY_S = 15


# ------------------------------------------------------------ SBC-11R4 frames (CRC added by the Uno)
def wr16(reg, val):
    return bytes([SLAVE, 0x06, reg >> 8, reg & 0xFF, val >> 8, val & 0xFF])


def wr32(reg, val):
    return bytes([SLAVE, 0x10, reg >> 8, reg & 0xFF, 0x00, 0x02, 0x04]) + val.to_bytes(4, "big")


def rd(reg, n=1):
    return bytes([SLAVE, 0x03, reg >> 8, reg & 0xFF, n >> 8, n & 0xFF])


def move_word(mm, far, limit=True):
    """0x002B relative move; only the limit in the direction of travel is enabled (none if not
    ``limit``)."""
    steps = round(mm * STEPS_PER_MM)
    if not 0 < steps <= 0xFFFFFF:
        raise ValueError(f"move of {mm} mm is out of range")
    if not limit:
        return (1 << 31 if far else 0) | steps
    if far:  # b31 dir Far, b27 IR2 stop-on-Low, b25 IR2 enable
        return (1 << 31) | (1 << 27) | (1 << 25) | steps
    return (1 << 26) | (1 << 24) | steps  # Near: b26 IR1 stop-on-Low, b24 IR1 enable


STOP_HOLD = wr16(0x2D, 0)
RELEASE = wr16(0x2D, 1)


class BackIllumError(RuntimeError):
    pass


# ------------------------------------------------------------ links to the Uno
class UnoLink:
    """One text command per line, one reply line per command (firmware kspec_bl_nano)."""

    def __init__(self, port):
        import serial  # pyserial, only needed with real hardware

        self.lock = threading.Lock()
        self.warnings = []
        self.s = serial.Serial(port, 9600, timeout=1.0)
        time.sleep(2.2)  # opening the port resets the Uno (DTR)
        self.s.reset_input_buffer()

    def cmd(self, line):
        with self.lock:
            self.s.write((line + "\n").encode())
            reply = self.s.readline().decode(errors="replace").strip()
            while reply.startswith("WARN"):  # unsolicited, e.g. "WARN WDT lights off"
                self.warnings.append(reply)
                reply = self.s.readline().decode(errors="replace").strip()
            return reply

    def close(self):
        self.s.close()


class FakeUno:
    """Firmware and stage simulator for development without hardware.

    The stage position (mm below Near) moves in real time scaled by ``time_scale``.
    """

    def __init__(self, time_scale=1.0, start_mm=0.0):
        self.lock = threading.Lock()
        self.warnings = []
        self.scale = time_scale
        self.light = False
        self.speed = HOME_SPEED
        self.pos0, self.target, self.t0, self.dur = start_mm, start_mm, time.time(), 0.0
        self.log = []

    def position(self):
        if self.dur <= 0:
            return self.target
        f = min(1.0, (time.time() - self.t0) / self.dur)
        return self.pos0 + f * (self.target - self.pos0)

    def cmd(self, line):
        with self.lock:
            self.log.append(line)
            line = line.upper()
            if line == "PING":
                return "OK PONG"
            if line.startswith("L "):
                if line in ("L MAIN ON",):
                    self.light = True
                elif line in ("L MAIN OFF", "L OFF"):
                    self.light = False
                return f"OK MAIN={int(self.light)} BACKUP=0 INTERLOCK=1"
            if line.startswith("WDT "):
                return f"OK WDT={line.split()[1]}"
            if line.startswith("WDTFRAME "):
                return "OK WDTFRAME"
            if line.startswith("MB "):
                return self._modbus(bytes.fromhex(line[3:]))
            return "ERR UNKNOWN"

    def _modbus(self, pdu):
        reg = (pdu[2] << 8) | pdu[3]
        if pdu[1] == 0x03 and reg == 0x2E:
            p = self.position()
            near_bit = 0 if p <= 0.0 else 1  # pressed = 0
            far_bit = 0 if p >= 151.0 else 1
            return f"OK 01030200{near_bit | (far_bit << 1):02X}0000"
        if pdu[1] == 0x10 and reg == 0x28:
            self.speed = int.from_bytes(pdu[7:11], "big")
        elif pdu[1] == 0x10 and reg == 0x2B:
            w = int.from_bytes(pdu[7:11], "big")
            mm = (w & 0xFFFFFF) / STEPS_PER_MM
            p = self.position()
            target = min(151.0, p + mm) if w >> 31 else max(0.0, p - mm)
            self.pos0, self.target, self.t0 = p, target, time.time()
            self.dur = abs(target - p) * STEPS_PER_MM / self.speed * self.scale
        elif pdu[1] == 0x06 and reg == 0x2D:
            p = self.position()
            self.pos0 = self.target = p
            self.dur = 0.0
        return "OK " + pdu.hex().upper() + "0000"

    def close(self):
        pass


# ------------------------------------------------------------ the unit
class BackIllumination:
    """High-level, blocking operations; call them from one thread at a time.

    ``state`` is OUT (at Near, verified), IN (lowered by ``in_depth_mm``), MOVING, or UNKNOWN
    (after an error or a restart away from Near: only ``retract`` is allowed then).
    """

    def __init__(self, link, in_depth_mm, in_limit_mm, speed_mm_s=10.0, time_scale=1.0):
        if not APPROACH_MM + 1 < in_depth_mm <= in_limit_mm <= STAGE_TRAVEL_MM:
            raise ValueError(
                f"need {APPROACH_MM + 1} < in_depth_mm ({in_depth_mm}) <= in_limit_mm "
                f"({in_limit_mm}) <= {STAGE_TRAVEL_MM}"
            )
        speed = round(speed_mm_s * STEPS_PER_MM)
        if not SLOW_SPEED <= speed <= MAX_SPEED:
            raise ValueError(f"speed_mm_s must be 1 to {MAX_SPEED / STEPS_PER_MM:.0f}")
        self.link = link
        self.depth = in_depth_mm
        self.speed = speed
        self.scale = time_scale
        self.state = "UNKNOWN"
        self.light = False
        self.last_error = None
        self._stop_ping = threading.Event()
        self._ping_thread = None
        self._abort = threading.Event()

    # -------------------------------------------------- low level
    def _cmd(self, line):
        if self._abort.is_set():
            raise BackIllumError("stopped by specstop")
        r = self.link.cmd(line)
        if not r.startswith("OK"):
            raise BackIllumError(f"Uno replied {r!r} to {line!r}")
        return r

    def _mb(self, pdu):
        """Send a Modbus frame once. Never resent: moves are relative."""
        return self._cmd("MB " + pdu.hex().upper())

    def _sleep(self, sec):
        if self._abort.wait(sec * self.scale):
            raise BackIllumError("stopped by specstop")

    def limits(self):
        """(near, far) pressed, read from the SBC input register 0x002E (pressed = 0)."""
        r = self._mb(rd(0x2E))
        v = int(r.split()[1][6:10], 16)
        return not v & 1, not v & 2

    def at_near(self):
        """True only if the Near switch reads pressed now (hardware read, no cache)."""
        return self.limits()[0]

    def _wait_near(self, tmax):
        t = time.time()
        while time.time() - t < tmax * self.scale:
            if self.at_near():
                return (time.time() - t) / self.scale
            self._sleep(0.05)
        return None

    def _move(self, mm, far, speed):
        self._mb(wr32(0x28, speed))  # the speed resets at SBC power-up: always rewrite
        self._mb(wr32(0x2B, move_word(mm, far)))
        self._sleep(mm * STEPS_PER_MM / speed + 1.5)

    def _seat(self):
        """Move SEAT_MM past the Near trip point with the limits off (the switch is already pressed)."""
        self._mb(wr32(0x28, SLOW_SPEED))
        self._mb(wr32(0x2B, move_word(SEAT_MM, far=False, limit=False)))
        self._sleep(SEAT_MM * STEPS_PER_MM / SLOW_SPEED + 0.2)

    # -------------------------------------------------- operations
    def connect(self):
        self._cmd("PING")
        self._cmd(f"WDT {WATCHDOG_S}")
        self._cmd("WDTFRAME " + STOP_HOLD.hex().upper())  # not stored: set at every connect
        self._cmd("L OFF")
        self.light = False
        self.state = "OUT" if self.at_near() else "UNKNOWN"
        self._ping_thread = threading.Thread(target=self._keepalive, daemon=True)
        self._ping_thread.start()
        return self.state

    def _keepalive(self):
        while not self._stop_ping.wait(PING_EVERY_S):
            try:
                self.link.cmd("PING")
            except Exception as e:  # the next operation reports the link problem
                self.last_error = f"keep-alive: {e!r}"

    def home(self):
        """Bounded move up to Near at 2 mm/s, then the seat; safe from any position."""
        if any(self.at_near() for _ in range(3)):  # a seated lever reads pressed every time
            return
        self._mb(wr32(0x28, HOME_SPEED))
        self._mb(wr32(0x2B, move_word(HOME_TRAVEL_MM, far=False)))
        if self._wait_near(HOME_TRAVEL_MM / (HOME_SPEED / STEPS_PER_MM) + 5) is None:
            raise BackIllumError("Near not reached while homing")
        self._seat()

    def insert(self):
        """OUT -> IN. The caller must hold the grating still and the camera idle."""
        if self.state not in ("OUT",):
            raise BackIllumError(f"insert needs state OUT, not {self.state}")
        self.state = "MOVING"
        try:
            self._cmd("L OFF")
            self.light = False
            self.home()
            self._move(self.depth, far=True, speed=self.speed)
            near, far = self.limits()
            if far:
                raise BackIllumError("Far switch pressed after the move down")
            if near:
                raise BackIllumError("still at Near after the move down: the stage did not move")
            self.state = "IN"
        except Exception:
            self.abort()
            raise

    def set_light(self, on):
        if on and self.state != "IN":
            raise BackIllumError(f"light on needs state IN, not {self.state}")
        self._cmd("L MAIN ON" if on else "L MAIN OFF")
        self.light = on

    def retract(self):
        """Any state -> OUT, verified at Near. From IN, checks for lost steps on the way."""
        self.state, was = "MOVING", self.state
        try:
            self._cmd("L OFF")
            self.light = False
            if was == "IN":
                self._move(self.depth - APPROACH_MM, far=False, speed=self.speed)
                if self.at_near():
                    raise BackIllumError("Near pressed before the slow approach: steps lost")
                self._mb(wr32(0x28, SLOW_SPEED))
                self._mb(wr32(0x2B, move_word(8, far=False)))
                th = self._wait_near(10)
                if th is None:
                    raise BackIllumError("Near not reached on the slow approach: steps lost")
                dist = th * SLOW_SPEED / STEPS_PER_MM
                if abs(dist - APPROACH_MM - 0.1) > APPROACH_TOL_MM:
                    self.last_error = f"Near after {dist:.2f} mm (expect ~2.1): steps lost"
                self._seat()
            else:
                self.home()
            self._mb(wr32(0x28, MAX_SPEED))
            self._mb(RELEASE)
            if not self.at_near():
                raise BackIllumError("not at Near after the retract")
            self.state = "OUT"
        except Exception:
            self.abort()
            raise

    def abort(self):
        """Stage stopped and held, then light off; position unknown until the next retract."""
        for line in ("MB " + STOP_HOLD.hex().upper(), "L OFF"):
            try:
                self.link.cmd(line)
            except Exception:
                pass
        self.light = False
        self.state = "UNKNOWN"

    def emergency_stop(self):
        """Stop the stage, then the light, from any thread; later moves raise until clear_stop.

        Returns the Uno replies; raises if either line was not acknowledged.
        """
        self._abort.set()
        replies = [self.link.cmd("MB " + STOP_HOLD.hex().upper()), self.link.cmd("L OFF")]
        self.light = False
        self.state = "UNKNOWN"
        if not all(r.startswith("OK") for r in replies):
            raise BackIllumError(f"Uno replies to the stop: {replies}")
        return replies

    def clear_stop(self):
        self._abort.clear()

    def status(self):
        return {"state": self.state, "light": self.light, "last_error": self.last_error,
                "warnings": list(self.link.warnings[-5:])}

    def close(self):
        """Light off and close the port. Without the keep-alive the Uno watchdog fires 60 s later
        and sends its WDTFRAME: at rest (OUT, motor released) that becomes the release frame, so
        the expiry does not re-energise the motor; in any other state it stays stop-and-hold."""
        self._stop_ping.set()
        try:
            self.link.cmd("L OFF")
            if self.state == "OUT":
                self.link.cmd("WDTFRAME " + RELEASE.hex().upper())
        finally:
            self.link.close()


def make_backillum(cfg):
    """Build the unit from the ``backillum`` block of isoplane_local.json (None: no unit)."""
    if not cfg:
        return None
    fake = cfg["port"] == "fake"
    scale = float(cfg.get("time_scale", 1.0)) if fake else 1.0  # real hardware runs in real time
    if fake:
        link = FakeUno(time_scale=scale, start_mm=float(cfg.get("fake_start_mm", 0.0)))
    else:
        link = UnoLink(cfg["port"])
    return BackIllumination(link, float(cfg["in_depth_mm"]), float(cfg["in_limit_mm"]),
                            float(cfg.get("speed_mm_s", 10.0)), time_scale=scale)
