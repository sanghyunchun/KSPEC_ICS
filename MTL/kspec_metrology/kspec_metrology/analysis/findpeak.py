import numpy as np
from photutils.detection import find_peaks, DAOStarFinder
from astropy.io import fits
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
            , threshold=5e3
            , boxsize=100
            , nwindow=100
            , mode="Raw"
            , x=None, y=None
            , niter_refine=2
            , SigmaClipping=False
            , ReturnFiberImage=False
            , ReturnSpotSize=False):

    log = get_logger()

    xchip = np.linspace(-5879.5, 5879.5, 11760)*3.76e-3
    ychip = np.linspace(-4420.5, 4420.5, 8842)*3.76e-3
    
    #---Stack "nframe" Image----------------------------------------------------------------------------------------------------------
    im = np.zeros((8842, 11760))
    for iframe in range(nexposure):
        # mtlexp가 저장한 경로와 같은 규칙으로 읽는다
        im += fits.getdata(image_path(data_dir, head, iframe)).astype(np.float64)[::-1,:] / nexposure

    ny, nx = im.shape
    
    #---Find Peaks Using any method---------------------------------------------------------------------------------------------------    
    log.info("Start finding peaks with %s", mode)
    if mode == "Raw":
        threshold_temp = threshold
        niter = 0
        while True:
            peak_table_raw = find_peaks(im, threshold=threshold_temp, box_size=boxsize)
            peak_table = dedupe_peaks_kdtree(peak_table_raw, min_dist=40)
            xf, yf = peak_table['x_peak'].data, peak_table['y_peak'].data   
            log.info(f"Found {xf.size} peaks")
            if xf.size > npeaks:
                log.warning("Too many peaks detected")
                threshold_temp *= 1.1
            elif xf.size < npeaks:
                log.warning(f"{npeaks-xf.size} peaks are not detected")
                threshold_temp *= 0.9
            niter += 1
            print(f"Peak finding iteration {niter}")
            if xf.size == npeaks:
                print("Done")
                break

    elif mode=="Predict":
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

    def crop(ifiber, half):
        """(jcen, icen) 픽셀을 중심으로 2*half 크기의 이미지와 좌표축을 잘라낸다."""
        i0, j0 = icen[ifiber], jcen[ifiber]
        return (im[j0-half:j0+half, i0-half:i0+half],
                xchip[i0-half:i0+half],
                ychip[j0-half:j0+half])

    # peak 값은 두 mode 모두 중심 픽셀의 밝기로 정의한다.
    # Raw mode에서는 photutils가 주는 peak_table['peak_value']와 동일하다.
    peak_value = im[jcen, icen]

    xobs = np.zeros(npeaks)
    yobs = np.zeros(npeaks)

    if ReturnSpotSize: # SW added on 2026-01-31
        xfwhm, yfwhm = np.zeros(npeaks), np.zeros(npeaks)

    if ReturnFiberImage:
        im_crop_full = np.zeros( (npeaks, nwindow*2, nwindow*2))

    for ifiber in range(npeaks):
        im_crop, x_crop, y_crop = crop(ifiber, nwindow)

        # background 제거: sigma clipping으로 구한 median을 빼고 음수는 0으로
        # SW added on 2026-01-31
        if SigmaClipping:
            _, im_med, _ = sigma_clipped_stats(im_crop, sigma=5.0)
            im_crop = np.clip(im_crop - im_med, a_min=0, a_max=None)

        xobs[ifiber], yobs[ifiber] = com(im_crop, x_crop, y_crop)

        # spot size는 background 제거를 거친 im_crop의 중앙 절반 window에서 측정
        if ReturnSpotSize: # SW added on 2026-01-31
            half = nwindow // 2
            core = slice(nwindow-half, nwindow+half)
            xfwhm[ifiber], yfwhm[ifiber] = measure_sigma(im_crop[core, core], x_crop[core], y_crop[core])

        if ReturnFiberImage:
            im_crop_full[ifiber] = im_crop

    #---Return------------------------------------------------------------------------------------------------------------------------
    # 기본  : im, xobs, yobs, peak_value
    # option: ReturnFiberImage -> im 다음에 im_crop_full 삽입
    #         ReturnSpotSize   -> 끝에 xfwhm, yfwhm 추가
    out = [im]
    if ReturnFiberImage:
        out.append(im_crop_full)
    out += [xobs, yobs, peak_value]
    if ReturnSpotSize:
        out += [xfwhm, yfwhm]

    return tuple(out)