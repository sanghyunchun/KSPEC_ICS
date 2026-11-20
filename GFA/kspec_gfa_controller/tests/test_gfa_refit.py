# tests/test_gfa_refit.py
"""Gaia refit of the GFA chip WCS (gfa_refit) and its use in gfa_astrometry."""
import json
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits
from astropy.table import Table
from astropy.wcs import WCS

import kspec_gfa_controller.gfa_astrometry as gfa_astrometry
from kspec_gfa_controller import gfa_refit
from kspec_gfa_controller.gfa_astrometry import GFAAstrometry, _get_default_logger

ETC = Path(gfa_refit.__file__).resolve().parent / "etc"
SIP = gfa_refit.load_distortion(str(ETC / "gfa_distortion.json"))["40103651"]
NX, NY = 1332, 1152
EPOCH = 2026.83
NAME = "D20261030_T120000_40103651_exp5s"


def true_header(crval=(150.0, -30.0), rot_deg=0.3, scale=0.4185):
    """TAN-SIP header with the fixed distortion: the 'true' chip."""
    h = fits.Header()
    h["CTYPE1"], h["CTYPE2"] = "RA---TAN-SIP", "DEC--TAN-SIP"
    h["CRVAL1"], h["CRVAL2"] = crval
    h["CRPIX1"], h["CRPIX2"] = (NX + 1) / 2, (NY + 1) / 2
    c, s = np.cos(np.radians(rot_deg)), np.sin(np.radians(rot_deg))
    k = scale / 3600
    h["CD1_1"], h["CD1_2"], h["CD2_1"], h["CD2_2"] = -k * c, k * s, k * s, k * c
    h["A_ORDER"] = h["B_ORDER"] = 3
    for key in ("A", "B"):
        for n, v in SIP[key].items():
            h[n] = v
    h["AP_ORDER"] = h["BP_ORDER"] = 3
    for key in ("AP", "BP"):
        for n, v in SIP[key].items():
            h[n] = v
    h["IMAGEW"], h["IMAGEH"] = NX, NY
    return h


def scene(n=60, seed=2, noise_px=0.05):
    """Catalogue at 2016.0 with proper motions, detections of the true chip at EPOCH."""
    rng = np.random.default_rng(seed)
    w = WCS(true_header())
    x = rng.uniform(20, NX - 20, n)
    y = rng.uniform(20, NY - 20, n)
    ra_e, dec_e = w.all_pix2world(x, y, 1)
    pmra, pmdec = rng.normal(0, 30, n), rng.normal(0, 30, n)  # mas/yr, large on purpose
    dt = EPOCH - gfa_refit.GAIA_EPOCH
    dec0 = dec_e - pmdec * dt / 3.6e6
    ra0 = ra_e - pmra * dt / 3.6e6 / np.cos(np.radians(dec0))
    flux = rng.uniform(500, 20000, n)
    xd, yd = x + rng.normal(0, noise_px, n), y + rng.normal(0, noise_px, n)
    cat = Table({"source_id": np.arange(n) + 1000, "ra": ra0, "dec": dec0, "pmra": pmra, "pmdec": pmdec})
    return cat, xd, yd, flux, (ra_e, dec_e)


def solve_field_like_header():
    """A starting solution as solve-field gives it: off by ~0.8" and 0.005 deg, with its own
    per-frame SIP of order 2 (the true quadratic terms x 1.05, no cubic terms)."""
    h = true_header(crval=(150.0 + 0.6 / 3600 / np.cos(np.radians(30)), -30.0 + 0.5 / 3600),
                    rot_deg=0.305)
    for n in list(h.keys()):
        if n.startswith(("A_", "B_", "AP_", "BP_")) and n[-1].isdigit():
            del h[n]
    for k in ("AP_ORDER", "BP_ORDER"):
        del h[k]
    h["A_ORDER"] = h["B_ORDER"] = 2
    for key in ("A", "B"):
        for n, v in SIP[key].items():
            p, q = map(int, n.split("_")[1:])
            if p + q == 2:
                h[n] = 1.05 * v
    return h


