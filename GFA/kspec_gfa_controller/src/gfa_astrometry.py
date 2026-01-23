# NOTE: 아래는 "네가 붙여준 최신 astrometry class"에
#   1) .corr들을 모아 combined_star.fits를 만드는 로직(star_catalog generation)
#   2) preproc 후/또는 field 변경 시 갱신하도록 호출
#   3) solve-field의 --corr 인자 파싱 꼬임 방지(= flag만 사용)
#   4) 이번 실행에서 생성된 corr만 모아 combined_star.fits 생성(더 안전)
#   5) star_catalog="img/star_catalog" 디렉토리면 그 안에 combined_star.fits 저장
# + 이번 요청 반영:
#   A) solve-field 경로 로그 중복 제거(캐시 + 변경될 때만 1회 로그)
#   B) "환경/경로" 로그 정리(중복 최소화)
#   C) astro 재사용 시 세션 검증(A안): astro FITS 헤더에 RA/DEC 기록 + 재사용 전 RA/DEC 일치 검사
#   D) raw 삭제 로깅 문구 정리(astro는 외부 삭제)
#
import os
import sys
import time
import json
import glob
import shutil
import subprocess
import logging
from typing import Optional, List, Union, Tuple
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
from astropy.io import fits
from astropy.table import Table, vstack
from astropy.coordinates import SkyCoord
import astropy.units as u

DEFAULT_SOLVE_FIELD = "/home/yyoon/astrometry/bin/solve-field"


def _get_solve_field_path(env: Optional[dict] = None) -> str:
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

    return str(sp)


def _get_default_config_path() -> str:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    default_path = os.path.join(script_dir, "etc", "astrometry_params.json")
    if not os.path.isfile(default_path):
        raise FileNotFoundError(f"Default config file not found at: {default_path}")
    return default_path


def _get_default_logger() -> logging.Logger:
    logger = logging.getLogger("gfa_astrometry_default")
    # ✅ 중복 핸들러 방지 + propagate 끄기(상위 로거 중복 출력 방지)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        logger.propagate = False
        h = logging.StreamHandler(sys.stdout)
        fmt = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S"
        )
        h.setFormatter(fmt)
        logger.addHandler(h)
    return logger


