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
import time
import uuid
from typing import Optional, Tuple, Union, List
from pathlib import Path

from concurrent.futures import ThreadPoolExecutor, as_completed
from astropy.io import fits

# Optional reuse from gfa_astrometry.py (config path / logger)
try:
    from .gfa_astrometry import _get_default_config_path, _get_default_logger
except Exception:
    _get_default_config_path = None
    _get_default_logger = None


# -----------------------------------------------------------------------------
# ✅ FORCE solve-field path (ignore conda PATH/which)
# -----------------------------------------------------------------------------
DEFAULT_SOLVE_FIELD = "/home/yyoon/astrometry/bin/solve-field"


def _get_solve_field_path(lg: logging.Logger, env: Optional[dict] = None) -> str:
    """
    Always use fixed solve-field path by default (DEFAULT_SOLVE_FIELD),
    regardless of conda PATH.
    Optionally allow override via env var ASTROMETRY_SOLVE_FIELD.
    """
    p = None
    if env is not None:
        p = env.get("ASTROMETRY_SOLVE_FIELD")
    if not p:
        p = os.environ.get("ASTROMETRY_SOLVE_FIELD")

    solve_field = (p or DEFAULT_SOLVE_FIELD).strip()
    sp = Path(solve_field)

    if not sp.exists():
        raise FileNotFoundError(f"solve-field not found: {solve_field}")
    if not os.access(str(sp), os.X_OK):
        raise PermissionError(f"solve-field is not executable: {solve_field}")

    lg.debug("Using solve-field from (fixed): %s", solve_field)
    return str(sp)


# ----------------------------
# Logging helpers
# ----------------------------
class _JobAdapter(logging.LoggerAdapter):
    """
    Adds per-job context to log records.
    Usage: lg = _JobAdapter(base_logger, {"job": "abc123", "image": "foo.fits"})
    """
    def process(self, msg, kwargs):
        extra = kwargs.get("extra", {})
        extra = {**self.extra, **extra}
        kwargs["extra"] = extra
        return msg, kwargs


def _ensure_logger_has_handler(lg: logging.Logger) -> None:
    """
    Ensure the logger has at least one StreamHandler, and does not duplicate handlers.
    """
    if lg.handlers:
        return

    lg.setLevel(logging.INFO)  # default; can be overridden by user code

    h = logging.StreamHandler()
    fmt = (
        "[%(asctime)s] %(levelname)s "
        "(%(name)s) "
        "[job=%(job)s image=%(image)s] "
        "%(message)s"
    )
    h.setFormatter(logging.Formatter(fmt))
    lg.addHandler(h)

    # Provide default values so formatting won't crash if adapter not used somewhere
    old_factory = logging.getLogRecordFactory()

    def record_factory(*args, **kwargs):
        record = old_factory(*args, **kwargs)
        if not hasattr(record, "job"):
            record.job = "-"
        if not hasattr(record, "image"):
            record.image = "-"
        return record

    logging.setLogRecordFactory(record_factory)


def _get_logger(logger: Optional[logging.Logger]) -> logging.Logger:
    if logger is not None:
        _ensure_logger_has_handler(logger)
        return logger

    if _get_default_logger is not None:
        lg = _get_default_logger()
        _ensure_logger_has_handler(lg)
        return lg

    lg = logging.getLogger("gfa_getcrval")
    _ensure_logger_has_handler(lg)
    return lg


def _load_config(config: Optional[Union[str, Path]], lg: logging.Logger) -> dict:
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

    config = Path(str(config))
    lg.debug("Loading config: %s", config)

    if not config.exists():
        raise FileNotFoundError(f"Config not found: {config}")

    with config.open("r") as f:
        cfg = json.load(f)

    # Helpful: log key fields at INFO, full config at DEBUG (careful if secrets exist)
    try:
        ast = cfg.get("astrometry", {})
        cpu = cfg.get("settings", {}).get("cpu", {})
        lg.info(
            "Config summary: scale_range=%s radius=%s cpulimit=%s",
            ast.get("scale_range", None),
            ast.get("radius", None),
            cpu.get("limit", None),
        )
        lg.debug("Config full:\n%s", json.dumps(cfg, indent=2, sort_keys=True))
    except Exception:
        lg.debug("Config loaded (could not summarize keys safely).")

    return cfg