def test_refine_recovers_the_true_chip():
    cat, x, y, flux, (ra_e, dec_e) = scene(noise_px=0.0)
    gc = gfa_refit.GaiaCatalog.__new__(gfa_refit.GaiaCatalog)  # in-memory, no files
    gc.ra, gc.dec = np.asarray(cat["ra"]), np.asarray(cat["dec"])
    gc.pmra, gc.pmdec = np.asarray(cat["pmra"]), np.asarray(cat["pmdec"])
    dt = EPOCH - gfa_refit.GAIA_EPOCH
    ra, dec = gc.ra + gc.pmra * dt / 3.6e6 / np.cos(np.radians(gc.dec)), gc.dec + gc.pmdec * dt / 3.6e6
    new, m, info = gfa_refit.refine_wcs(solve_field_like_header(), x, y, flux, ra, dec, SIP)
    assert new is not None and info["n_fit"] >= 55
    truth = true_header()
    xi, eta = gfa_refit.gnomonic(new["CRVAL1"], new["CRVAL2"], truth["CRVAL1"], truth["CRVAL2"])
    assert np.hypot(xi, eta) * 3600 < 0.02
    rot = np.degrees(np.arctan2(new["CD1_2"], new["CD2_2"]) - np.arctan2(truth["CD1_2"], truth["CD2_2"]))
    assert abs(rot) * 3600 < 0.5  # arcsec of angle (0.01" at the 1.47 deg lever)
    assert new["GFAREFIT"] is True and new["A_ORDER"] == 3 and new["A_2_1"] == SIP["A"]["A_2_1"]
    # the new header maps the detections onto the epoch positions
    w = WCS(new)
    r2, d2 = w.all_pix2world(m["x"], m["y"], 1)
    assert np.max(np.hypot((r2 - m["ra"]) * np.cos(np.radians(d2)), d2 - m["dec"])) * 3600 < 0.2


def test_refine_without_proper_motion_is_worse():
    """The proper motions matter: without them the residual is much larger."""
    cat, x, y, flux, _ = scene()
    _, _, info_pm = gfa_refit.refine_wcs(solve_field_like_header(), x, y, flux,
                                         *scene()[4], SIP)
    _, _, info_no = gfa_refit.refine_wcs(solve_field_like_header(), x, y, flux,
                                         np.asarray(cat["ra"]), np.asarray(cat["dec"]), SIP)
    assert info_pm["rms_arcsec"] < 0.05
    assert info_no.get("rms_arcsec", 1.0) > 3 * info_pm["rms_arcsec"]


def test_refine_too_few_stars_returns_none():
    cat, x, y, flux, (ra, dec) = scene(n=4)
    new, m, info = gfa_refit.refine_wcs(solve_field_like_header(), x, y, flux, ra, dec, SIP)
    assert new is None and m is None and "reason" in info


def test_frame_epoch_from_name_then_date():
    e = gfa_refit.frame_epoch(fits.Header(), "/x/D20261030_T120000_40103651_exp5s.fits")
    assert abs(e - 2026.8282) < 1e-4
    h = fits.Header()
    h["DATE-OBS"] = "2026-10-28"
    assert abs(gfa_refit.frame_epoch(h, "astro.fits") - 2026.8213) < 2e-3
    assert gfa_refit.frame_epoch(fits.Header(), "x.fits") is None


def test_catalog_reads_files_dedups_and_moves_to_epoch(tmp_path):
    cat = Table({"source_id": [1, 2], "ra": [10.0, 10.05], "dec": [-30.0, -30.0],
                 "pmra": [100.0, 0.0], "pmdec": [-50.0, np.nan]})
    cat.write(tmp_path / "a.fits")
    cat[:1].write(tmp_path / "b.ecsv")  # overlaps a.fits
    gc = gfa_refit.GaiaCatalog(str(tmp_path))
    assert len(gc) == 2
    ra, dec = gc.cone(10.0, -30.0, 0.01, 2026.0)
    assert len(ra) == 1
    assert abs((dec[0] + 30.0) * 3.6e6 - (-500.0)) < 1e-6  # 10 yr x -50 mas/yr
    assert abs((ra[0] - 10.0) * np.cos(np.radians(-30)) * 3.6e6 - 1000.0) < 1.0
    assert len(gfa_refit.GaiaCatalog(str(tmp_path / "none"))) == 0


