"""
Gaia DR3 star lists for the GFA refit, one file per tile (run before the night, with network).

The GFA chips sit on a ring 1.473 deg from the tile center, so each list covers that ring
(cones of 0.2 deg every 0.3 deg along it: 1.473 +- 0.15 deg, any instrument rotation), G < 19
by default: ra, dec (ICRS, epoch
2016.0), pmra, pmdec (mas/yr), phot_g_mean_mag, source_id. Sizes: ~2 000 stars at high
latitude, ~75 000 (3 MB) in the Galactic plane. Copy the files to the directory of
astrometry_params.json "astrometry.refine.catalog_dir" (default ~/work/DATA/GFADATA/gaia)
on the GFA PC; the GFA server reads every file there and uses the stars around each chip.
Without a file for a field the pointing keeps the solve-field solution.

Usage:
    python -m GFA.make_gaia_catalog OUTDIR NAME RA DEC [NAME RA DEC ...]
    python -m GFA.make_gaia_catalog OUTDIR --tiles tiles.csv     # columns TILE, RA, DEC
RA / DEC in degrees or sexagesimal (hh:mm:ss, dd:mm:ss).
"""

import argparse
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.table import Table, vstack
import numpy as np

TAP = "https://gea.esac.esa.int/tap-server/tap"
R_MID = 1.473  # deg, chip centers from the tile center
R_CIRCLE, STEP_DEG = 0.20, 0.30  # cones along the ring: cover 1.473 +- 0.15 deg (chip half-diagonal 0.10)


def to_deg(ra, dec):
    if ":" in str(ra) or ":" in str(dec):
        c = SkyCoord(str(ra), str(dec), unit=(u.hourangle, u.deg))
        return c.ra.deg, c.dec.deg
    return float(ra), float(dec)


def _sync(adql, timeout=120):
    data = urllib.parse.urlencode(
        {"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv", "QUERY": adql}
    ).encode()
    with urllib.request.urlopen(urllib.request.Request(f"{TAP}/sync", data=data), timeout=timeout) as r:
        text = r.read().decode()
    return Table.read(text.splitlines(), format="ascii.csv")


def ring_circles(ra0, dec0, r_mid=R_MID, step=STEP_DEG):
    """Centers of the circles (radius R_CIRCLE) that cover the GFA ring around a tile."""
    c0 = SkyCoord(ra0 * u.deg, dec0 * u.deg)
    n = int(np.ceil(2 * np.pi * r_mid / step))
    pa = np.arange(n) * 360.0 / n
    return c0.directional_offset_by(pa * u.deg, r_mid * u.deg)


def query(ra0, dec0, gmax, workers=6):
    """
    Gaia DR3 around the GFA ring: small cones along it, in parallel.

    One annulus query is slow and hits the anonymous limits of the archive
    (60 s, 50 000 rows) in the Galactic plane; ~31 cones of 0.2 deg take a few
    seconds each. Duplicates (cone overlaps) are dropped by source_id.
    """
    from concurrent.futures import ThreadPoolExecutor

    cols = "source_id, ra, dec, pmra, pmdec, phot_g_mean_mag"
    qs = [
        f"SELECT {cols} FROM gaiadr3.gaia_source WHERE 1 = CONTAINS(POINT(ra, dec), "
        f"CIRCLE({c.ra.deg:.6f}, {c.dec.deg:.6f}, {R_CIRCLE})) AND phot_g_mean_mag < {gmax}"
        for c in ring_circles(ra0, dec0)
    ]

    def run(q):
        for attempt in range(3):
            try:
                return _sync(q)
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(5 * (attempt + 1))

    with ThreadPoolExecutor(max_workers=workers) as ex:
        parts = list(ex.map(run, qs))
    t = vstack([p for p in parts if len(p)], metadata_conflicts="silent")
    _, keep = np.unique(np.asarray(t["source_id"]), return_index=True)
    return t[np.sort(keep)]


def write(t, path, name, ra0, dec0, gmax):
    hdu = fits.BinTableHDU(t)
    h = hdu.header
    h["EXTNAME"] = "GAIA"
    h["TILE"] = str(name)
    h["TILE_RA"] = (ra0, "[deg] tile center")
    h["TILE_DEC"] = (dec0, "[deg] tile center")
    h["R_MID"] = (R_MID, "[deg] ring of cones around the tile center")
    h["R_CONE"] = (R_CIRCLE, "[deg] cone radius")
    h["GMAX"] = gmax
    h["REF_EPOC"] = (2016.0, "Gaia DR3 reference epoch")
    h["CATALOG"] = "gaiadr3.gaia_source"
    fits.HDUList([fits.PrimaryHDU(), hdu]).writeto(path, overwrite=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("outdir")
    ap.add_argument("tiles", nargs="*", help="NAME RA DEC triples")
    ap.add_argument("--tiles", dest="tile_file", help="CSV / ECSV with columns TILE, RA, DEC")
    ap.add_argument("--gmax", type=float, default=19.0)
    ap.add_argument("--overwrite", action="store_true", help="query tiles that already have a file")
    a = ap.parse_args(argv)

    todo = []
    if a.tile_file:
        t = Table.read(a.tile_file, format="ascii.ecsv" if a.tile_file.endswith(".ecsv") else "ascii.csv")
        todo += [(str(r["TILE"]), r["RA"], r["DEC"]) for r in t]
    if len(a.tiles) % 3:
        ap.error("tiles come as NAME RA DEC triples")
    todo += [tuple(a.tiles[i:i + 3]) for i in range(0, len(a.tiles), 3)]
    if not todo:
        ap.error("no tiles")

    os.makedirs(a.outdir, exist_ok=True)
    failed = []
    for name, ra, dec in todo:
        path = os.path.join(a.outdir, f"gaia_{name}.fits")
        if os.path.exists(path) and not a.overwrite:
            print(f"{name}: exists, skipped ({path})")
            continue
        ra0, dec0 = to_deg(ra, dec)
        t0 = time.time()
        try:
            t = query(ra0, dec0, a.gmax)
        except Exception as e:
            print(f"{name}: failed: {e}", flush=True)
            t = None
        if t is None:
            failed.append(name)
            continue
        write(t, path, name, ra0, dec0, a.gmax)
        print(f"{name}: {len(t)} stars, {os.path.getsize(path) / 1e6:.1f} MB, {time.time() - t0:.1f} s -> {path}",
              flush=True)
    if failed:
        print(f"FAILED: {' '.join(failed)} (run again; finished tiles are skipped)")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
