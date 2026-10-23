"""Add ICS cards to a LightField FITS file without re-serialising its header.

LightField writes long values as HIERARCH + CONTINUE cards that astropy cannot parse back
("Unparsable card (CONTINUE)"), so the header is edited as raw 80-character cards: the new
cards go in front of END, the header is padded to a 2880-byte block, and the data are copied
unchanged.
"""

import os

BLOCK = 2880
CARD = 80


def _card(key, value, comment=""):
    from astropy.io import fits

    return fits.Card(key, value, comment).image


def _header_end(raw):
    """Byte offset just past the END card of the primary header."""
    for start in range(0, len(raw), BLOCK):
        block = raw[start:start + BLOCK]
        for i in range(0, len(block), CARD):
            if block[i:i + CARD].rstrip() == b"END":
                return start + i
    raise ValueError("no END card in the primary header")


def append_cards(path, cards):
    """Insert ``cards`` [(key, value, comment), ...] before END; existing keys are kept.

    The file is rewritten through a temporary file and replaced atomically.
    """
    with open(path, "rb") as f:
        raw = f.read()
    end = _header_end(raw)
    data_start = (end // BLOCK + 1) * BLOCK
    existing = {raw[i:i + 8].rstrip() for i in range(0, end, CARD)}
    new = b""
    for key, value, comment in cards:
        if key.encode() in existing:
            raise KeyError(f"{key} is already in the LightField header")
        new += _card(key, value, comment).encode("ascii")
    head = raw[:end] + new + b"END".ljust(CARD)
    head += b" " * (-len(head) % BLOCK)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(head)
        f.write(raw[data_start:])
    os.replace(tmp, path)


def ics_cards(header, frame, func, expnum):
    """Cards from the ICS header dict (``Lib/make_spec_header.py``) and the frame time stamps.

    The ICS EXPTIME (seconds) goes to EXPREQ: LightField's own EXPTIME (milliseconds) stays.
    """
    header = dict(header or {})
    cards = [
        ("OBSTYPE", str(header.get("OBSTYPE", "None")), "ICS frame type"),
        ("ICSFUNC", func, "ICS command that took the frame"),
        ("OBSDATE", str(header.get("OBSDATE", "None")), "ICS observing night"),
        ("PROJID", str(header.get("PROJID", "None")), "ICS project"),
        ("TILEID", str(header.get("TileID", "None")), "ICS tile"),
        ("RA", str(header.get("RA", "None")), "ICS tile RA"),
        ("DEC", str(header.get("DEC", "None")), "ICS tile Dec"),
        ("EXPREQ", str(header.get("EXPTIME", "None")), "[s] exposure time requested by ICS"),
        ("EXPNUM", str(expnum), "exposure number"),
        ("FWHM", str(header.get("FWHM", "None")), "ICS seeing estimate"),
        ("UTSTART", frame.ut_start, "exposure start (UTC, SPE time stamp)"),
        ("UTEND", frame.ut_end, "exposure end (UTC, SPE time stamp)"),
        ("SPECBACK", "ISOPLANE", "spectrograph backend"),
        ("LFEXPER", str(frame.setup.get("experiment", "None")), "LightField experiment"),
    ]
    return cards