def _read_ra_dec(image_path: Union[str, Path], lg: logging.Logger) -> Tuple[str, str]:
    """
    Read RA/DEC from FITS header.
    Raises KeyError / ValueError if missing.
    """
    image_path = Path(image_path)
    lg.debug("Reading FITS header RA/DEC from: %s", image_path)

    with fits.open(str(image_path)) as hdul:
        hdr = hdul[0].header

    ra = hdr.get("RA", None)
    dec = hdr.get("DEC", None)

    if ra is None or dec is None:
        # log which keys exist to help debugging
        sample_keys = list(hdr.keys())[:50]
        lg.error("RA/DEC missing in header. First 50 header keys: %s", sample_keys)
        raise ValueError(f"RA/DEC is None in header: {image_path}")

    # Keep as strings for solve-field
    try:
        ra_s = str(ra).strip()
        dec_s = str(dec).strip()
    except Exception as e:
        lg.exception("Failed to convert RA/DEC to string. RA=%r DEC=%r", ra, dec)
        raise ValueError(f"RA/DEC not convertible to string (RA={ra}, DEC={dec})") from e

    lg.info("Header RA=%s DEC=%s", ra_s, dec_s)
    return ra_s, dec_s


def _list_dir(path: Path, limit: int = 200) -> List[str]:
    """
    Safe directory listing helper for error logs.
    """
    try:
        items = sorted(os.listdir(path))
        if len(items) > limit:
            return items[:limit] + [f"... ({len(items)-limit} more)"]
        return items
    except Exception:
        return ["<failed to list directory>"]


def _run_solve_field(
    cmd: str,
    lg: logging.Logger,
    timeout: Optional[int] = None,
    env: Optional[dict] = None,
) -> None:
    """
    Run solve-field with rich logging and good error reporting.
    """
    lg.debug("Executing solve-field command:\n%s", cmd)

    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            check=False,      # we handle returncode ourselves for better logs
            timeout=timeout,  # optional
            env=env,          # ✅ allow caller to control runtime env
        )
    except subprocess.TimeoutExpired as e:
        dt = time.perf_counter() - t0
        lg.error("solve-field TIMEOUT after %.3fs", dt)
        if getattr(e, "stdout", None):
            lg.error("stdout (partial):\n%s", e.stdout)
        if getattr(e, "stderr", None):
            lg.error("stderr (partial):\n%s", e.stderr)
        raise RuntimeError("solve-field timed out") from e
    except Exception:
        dt = time.perf_counter() - t0
        lg.exception("solve-field crashed after %.3fs (exception)", dt)
        raise

    dt = time.perf_counter() - t0
    lg.info("solve-field finished: rc=%s elapsed=%.3fs", proc.returncode, dt)

    if proc.stdout:
        lg.debug("solve-field stdout:\n%s", proc.stdout)
    if proc.stderr:
        lg.debug("solve-field stderr:\n%s", proc.stderr)

    if proc.returncode != 0:
        lg.error("solve-field failed (rc=%s). See stderr below.", proc.returncode)
        if proc.stderr:
            lg.error("stderr:\n%s", proc.stderr)
        raise RuntimeError(f"solve-field failed with return code {proc.returncode}")


def _find_solved_new_file(image_path: Path, work_dir: Path, lg: logging.Logger) -> Path:
    """
    Find .new output produced by solve-field.
    Logs all patterns tried and directory contents upon failure.
    """
    base = image_path.name

    patterns = []
    if base.lower().endswith(".fits"):
        patterns.append(str(work_dir / (base[:-5] + ".new")))
    elif base.lower().endswith(".fit"):
        patterns.append(str(work_dir / (base[:-4] + ".new")))
    else:
        patterns.append(str(work_dir / (image_path.stem + ".new")))

    patterns.append(str(work_dir / (image_path.stem + "*.new")))

    lg.debug("Searching for solved .new file with patterns: %s", patterns)

    found: List[str] = []
    for pat in patterns:
        found.extend(glob.glob(pat))

    found = sorted(set(found))
    if not found:
        listing = _list_dir(work_dir)
        lg.error("No .new file found in %s. Dir listing: %s", work_dir, listing)
        raise FileNotFoundError(
            f"Solved .new file not found in {work_dir}. Tried patterns={patterns}. "
            f"Files={listing}"
        )

    solved = Path(found[0])
    lg.info("Found solved file: %s", solved.name)
    lg.debug("All candidate .new files: %s", found)
    return solved


