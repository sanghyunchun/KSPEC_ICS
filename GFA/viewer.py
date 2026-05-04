#!/usr/bin/env python3
"""
fits_live_viewer.py

Live GUI viewer for FITS images from 6 cameras, grouped by acquisition time.
- Watches: <root>/<folder>/<YYYY-MM-DD>/
- Filenames like: D20260126_T102110_40103667_exp5s.fits
- Displays 6 cameras at once
- Prev/Next navigation
- Auto-update (polling) for new images
- Locks one reference star per camera from the initial frame
- Shows fixed-position cutouts to monitor guiding drift
- Estimates relative motion (dx, dy) of the star within the locked cutout

Extra behavior:
- If watched directory is empty, show demo images from ./demo_guiding_save
- If actual images appear, switch from demo to actual and relock references
- If actual images are all deleted, switch back to demo and relock references
"""

import argparse
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from astropy.io import fits
from astropy.visualization import ZScaleInterval

import tkinter as tk
from tkinter import ttk, messagebox

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.patches import Circle, Rectangle


# ---- Optics / plate scale ----
PIX_SIZE = 4 * 2.74e-6  # 4x4 binning (meters)
FLEN = 5.12             # meters
PIX_SCALE = np.rad2deg(PIX_SIZE / FLEN) * 3600.0  # arcsec / pixel


FNAME_RE = re.compile(
    r"^D(?P<date>\d{8})_T(?P<time>\d{6})_(?P<serial>\d+)_exp(?P<exp>[\d\.]+)s\.fits$"
)


@dataclass(frozen=True)
class FrameKey:
    date: str  # YYYYMMDD
    t: str     # HHMMSS

    def sortable(self) -> str:
        return f"{self.date}{self.t}"


def yyyymmdd_to_folder(yyyymmdd: str) -> str:
    if not re.fullmatch(r"\d{8}", yyyymmdd):
        raise ValueError("date must be YYYYMMDD (e.g. 20260126)")
    return f"{yyyymmdd[0:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"


def time_to_sec(hhmmss: str) -> int:
    hh = int(hhmmss[0:2])
    mm = int(hhmmss[2:4])
    ss = int(hhmmss[4:6])
    return hh * 3600 + mm * 60 + ss


def parse_filename(name: str) -> Optional[Tuple[FrameKey, str]]:
    m = FNAME_RE.match(name)
    if not m:
        return None
    key = FrameKey(m.group("date"), m.group("time"))
    serial = m.group("serial")
    return key, serial


def scan_groups(day_dir: str) -> Dict[FrameKey, Dict[str, str]]:
    """
    Returns:
      { FrameKey -> { serial -> filepath } }

    Files whose timestamps are within 4 seconds are grouped together.
    """
    groups: Dict[FrameKey, Dict[str, str]] = {}
    if not os.path.isdir(day_dir):
        return groups

    threshold_sec = 4
    group_keys: List[FrameKey] = []

    for fn in sorted(os.listdir(day_dir)):
        if not fn.endswith(".fits"):
            continue

        parsed = parse_filename(fn)
        if not parsed:
            continue

        key, serial = parsed
        t_sec = time_to_sec(key.t)

        matched_key: Optional[FrameKey] = None
        for gkey in group_keys:
            if gkey.date != key.date:
                continue
            if abs(time_to_sec(gkey.t) - t_sec) <= threshold_sec:
                matched_key = gkey
                break

        if matched_key is None:
            matched_key = key
            group_keys.append(matched_key)

        groups.setdefault(matched_key, {})[serial] = os.path.join(day_dir, fn)

    return groups


def sorted_keys(groups: Dict[FrameKey, Dict[str, str]]) -> List[FrameKey]:
    return sorted(groups.keys(), key=lambda k: k.sortable())


def robust_stats(x: np.ndarray) -> Tuple[float, float]:
    """Median + robust sigma (MAD)."""
    med = float(np.median(x))
    mad = float(np.median(np.abs(x - med)))
    sigma = 1.4826 * mad if mad > 0 else float(np.std(x))
    return med, sigma