def test_replace_wcs_drops_the_old_sip():
    h = solve_field_like_header()
    h["OBJECT"] = "keep"
    new, _, _ = gfa_refit.refine_wcs(solve_field_like_header(), *scene()[1:4], *scene()[4], SIP)
    gfa_refit.replace_wcs(h, new)
    assert h["OBJECT"] == "keep" and h["A_ORDER"] == 3 and h["B_0_2"] == SIP["B"]["B_0_2"]
    assert "A_2_0" in h and h["A_2_0"] == SIP["A"]["A_2_0"]
    assert h["GFAREFIT"] is True


def test_shipped_distortion_and_config():
    d = json.loads((ETC / "gfa_distortion.json").read_text())
    assert set(d["cameras"]) >= {"40103651", "40103663", "40103831", "40103833", "40103834"}
    cams = gfa_refit.load_distortion(str(ETC / "gfa_distortion.json"))
    assert "default" in cams and cams["default"]["A"]["A_1_1"] == pytest.approx(SIP["A"]["A_1_1"], rel=0.01)
    cfg = json.loads((ETC / "astrometry_params.json").read_text())["astrometry"]["refine"]
    assert cfg["enabled"] is True and cfg["error_model_arcsec"] == [0.079, 0.135]


# --- in gfa_astrometry.astrometry_raw --------------------------------------------------------
def _config(path, tmp_path, catalog_dir):
    cfg = {
        "paths": {"directories": {"raw_images": str(tmp_path / "raw"), "temp_files": str(tmp_path / "temp"),
                                  "final_astrometry_images": str(tmp_path / "final"),
                                  "star_catalog": str(tmp_path / "stars.fits")}},
        "settings": {"cpu": {"limit": 1}},
        "astrometry": {"scale_range": [0.1, 2.0], "radius": 1.0,
                       "source_list": {"enabled": True, "min_sources": 5},
                       "refine": {"enabled": True, "catalog_dir": str(catalog_dir)}},
    }
    path.write_text(json.dumps(cfg))


def _patch_solve(monkeypatch, wcs_header):
    monkeypatch.setattr(gfa_astrometry, "_get_solve_field_path", lambda env=None: "/fake/solve-field")

    def fake_run(cmd, capture_output, text, env):
        work = Path(cmd[cmd.index("-D") + 1])
        out = cmd[cmd.index("-o") + 1]
        fits.PrimaryHDU(header=wcs_header).writeto(work / f"{out}.wcs", overwrite=True)
        cols = [fits.Column(name="index_ra", format="D", array=np.array([1.0]), unit="degrees"),
                fits.Column(name="index_dec", format="D", array=np.array([1.0]), unit="degrees"),
                fits.Column(name="FLUX", format="E", array=np.array([1.0]))]
        fits.HDUList([fits.PrimaryHDU(), fits.BinTableHDU.from_columns(cols)]).writeto(work / f"{out}.corr")

        class R:
            returncode, stdout, stderr = 0, "", ""

        return R()

    monkeypatch.setattr("kspec_gfa_controller.gfa_astrometry.subprocess.run", fake_run)


def _star_frame(x, y, flux, fwhm=7.0):
    yy, xx = np.mgrid[0:NY, 0:NX]
    img = np.full((NY, NX), 100.0)
    sig = fwhm / 2.3548
    for xi, yi, f in zip(x, y, flux):
        sl = (slice(max(int(yi) - 30, 0), int(yi) + 30), slice(max(int(xi) - 30, 0), int(xi) + 30))
        img[sl] += f / (2 * np.pi * sig**2) * np.exp(-((xx[sl] - (xi - 1)) ** 2 + (yy[sl] - (yi - 1)) ** 2) / (2 * sig**2))
    return img + np.random.default_rng(0).normal(0, 1.0, img.shape)


