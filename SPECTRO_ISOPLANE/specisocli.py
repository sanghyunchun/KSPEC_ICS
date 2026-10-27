"""Parse GUI commands for the IsoPlane SPEC server."""

import math

from SPECTRO.speccli import create_spec_command
from Lib.make_spec_header import set_header_info


NO_ARGUMENT_COMMANDS = {
    "specstatus": "Show IsoPlane status.",
    "specstop": "Emergency stop of IsoPlane.",
    "illuon": "Move back-illumination stage IN and switch on the light.",
    "illuoff": "Switch off the light and move back-illumination stage OUT.",
    "illulighton": "Switch on back-illumination light without moving the stage.",
    "illulightoff": "Switch off back-illumination light without moving the stage.",
}
FRAME_COMMANDS = {"getdark", "getflat", "getarc", "getobj"}
FRAME_TYPES = {"getbias": "Bias", "getdark": "Dark", "getflat": "Flat",
               "getarc": "Arc", "getobj": "Object"}


def make_frame_header(command, *, night, project, tile_id, object_name, ra, dec, fwhm):
    """Attach the selected GUI tile to a validated IsoPlane frame command."""
    func = command["func"]
    if func not in FRAME_TYPES:
        return None
    return set_header_info(
        obsdate=night, obstype=FRAME_TYPES[func], TileID=tile_id,
        obsra=ra, obsdec=dec, exptime=command.get("time", 0),
        expnum=command["numframe"], projID=project, fwhm=fwhm,
        object_name=object_name or tile_id,
    )


def _positive_count(value):
    try:
        count = int(value)
    except ValueError:
        raise ValueError("Number of frames must be a positive integer") from None
    if count < 1:
        raise ValueError("Number of frames must be a positive integer")
    return count


def _exposure_time(value):
    try:
        seconds = float(value)
    except ValueError:
        raise ValueError("Exposure time must be a finite, non-negative number of seconds") from None
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError("Exposure time must be a finite, non-negative number of seconds")
    return seconds


def make_speciso_command(arg, header=None):
    """Return the SPEC wire message accepted by SPECTRO_ISOPLANE.command.Isoplane."""
    parts = arg.split()
    if not parts:
        raise ValueError("Enter an IsoPlane command")
    func, *params = parts

    if func in NO_ARGUMENT_COMMANDS:
        if params:
            raise ValueError(f"Usage: {func}")
        return create_spec_command(func, message=NO_ARGUMENT_COMMANDS[func])

    if func == "specinitial":
        if len(params) not in (1, 2):
            raise ValueError("Usage: specinitial <night> [experiment]")
        extra = {"experiment": params[1]} if len(params) == 2 else {}
        return create_spec_command(func, dirname=params[0],
                                   message="Initialize IsoPlane.", **extra)

    if func == "getbias":
        if len(params) != 1:
            raise ValueError("Usage: getbias <number_of_frames>")
        count = _positive_count(params[0])
        return create_spec_command(func, numframe=count, header=header or {},
                                   message=f"Take {count} bias frame(s).")

    if func in FRAME_COMMANDS:
        if len(params) != 2:
            raise ValueError(f"Usage: {func} <exposure_seconds> <number_of_frames>")
        seconds = _exposure_time(params[0])
        count = _positive_count(params[1])
        return create_spec_command(func, time=seconds, numframe=count,
                                   header=header or {},
                                   message=f"Take {count} {func[3:]} frame(s) at {seconds:g} s.")

    raise ValueError(f"Unknown IsoPlane command: {func}")


async def handle_speciso(arg, ICS_client, header=None):
    """Send a validated GUI command to the IsoPlane server queue."""
    message = make_speciso_command(arg, header)
    await ICS_client.send_message("ISOPLANE", message)