def estimate_fwhm_arcsec(data: np.ndarray) -> Optional[Tuple[float, float, float, float, float]]:
    """
    Estimate FWHM by 2nd moments around a moderately bright, unsaturated peak.
    Returns:
        (peak_signal, fwhm_arcsec, x, y, fwhm_pix)
    or None if failed.
    """
    if data.ndim != 2:
        return None

    img = np.array(data, dtype=np.float64, copy=False)

    if not np.isfinite(img).any():
        return None
    finite = img[np.isfinite(img)]
    if finite.size < 100:
        return None

    med, sig = robust_stats(finite)

    h, w = img.shape
    y0, y1 = int(0.1 * h), int(0.9 * h)
    x0, x1 = int(0.1 * w), int(0.9 * w)
    roi = img[y0:y1, x0:x1]

    sat = float(np.percentile(finite, 99.99))
    upper = 0.90 * sat
    lower = med + 5.0 * sig

    cand = roi.copy()
    bad = (~np.isfinite(cand)) | (cand >= upper) | (cand <= lower)
    cand[bad] = -np.inf

    if not np.isfinite(cand).any():
        return None

    iy, ix = np.unravel_index(np.argmax(cand), cand.shape)
    peak_signal = float(cand[iy, ix])
    py, px = iy + y0, ix + x0

    half = 12
    ys = max(py - half, 0)
    ye = min(py + half + 1, h)
    xs = max(px - half, 0)
    xe = min(px + half + 1, w)
    cut = img[ys:ye, xs:xe]

    border = np.concatenate([
        cut[0, :], cut[-1, :], cut[:, 0], cut[:, -1]
    ])
    finite_border = border[np.isfinite(border)]
    bkg = float(np.median(finite_border)) if finite_border.size > 0 else med

    wgt = cut - bkg
    wgt[~np.isfinite(wgt)] = 0.0
    wgt[wgt < 0] = 0.0
    s = float(wgt.sum())
    if s <= 0:
        return None

    yy, xx = np.indices(cut.shape)
    cx = float((wgt * xx).sum() / s)
    cy = float((wgt * yy).sum() / s)

    vx = float((wgt * (xx - cx) ** 2).sum() / s)
    vy = float((wgt * (yy - cy) ** 2).sum() / s)
    if vx <= 0 or vy <= 0:
        return None

    sigma_pix = float(np.sqrt(0.5 * (vx + vy)))
    fwhm_pix = 2.355 * sigma_pix
    fwhm_arcsec = fwhm_pix * PIX_SCALE

    x_img = xs + cx
    y_img = ys + cy
    return peak_signal, fwhm_arcsec, x_img, y_img, fwhm_pix


def read_fits_2d(path: str) -> Optional[np.ndarray]:
    try:
        with fits.open(path, memmap=False) as hdul:
            for hdu in hdul:
                if hdu.data is None:
                    continue
                arr = np.asarray(hdu.data)
                if arr.ndim == 2:
                    return arr
                if arr.ndim == 3 and 1 in arr.shape:
                    arr2 = np.squeeze(arr)
                    if arr2.ndim == 2:
                        return arr2
    except Exception:
        return None
    return None


def autoscale_limits(img: np.ndarray) -> Tuple[float, float]:
    finite = img[np.isfinite(img)]
    if finite.size < 10:
        return 0.0, 1.0
    try:
        vmin, vmax = ZScaleInterval().get_limits(finite)
        if np.isfinite(vmin) and np.isfinite(vmax) and vmax > vmin:
            return float(vmin), float(vmax)
    except Exception:
        pass
    p1, p99 = np.percentile(finite, [1, 99])
    if p99 <= p1:
        p1, p99 = float(finite.min()), float(finite.max())
        if p99 <= p1:
            p99 = p1 + 1.0
    return float(p1), float(p99)


