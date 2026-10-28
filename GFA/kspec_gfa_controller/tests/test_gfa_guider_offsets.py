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
