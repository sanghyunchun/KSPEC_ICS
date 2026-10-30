# tests/test_gfa_guider_offsets.py
"""
End-to-end checks of the guiding offset geometry on synthetic GFA frames.

A reference astrometry product (astro_*.fits WCS + combined_star.fits) is written
for each camera, the telescope is moved by a known on-sky offset, raw frames are
rendered at the new pointing, and the real GFAGuider.exe_cal() is run on them
(real photutils / scipy, no stubs). The offsets must be the on-sky east/north
offsets that the ICS applies with SkyCoord.spherical_offsets_by
(script/scriptcli.py: apply_offset), for any declination and camera rotation.

Camera layout: six cameras on a 1.473 deg ring, rotated like the commissioning
solve-field WCS (2026-01-24: 0, +-61, +-121, 179 deg; 0.418 arcsec/pix, det(CD) < 0).
"""
import json
import logging
import math
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import numpy as np
import pytest
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.table import Table
from astropy.wcs import WCS

SRC = Path(__file__).resolve().parents[1] / "src" / "kspec_gfa_controller"
CONFIG = SRC / "etc" / "astrometry_params.json"

NX, NY = 600, 600
SCALE = 0.418  # arcsec/pix (commissioning WCS, 4x4 binning)
FWHM = 1.2  # arcsec
RING_DEG = 1.473
# (serial, position angle of the camera on the ring, camera rotation)
CAMERAS = [
    ("40103651", 180.0, 0.0),
    ("40103667", 120.0, -61.0),
    ("40103831", 60.0, -121.0),
    ("40103663", 0.0, 179.0),
    ("40103833", -60.0, 121.0),
    ("40103834", -120.0, 61.0),
]


_STUBBED = ("scipy", "photutils")


def _stubbed_modules():
    """scipy/photutils entries of sys.modules, split into real modules and stubs."""
    real, stubs = {}, {}
    for name, mod in list(sys.modules.items()):
        if name.split(".")[0] in _STUBBED:
            (real if getattr(mod, "__file__", None) else stubs)[name] = mod
    return real, stubs


def _load_real_guider():
    """
    Load gfa_guider.py against the real scipy/photutils.

    test_gfa_guider.py installs stub scipy/photutils modules in sys.modules; set
    them aside while importing and put them back afterwards. Returns the module
    and the real scipy/photutils modules (for the per-test fixture below).
    """
    _, stubs = _stubbed_modules()
    for name in stubs:
        del sys.modules[name]
    try:
        pytest.importorskip("photutils.detection")
        pytest.importorskip("scipy.optimize")
        spec = spec_from_file_location(
            "gfa_guider__offsets_under_test", SRC / "gfa_guider.py"
        )
        mod = module_from_spec(spec)
        spec.loader.exec_module(mod)
        real, _ = _stubbed_modules()
        return mod, real
    finally:
        sys.modules.update(stubs)


gg, _REAL_MODULES = _load_real_guider()


@pytest.fixture(autouse=True)
def _real_scipy_photutils():
    """
    photutils/astropy import scipy submodules lazily, so the real modules must be
    in sys.modules while these tests run; restore the previous state afterwards.
    """
    saved = {n: m for n, m in sys.modules.items() if n.split(".")[0] in _STUBBED}
    for name in saved:
        del sys.modules[name]
    sys.modules.update(_REAL_MODULES)
    yield
    for name in [n for n in sys.modules if n.split(".")[0] in _STUBBED]:
        del sys.modules[name]
    sys.modules.update(saved)


def apply_offset(coord: SkyCoord, offset_ra: float, offset_dec: float) -> SkyCoord:
    """ICS script/scriptcli.py apply_offset (without the string round trip)."""
    return coord.spherical_offsets_by(offset_ra * u.arcsec, offset_dec * u.arcsec)


def camera_wcs(center: SkyCoord, rot_deg: float, parity: int = -1) -> WCS:
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crpix = [NX / 2 + 0.5, NY / 2 + 0.5]
    w.wcs.crval = [center.ra.deg, center.dec.deg]
    t = np.radians(rot_deg)
    rot = np.array([[np.cos(t), -np.sin(t)], [np.sin(t), np.cos(t)]])
    w.wcs.cd = SCALE / 3600.0 * rot @ np.diag([parity, 1.0])
    return w