def test_astrometry_raw_refits_and_writes_the_guide_catalogue(tmp_path, monkeypatch):
    cat, x, y, flux, _ = scene(n=40, noise_px=0.0)
    (tmp_path / "gaia").mkdir()
    cat.write(tmp_path / "gaia" / "gaia_9999.fits")
    _config(tmp_path / "cfg.json", tmp_path, tmp_path / "gaia")
    _patch_solve(monkeypatch, solve_field_like_header())
    ast = GFAAstrometry(config=str(tmp_path / "cfg.json"), logger=_get_default_logger())
    raw = Path(ast.dir_path) / f"{NAME}.fits"
    h = fits.Header()
    h["RA"], h["DEC"] = "10:00:00", "-30:00:00"
    fits.PrimaryHDU(_star_frame(x, y, 5 * flux).astype(np.float32), header=h).writeto(raw)

    cr1, cr2, astro, corr = ast.astrometry_raw(str(raw))

    hdr = fits.getheader(astro)
    assert hdr["GFAREFIT"] is True and hdr["GFARFN"] >= 30
    truth = true_header()
    xi, eta = gfa_refit.gnomonic(cr1, cr2, truth["CRVAL1"], truth["CRVAL2"])
    assert np.hypot(xi, eta) * 3600 < 0.1  # 0.8" off before the refit
    assert corr.endswith(f"{NAME}.refit.corr")
    t = fits.open(corr)[1]
    assert t.columns["index_ra"].unit == "degrees"  # units of solve-field's .corr kept
    assert len(t.data) == hdr["GFARFN"]
    # the guide catalogue built from it
    out = ast.build_combined_star_from_corr(corr_files=[corr])
    assert len(fits.getdata(out, 1)) == hdr["GFARFN"]


def test_astrometry_raw_without_catalogue_keeps_solve_field(tmp_path, monkeypatch):
    cat, x, y, flux, _ = scene(n=40, noise_px=0.0)
    _config(tmp_path / "cfg.json", tmp_path, tmp_path / "empty")
    _patch_solve(monkeypatch, solve_field_like_header())
    ast = GFAAstrometry(config=str(tmp_path / "cfg.json"), logger=_get_default_logger())
    raw = Path(ast.dir_path) / f"{NAME}.fits"
    h = fits.Header()
    h["RA"], h["DEC"] = "10:00:00", "-30:00:00"
    fits.PrimaryHDU(_star_frame(x, y, 5 * flux).astype(np.float32), header=h).writeto(raw)
    cr1, cr2, astro, corr = ast.astrometry_raw(str(raw))
    assert "GFAREFIT" not in fits.getheader(astro)
    assert corr.endswith(f"{NAME}.corr") and not corr.endswith(".refit.corr")
    assert (cr1, cr2) == (solve_field_like_header()["CRVAL1"], solve_field_like_header()["CRVAL2"])


def test_combined_star_glob_prefers_the_refit_corr(tmp_path, monkeypatch):
    _config(tmp_path / "cfg.json", tmp_path, tmp_path / "gaia")
    monkeypatch.setattr(gfa_astrometry, "_get_solve_field_path", lambda env=None: "/fake/solve-field")
    ast = GFAAstrometry(config=str(tmp_path / "cfg.json"), logger=_get_default_logger())

    def corr(path, n):
        cols = [fits.Column(name="index_ra", format="D", array=np.zeros(n), unit="degrees"),
                fits.Column(name="index_dec", format="D", array=np.zeros(n), unit="degrees"),
                fits.Column(name="FLUX", format="E", array=np.ones(n))]
        path.parent.mkdir(parents=True, exist_ok=True)
        fits.HDUList([fits.PrimaryHDU(), fits.BinTableHDU.from_columns(cols)]).writeto(path)

    corr(Path(ast.temp_dir) / "a" / "a.corr", 3)
    corr(Path(ast.temp_dir) / "a" / "a.refit.corr", 7)
    corr(Path(ast.temp_dir) / "b" / "b.corr", 2)  # not refit: kept
    out = ast.build_combined_star_from_corr(corr_files=None)
    assert len(fits.getdata(out, 1)) == 9
