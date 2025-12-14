#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# @Author: Mingyeong Yang
# @Filename: gfa_getcrval.py
#
# Independent pointing-oriented utility:
# Given a FITS image with RA/DEC in header, run astrometry.net (solve-field)
# and return CRVAL1/CRVAL2 from the solved WCS.

from __future__ import annotations

import os
import json
import glob
import shutil
import tempfile
import subprocess
import logging
from typing import Optional, Tuple, Union
from pathlib import Path

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple, Union, Optional
from pathlib import Path
import math

from astropy.io import fits

# Optional reuse from gfa_astrometry.py (config path / logger)
try:
    from gfa_astrometry import _get_default_config_path, _get_default_logger
except Exception:
    _get_default_config_path = None
    _get_default_logger = None


def _load_config(config: Optional[Union[str, Path]]) -> dict:
    """
    Load JSON config.
    If config is None and gfa_astrometry._get_default_config_path exists, use it.
    Otherwise, raise ValueError.
    """
    if config is None:
        if _get_default_config_path is None:
            raise ValueError(
                "config is None but gfa_astrometry._get_default_config_path is not available. "
                "Please pass config path explicitly."
            )
        config = _get_default_config_path()

    config = str(config)
    with open(config, "r") as f:
        return json.load(f)


def _get_logger(logger: Optional[logging.Logger]) -> logging.Logger:
    if logger is not None:
        return logger
    if _get_default_logger is not None:
        return _get_default_logger()

    # Fallback minimal logger
    lg = logging.getLogger("gfa_getcrval")
    if not lg.handlers:
        lg.setLevel(logging.INFO)
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s"))
        lg.addHandler(h)
    return lg


def _read_ra_dec(image_path: Union[str, Path]) -> Tuple[float, float]:
    """
    Read RA/DEC from FITS header.
    Raises KeyError / ValueError if missing.
    """
    with fits.open(str(image_path)) as hdul:
        hdr = hdul[0].header

    ra = hdr.get("RA", None)
    dec = hdr.get("DEC", None)

    if ra is None or dec is None:
        raise ValueError(f"RA/DEC is None in header: {image_path}")

    # Some FITS store RA/DEC as strings; try float conversion.
    try:
        ra_f = float(ra)
        dec_f = float(dec)
    except Exception as e:
        raise ValueError(f"RA/DEC not convertible to float (RA={ra}, DEC={dec})") from e

    return ra_f, dec_f