# ----------------------------
# Public API
# ----------------------------
def get_crval_from_image(
    image_path: Union[str, Path],
    config: Optional[Union[str, Path]] = None,
    logger: Optional[logging.Logger] = None,
    work_dir: Optional[Union[str, Path]] = None,
    keep_work_dir: bool = False,
    solve_field: Optional[Union[str, Path]] = None,
    subprocess_env: Optional[dict] = None,
) -> Tuple[float, float]:
    """
    Pointing-oriented function:
    Given a FITS image (with RA/DEC in header), run solve-field and return (CRVAL1, CRVAL2).

    - solve_field: optional explicit path (overrides everything)
    - subprocess_env: optional env for subprocess.run (if None, uses os.environ.copy()).
                     NOTE: even if you pass env, solve-field path is still forced unless
                     you override with solve_field or ASTROMETRY_SOLVE_FIELD env var.
    """
    base_logger = _get_logger(logger)

    image_path = Path(image_path)
    job_id = uuid.uuid4().hex[:8]
    lg = _JobAdapter(base_logger, {"job": job_id, "image": image_path.name})

    lg.info("Start get_crval_from_image")
    lg.debug(
        "Inputs: image_path=%s config=%s work_dir=%s keep_work_dir=%s",
        image_path,
        config,
        work_dir,
        keep_work_dir,
    )

    if not image_path.exists():
        lg.error("Input FITS does not exist: %s", image_path)
        raise FileNotFoundError(f"Input FITS not found: {image_path}")

    # env for subprocess
    env = subprocess_env if subprocess_env is not None else os.environ.copy()

    # ✅ choose solve-field path (fixed by default)
    if solve_field is not None:
        sf = Path(str(solve_field))
        if not sf.exists():
            raise FileNotFoundError(f"solve-field not found: {sf}")
        if not os.access(str(sf), os.X_OK):
            raise PermissionError(f"solve-field is not executable: {sf}")
        solve_field_path = str(sf)
        lg.debug("Using solve-field from (explicit): %s", solve_field_path)
    else:
        solve_field_path = _get_solve_field_path(lg, env=env)

    # Load config for astrometry parameters
    inpar = _load_config(config, lg)

    # Read RA/DEC from header
    ra_in, dec_in = _read_ra_dec(image_path, lg)

    # Work dir
    tmp_created = False
    if work_dir is None:
        work_dir = Path(tempfile.mkdtemp(prefix="gfa_getcrval_"))
        tmp_created = True
        lg.info("Created temp work_dir: %s", work_dir)
    else:
        work_dir = Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        lg.info("Using provided work_dir: %s", work_dir)

    t_all0 = time.perf_counter()
    try:
        # Parameters
        try:
            scale_low, scale_high = inpar["astrometry"]["scale_range"]
            radius = inpar["astrometry"]["radius"]
            cpu_limit = inpar["settings"]["cpu"]["limit"]
        except Exception as e:
            lg.exception("Config missing required keys for astrometry parameters.")
            raise KeyError(
                "Config missing required keys: astrometry.scale_range, astrometry.radius, settings.cpu.limit"
            ) from e

        lg.info(
            "Astrometry params: scale_low=%s scale_high=%s radius=%s cpulimit=%s",
            scale_low,
            scale_high,
            radius,
            cpu_limit,
        )

        # Build command
        cmd = (
            f"{solve_field_path} "
            f"--cpulimit {cpu_limit} "
            f"--dir {str(work_dir)} "
            f"--scale-units degwidth --scale-low {scale_low} --scale-high {scale_high} "
            f"--no-verify --no-plots --crpix-center -O "
            f"--ra {ra_in} --dec {dec_in} --radius {radius} "
            f"{str(image_path)}"
        )

        lg.info("Running solve-field")
        lg.debug("Running command: %s", cmd)

        _run_solve_field(cmd, lg, env=env)

        solved_path = _find_solved_new_file(image_path, work_dir, lg)

        with fits.open(str(solved_path)) as hdul:
            hdr = hdul[0].header
            try:
                crval1 = float(hdr["CRVAL1"])
                crval2 = float(hdr["CRVAL2"])
            except Exception:
                lg.exception("CRVAL1/CRVAL2 missing or invalid in solved header.")
                wcs_keys = [
                    k
                    for k in hdr.keys()
                    if "CRVAL" in k or "CTYPE" in k or "CD" in k or "CDELT" in k
                ]
                lg.error("Candidate WCS keys present: %s", wcs_keys[:80])
                raise

        lg.info("Result: CRVAL1=%s CRVAL2=%s", crval1, crval2)
        return crval1, crval2

    finally:
        dt_all = time.perf_counter() - t_all0
        lg.info("End get_crval_from_image (elapsed=%.3fs)", dt_all)

        if not keep_work_dir:
            try:
                lg.info(
                    "Cleaning up work_dir: %s (tmp_created=%s)", work_dir, tmp_created
                )
                shutil.rmtree(str(work_dir), ignore_errors=True)
            except Exception:
                lg.exception("Failed to remove work_dir: %s", work_dir)
        else:
            lg.info("Keeping work_dir: %s", work_dir)