class GFAAstrometry:
    def __init__(self, config: str = None, logger: logging.Logger = None):
        if config is None:
            config = _get_default_config_path()
        if logger is None:
            logger = _get_default_logger()

        self.logger = logger
        self.logger.info("Initializing gfa_astrometry class.")

        with open(config, "r") as f:
            self.inpar = json.load(f)

        base_dir = os.path.abspath(os.path.dirname(__file__))

        # raw / temp / final(astrometry outputs) only
        self.dir_path = os.path.join(base_dir, self.inpar["paths"]["directories"]["raw_images"])
        self.temp_dir = os.path.join(base_dir, self.inpar["paths"]["directories"]["temp_files"])
        self.final_astrometry_dir = os.path.join(
            base_dir, self.inpar["paths"]["directories"]["final_astrometry_images"]
        )

        # ✅ star_catalog는 "디렉토리" 또는 "파일 경로" 둘 다 가능하게 처리
        star_catalog_root = os.path.join(base_dir, self.inpar["paths"]["directories"]["star_catalog"])
        if star_catalog_root.lower().endswith(".fits"):
            self.combined_star_path = star_catalog_root
            self.star_catalog_dir = os.path.dirname(star_catalog_root)
        else:
            self.star_catalog_dir = star_catalog_root
            self.combined_star_path = os.path.join(self.star_catalog_dir, "combined_star.fits")

        os.makedirs(self.dir_path, exist_ok=True)
        os.makedirs(self.temp_dir, exist_ok=True)
        os.makedirs(self.final_astrometry_dir, exist_ok=True)
        os.makedirs(self.star_catalog_dir, exist_ok=True)

        # ✅ 로그 정리: Paths는 1회만 깔끔히
        self.logger.info("Paths:")
        self.logger.info(f"  raw_images        = {self.dir_path}")
        self.logger.info(f"  temp_files        = {self.temp_dir}")
        self.logger.info(f"  final_astrometry  = {self.final_astrometry_dir}")
        self.logger.info(f"  star_catalog_dir  = {self.star_catalog_dir}")
        self.logger.info(f"  combined_star.fits= {self.combined_star_path}")

        self._subprocess_env: Optional[dict] = None

        # ✅ solve-field path 캐시(바뀔 때만 로그)
        self._solve_field_path: Optional[str] = None
        self._solve_field_key: Optional[str] = None
        self._resolve_solve_field_path(log=True)

        # ✅ 세션 검증 tolerance(arcsec). 필요하면 config로 빼도 됨.
        self._session_radec_tol_arcsec = 30.0

    def set_subprocess_env(self, env: dict) -> None:
        self._subprocess_env = env
        # env가 바뀌었을 수 있으니 solve-field도 갱신(바뀌면만 로그)
        self._resolve_solve_field_path(log=True)

    def _get_subprocess_env(self) -> dict:
        return self._subprocess_env if self._subprocess_env is not None else os.environ.copy()

    # -------------------------------
    # ✅ solve-field path resolve + 중복 로그 방지
    # -------------------------------
    def _resolve_solve_field_path(self, log: bool = False) -> str:
        env = self._get_subprocess_env()
        key = str(env.get("ASTROMETRY_SOLVE_FIELD") or os.environ.get("ASTROMETRY_SOLVE_FIELD") or DEFAULT_SOLVE_FIELD).strip()
        if (self._solve_field_path is None) or (self._solve_field_key != key):
            p = _get_solve_field_path(env=env)
            self._solve_field_path = p
            self._solve_field_key = key
            if log:
                self.logger.debug(f"Using solve-field: {p}")
        return self._solve_field_path

    # -------------------------------
    # ✅ RA/DEC raw header 읽기
    # -------------------------------
    def _read_radec_from_header(self, fits_path: str) -> Tuple[str, str]:
        with fits.open(fits_path, mode="readonly", memmap=True) as hdul:
            hdr = hdul[0].header
            ra = hdr.get("RA")
            dec = hdr.get("DEC")

        if ra is None or dec is None:
            raise KeyError(f"RA/DEC header missing in: {fits_path}")
        return str(ra), str(dec)

    # -------------------------------
    # ✅ RA/DEC 파싱(문자열/도 단위 혼합 대응)
    # -------------------------------
    def _parse_radec_to_deg(self, ra: Union[str, float], dec: Union[str, float]) -> Tuple[float, float]:
        # 1) 숫자면 degree로 취급
        try:
            ra_f = float(ra)
            dec_f = float(dec)
            return ra_f, dec_f
        except Exception:
            pass

        ra_s = str(ra).strip()
        dec_s = str(dec).strip()

        # 2) sexagesimal 가능성: RA는 hourangle 우선, 실패하면 deg로
        try:
            c = SkyCoord(ra_s, dec_s, unit=(u.hourangle, u.deg), frame="icrs")
            return float(c.ra.deg), float(c.dec.deg)
        except Exception:
            c = SkyCoord(ra_s, dec_s, unit=(u.deg, u.deg), frame="icrs")
            return float(c.ra.deg), float(c.dec.deg)

    def _angular_sep_arcsec(self, ra1, dec1, ra2, dec2) -> float:
        r1, d1 = self._parse_radec_to_deg(ra1, dec1)
        r2, d2 = self._parse_radec_to_deg(ra2, dec2)
        c1 = SkyCoord(r1 * u.deg, d1 * u.deg, frame="icrs")
        c2 = SkyCoord(r2 * u.deg, d2 * u.deg, frame="icrs")
        return float(c1.separation(c2).arcsec)

    # -------------------------------
    # ✅ astro 재사용 세션 검증:
    #   - astro_*.fits 헤더의 RA/DEC vs 현재 raw(또는 input_files) RA/DEC
    # -------------------------------
    def _get_reference_radec_from_inputs(
        self, input_files: Optional[List[Union[str, Path]]] = None
    ) -> Optional[Tuple[str, str]]:
        if input_files is None:
            cand = sorted(glob.glob(os.path.join(self.dir_path, "*.fits")))
        else:
            cand = [os.path.abspath(str(f)) for f in input_files]
        if not cand:
            return None
        return self._read_radec_from_header(cand[0])

    def _get_reference_radec_from_astro_outputs(self, astro_files: List[str]) -> Optional[Tuple[str, str]]:
        if not astro_files:
            return None
        fp = astro_files[0]
        try:
            with fits.open(fp, mode="readonly", memmap=True) as hdul:
                hdr = hdul[0].header
                ra = hdr.get("RA")
                dec = hdr.get("DEC")
            if ra is None or dec is None:
                return None
            return str(ra), str(dec)
        except Exception:
            return None

    def _delete_astro_outputs(self) -> int:
        # 외부에서 지워지긴 하지만, "세션 mismatch"일 때는 내부에서도 섞임 방지용으로 지워준다.
        cnt = 0
        for p in glob.glob(os.path.join(self.final_astrometry_dir, "astro_*.fits")):
            try:
                os.remove(p)
                cnt += 1
            except Exception:
                pass
        return cnt

    # -------------------------------
    # ✅ .corr -> vstack -> combined_star.fits 생성
    # -------------------------------
    def build_combined_star_from_corr(
        self,
        corr_files: Optional[List[str]] = None,
        corr_glob: str = "**/*.corr",
        min_rows: int = 1,
        cleanup: bool = False,
    ) -> str:
        out_path = self.combined_star_path
        os.makedirs(os.path.dirname(out_path), exist_ok=True)

        if corr_files is None:
            corr_files = sorted(glob.glob(os.path.join(self.temp_dir, corr_glob), recursive=True))

        self.logger.info(f"Building combined star catalog from .corr files: found {len(corr_files)} files.")
        self.logger.info(f"combined_star.fits output will be: {out_path}")

        if not corr_files:
            raise FileNotFoundError(
                f"No .corr files found. temp_dir={self.temp_dir}, pattern={corr_glob}\n"
                f"→ solve-field가 실제로 .corr을 만들었는지/출력 경로가 맞는지 확인 필요."
            )

        tables: List[Table] = []
        bad: List[str] = []

        for fp in corr_files:
            try:
                if not os.path.exists(fp):
                    bad.append(fp)
                    self.logger.warning(f"corr missing (skip): {fp}")
                    continue

                with fits.open(fp, memmap=True) as hdul:
                    if len(hdul) < 2 or hdul[1].data is None:
                        raise ValueError("No table found in HDU[1].")
                    tables.append(Table(hdul[1].data))
            except Exception as e:
                bad.append(fp)
                self.logger.warning(f"Failed reading corr={fp}: {e}")

        if not tables:
            raise RuntimeError(f"All .corr files failed to read. bad(sample)={bad[:10]}")

        combined = vstack(tables, metadata_conflicts="silent")
        combined.write(out_path, overwrite=True)

        nrows = len(combined)
        if nrows < int(min_rows):
            self.logger.warning(f"combined_star.fits created but has very few rows: N={nrows}")

        self.logger.info(f"✅ combined_star.fits created: {out_path} (N={nrows})")

        if cleanup:
            for fp in corr_files:
                try:
                    os.remove(fp)
                except Exception:
                    pass

        return out_path

    # -------------------------------
    # ✅ solve-field 실행 (파일별 독립 작업폴더)
    # + astro FITS 헤더에 RA/DEC 기록(세션 검증용)
    # -------------------------------
    def astrometry_raw(self, raw_fits_path: str) -> Tuple[float, float, str, str]:
        env = self._get_subprocess_env()
        solve_field_path = self._resolve_solve_field_path(log=False)

        scale_low, scale_high = self.inpar["astrometry"]["scale_range"]
        radius = self.inpar["astrometry"]["radius"]
        cpu_limit = self.inpar["settings"]["cpu"]["limit"]

        raw_fits_path = os.path.abspath(raw_fits_path)
        if not os.path.exists(raw_fits_path):
            raise FileNotFoundError(f"Raw FITS not found: {raw_fits_path}")

        ra_in, dec_in = self._read_radec_from_header(raw_fits_path)

        base = os.path.basename(raw_fits_path)
        stem = Path(base).stem

        work_dir = os.path.join(self.temp_dir, stem)
        os.makedirs(work_dir, exist_ok=True)

        outbase = stem
        corr_path = os.path.join(work_dir, f"{outbase}.corr")
        new_path = os.path.join(work_dir, f"{outbase}.new")

        cmd = [
            solve_field_path,
            raw_fits_path,
            "-D", work_dir,
            "-o", outbase,
            "--overwrite",
            "--corr", corr_path,
            "--no-plots",
            "--no-verify",
            "--crpix-center",
            "-X", "X",
            "-Y", "Y",
            "-s", "FLUX",
            "--scale-units", "degwidth",
            "-L", str(scale_low),
            "-H", str(scale_high),
            "--ra", str(ra_in),
            "--dec", str(dec_in),
            "--radius", str(radius),
            "-l", "120",
            "-c", "0.1",
            "-E", "2",
            "--cpulimit", str(cpu_limit),
        ]

        self.logger.info(f"[{stem}] Running command: {' '.join(cmd)}")

        p = subprocess.run(cmd, capture_output=True, text=True, env=env)

        self.logger.info(f"[{stem}] solve-field returncode={p.returncode}")
        if p.stdout:
            self.logger.debug(f"[{stem}] solve-field stdout:\n{p.stdout}")
        if p.stderr:
            self.logger.debug(f"[{stem}] solve-field stderr:\n{p.stderr}")

        if not os.path.exists(new_path):
            try:
                listing = sorted(os.listdir(work_dir))[:80]
            except Exception:
                listing = []

            raise RuntimeError(
                f"[{stem}] solve-field FAILED: .new file not created.\n"
                f"  raw_fits={raw_fits_path}\n"
                f"  work_dir={work_dir}\n"
                f"  returncode={p.returncode}\n"
                f"  files(sample)={listing}\n"
                f"  stderr(tail)=\n{(p.stderr or '')[-2000:]}"
            )

        if p.returncode != 0:
            self.logger.warning(
                f"[{stem}] solve-field returncode != 0 but .new exists. "
                f"Continuing. returncode={p.returncode}"
            )

        try:
            listing = sorted(os.listdir(work_dir))
        except Exception:
            listing = []

        if os.path.exists(corr_path):
            self.logger.info(f"[{stem}] ✅ corr produced: {corr_path}")
        else:
            self.logger.warning(
                f"[{stem}] ⚠️ corr NOT found where expected: {corr_path}\n"
                f"  work_dir listing(sample)={listing[:50]}"
            )

        out_fits_name = f"astro_{stem}.fits"
        out_fits_path = os.path.join(self.final_astrometry_dir, out_fits_name)

        if os.path.exists(out_fits_path):
            os.remove(out_fits_path)

        os.rename(new_path, out_fits_path)

        # ✅ astro FITS 헤더에 "이 astrometry가 어떤 입력(RA/DEC)으로 생성됐는지" 기록
        #    (헤더 키는 요청대로 RA, DEC 사용)
        try:
            with fits.open(out_fits_path, mode="update", memmap=False) as hdul:
                hdr = hdul[0].header
                hdr["RA"] = (str(ra_in), "Input RA used for astrometry (session key)")
                hdr["DEC"] = (str(dec_in), "Input DEC used for astrometry (session key)")
                hdul.flush()
        except Exception as e:
            self.logger.warning(f"[{stem}] Failed to write RA/DEC into astro header: {e}")

        try:
            _, hdr = fits.getdata(out_fits_path, ext=0, header=True)
            crval1 = float(hdr["CRVAL1"])
            crval2 = float(hdr["CRVAL2"])
        except Exception as e:
            raise RuntimeError(
                f"[{stem}] .new existed but failed to read CRVAL1/CRVAL2 after rename.\n"
                f"  out_fits_path={out_fits_path}\n"
                f"  error={e}"
            ) from e

        self.logger.info(f"[{stem}] Astrometry done. CRVAL1={crval1}, CRVAL2={crval2}")
        return crval1, crval2, out_fits_path, corr_path

    def rm_tempfiles(self):
        self.logger.info("Removing temporary files.")
        try:
            shutil.rmtree(self.temp_dir)
            os.makedirs(self.temp_dir, exist_ok=True)
            self.logger.debug(f"Temporary files removed from {self.temp_dir}.")
        except Exception as e:
            self.logger.error(f"Error removing temporary files: {e}")

    # -------------------------------------------------------------------------
    # ✅ procimg 없이 "astrometry inputs" 확보 (astro dir 있으면 사용 / 없으면 생성)
    # + astro 재사용 시 RA/DEC 세션 검증(A안)
    # -------------------------------------------------------------------------
    def ensure_astrometry_ready(
        self,
        input_files: Optional[List[Union[str, Path]]] = None,
        force: bool = False,
        run_missing_only: bool = True,
        build_star_catalog: bool = True,
        star_catalog_force: bool = False,
        fallback_glob_on_empty_corr_ok: bool = True,
    ) -> List[str]:
        os.makedirs(self.final_astrometry_dir, exist_ok=True)
        os.makedirs(self.star_catalog_dir, exist_ok=True)

        existing_outputs = sorted(glob.glob(os.path.join(self.final_astrometry_dir, "astro_*.fits")))

        # ✅ 재사용 경로: existing astro가 있고 force=False일 때
        if existing_outputs and not force:
            # --- 세션 검증 (A안): astro header RA/DEC vs current raw/input RA/DEC ---
            cur_radec = self._get_reference_radec_from_inputs(input_files=input_files)
            astro_radec = self._get_reference_radec_from_astro_outputs(existing_outputs)

            if cur_radec is not None and astro_radec is not None:
                sep_arcsec = self._angular_sep_arcsec(cur_radec[0], cur_radec[1], astro_radec[0], astro_radec[1])
                if sep_arcsec > float(self._session_radec_tol_arcsec):
                    self.logger.info(
                        "Astrometry outputs exist but session RA/DEC mismatch → re-running astrometry.\n"
                        f"  current RA/DEC = ({cur_radec[0]}, {cur_radec[1]})\n"
                        f"  astro   RA/DEC = ({astro_radec[0]}, {astro_radec[1]})\n"
                        f"  separation     = {sep_arcsec:.2f} arcsec (tol={self._session_radec_tol_arcsec:.1f})"
                    )
                    # 섞임 방지: 기존 astro 제거 후 강제 재생성
                    deleted = self._delete_astro_outputs()
                    self.logger.info(f"Deleted {deleted} old astro outputs before re-run.")
                    force = True  # 아래 로직으로 내려가서 preproc 수행
                else:
                    self.logger.info(
                        f"Astrometry directory has outputs → reusing (session OK, sep={sep_arcsec:.2f} arcsec)."
                    )
                    if build_star_catalog and star_catalog_force:
                        self.logger.info(
                            "star_catalog_force=True → rebuilding combined_star.fits from existing corr under temp_dir"
                        )
                        try:
                            self.build_combined_star_from_corr(corr_files=None)
                        except Exception as e:
                            self.logger.warning(f"Star catalog build skipped/failed: {e}")

                    self.logger.info(f"combined_star expected at: {self.combined_star_path}")
                    self.logger.info(f"combined_star exists? {os.path.exists(self.combined_star_path)}")
                    return existing_outputs
            else:
                # raw/input이 없거나 astro에 RA/DEC가 없으면 보수적으로 재사용(로그만 남김)
                why = []
                if cur_radec is None:
                    why.append("current RA/DEC unavailable (no input/raw)")
                if astro_radec is None:
                    why.append("astro RA/DEC missing in header")
                self.logger.info(
                    "Astrometry directory has outputs → reusing (session check skipped: "
                    + ", ".join(why)
                    + ")."
                )
                if build_star_catalog and star_catalog_force:
                    self.logger.info(
                        "star_catalog_force=True → rebuilding combined_star.fits from existing corr under temp_dir"
                    )
                    try:
                        self.build_combined_star_from_corr(corr_files=None)
                    except Exception as e:
                        self.logger.warning(f"Star catalog build skipped/failed: {e}")

                self.logger.info(f"combined_star expected at: {self.combined_star_path}")
                self.logger.info(f"combined_star exists? {os.path.exists(self.combined_star_path)}")
                return existing_outputs

        # ✅ 여기부터는: outputs 없거나(force=True 포함) → preproc 실행
        self.logger.info("Astrometry outputs missing or force=True → running astrometry preprocessing...")

        results, corr_ok = self.preproc(
            input_files=input_files,
            force=force,
            run_missing_only=run_missing_only,
        )

        existing_outputs = sorted(glob.glob(os.path.join(self.final_astrometry_dir, "astro_*.fits")))
        if not existing_outputs:
            raise RuntimeError(
                f"Astrometry expected outputs not found in {self.final_astrometry_dir} (astro_*.fits)"
            )

        if build_star_catalog:
            try:
                if corr_ok:
                    self.logger.info(f"Building combined_star.fits from this run corr_ok={len(corr_ok)} files")
                    self.build_combined_star_from_corr(corr_files=corr_ok)
                else:
                    msg = "No corr_ok collected from this run."
                    if fallback_glob_on_empty_corr_ok:
                        msg += " Falling back to glob temp_dir for any existing corr."
                    self.logger.warning(msg)

                    if fallback_glob_on_empty_corr_ok:
                        self.build_combined_star_from_corr(corr_files=None)
            except Exception as e:
                self.logger.warning(f"Star catalog build skipped/failed: {e}")

        self.logger.info(f"combined_star expected at: {self.combined_star_path}")
        self.logger.info(f"combined_star exists? {os.path.exists(self.combined_star_path)}")

        return existing_outputs

    def preproc(
        self,
        input_files: Optional[List[Union[str, Path]]] = None,
        force: bool = False,
        run_missing_only: bool = True,
    ) -> Tuple[List[Tuple[float, float, str, str]], List[str]]:
        start = time.time()

        if input_files is None:
            input_paths = sorted(glob.glob(os.path.join(self.dir_path, "*.fits")))
        else:
            input_paths = [os.path.abspath(str(f)) for f in input_files]

        if not input_paths:
            self.logger.warning("No FITS files provided or found.")
            return [], []

        os.makedirs(self.final_astrometry_dir, exist_ok=True)

        existing_outputs = sorted(glob.glob(os.path.join(self.final_astrometry_dir, "astro_*.fits")))
        astro_dir_empty = (len(existing_outputs) == 0)

        to_run: List[str] = []

        if force:
            self.logger.info("force=True → running astrometry for ALL files.")
            to_run = input_paths
        else:
            if astro_dir_empty:
                self.logger.info("No astrometry results found (astro dir empty) → running FULL astrometry.")
                to_run = input_paths
            else:
                if not run_missing_only:
                    self.logger.info("Astrometry results already exist and run_missing_only=False → skipping astrometry.")
                    return [], []

                existing_set = set(os.path.basename(p) for p in existing_outputs)

                for raw_path in input_paths:
                    stem = Path(os.path.basename(raw_path)).stem
                    expected = f"astro_{stem}.fits"
                    if expected not in existing_set:
                        to_run.append(raw_path)

                if to_run:
                    self.logger.info(f"Astrometry results exist → running ONLY missing outputs: {len(to_run)} files.")
                else:
                    self.logger.info("All expected astrometry outputs already exist → nothing to do.")
                    return [], []

        cpu_limit = int(self.inpar["settings"]["cpu"]["limit"])
        max_workers = max(1, min(cpu_limit, len(to_run)))

        failed: List[str] = []
        results: List[Tuple[float, float, str, str]] = []
        corr_ok: List[str] = []

        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futs = {ex.submit(self.astrometry_raw, p): p for p in to_run}
            for fut in as_completed(futs):
                path = futs[fut]
                try:
                    cr1, cr2, astro_path, corr_path = fut.result()
                    results.append((cr1, cr2, astro_path, corr_path))
                    if corr_path and os.path.exists(corr_path):
                        corr_ok.append(corr_path)
                except Exception as e:
                    self.logger.error(f"Error processing {os.path.basename(path)}: {e}")
                    failed.append(path)

        if failed:
            self.logger.warning(f"{len(failed)} files failed: {[os.path.basename(x) for x in failed]}")

        self.logger.info(
            f"Preprocessing(astrometry) completed in {time.time() - start:.2f} seconds. "
            f"(ok={len(results)}, failed={len(failed)}, corr_ok={len(corr_ok)})"
        )
        return results, corr_ok

    # ✅ raw만 삭제(astro는 외부에서 자동 삭제)
    def clear_raw_files(self) -> None:
        self.logger.info("Deleting raw files.")
        deleted_raw = self.delete_all_files_in_dir(self.dir_path)
        self.logger.info(f"Deleted {deleted_raw} raw files.")

    def delete_all_files_in_dir(self, dir_path: str) -> int:
        if not os.path.isdir(dir_path):
            self.logger.warning(f"Directory not found: {dir_path}")
            return 0

        cnt = 0
        for p in glob.glob(os.path.join(dir_path, "*")):
            try:
                if os.path.isfile(p) or os.path.islink(p):
                    os.remove(p)
                    cnt += 1
            except Exception as e:
                self.logger.error(f"Failed to delete {p}: {e}")
        return cnt
