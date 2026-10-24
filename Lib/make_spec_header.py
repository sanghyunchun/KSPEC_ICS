"""Header dict sent with the SPEC frame commands (getbias, getflat, getarc, getobj).

The spectrograph server writes it into every frame: SPECTRO_ISOPLANE/fitsio.py, card table in
SPECTRO_ISOPLANE/README.md ("Header cards"). A value that is None (or 'None') is unknown, and the
server leaves its card out.
"""
import json

FWHM_UNKNOWN = 9.99  # what the scripts send when the GFA has no seeing estimate


def site_info(path='./Lib/KSPEC.ini'):
    """OBSERVAT, SITELAT, SITELONG, SITEELEV from the KSPEC.ini SITE block (None when unset)."""
    try:
        with open(path, 'r') as f:
            site = json.load(f).get('SITE') or {}
    except (OSError, ValueError):
        site = {}
    return {'OBSERVAT': site.get('name'), 'SITELAT': site.get('latitude_deg'),
            'SITELONG': site.get('longitude_deg'), 'SITEELEV': site.get('elevation_m')}


def set_header_info(obstype: str='None', obsdate: str='19820913', TileID: str='0000', obsra: str='00:00:00.000',obsdec: str='00:00:00.000',
        exptime: int=10, expnum: str='None', projID: str='None', fwhm: float='9.99',
        object_name: str=None, expidx: int=None, extra_cards: list=None):
    """Header dict for one SPEC frame command.

    expnum is the number of exposures in the sequence (NEXP); expidx is the number of the first
    frame of this command in that sequence (EXPNUM; None: the server counts from 1). extra_cards
    [(key, value, comment), ...] are written as given (see fitsio.ics_cards).
    """
    try:
        fwhm = None if float(fwhm) == FWHM_UNKNOWN else float(fwhm)
    except (TypeError, ValueError):
        fwhm = None

    headerinfo = {'OBSDATE': obsdate, 'OBSTYPE': obstype, 'PROJID': projID, 'TileID': TileID, 'RA': obsra, 'DEC': obsdec, 'EXPTIME': exptime,
        'NEXP': expnum, 'EXPNUM': expidx, 'FWHM': fwhm, 'OBJECT': object_name, **site_info()}
    if extra_cards:
        headerinfo['CARDS'] = [list(card) for card in extra_cards]

    return headerinfo