def layout(boresight: SkyCoord, cameras, parity=-1):
    """Camera WCS for a boresight; the cameras move rigidly with the telescope."""
    out = []
    for serial, pa, rot in cameras:
        if len(cameras) == 1:
            center = boresight
        else:
            center = boresight.directional_offset_by(pa * u.deg, RING_DEG * u.deg)
        out.append((serial, camera_wcs(center, rot, parity)))
    return out


def render(w: WCS, stars: SkyCoord, peak: np.ndarray, rng) -> np.ndarray:
    x, y = w.world_to_pixel(stars)
    img = 100.0 + rng.normal(0.0, 5.0, (NY, NX))
    sig = FWHM / SCALE / 2.3548
    for xi, yi, a in zip(x, y, peak):
        if not (5 < xi < NX - 5 and 5 < yi < NY - 5):
            continue
        y0, x0 = int(yi), int(xi)
        yy, xx = np.mgrid[max(0, y0 - 12) : y0 + 13, max(0, x0 - 12) : x0 + 13]
        img[yy, xx] += a * np.exp(-((xx - xi) ** 2 + (yy - yi) ** 2) / (2 * sig**2))
    return img


class GuidingRig:
    """Reference products on disk + a GFAGuider; renders raw frames per pointing."""

    def __init__(self, root: Path, boresight: SkyCoord, cameras, parity=-1, seed=1,
                 n_stars=20, peak_range=(800.0, 3000.0), sep_range_deg=None, config=CONFIG):
        """
        n_stars, peak_range : catalogue stars per camera and their peak (ADU above bkg).
        sep_range_deg       : (min, max) distance of the stars from the chip centre;
                              None places them anywhere 40 px from the edges.
        config              : astrometry_params.json to run the guider with.
        """
        self.root = root
        self.boresight = boresight
        self.cameras = cameras
        self.parity = parity
        self.rng = np.random.default_rng(seed)
        for d in ("raw", "astroimg", "cutout", "star_catalog"):
            (root / d).mkdir(parents=True, exist_ok=True)

        ra_s, dec_s = boresight.to_string("hmsdms", sep=":", precision=2).split()
        self.radec = (ra_s, dec_s)
        ras, decs, peaks = [], [], []
        for serial, w in layout(boresight, cameras, parity):
            n = n_stars
            if sep_range_deg is None:
                px = self.rng.uniform(40, NX - 40, n)
                py = self.rng.uniform(40, NY - 40, n)
            else:
                px, py = self._annulus(w, n, sep_range_deg)
            s = w.pixel_to_world(px, py)
            ras.append(s.ra.deg)
            decs.append(s.dec.deg)
            peaks.append(self.rng.uniform(*peak_range, n))
            hdr = w.to_header()
            hdr["RA"], hdr["DEC"] = ra_s, dec_s
            fits.writeto(
                root / "astroimg" / f"astro_D20261027_T000000_{serial}_exp5s.fits",
                np.zeros((NY, NX), np.float32),
                hdr,
            )
        self.stars = SkyCoord(np.concatenate(ras) * u.deg, np.concatenate(decs) * u.deg)
        self.peak = np.concatenate(peaks)
        Table(
            {
                "index_ra": self.stars.ra.deg,
                "index_dec": self.stars.dec.deg,
                "FLUX": self.peak,
            }
        ).write(root / "star_catalog" / "combined_star.fits")

        log = logging.getLogger("test_gfa_guider_offsets")
        log.addHandler(logging.NullHandler())
        log.propagate = False
        self.guider = gg.GFAGuider(config=str(config), logger=log, save_root=root)

    def _annulus(self, w, n, sep_range_deg):
        """n pixel positions (40 px from the edges) at the given distance from the chip centre."""
        centre = w.pixel_to_world((NX - 1) / 2, (NY - 1) / 2)
        px, py = [], []
        while len(px) < n:
            x, y = self.rng.uniform(40, NX - 40), self.rng.uniform(40, NY - 40)
            sep = centre.separation(w.pixel_to_world(x, y)).deg
            if sep_range_deg[0] <= sep <= sep_range_deg[1]:
                px.append(x)
                py.append(y)
        return np.array(px), np.array(py)

    def measure(self, pointing: SkyCoord):
        for p in (self.root / "raw").glob("*.fits"):
            p.unlink()
        for serial, w in layout(pointing, self.cameras, self.parity):
            fits.writeto(
                self.root / "raw" / f"D20261027_T000200_{serial}_exp5s.fits",
                render(w, self.stars, self.peak, self.rng),
                fits.Header({"RA": self.radec[0], "DEC": self.radec[1]}),
            )
        return self.guider.exe_cal()

    def error(self, pointing: SkyCoord):
        e, n = self.boresight.spherical_offsets_to(pointing)
        return e.to_value(u.arcsec), n.to_value(u.arcsec)


