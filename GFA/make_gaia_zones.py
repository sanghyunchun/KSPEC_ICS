"""
Full Gaia DR3 catalogue (G < 19) in declination zones, for the GFA refit.

The GFA server first looks for a tile list (GFA/make_gaia_catalog.py) that holds the chip; when
there is none it cuts the stars of the GFA ring from this catalogue into a new list
(astrometry_params.json "astrometry.refine.full_catalog_dir", default
~/work/DATA/GFADATA/gaia_zones). The zones are read by position with numpy only
(kspec_gfa_controller.gfa_refit.ZoneCatalog): z<k>.npy per 0.2 deg of declination, sorted by ra,
columns ra, dec (ICRS, epoch 2016.0), pmra, pmdec (mas/yr), phot_g_mean_mag; 28 bytes per star.
G < 19: 577 M stars, ~16 GB.

Built on a machine with network and memory (~50 GB for the whole sky), from the Gaia DR3 bulk
files on the ESA CDN (3386 gaia_source csv.gz, ~780 GB, streamed: each file is downloaded,
cut to the columns and G limit, saved as .npy and deleted):

    python -m GFA.make_gaia_zones download RAWDIR [--gmax 19] [--workers 6] [--limit N]
    python -m GFA.make_gaia_zones build RAWDIR OUTDIR [--zone-deg 0.2]

Both steps can be run again: finished files are skipped. build refuses until every bulk file is
in RAWDIR (--partial writes the zone files of what is there but claims no zone as complete, so
the GFA server does not use it; for tests). Copy OUTDIR to the GFA PC.
"""

import argparse
import hashlib
import os
import sys
import time
import urllib.request
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np

CDN = "http://cdn.gea.esac.esa.int/Gaia/gdr3/gaia_source/"
COLS = ["ra", "dec", "pmra", "pmdec", "phot_g_mean_mag"]


def _refit():
    """kspec_gfa_controller.gfa_refit, from the installed package or this checkout."""
    try:
        from kspec_gfa_controller import gfa_refit
    except ImportError:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        "kspec_gfa_controller", "src"))
        from kspec_gfa_controller import gfa_refit
    return gfa_refit


def bulk_files():
    """[(name, md5)] of the gaia_source bulk files."""
    with urllib.request.urlopen(CDN + "_MD5SUM.txt", timeout=120) as r:
        lines = r.read().decode().split("\n")
    return [(p[1], p[0]) for p in (ln.split() for ln in lines) if len(p) == 2 and p[1].endswith(".csv.gz")]


def cut(csv_gz, gmax, dtype):
    """The columns of ``dtype`` of the stars with G < gmax in one bulk file."""
    import pandas as pd

    t = pd.read_csv(csv_gz, comment="#", usecols=COLS, na_values=["null"], compression="gzip")
    t = t[t["phot_g_mean_mag"] < gmax]
    out = np.zeros(len(t), dtype)
    for c in COLS:
        out[c] = t[c].to_numpy()
    return out


def one_file(name, md5, rawdir, gmax):
    """Download, check, cut and save one bulk file; returns (name, stars, MB, seconds)."""
    dst = os.path.join(rawdir, name.replace(".csv.gz", ".npy"))
    if os.path.exists(dst):
        return name, None, 0.0, 0.0
    t0 = time.time()
    tmp = os.path.join(rawdir, name + ".part")
    h = hashlib.md5()
    with urllib.request.urlopen(CDN + name, timeout=600) as r, open(tmp, "wb") as fh:
        while True:
            b = r.read(1 << 22)
            if not b:
                break
            h.update(b)
            fh.write(b)
    if h.hexdigest() != md5:
        os.remove(tmp)
        raise RuntimeError(f"{name}: md5 mismatch")
    mb = os.path.getsize(tmp) / 1e6
    stars = cut(tmp, gmax, _refit().ZONE_DTYPE)
    np.save(dst + ".part.npy", stars)
    os.replace(dst + ".part.npy", dst)
    os.remove(tmp)
    return name, len(stars), mb, time.time() - t0


def download(a):
    os.makedirs(a.rawdir, exist_ok=True)
    files = bulk_files()
    with open(os.path.join(a.rawdir, "files.txt"), "w") as fh:
        fh.write("\n".join(f"{n} {m}" for n, m in files) + "\n")
    todo = [(n, m) for n, m in files if not os.path.exists(os.path.join(a.rawdir, n.replace(".csv.gz", ".npy")))]
    if a.limit:
        todo = todo[: a.limit]
    print(f"{len(files)} bulk files, {len(todo)} to do, G < {a.gmax}", flush=True)
    failed, t0, done_mb = [], time.time(), 0.0
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(one_file, n, m, a.rawdir, a.gmax): n for n, m in todo}
        for k, f in enumerate(as_completed(futs), 1):
            try:
                name, n, mb, dt = f.result()
                done_mb += mb
                rate = done_mb / max(time.time() - t0, 1e-3)
                print(f"[{k}/{len(todo)}] {name}: {n} stars, {mb:.0f} MB, {dt:.0f} s "
                      f"({rate:.1f} MB/s overall)", flush=True)
            except Exception as e:
                failed.append(futs[f])
                print(f"[{k}/{len(todo)}] {futs[f]}: FAILED {e}", flush=True)
    if failed:
        print(f"{len(failed)} failed; run again to retry them")
        return 1
    return 0


def build(a):
    g = _refit()
    names = [ln.split()[0] for ln in open(os.path.join(a.rawdir, "files.txt")) if ln.strip()]
    have = [n for n in names if os.path.exists(os.path.join(a.rawdir, n.replace(".csv.gz", ".npy")))]
    if len(have) < len(names) and not a.partial:
        print(f"{len(names) - len(have)} of {len(names)} bulk files missing: run download first")
        return 1
    t0 = time.time()
    stars = np.concatenate([np.load(os.path.join(a.rawdir, n.replace(".csv.gz", ".npy"))) for n in have])
    print(f"{len(stars)} stars from {len(have)} files, {time.time() - t0:.0f} s", flush=True)
    meta = {"source": CDN, "files": len(have)}
    if len(have) < len(names):
        meta["partial"] = True
    index = g.write_zones(stars, a.outdir, zone_deg=a.zone_deg, gmax=a.gmax, meta=meta)
    if meta.get("partial"):  # claim nothing: the server must not take missing sky for empty sky
        index["zones"] = []
        import json

        with open(os.path.join(a.outdir, "index.json"), "w") as fh:
            json.dump(index, fh, indent=1)
    size = sum(os.path.getsize(os.path.join(a.outdir, f)) for f in os.listdir(a.outdir)) / 1e9
    print(f"wrote {a.outdir}: {len(index['zones'])} complete zones, {size:.1f} GB, "
          f"{time.time() - t0:.0f} s", flush=True)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("download")
    d.add_argument("rawdir")
    d.add_argument("--gmax", type=float, default=19.0)
    d.add_argument("--workers", type=int, default=6)
    d.add_argument("--limit", type=int, default=0, help="only this many files (tests)")
    b = sub.add_parser("build")
    b.add_argument("rawdir")
    b.add_argument("outdir")
    b.add_argument("--zone-deg", type=float, default=0.2)
    b.add_argument("--gmax", type=float, default=19.0)
    b.add_argument("--partial", action="store_true")
    a = ap.parse_args(argv)
    return download(a) if a.cmd == "download" else build(a)


if __name__ == "__main__":
    sys.exit(main())