def extract_cutout(img: np.ndarray, x: float, y: float, half_size: int = 12):
    """
    Extract a square cutout centered near (x, y).
    Returns:
        cutout, xs, xe, ys, ye
    where [ys:ye, xs:xe] are the bounds in the original image.
    """
    h, w = img.shape
    cx = int(round(x))
    cy = int(round(y))

    xs = max(cx - half_size, 0)
    xe = min(cx + half_size + 1, w)
    ys = max(cy - half_size, 0)
    ye = min(cy + half_size + 1, h)

    cut = img[ys:ye, xs:xe]
    return cut, xs, xe, ys, ye


def centroid_in_cutout(img: np.ndarray) -> Optional[Tuple[float, float]]:
    """
    Estimate centroid inside a cutout using simple background-subtracted moments.
    Returns (x, y) in cutout-local coordinates, or None.
    """
    if img.ndim != 2:
        return None

    arr = np.array(img, dtype=np.float64, copy=False)
    finite = arr[np.isfinite(arr)]
    if finite.size < 20:
        return None

    med = float(np.median(finite))

    border = np.concatenate([arr[0, :], arr[-1, :], arr[:, 0], arr[:, -1]])
    border = border[np.isfinite(border)]
    bkg = float(np.median(border)) if border.size > 0 else med

    wgt = arr - bkg
    wgt[~np.isfinite(wgt)] = 0.0
    wgt[wgt < 0] = 0.0

    s = float(wgt.sum())
    if s <= 0:
        return None

    yy, xx = np.indices(arr.shape)
    cx = float((wgt * xx).sum() / s)
    cy = float((wgt * yy).sum() / s)
    return cx, cy