@pytest.mark.parametrize("parity", [-1, 1])
@pytest.mark.parametrize("rot", [0.0, 61.0, 121.0, 179.0])
@pytest.mark.parametrize("dec", [0.0, -37.0, -60.0, -75.0])
def test_offset_is_on_sky_east_north(tmp_path, dec, rot, parity):
    bore = SkyCoord(150.0 * u.deg, dec * u.deg)
    rig = GuidingRig(tmp_path, bore, [("40103651", 0.0, rot)], parity=parity)

    d_east, d_north = 3.0, -2.0
    cur = bore.spherical_offsets_by(d_east * u.arcsec, d_north * u.arcsec)
    fdx, fdy, fwhm = rig.measure(cur)

    # The offset brings the telescope back to the reference pointing
    assert fdx == pytest.approx(-d_east, abs=0.05)
    assert fdy == pytest.approx(-d_north, abs=0.05)
    resid = rig.error(apply_offset(cur, fdx, fdy))
    assert np.hypot(*resid) < 0.07

    # FWHM uses the WCS pixel scale, not the config value
    assert fwhm == pytest.approx(FWHM, abs=0.05)


@pytest.mark.parametrize("ncam", [6, 5])
@pytest.mark.parametrize("dec", [-37.0, -60.0, -70.0])
def test_closed_loop_converges(tmp_path, dec, ncam):
    bore = SkyCoord(87.4 * u.deg, dec * u.deg)
    rig = GuidingRig(tmp_path, bore, CAMERAS[:ncam])

    cur = bore.spherical_offsets_by(3.0 * u.arcsec, -2.0 * u.arcsec)
    errors = []
    for _ in range(3):
        fdx, fdy, _ = rig.measure(cur)
        cur = apply_offset(cur, fdx, fdy)
        errors.append(np.hypot(*rig.error(cur)))

    # One cycle removes the drift (no overshoot); later cycles stay inside the deadband
    assert errors[0] < 0.1
    assert max(errors) < 0.25


@pytest.mark.parametrize("cuts", ["shipped", "previous"])
def test_faint_off_centre_guide_stars(tmp_path, monkeypatch, cuts):
    """
    Full-size chips (1332 x 1152), five cameras, only faint stars (peak 120-280 ADU)
    between 0.065 and 0.095 deg from each chip centre. The previous cuts (peak and
    catalogue flux >= 300, within 0.06 deg) leave no guide star; the shipped ones
    (>= 100, within 0.10 deg, i.e. the whole chip) recover the drift.
    """
    mod = sys.modules[__name__]
    monkeypatch.setattr(mod, "NX", 1332)
    monkeypatch.setattr(mod, "NY", 1152)
    config = CONFIG
    if cuts == "previous":
        inpar = json.loads(CONFIG.read_text())
        inpar["detection"]["peak_detection"]["min"] = 300
        inpar["catalog_matching"]["tolerance"].update(angular_distance=0.06, mag_flux_min=300)
        config = tmp_path / "previous_cuts.json"
        config.write_text(json.dumps(inpar))

    bore = SkyCoord(87.4 * u.deg, -46.0 * u.deg)
    rig = GuidingRig(tmp_path / "rig", bore, CAMERAS[:5], n_stars=12,
                     peak_range=(120.0, 280.0), sep_range_deg=(0.065, 0.095), config=config)
    cur = bore.spherical_offsets_by(3.0 * u.arcsec, -2.0 * u.arcsec)
    fdx, fdy, _ = rig.measure(cur)

    if cuts == "previous":
        assert math.isnan(fdx) and math.isnan(fdy)
    else:
        assert fdx == pytest.approx(-3.0, abs=0.1)
        assert fdy == pytest.approx(2.0, abs=0.1)


