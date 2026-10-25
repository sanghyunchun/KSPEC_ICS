import numpy as np
from astropy.io import fits
from kspec_metrology.analysis import peakfind
from kspec_metrology.analysis.utils import com, dedupe_peaks_kdtree, measure_sigma
from kspec_metrology.analysis.utils import transform, focal2camera_coeff_comm, nearest_index_sorted
from kspec_metrology.logging.log import get_logger
from kspec_metrology.naming import image_path
from astropy.table import Table
from astropy.stats import sigma_clipped_stats


def findpeak(npeaks
            , data_dir='./MTL/data/'
            , head='test'
            , nexposure=1
            , threshold=1e3
            , boxsize=40
            , nwindow=40
            , mode="Raw"
            , x=None, y=None
            , predict=None
            , niter_max=10
            , niter_refine=2
            , niter_recenter=0
            , max_shift=None
            , finder='sep'
            , finder_opts=None
            , background='crop'
            , background_opts=None
            , sat_level=65000.
            , exclude=None
            , exclude_r=60
            , min_dist=40
            , ReturnFiberImage=False
            , ReturnSpotSize=False
            , ReturnNsat=False):

    """이미지에서 fiber peak을 찾아 중심 위치를 잰다.

    predict : (xchip, ychip) 'Predict' mode 에서 출발할 칩 좌표 [mm] (mtlcal 이 이미 맞춘 변환으로
        예측해 넘긴다). None 이면 x, y 를 상수 focal2camera_coeff_comm 으로 투영한다 (옛 방식).
    npeaks : 찾을 spot 개수. 정수면 정확히 그 개수가 되도록 문턱값을 맞추고,
        (nmin, nmax) 면 그 범위 안이면 받아들인다. fiducial 전용 노출처럼 fiber 가
        보일 수도 안 보일 수도 있는 이미지에서 쓴다 (예: (nfid, nfid+nfib)).
        nmax 를 넘으면 어두운 것부터 버리고, nmin 에 못 미치면 예외를 낸다.
    sat_level : 포화 수준 [ADU, 배경 빼기 전]. ReturnNsat 때 창 안의 포화 화소 수를
        센다 (fiducial 노출을 고를 때 쓴다).
    min_dist : 검출된 peak 가운데 이보다 가까운 것은 하나로 합친다 [px] (밝은 쪽을 남김).
        spot 이 크거나 둘로 갈라져 보이면 (실험실 PSF) sep 이 한 spot 을 여러 개로
        쪼개므로 spot 크기보다 크게(예: 80) 잡는다. 이웃 spot 간격보다는 작아야 한다.
    exclude : (xchip, ychip) 칩 좌표 [mm] 배열. 그 자리 반지름 exclude_r [px] 안을 배경값으로
        덮은 뒤 peak 을 찾는다. fiber 노출에 fiducial 이 같이 찍혔을 때(또는 그 반대)
        이미 아는 쪽을 지우는 데 쓴다. 'Raw' 모드에서만 뜻이 있다.

    finder : peak을 찾는 방법. 'sep'(기본), 'find_peaks', 'daofind',
        'segmentation'. 어느 것을 쓰든 뒤 단계는 같다 (peakfind 참고).
    finder_opts : 방법별 추가 인자 dict. 예) {'minarea': 8} (sep),
        {'fwhm': 8.0} (daofind), {'npixels': 5} (segmentation).
        'find_peaks'는 box_size를 boxsize 인자에서 받는다.
    background : 'crop'(기본) 이면 peak 을 찾을 때는 배경을 빼지 않고, centroid
        를 잴 때 잘라낸 창마다 sigma clipping 으로 구한 median 을 빼고 음수를
        0 으로 자른다 (창 안에서 spot 은 clip 되어 빠지고 배경만 남는다). 창마다
        따로 재므로 기울어진 배경에도 맞는다. 'scalar' | 'background2d' | 'sep'
        이면 peak 을 찾기 전에 이미지 전체에서 배경을 뺀다 (그때는 threshold 가
        뺀 뒤 기준이 된다). None 이면 아무것도 하지 않는다.
    background_opts : 배경 추정에 넘길 인자 dict. 'crop'은 sigma만 받는다
        (기본 5.0).
    threshold : 검출 문턱값 [ADU]. background를 뺐으면 뺀 뒤 기준이다.
    niter_recenter : center of mass를 잰 뒤 창을 그 무게중심으로 옮겨 다시
        재는 횟수. 0이면 peak 픽셀을 중심으로 한 번만 잰다 (예전 동작).
        PSF가 비대칭이면 peak과 무게중심이 어긋나 창이 한쪽 꼬리만 자르게
        되는데, 창을 무게중심에 맞추면 양쪽을 고르게 잘라 치우침이 사라진다.
        PSF가 창에 비해 클수록 효과가 크다.
    max_shift : 재중심 때 창이 처음 peak에서 벗어날 수 있는 최대 거리
        [pixel]. 넘으면 이웃 spot에 끌려가는 것으로 보고 처음 결과를 쓴다.
        None이면 nwindow//2.
    """
    log = get_logger()

    #---Stack "nframe" Image----------------------------------------------------------------------------------------------------------
    im = None
    for iframe in range(nexposure):
        # mtlexp가 저장한 경로와 같은 규칙으로 읽는다
        frame = fits.getdata(image_path(data_dir, head, iframe)).astype(np.float64)[::-1,:] / nexposure
        im = frame if im is None else im + frame

    ny, nx = im.shape

    # 픽셀 -> 칩 좌표 [mm]. 칩 중심이 원점, 화소 3.76 um. (8842 x 11760 이면 예전 상수와 같다)
    xchip = (np.arange(nx) - (nx-1)/2.)*3.76e-3
    ychip = (np.arange(ny) - (ny-1)/2.)*3.76e-3

    # 포화 판정은 배경을 빼기 전 값 기준이므로, 뺄 배경 수준을 대략 기억해 둔다.
    # 배경 잡음도 재 둔다: 문턱값 탐색이 잡음 속으로 내려가지 않게 하는 바닥이 된다.
    sample = im[::16, ::16]
    raw_level = float(np.median(sample))
    raw_noise = float(1.4826*np.median(np.abs(sample - raw_level)))
    threshold_floor = raw_level*(0 if (background and background != 'crop') else 1) + 5.*raw_noise

    if isinstance(npeaks, (tuple, list)):
        nmin, nmax = int(npeaks[0]), int(npeaks[1])
    else:
        nmin = nmax = int(npeaks)

    #---이미 아는 spot 지우기 (fiber 노출의 fiducial, fiducial 노출의 fiber)------------------
    if exclude is not None and len(exclude[0]):
        ex_u = nearest_index_sorted(xchip, np.atleast_1d(exclude[0])).astype(int)
        ex_v = nearest_index_sorted(ychip, np.atleast_1d(exclude[1])).astype(int)
        r = int(exclude_r)
        yy, xx = np.ogrid[-r:r+1, -r:r+1]
        disc = (xx*xx + yy*yy) <= r*r
        for u0, v0 in zip(ex_u, ex_v):
            y0, y1 = max(v0-r, 0), min(v0+r+1, ny); x0, x1 = max(u0-r, 0), min(u0+r+1, nx)
            d = disc[(y0-(v0-r)):(y1-(v0-r)), (x0-(u0-r)):(x1-(u0-r))]
            patch = im[y0:y1, x0:x1]
            patch[d] = raw_level
        log.info("Masked %d known spot(s) (r = %d px) before peak finding", ex_u.size, r)

    #---Background--------------------------------------------------------------
    # 'crop'은 여기서 빼지 않고 centroid 단계에서 조각마다 뺀다.
    crop_background = (background == 'crop')
    crop_sigma = dict(background_opts or {}).get('sigma', 5.0)
    if background is not None and not crop_background:
        im, _ = peakfind.subtract_background(im, method=background,
                                             options=background_opts,
                                             inplace=True)
    
    #---Find Peaks Using any method---------------------------------------------------------------------------------------------------    
    log.info("Start finding peaks with %s (finder=%s)", mode, finder)
    fopts = dict(finder_opts or {})
    if finder == 'find_peaks':
        fopts.setdefault('box_size', boxsize)
    if mode == "Raw":
        # 검출 개수가 npeaks (또는 nmin..nmax 범위) 가 되는 문턱값을 찾는다.
        #
        # 문턱을 올리면 검출이 줄고 내리면 늘어난다. 한 번이라도 양쪽을 다 봤으면
        # 그 사이를 이분법으로 좁히고, 아직 한쪽만 봤으면 10%씩 옮긴다. 개수가
        # 이산적이라 정확히 npeaks가 되는 문턱이 아예 없을 수도 있으므로
        # (cosmic ray, hot pixel, 어두운 fiber 하나 등) niter_max에서 끊고
        # 가장 가까웠던 시도로 넘어간다. 옛 구현은 상한이 없어서 이 경우
        # 무한 루프였다.
        def miss(n):
            return 0 if nmin <= n <= nmax else (nmin-n if n < nmin else n-nmax)

        threshold_temp = threshold
        t_many = None       # 너무 많이 나온 문턱 (더 올려야 한다)
        t_few = None        # 너무 적게 나온 문턱 (더 내려야 한다)
        best = None         # (범위에서 벗어난 개수, peak_table, 문턱)

        for niter in range(1, niter_max+1):
            peak_table_raw = peakfind.find(im, threshold_temp,
                                           method=finder, options=fopts)
            peak_table = dedupe_peaks_kdtree(peak_table_raw, min_dist=min_dist)
            nfound = len(peak_table)
            log.info("Iteration %d: threshold %.4g -> %d peaks (target %s)",
                     niter, threshold_temp, nfound,
                     nmin if nmin == nmax else f"{nmin}..{nmax}")

            if best is None or miss(nfound) < best[0]:
                best = (miss(nfound), peak_table, threshold_temp)

            if miss(nfound) == 0:
                break

            if nfound > nmax:
                t_many = threshold_temp
            else:
                t_few = threshold_temp

            if t_many is not None and t_few is not None:
                threshold_temp = 0.5*(t_many + t_few)       # 양쪽을 봤으니 이분법
            elif nfound > nmax:
                threshold_temp *= 1.1
            else:
                threshold_temp *= 0.9
            if threshold_temp < threshold_floor:
                # 배경 잡음(5 sigma) 아래로는 내려가지 않는다: 잡음을 peak 으로 세기 시작하고
                # sep 의 pixel stack 이 넘친다. 여기서 끊고 가장 가까웠던 시도를 쓴다.
                log.warning("Threshold would drop below the noise floor (%.0f = background %.0f + 5 sigma); "
                            "stopping the search -- the image has fewer spots than expected",
                            threshold_floor, raw_level)
                break
        if miss(nfound) != 0:
            # 못 맞췄다. 가장 가까웠던 시도를 쓴다.
            _, peak_table, threshold_temp = best
            nfound = len(peak_table)
            log.warning("Could not reach %s peaks in %d iterations; "
                        "using the closest attempt (%d peaks at threshold %.4g)",
                        nmin if nmin == nmax else f"{nmin}..{nmax}", niter_max,
                        nfound, threshold_temp)

            if nfound < nmin:
                raise RuntimeError(
                    f"Only {nfound} peaks found but {nmin} expected (threshold searched down to "
                    f"{threshold_temp:.0f}, noise floor {threshold_floor:.0f}). "
                    "Some spots are missing or too faint: check the image (lab.check_peaks), "
                    "the exposure, FIBER_EXCLUDE for dead fibers, and the fiber table.")

            # 남는 것은 가장 어두운 쪽부터 버린다 (cosmic ray / hot pixel로 본다)
            order = np.argsort(-np.asarray(peak_table['peak_value'], dtype=float))
            peak_table = peak_table[order[:nmax]]
            log.warning("Dropped %d faintest detections to match %d",
                        nfound-nmax, nmax)

        xf, yf = peak_table['x_peak'].data, peak_table['y_peak'].data
        npeaks = xf.size
        log.info("Found %d peaks at threshold %.4g", xf.size, threshold_temp)

    elif mode=="Predict":
        if predict is not None:
            # 이미 맞춘 변환으로 예측한 칩 좌표 (mtlcal 이 넘긴다). 상수 계수보다 믿을 만하다.
            xpredict, ypredict = np.asarray(predict[0], float), np.asarray(predict[1], float)
            npeaks = int(xpredict.size)
        else:
            npeaks = int(np.size(x))
            coeff_temp = np.copy(focal2camera_coeff_comm)
            xpredict, ypredict = transform(x, y, coeff_temp)

        # refined 결과를 따로 보관 (원본 보호)
        xref = xpredict.copy()
        yref = ypredict.copy()

        for it in range(niter_refine):
            # 매 iteration마다 현재 예측값 기준으로 픽셀 인덱스 갱신
            ix0 = nearest_index_sorted(xchip, xref).astype(int)
            iy0 = nearest_index_sorted(ychip, yref).astype(int)

            for i in range(xref.size):
                xcen = ix0[i]
                ycen = iy0[i]

                # --- crop 범위 (경계 안전)
                x0 = max(xcen - nwindow, 0)
                x1 = min(xcen + nwindow, nx)
                y0 = max(ycen - nwindow, 0)
                y1 = min(ycen + nwindow, ny)

                im_temp = im[y0:y1, x0:x1]
                if im_temp.size == 0:
                    continue

                # --- crop 내부 max 픽셀 찾기
                itemp, jtemp = np.unravel_index(np.argmax(im_temp), im_temp.shape)

                # --- crop 좌표 -> 원본 픽셀 인덱스
                x_idx = x0 + jtemp
                y_idx = y0 + itemp

                # --- 최종 mm 좌표로 업데이트 (핵심!)
                xref[i] = xchip[x_idx]
                yref[i] = ychip[y_idx]

        # 이제 xref, yref가 "peak로 보정된" mm 예측값
        xpredict = xref
        ypredict = yref

    #---Calculate Center--------------------------------------------------------------------------------------------------------------
    # 중심 픽셀 인덱스: Raw는 검출된 peak, Predict는 보정된 예측 위치
    if mode == "Predict":
        icen = nearest_index_sorted(xchip, xpredict).astype(int)
        jcen = nearest_index_sorted(ychip, ypredict).astype(int)
    else:
        icen, jcen = np.asarray(xf, dtype=int), np.asarray(yf, dtype=int)

    def crop_at(i0, j0, half):
        """(j0, i0) 픽셀을 중심으로 2*half 크기의 이미지와 좌표축을 잘라낸다."""
        return (im[j0-half:j0+half, i0-half:i0+half],
                xchip[i0-half:i0+half],
                ychip[j0-half:j0+half])

    def measure(i0, j0):
        """창 하나를 잘라 (필요하면 배경을 빼고) 무게중심을 잰다."""
        im_crop, x_crop, y_crop = crop_at(i0, j0, nwindow)
        if crop_background:
            # sigma clipping으로 구한 median을 빼고 음수는 0으로
            _, im_med, _ = sigma_clipped_stats(im_crop, sigma=crop_sigma)
            im_crop = np.clip(im_crop - im_med, a_min=0, a_max=None)
        xc, yc = com(im_crop, x_crop, y_crop)
        return xc, yc, im_crop, x_crop, y_crop

    shift_limit = nwindow // 2 if max_shift is None else max_shift
    nrevert = 0
    shifts = np.zeros(npeaks)       # 재중심으로 창이 peak에서 움직인 거리 [px]

    # peak 값은 두 mode 모두 중심 픽셀의 밝기로 정의한다.
    # Raw mode에서는 photutils가 주는 peak_table['peak_value']와 동일하다.
    peak_value = im[jcen, icen]

    xobs = np.zeros(npeaks)
    yobs = np.zeros(npeaks)
    nsat = np.zeros(npeaks, dtype=int)

    if ReturnSpotSize:
        xsigma, ysigma = np.zeros(npeaks), np.zeros(npeaks)

    if ReturnFiberImage:
        im_crop_full = np.zeros( (npeaks, nwindow*2, nwindow*2))

    for ifiber in range(npeaks):
        i0, j0 = int(icen[ifiber]), int(jcen[ifiber])
        first = measure(i0, j0)
        xc, yc, im_crop, x_crop, y_crop = first

        # 창을 무게중심으로 옮겨 가며 다시 잰다
        for _ in range(niter_recenter):
            inew = int(nearest_index_sorted(xchip, np.atleast_1d(xc))[0])
            jnew = int(nearest_index_sorted(ychip, np.atleast_1d(yc))[0])
            if np.hypot(inew-icen[ifiber], jnew-jcen[ifiber]) > shift_limit:
                # 이웃 spot에 끌려가고 있다. 처음(peak 중심) 결과로 되돌린다.
                xc, yc, im_crop, x_crop, y_crop = first
                i0, j0 = int(icen[ifiber]), int(jcen[ifiber])
                nrevert += 1
                break
            if (inew, jnew) == (i0, j0):
                break                               # 더 움직이지 않는다
            i0, j0 = inew, jnew
            xc, yc, im_crop, x_crop, y_crop = measure(i0, j0)

        xobs[ifiber], yobs[ifiber] = xc, yc
        shifts[ifiber] = np.hypot(i0-icen[ifiber], j0-jcen[ifiber])
        # 포화 화소 수: 배경을 뺀 이미지라면 뺀 만큼을 되돌려 센다 (배경은 포화에 비해 작다)
        raw_crop = im[j0-nwindow:j0+nwindow, i0-nwindow:i0+nwindow]
        nsat[ifiber] = int(np.count_nonzero(
            raw_crop >= sat_level - (raw_level if (background and not crop_background) else 0.)))

        # spot size는 background 제거를 거친 im_crop의 중앙 절반 window에서 측정
        if ReturnSpotSize:
            half = nwindow // 2
            core = slice(nwindow-half, nwindow+half)
            xsigma[ifiber], ysigma[ifiber] = measure_sigma(
                im_crop[core, core], x_crop[core], y_crop[core])

        if ReturnFiberImage:
            im_crop_full[ifiber] = im_crop

    if niter_recenter:
        # max_shift를 실제 PSF에 맞게 정하는 근거. 정상 spot의 이동량보다
        # 조금 크게 (예: 최대값의 1.5배) 잡으면 이웃에 끌려가는 창만 걸러진다.
        log.info("Recentering shift [px]: median %.1f, 95%% %.1f, max %.1f "
                 "(limit %d)", np.median(shifts), np.percentile(shifts, 95),
                 shifts.max(), shift_limit)
    if niter_recenter and nrevert:
        log.warning("Recentering pulled %d window(s) more than %d px away "
                    "from their peak; used the peak-centred result for them",
                    nrevert, shift_limit)

    #---Return------------------------------------------------------------------------------------------------------------------------
    # 기본  : im, xobs, yobs, peak_value
    # option: ReturnFiberImage -> im 다음에 im_crop_full 삽입
    #         ReturnSpotSize   -> 끝에 xsigma, ysigma 추가 [mm].
    #                             FWHM이 아니라 2차 모멘트(sigma)다.
    #                             픽셀로 보려면 3.76e-3으로 나눈다.
    #         ReturnNsat       -> 맨 끝에 창마다 센 포화 화소 수 추가
    out = [im]
    if ReturnFiberImage:
        out.append(im_crop_full)
    out += [xobs, yobs, peak_value]
    if ReturnSpotSize:
        out += [xsigma, ysigma]
    if ReturnNsat:
        out.append(nsat)

    return tuple(out)