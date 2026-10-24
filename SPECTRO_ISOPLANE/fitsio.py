"""Add ICS cards to a LightField FITS file without re-serialising its header.

LightField writes long values as HIERARCH + CONTINUE cards that astropy cannot parse back
("Unparsable card (CONTINUE)"), so the header is edited as raw 80-character cards: the new
cards go in front of END, the header is padded to a 2880-byte block, and the data are copied
unchanged.
"""

import os
import re

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


# LightField's own non-HIERARCH cards (January 2026 frames) and FITS structure keywords: an ICS
# card with one of these names would make append_cards fail after the exposure.
RESERVED = {"SIMPLE", "BITPIX", "NAXIS", "NAXIS1", "NAXIS2", "NAXIS3", "EXTEND", "BSCALE",
            "BZERO", "DATE", "DATE-OBS", "EXPTIME", "LONGSTRN", "END", "COMMENT", "HISTORY",
            "CONTINUE", "HIERARCH"}
KEY_RE = re.compile(r"^[A-Z0-9_-]{1,8}$")

FUNC_OBSTYPE = {"getbias": "Bias", "getdark": "Dark", "getflat": "Flat", "getarc": "Arc",
                "getobj": "Object"}

# (card, header-dict key, type, comment). Unknown values (None, "None", "") leave the card out.
ICS_KEYS = [
    ("OBSDATE", "OBSDATE", str, "ICS observing night"),
    ("PROJID", "PROJID", str, "ICS project"),
    ("TILEID", "TileID", str, "ICS tile"),
    ("OBJECT", "OBJECT", str, "ICS object name"),
    ("TILERA", "RA", str, "tile centre RA (planned, not the TCS position)"),
    ("TILEDEC", "DEC", str, "tile centre Dec (planned, not the TCS position)"),
    ("EXPREQ", "EXPTIME", float, "[s] exposure time requested by ICS"),
    ("FWHM", "FWHM", float, "[arcsec] GFA seeing estimate"),
    ("OBSERVAT", "OBSERVAT", str, "observatory (KSPEC.ini SITE)"),
    ("SITELAT", "SITELAT", float, "[deg] site latitude, north positive"),
    ("SITELONG", "SITELONG", float, "[deg] site longitude, east positive"),
    ("SITEELEV", "SITEELEV", float, "[m] site elevation"),
]


def _known(value):
    return value is not None and str(value).strip() not in ("", "None")


def _typed(value, kind):
    if kind is str:
        return str(value)
    try:
        return kind(float(value)) if kind is int else float(value)
    except (TypeError, ValueError):
        return str(value)  # keep what the ICS sent rather than losing it


def extra_cards(header):
    """The header's CARDS [(key, value, comment), ...], checked; ValueError when one is invalid.

    For cards from other subsystems (TCS, lamps, tile configuration): they are written as given,
    after the cards above. Keys must be valid FITS keywords not used by LightField, the cards
    above, or another extra card.
    """
    taken = RESERVED | {k for k, *_ in ICS_KEYS} | {
        "OBSTYPE", "ICSFUNC", "EXPNUM", "NEXP", "UTSTART", "UTEND", "SPECBACK", "LFEXPER",
        "DATASEC", "BIASSEC", "BILLUM"}
    out = []
    for card in (header or {}).get("CARDS") or []:
        if len(card) not in (2, 3):
            raise ValueError(f"extra card {card!r} is not (key, value[, comment])")
        key, value = str(card[0]).upper(), card[1]
        comment = str(card[2]) if len(card) == 3 else ""
        if not KEY_RE.match(key):
            raise ValueError(f"extra card key {key!r} is not a FITS keyword")
        if key in taken:
            raise ValueError(f"extra card key {key} is already used")
        if value is not None and not isinstance(value, (str, int, float, bool)):
            raise ValueError(f"extra card {key} value {value!r} is not a FITS value")
        taken.add(key)
        if _known(value):
            out.append((key, value, comment))
    return out


def ics_cards(header, frame, func, index=0, nframe=1, sensor_bias_rows=0):
    """Cards from the ICS header dict (``Lib/make_spec_header.py``) and the frame time stamps.

    ``index`` is the frame's position (0-based) among the ``nframe`` frames of this command.
    EXPNUM counts from the header EXPNUM (the sequence number of the first frame; default 1),
    NEXP is the header NEXP (frames in the sequence; default ``nframe``). OBSTYPE falls back to
    the command's frame type. The ICS EXPTIME (seconds) goes to EXPREQ: LightField's own EXPTIME
    (milliseconds) stays.
    """
    header = dict(header or {})
    first = _typed(header["EXPNUM"], int) if _known(header.get("EXPNUM")) else 1
    nexp = _typed(header["NEXP"], int) if _known(header.get("NEXP")) else nframe
    obstype = header.get("OBSTYPE")
    cards = [
        ("OBSTYPE", str(obstype) if _known(obstype) else FUNC_OBSTYPE.get(func, "None"),
         "ICS frame type"),
        ("ICSFUNC", func, "ICS command that took the frame"),
    ]
    cards += [(card, _typed(header[key], kind), comment)
              for card, key, kind, comment in ICS_KEYS if _known(header.get(key))]
    cards += [
        ("EXPNUM", first + index if isinstance(first, int) else first,
         "exposure number in the sequence"),
        ("NEXP", nexp, "exposures in the sequence"),
    ]
    if _known(frame.ut_start):
        cards.append(("UTSTART", frame.ut_start, "exposure start (UTC, SPE time stamp)"))
    if _known(frame.ut_end):
        cards.append(("UTEND", frame.ut_end, "exposure end (UTC, SPE time stamp)"))
    cards += [
        ("SPECBACK", "ISOPLANE", "spectrograph backend"),
        ("LFEXPER", str(frame.setup.get("experiment", "None")), "LightField experiment"),
    ]
    return cards + overscan_cards(frame.setup, sensor_bias_rows) + extra_cards(header)


def _int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def overscan_cards(setup, sensor_bias_rows=0):
    """DATASEC/BIASSEC (raw orientation, 1-based) for a full-sensor readout.

    LightField reads rows beyond the sensor height last, so they follow the sensor rows.
    ``sensor_bias_rows`` more rows at the end of the sensor also read at the bias level: one
    on the 2026 PIXIS (row 1300 sits at the overscan level in every frame), so a 1330-row
    readout has 31 bias rows.
    """
    cols, rows, phys = (_int(setup.get(k)) for k in ("sensor_cols", "sensor_rows", "physical_rows"))
    if not (cols and rows and phys) or setup.get("roi_selection") != "FullSensor":
        return []
    first_bias = min(phys, rows) - sensor_bias_rows + 1
    if first_bias > rows:
        return []
    return [
        ("DATASEC", f"[1:{cols},1:{first_bias - 1}]", "light-sensitive rows (raw orientation)"),
        ("BIASSEC", f"[1:{cols},{first_bias}:{rows}]", "rows at the bias level (overscan)"),
    ]