class FitsLiveViewer:
    def __init__(
        self,
        root_dir: str,
        folder_name: str,
        date_yyyymmdd: str,
        camera_serials: List[str],
        poll_sec: float,
    ):
        self.root_dir = root_dir
        self.folder_name = folder_name
        self.date_yyyymmdd = date_yyyymmdd
        self.date_folder = yyyymmdd_to_folder(date_yyyymmdd)
        self.day_dir = os.path.join(self.root_dir, "raw", self.date_folder)

        self.camera_serials = camera_serials
        self.poll_sec = poll_sec

        self.groups: Dict[FrameKey, Dict[str, str]] = {}
        self.keys: List[FrameKey] = []
        self.idx: int = -1
        self.follow_latest: bool = True

        self.reference_centers: Dict[str, Tuple[float, float]] = {}
        self.reference_fwhm_pix: Dict[str, float] = {}
        self.reference_locked: bool = False

        self._closing = False
        self._after_id = None

        # Actual watched data
        self.actual_groups: Dict[FrameKey, Dict[str, str]] = {}

        # Demo fallback
        self.demo_active: bool = False
        self.demo_dir = Path(__file__).resolve().parent / "demo_save"

        self._build_gui()
        self.win.protocol("WM_DELETE_WINDOW", self.on_close)

        self._initial_scan()
        self._schedule_poll()

    def _build_gui(self):
        self.win = tk.Tk()
        self.win.title("FITS Live Viewer")

        top = ttk.Frame(self.win, padding=8)
        top.pack(side=tk.TOP, fill=tk.X)

        self.status_var = tk.StringVar(value="")
        ttk.Label(top, textvariable=self.status_var).pack(side=tk.LEFT)

        btns = ttk.Frame(self.win, padding=8)
        btns.pack(side=tk.BOTTOM, fill=tk.X)

        self.prev_btn = ttk.Button(btns, text="◀ Prev", command=self.on_prev)
        self.prev_btn.pack(side=tk.LEFT)

        self.next_btn = ttk.Button(btns, text="Next ▶", command=self.on_next)
        self.next_btn.pack(side=tk.LEFT, padx=(8, 0))

        self.latest_btn = ttk.Button(btns, text="Go to Latest", command=self.on_latest)
        self.latest_btn.pack(side=tk.LEFT, padx=(8, 0))

        self.relock_btn = ttk.Button(btns, text="Relock Ref", command=self.on_relock)
        self.relock_btn.pack(side=tk.LEFT, padx=(8, 0))

        self.follow_var = tk.BooleanVar(value=True)
        self.follow_chk = ttk.Checkbutton(
            btns, text="Follow latest", variable=self.follow_var, command=self.on_toggle_follow
        )
        self.follow_chk.pack(side=tk.LEFT, padx=(16, 0))

        ttk.Label(btns, text=f"pixscale = {PIX_SCALE:.3f} arcsec/pix").pack(side=tk.RIGHT)

        self.fig, self.axes = plt.subplots(2, 3, figsize=(12, 7))
        self.fig.tight_layout(pad=2.0)

        self.canvas = FigureCanvasTkAgg(self.fig, master=self.win)
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.img_artists = [None] * 6
        self.overlay_artists: List = []
        self.inset_axes: List = []

        for ax, serial in zip(self.axes.flatten(), self.camera_serials):
            ax.set_title(serial)
            ax.set_xticks([])
            ax.set_yticks([])

    def _reset_reference_state(self):
        self.reference_centers = {}
        self.reference_fwhm_pix = {}
        self.reference_locked = False

    def _copy_groups(self, groups: Dict[FrameKey, Dict[str, str]]) -> Dict[FrameKey, Dict[str, str]]:
        return {k: dict(v) for k, v in groups.items()}

    def _load_demo_groups(self) -> Dict[FrameKey, Dict[str, str]]:
        """
        Load one demo frame from demo_guiding_save directory.
        The files are mapped to camera order as:
            K, -, S, P, E, C
        """
        demo_groups: Dict[FrameKey, Dict[str, str]] = {}

        demo_files = [
            self.demo_dir / "01_K.fits",
            self.demo_dir / "02_dash.fits",
            self.demo_dir / "03_S.fits",
            self.demo_dir / "04_P.fits",
            self.demo_dir / "05_E.fits",
            self.demo_dir / "06_C.fits",
        ]

        if not all(p.is_file() for p in demo_files):
            return demo_groups

        key = FrameKey(self.date_yyyymmdd, "000000")
        demo_groups[key] = {}

        for serial, path in zip(self.camera_serials, demo_files):
            demo_groups[key][serial] = str(path)

        return demo_groups

    def _activate_demo_mode(self):
        demo_groups = self._load_demo_groups()
        if not demo_groups:
            self.demo_active = False
            self.groups = {}
            self.keys = []
            self.idx = -1
            self._reset_reference_state()
            self._clear_empty_view("No FITS found and no demo images available.")
            return

        self.demo_active = True
        self.groups = self._copy_groups(demo_groups)
        self.keys = sorted_keys(self.groups)
        self.idx = len(self.keys) - 1 if self.keys else -1
        self._reset_reference_state()
        if self.keys:
            self._lock_reference_stars()
            self._render_current()
        else:
            self._clear_empty_view("Demo images could not be loaded.")

    def _activate_actual_mode(self):
        self.demo_active = False
        self.groups = self._copy_groups(self.actual_groups)
        self.keys = sorted_keys(self.groups)
        self.idx = len(self.keys) - 1 if self.keys else -1
        self._reset_reference_state()
        if self.keys:
            self._lock_reference_stars()
            self._render_current()
        else:
            self._clear_empty_view(f"No FITS found yet in {self.day_dir}")

    def _clear_empty_view(self, message: str):
        self._clear_overlays()
        for ax, serial in zip(self.axes.flatten(), self.camera_serials):
            ax.clear()
            ax.set_title(f"{serial}\n(empty)")
            ax.set_xticks([])
            ax.set_yticks([])
        self.canvas.draw_idle()
        self.status_var.set(message)

    def _initial_scan(self):
        # 없으면 자동 생성
        if not os.path.isdir(self.day_dir):
            try:
                os.makedirs(self.day_dir, exist_ok=True)
                print(f"[INFO] Created directory: {self.day_dir}")
            except Exception as e:
                messagebox.showerror(
                    "Directory creation failed",
                    f"Could not create:\n{self.day_dir}\n\n{e}"
                )
                try:
                    self.win.destroy()
                except Exception:
                    pass
                return

        _ = self._rescan()

        if self.actual_groups:
            self._activate_actual_mode()
        else:
            self._activate_demo_mode()

    def _rescan(self) -> bool:
        """
        Rescan the watched directory only.
        Returns True if actual watched data changed.
        """
        new_groups = scan_groups(self.day_dir)
        changed = (new_groups != self.actual_groups)
        self.actual_groups = self._copy_groups(new_groups)
        return changed

    def _lock_reference_stars(self):
        """
        Lock reference star positions from the current frame, one per camera.

        First, find an approximate star position using estimate_fwhm_arcsec().
        Then, re-center it using centroid_in_cutout() on a fixed cutout.
        This makes the locked reference center consistent with the centroid
        method used later in _render_current(), so dx/dy on the reference
        frame should be close to 0.
        """
        if not self.keys or self.idx < 0 or self.idx >= len(self.keys):
            self.reference_centers = {}
            self.reference_fwhm_pix = {}
            self.reference_locked = False
            return

        key = self.keys[self.idx]
        frame = self.groups.get(key, {})

        self.reference_centers = {}
        self.reference_fwhm_pix = {}

        for serial in self.camera_serials:
            path = frame.get(serial)
            if path is None or not os.path.isfile(path):
                continue

            img = read_fits_2d(path)
            if img is None:
                continue

            f = estimate_fwhm_arcsec(img)
            if f is None:
                continue

            peak_signal, fwhm_arcsec, x0, y0, fwhm_pix = f

            cut_half = max(12, int(np.ceil(4.0 * fwhm_pix)))
            cutout, xs, xe, ys, ye = extract_cutout(img, x0, y0, half_size=cut_half)

            c = centroid_in_cutout(cutout)
            if c is not None:
                cx_local, cy_local = c
                x_ref = xs + cx_local
                y_ref = ys + cy_local
            else:
                x_ref = x0
                y_ref = y0

            self.reference_centers[serial] = (x_ref, y_ref)
            self.reference_fwhm_pix[serial] = fwhm_pix

        self.reference_locked = len(self.reference_centers) > 0

    def _schedule_poll(self):
        if self._closing:
            return

        try:
            self._after_id = self.win.after(int(self.poll_sec * 1000), self._poll)
        except Exception:
            self._after_id = None

    def _poll(self):
        if self._closing:
            return

        try:
            changed = self._rescan()
            has_actual = bool(self.actual_groups)

            if has_actual:
                if self.demo_active:
                    self._activate_actual_mode()
                elif changed:
                    self.groups = self._copy_groups(self.actual_groups)
                    self.keys = sorted_keys(self.groups)
                    self.idx = len(self.keys) - 1 if self.keys else -1

                    if not self.reference_locked and self.keys:
                        self._lock_reference_stars()

                    self._render_current()
                else:
                    self._update_status()
            else:
                if not self.demo_active:
                    self._activate_demo_mode()
                else:
                    self._update_status()

        except Exception as e:
            print(f"[poll] {e}")

        if not self._closing:
            self._schedule_poll()

    def _update_status(self):
        if not self.keys:
            if self.demo_active:
                self.status_var.set("[DEMO] No actual FITS in watched directory.")
            else:
                self.status_var.set(f"[raw/{self.date_folder}] No frames yet.")
            return

        key = self.keys[self.idx] if 0 <= self.idx < len(self.keys) else self.keys[-1]
        lock_txt = "LOCKED" if self.reference_locked else "UNLOCKED"

        prefix = "[DEMO] " if self.demo_active else f"[{self.folder_name}/{self.date_folder}] "

        self.status_var.set(
            f"{prefix}"
            f"Frame {self.idx+1}/{len(self.keys)}  "
            f"D{key.date} T{key.t}  "
            f"[ref: {lock_txt}] "
            f"(updated: {time.strftime('%H:%M:%S')})"
        )

        if self.demo_active:
            self.win.title("FITS Live Viewer - DEMO - K-SPEC")
        else:
            self.win.title(f"FITS Live Viewer - {self.folder_name} - D{key.date} T{key.t}")

    def on_toggle_follow(self):
        self.follow_latest = bool(self.follow_var.get())

    def on_prev(self):
        if not self.keys:
            return
        self.follow_latest = False
        self.follow_var.set(False)
        self.idx = max(0, self.idx - 1)
        self._render_current()

    def on_next(self):
        if not self.keys:
            return
        self.follow_latest = False
        self.follow_var.set(False)
        self.idx = min(len(self.keys) - 1, self.idx + 1)
        self._render_current()

    def on_latest(self):
        if not self.keys:
            return
        self.idx = len(self.keys) - 1
        self._render_current()

    def on_relock(self):
        if not self.keys:
            return
        self._lock_reference_stars()
        self._render_current()

    def on_close(self):
        if self._closing:
            return

        self._closing = True

        try:
            self.win.withdraw()
        except Exception:
            pass

        try:
            self.win.quit()
        except Exception:
            pass

        try:
            self.win.after_idle(self.win.destroy)
        except Exception:
            try:
                self.win.destroy()
            except Exception:
                pass

    def _clear_overlays(self):
        for a in self.overlay_artists:
            try:
                a.remove()
            except Exception:
                pass
        self.overlay_artists = []

        for iax in self.inset_axes:
            try:
                iax.remove()
            except Exception:
                pass
        self.inset_axes = []

    def _render_current(self):
        if not self.keys:
            return

        self.idx = int(np.clip(self.idx, 0, len(self.keys) - 1))
        key = self.keys[self.idx]
        frame = self.groups.get(key, {})

        self._clear_overlays()

        for i, (ax, serial) in enumerate(zip(self.axes.flatten(), self.camera_serials)):
            path = frame.get(serial)
            ax.set_title(serial)
            ax.set_xticks([])
            ax.set_yticks([])

            if path is None or not os.path.isfile(path):
                ax.clear()
                ax.set_title(f"{serial}\n(missing)")
                ax.set_xticks([])
                ax.set_yticks([])
                self.img_artists[i] = None
                continue

            img = read_fits_2d(path)
            if img is None:
                ax.clear()
                ax.set_title(f"{serial}\n(read error)")
                ax.set_xticks([])
                ax.set_yticks([])
                self.img_artists[i] = None
                continue

            vmin, vmax = autoscale_limits(img)

            ax.clear()
            im = ax.imshow(
                img,
                origin="lower",
                vmin=vmin,
                vmax=vmax,
                interpolation="nearest",
                cmap="Greys_r",
            )
            ax.set_title(serial)
            ax.set_xticks([])
            ax.set_yticks([])
            self.img_artists[i] = im

            ref = self.reference_centers.get(serial)

            if ref is not None:
                x_ref, y_ref = ref
                fwhm_pix_ref = self.reference_fwhm_pix.get(serial, 3.0)

                cut_half = max(12, int(np.ceil(4.0 * fwhm_pix_ref)))
                cutout, xs, xe, ys, ye = extract_cutout(img, x_ref, y_ref, half_size=cut_half)

                ref_circ = Circle(
                    (x_ref, y_ref),
                    radius=max(6.0, 4.0 * fwhm_pix_ref),
                    fill=False,
                    linewidth=1.5,
                    edgecolor="darkorange",
                    alpha=0.9,
                )
                ax.add_patch(ref_circ)
                self.overlay_artists.append(ref_circ)

                rect = Rectangle(
                    (xs, ys),
                    xe - xs,
                    ye - ys,
                    fill=False,
                    linewidth=1.2,
                    edgecolor="cyan",
                    alpha=0.9,
                )
                ax.add_patch(rect)
                self.overlay_artists.append(rect)

                c = centroid_in_cutout(cutout)

                peak_signal = np.nan
                finite_cut = cutout[np.isfinite(cutout)]
                if finite_cut.size > 0:
                    peak_signal = float(np.max(finite_cut))

                dx = np.nan
                dy = np.nan
                x_now = None
                y_now = None
                cx_local = None
                cy_local = None

                if c is not None:
                    cx_local, cy_local = c
                    x_now = xs + cx_local
                    y_now = ys + cy_local
                    dx = x_now - x_ref
                    dy = y_now - y_ref

                    current_circ = Circle(
                        (x_now, y_now),
                        radius=max(4.0, 2.0 * fwhm_pix_ref),
                        fill=False,
                        linewidth=1.2,
                        edgecolor="lime",
                        alpha=0.9,
                    )
                    ax.add_patch(current_circ)
                    self.overlay_artists.append(current_circ)

                txt = ax.text(
                    0.02, 0.98,
                    f"dx={dx:+.2f}, dy={dy:+.2f} pix\n"
                    f"({dx*PIX_SCALE:+.2f}, {dy*PIX_SCALE:+.2f} arcsec)\n"
                    f"Count={peak_signal:.1f}",
                    transform=ax.transAxes,
                    ha="left", va="top",
                    color="w",
                    bbox=dict(facecolor="black", alpha=0.45, edgecolor="none", pad=3),
                )
                self.overlay_artists.append(txt)

                iax = ax.inset_axes([0.75, 0.75, 0.25, 0.24])
                self.inset_axes.append(iax)

                cvmin, cvmax = autoscale_limits(cutout)
                iax.imshow(
                    cutout,
                    origin="lower",
                    vmin=cvmin,
                    vmax=cvmax,
                    interpolation="nearest",
                    cmap="Greys_r",
                )

                x_ref_local = x_ref - xs
                y_ref_local = y_ref - ys
                iax.plot(x_ref_local, y_ref_local, marker="+", markersize=10, color="black")

                if c is not None and cx_local is not None and cy_local is not None:
                    iax.plot(cx_local, cy_local, marker="+", markersize=10, color="lime")

                iax.set_xticks([])
                iax.set_yticks([])
                iax.set_facecolor("black")
                for spine in iax.spines.values():
                    spine.set_edgecolor("cyan")
                    spine.set_linewidth(0.5)

            else:
                txt = ax.text(
                    0.02, 0.98,
                    "No locked reference",
                    transform=ax.transAxes,
                    ha="left", va="top",
                    color="w",
                    bbox=dict(facecolor="black", alpha=0.45, edgecolor="none", pad=3),
                )
                self.overlay_artists.append(txt)

            fn = os.path.basename(path)
            small = ax.text(
                0.02, 0.02, fn,
                transform=ax.transAxes,
                ha="left", va="bottom",
                color="w",
                fontsize=7,
                bbox=dict(facecolor="black", alpha=0.35, edgecolor="none", pad=2),
            )
            self.overlay_artists.append(small)

        self.fig.tight_layout(pad=2.0)
        self.canvas.draw_idle()
        self._update_status()

    def run(self):
        self.win.mainloop()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="../../DATA/GFADATA/img", help="GFA camera directory")
    ap.add_argument("--date", required=True, help="YYYYMMDD, e.g. 20260126")
    ap.add_argument("--interval", type=float, default=2.0, help="Polling interval in seconds")
    ap.add_argument(
        "--cameras",
        default="40103834,40103651,40103667,40103833,40103663,40103831",
        help="Comma-separated camera serials (order shown). Default uses your list.",
    )
    args = ap.parse_args()

    cams = [c.strip() for c in args.cameras.split(",") if c.strip()]
    if len(cams) != 6:
        raise SystemExit("Please provide exactly 6 camera serials in --cameras")

    viewer = FitsLiveViewer(
        root_dir=os.path.abspath(args.root),
        folder_name="raw",
        date_yyyymmdd=args.date,
        camera_serials=cams,
        poll_sec=args.interval,
    )
    viewer.run()


if __name__ == "__main__":
    main()