def get_crval_from_image(
    image_path: Union[str, Path],
    config: Optional[Union[str, Path]] = None,
    logger: Optional[logging.Logger] = None,
    work_dir: Optional[Union[str, Path]] = None,
    keep_work_dir: bool = False,
) -> Tuple[float, float]:
    """
    Pointing-oriented function:
    Given a FITS image (with RA/DEC in header), run solve-field and return (CRVAL1, CRVAL2).

    Parameters
    ----------
    image_path : str or Path
        Input FITS image path. Must contain RA/DEC in header.
    config : str or Path, optional
        JSON config path (can reuse the same astrometry_params.json structure used by gfa_astrometry).
        If None, tries gfa_astrometry._get_default_config_path().
    logger : logging.Logger, optional
        Logger. If None, tries gfa_astrometry._get_default_logger().
    work_dir : str or Path, optional
        Directory for solve-field outputs. If None, a temporary directory is created.
    keep_work_dir : bool
        If True, do not delete temporary outputs.

    Returns
    -------
    (crval1, crval2) : tuple[float, float]
    """

    lg = _get_logger(logger)
    image_path = Path(image_path)

    if not image_path.exists():
        raise FileNotFoundError(f"Input FITS not found: {image_path}")

    # Ensure solve-field exists
    solve_field_path = shutil.which("solve-field")
    if not solve_field_path:
        raise FileNotFoundError("solve-field not found! Please install astrometry.net and ensure it is in PATH.")

    # Load config for astrometry parameters
    inpar = _load_config(config)

    # Read RA/DEC from header (required by your spec)
    ra_in, dec_in = _read_ra_dec(image_path)

    # Work dir
    tmp_created = False
    if work_dir is None:
        work_dir = Path(tempfile.mkdtemp(prefix="gfa_getcrval_"))
        tmp_created = True
    else:
        work_dir = Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Parameters (keep consistent with your gfa_astrometry style)
        scale_low, scale_high = inpar["astrometry"]["scale_range"]
        radius = inpar["astrometry"]["radius"]
        cpu_limit = inpar["settings"]["cpu"]["limit"]

        # Build command
        # Note: using the original image directly (no preproc) because this module is independent.
        cmd = (
            f"{solve_field_path} "
            f"--cpulimit {cpu_limit} "
            f"--dir {str(work_dir)} "
            f"--scale-units degwidth --scale-low {scale_low} --scale-high {scale_high} "
            f"--no-verify --no-plots --crpix-center -O "
            f"--ra {ra_in} --dec {dec_in} --radius {radius} "
            f"{str(image_path)}"
        )

        lg.info(f"solve-field on: {image_path.name}")
        lg.debug(f"Command: {cmd}")

        try:
            subprocess.run(cmd, shell=True, capture_output=True, text=True, check=True)
        except subprocess.CalledProcessError as e:
            lg.error("solve-field failed.")
            lg.error(f"stderr:\n{e.stderr}")
            raise RuntimeError(f"solve-field execution failed for {image_path}") from e

        # solve-field output naming: <basename>.new in work_dir (commonly)
        base = image_path.name
        new_pat = str(work_dir / base.replace(".fits", ".new"))
        new_files = glob.glob(new_pat)

        # Some FITS may use .fit or uppercase; fallback to glob by stem:
        if not new_files:
            new_files = glob.glob(str(work_dir / (image_path.stem + ".new")))

        if not new_files:
            # Provide directory listing for debugging
            listing = sorted(os.listdir(work_dir))
            raise FileNotFoundError(
                f"Solved .new file not found in {work_dir}. "
                f"Expected like: {new_pat}. "
                f"Files: {listing}"
            )

        solved_path = Path(new_files[0])

        # .new is a FITS file; we can read header directly.
        with fits.open(str(solved_path)) as hdul:
            hdr = hdul[0].header
            crval1 = float(hdr["CRVAL1"])
            crval2 = float(hdr["CRVAL2"])

        lg.info(f"CRVAL1={crval1}, CRVAL2={crval2}")
        return crval1, crval2

    finally:
        # Cleanup temporary dir if created here and not requested to keep
        if (tmp_created or (work_dir is not None)) and (not keep_work_dir):
            # If user passed work_dir explicitly, we still respect keep_work_dir=False and clean it.
            # If you prefer "only delete when we created it", change condition accordingly.
            try:
                shutil.rmtree(str(work_dir), ignore_errors=True)
            except Exception:
                pass


def get_crvals_from_images(
    image_paths: List[Union[str, Path]],
    config: Optional[Union[str, Path]] = None,
    logger: Optional[logging.Logger] = None,
    max_workers: int = 4,
    keep_work_dir: bool = False,
) -> Tuple[List[float], List[float]]:
    """
    여러 FITS 이미지에 대해 (CRVAL1, CRVAL2) 리스트를 반환.
    - 병렬 실행(ThreadPoolExecutor)
    - 입력 순서 유지
    - 실패한 항목은 NaN으로 채움

    Parameters
    ----------
    image_paths : list[str|Path]
        입력 FITS 경로들 (각 파일 헤더에 RA/DEC 있어야 함)
    max_workers : int
        동시에 돌릴 solve-field 개수 (권장: 2~4부터)
    """

    lg = _get_logger(logger)

    # 입력 순서 유지용
    image_paths = [Path(p) for p in image_paths]
    n = len(image_paths)

    cr1 = [float("nan")] * n
    cr2 = [float("nan")] * n

    def _one(i: int, p: Path):
        c1, c2 = get_crval_from_image(
            p,
            config=config,
            logger=lg,
            work_dir=None,          # 각 작업이 자체 tempdir 사용
            keep_work_dir=keep_work_dir,
        )
        return i, c1, c2

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(_one, i, p) for i, p in enumerate(image_paths)]
        for fut in as_completed(futures):
            try:
                i, c1, c2 = fut.result()
                cr1[i] = c1
                cr2[i] = c2
            except Exception as e:
                # 해당 항목은 NaN 유지
                lg.error(f"Failed: {e}")

    return cr1, cr2