def get_crvals_from_images(
    image_paths: List[Union[str, Path]],
    config: Optional[Union[str, Path]] = None,
    logger: Optional[logging.Logger] = None,
    max_workers: int = 4,
    keep_work_dir: bool = False,
    solve_field: Optional[Union[str, Path]] = None,
    subprocess_env: Optional[dict] = None,
) -> Tuple[List[float], List[float]]:
    """
    여러 FITS 이미지에 대해 (CRVAL1, CRVAL2) 리스트를 반환.
    - 병렬 실행(ThreadPoolExecutor)
    - 입력 순서 유지
    - 실패한 항목은 NaN으로 채움
    """
    base_logger = _get_logger(logger)
    lg = _JobAdapter(base_logger, {"job": "batch", "image": "-"})

    image_paths = [Path(p) for p in image_paths]
    n = len(image_paths)

    lg.info(
        "Start get_crvals_from_images: n=%s max_workers=%s keep_work_dir=%s",
        n,
        max_workers,
        keep_work_dir,
    )
    lg.debug("Image list:\n%s", "\n".join(str(p) for p in image_paths))

    cr1 = [float("nan")] * n
    cr2 = [float("nan")] * n

    def _one(i: int, p: Path):
        job_id = f"img{i:04d}_{uuid.uuid4().hex[:6]}"
        img_lg = _JobAdapter(base_logger, {"job": job_id, "image": p.name})
        img_lg.info("Submitting image %s/%s: %s", i + 1, n, p.name)

        c1, c2 = get_crval_from_image(
            p,
            config=config,
            logger=base_logger,
            work_dir=None,
            keep_work_dir=keep_work_dir,
            solve_field=solve_field,
            subprocess_env=subprocess_env,
        )
        img_lg.info("Done image %s/%s: CRVAL1=%s CRVAL2=%s", i + 1, n, c1, c2)
        return i, c1, c2

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(_one, i, p) for i, p in enumerate(image_paths)]

        for fut in as_completed(futures):
            try:
                i, c1, c2 = fut.result()
                cr1[i] = c1
                cr2[i] = c2
            except Exception as e:
                lg.error("Failed one image task: %r", e, exc_info=True)

    dt = time.perf_counter() - t0
    ok = sum(1 for x in cr1 if x == x)  # NaN check: NaN != NaN
    lg.info("End get_crvals_from_images: ok=%s/%s elapsed=%.3fs", ok, n, dt)

    return cr1, cr2


# Optional: quick CLI-style debug run
# if __name__ == "__main__":
#     import sys
#     logging.getLogger("gfa_getcrval").setLevel(logging.DEBUG)
#     c1, c2 = get_crval_from_image(sys.argv[1], config=sys.argv[2] if len(sys.argv) > 2 else None)
#     print(c1, c2)