# ---------------------------------------------------------------------------
# Windowed centroid and neighbour handling (cal_centroid_offset)
# ---------------------------------------------------------------------------
PIX_DEG = 0.4 / 3600.0


class _LinearWCS:
    """x, y (0-based pixels) -> (ra, dec) in degrees near (0, 0): 1 px = 0.4 arcsec."""

    def pixel_to_world_values(self, x, y):
        return (np.asarray(x) * PIX_DEG, np.asarray(y) * PIX_DEG)


def _gauss_image(shape, stars, fwhm, sky=100.0, noise=0.0, seed=0):
    """stars: (x, y, peak) in 0-based pixels; returns sky + stars (+ noise), minus sky."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[: shape[0], : shape[1]].astype(float)
    sig = fwhm / 2.3548
    img = np.full(shape, sky)
    for x, y, a in stars:
        img += a * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * sig**2))
    if noise:
        img += rng.normal(0.0, noise, shape)
    return img - sky


def _guider(tmp_path, fwhm_px=None):
    config = CONFIG
    if fwhm_px is not None:
        inpar = json.loads(CONFIG.read_text())
        inpar["detection"]["centroid"]["fwhm_px"] = fwhm_px
        config = tmp_path / "cfg_fwhm.json"
        config.write_text(json.dumps(inpar))
    log = logging.getLogger("test_gfa_guider_centroid")
    log.addHandler(logging.NullHandler())
    log.propagate = False
    return gg.GFAGuider(config=str(config), logger=log, save_root=tmp_path / "rig")


def _measure(g, img, pred_xy, noise=5.0):
    """Run cal_centroid_offset for 0-based predicted positions; return (x, y, peak) per star."""
    pred = np.asarray(pred_xy, float).reshape(-1, 2)
    dra_f, ddec_f = pred[:, 0] + 1.0, pred[:, 1] + 1.0
    dx, dy, peakc, _ = g.cal_centroid_offset(
        np.round(dra_f).astype(int), np.round(ddec_f).astype(int), dra_f, ddec_f,
        noise, _LinearWCS(), np.ones(len(pred)), 1, [], img,
    )
    x = pred[:, 0] + np.asarray(dx) / 0.4
    y = pred[:, 1] + np.asarray(dy) / 0.4
    return x, y, np.asarray(peakc)


def test_windowed_centroid_recovers_subpixel_position():
    img = _gauss_image((61, 61), [(30.37, 28.81, 1000.0)], fwhm=8.0)
    x, y = gg.GFAGuider.windowed_centroid(img, 30.0, 29.0, 8.0 / 2.3548, max_shift=8.0)
    assert abs(x - 30.37) < 0.01 and abs(y - 28.81) < 0.01


@pytest.mark.parametrize("fwhm", [3.0, 8.0])
def test_cal_centroid_offset_subpixel_accuracy(tmp_path, fwhm):
    """Noisy stars at sub-pixel positions, predicted 3 px off: < 0.05 px error."""
    # sub-pixel phases all over; no star within 2.5 FWHM of another
    true = np.array([[40.3, 40.7], [100.6, 45.2], [160.1, 40.9],
                     [45.8, 150.4], [105.45, 155.55], [158.2, 100.75]])
    stars = [(x, y, 2000.0) for x, y in true]
    img = _gauss_image((200, 200), stars, fwhm=fwhm, noise=5.0, seed=4)
    g = _guider(tmp_path)  # shipped fwhm_px (8) for both PSFs
    x, y, peak = _measure(g, img, true + [2.0, -2.0])
    assert np.all(peak > 0)
    assert np.max(np.hypot(x - true[:, 0], y - true[:, 1])) < 0.05


def test_brighter_neighbour_in_box_does_not_capture(tmp_path):
    """
    A star 3x brighter 25 px away (inside the 41 px box, outside 2.5 FWHM): the
    old guider took the brightest peak in the box; the seed must be the nearest.
    """
    target = (100.3, 100.6)
    img = _gauss_image((200, 200), [(*target, 800.0), (118.0, 117.8, 2400.0)],
                       fwhm=8.0, noise=5.0)
    g = _guider(tmp_path)
    x, y, peak = _measure(g, img, [(101.5, 99.5)])
    assert 600 < peak[0] < 900
    assert math.hypot(x[0] - target[0], y[0] - target[1]) < 0.1


@pytest.mark.parametrize("fwhm, rejected", [(8.0, True), (4.0, False)])
def test_close_brighter_neighbour(tmp_path, fwhm, rejected):
    """
    A star 3x brighter 12 px away. At FWHM 8 (12 px = 1.5 FWHM) it would shift the
    windowed centroid by ~1.6 px: the guide star is rejected instead of being
    pulled to the neighbour. At FWHM 4 (3 FWHM) the guide star is measured.
    """
    target = (100.4, 100.3)
    img = _gauss_image((200, 200), [(*target, 800.0), (112.4, 100.3, 2400.0)],
                       fwhm=fwhm, noise=5.0)
    g = _guider(tmp_path, fwhm_px=fwhm)
    x, y, peak = _measure(g, img, [(100.0, 101.0)])
    if rejected:
        assert peak[0] == -1
    else:
        assert peak[0] > 0
        assert math.hypot(x[0] - target[0], y[0] - target[1]) < 0.1


def test_faint_neighbour_is_tolerated(tmp_path):
    """A 0.2x neighbour 15 px away (expected shift 0.02 px) keeps the star."""
    target = (100.0, 100.0)
    img = _gauss_image((200, 200), [(*target, 2000.0), (115.0, 100.0, 400.0)],
                       fwhm=7.0, noise=5.0)
    g = _guider(tmp_path)
    x, y, peak = _measure(g, img, [target])
    assert peak[0] > 0
    assert math.hypot(x[0] - target[0], y[0] - target[1]) < 0.1


def test_saturated_plateau_is_one_source(tmp_path):
    """
    A clipped (saturated) star has a flat top wider than 1 FWHM: find_peaks reports
    several equal peaks on it. They are one source, not neighbours.
    """
    target = (100.2, 99.7)
    img = _gauss_image((200, 200), [(*target, 20000.0)], fwhm=8.0, noise=5.0)
    img = np.minimum(img, 3800.0)
    g = _guider(tmp_path)
    x, y, peak = _measure(g, img, [(101.0, 101.0)])
    assert peak[0] == pytest.approx(3800.0, abs=30)
    assert math.hypot(x[0] - target[0], y[0] - target[1]) < 0.2


@pytest.mark.parametrize("fwhm", [3.0, 8.0, 13.0])
def test_windowed_psf_sigma(fwhm):
    """The windowed second moment under an 8 px window gives the PSF FWHM back."""
    img = _gauss_image((121, 121), [(60.3, 59.6, 1000.0)], fwhm=fwhm)
    s = gg.GFAGuider.windowed_psf_sigma(img, 60.3, 59.6, 8.0 / 2.3548)
    assert 2.3548 * s == pytest.approx(fwhm, rel=0.03)


@pytest.mark.parametrize("measure", [True, False])
def test_fwhm_measured_per_frame(tmp_path, measure):
    """
    3 px stars, config FWHM 8 px. A 0.5x neighbour 10 px from the guide star
    shifts an 8 px window by ~0.6 px but a 3 px one by nothing. With
    measure_fwhm the frame FWHM is measured from the isolated stars, the window
    shrinks and the guide star is kept and measured; without, it is rejected.
    """
    iso = [(40.4, 40.2), (160.7, 40.5), (40.1, 160.6), (160.3, 159.8)]
    target = (100.35, 100.65)
    stars = [(x, y, 1500.0) for x, y in iso] + [(*target, 1500.0), (110.35, 100.65, 750.0)]
    img = _gauss_image((200, 200), stars, fwhm=3.0, noise=5.0)
    g = _guider(tmp_path)
    g.measure_fwhm = measure
    x, y, peak = _measure(g, img, iso + [target])
    assert np.all(peak[:4] > 0)
    if measure:
        assert peak[4] > 0
        assert math.hypot(x[4] - target[0], y[4] - target[1]) < 0.05
    else:
        assert peak[4] == -1
