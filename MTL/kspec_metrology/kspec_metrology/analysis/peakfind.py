"""광섬유 peak 검출 방법 모음과 background 제거.

findpeak()의 "peak을 찾는 단계"만 갈아 끼울 수 있게 떼어 놓은 모듈이다.
어떤 방법을 쓰든 돌려주는 표의 형식이 photutils.find_peaks와 똑같으므로
(id, x_peak, y_peak, peak_value / x_peak, y_peak은 정수 픽셀), 뒤따르는
dedupe_peaks_kdtree, center of mass, matchfiber는 손댈 필요가 없다.

    from kspec_metrology.analysis import peakfind
    table = peakfind.find(im, threshold=1e3, method='sep')

방법마다 필요한 인자가 다르므로 공통 인자(im, threshold) 외에는 options
dict으로 넘긴다. findpeak(finder=..., finder_opts=...)가 그대로 전달한다.

8842 x 11760 full frame 기준 대략적인 소요 시간 (spot 181개):

    sep           0.5 s      가장 빠르다. 넓은 spot도 잘 잡는다
    segmentation  1.2 s      연결 성분. npixels로 잡티를 거른다
    find_peaks    4.2 s      기존 방법. 국소 최대만 보므로 단순하다
    daofind      23   s      PSF 모양까지 본다. 가장 느리지만 blend에 강하다

background 제거는 세 가지다.

    'scalar'        전체에서 sigma clipped median 하나를 빼기  (~0.9 s)
    'background2d'  photutils Background2D로 변화하는 배경 빼기 (~6 s)
    'sep'           sep.Background로 같은 일을 더 빠르게        (~0.6 s)

'crop'은 여기가 아니라 findpeak의 centroid 단계에서 잘라낸 조각마다 빼는
방식이고, 전역 배경이 평평할 때는 그쪽이 더 안전하다.
"""

import numpy as np
from astropy.stats import SigmaClip, sigma_clipped_stats
from astropy.table import Table
from photutils.detection import DAOStarFinder, find_peaks as _photutils_find_peaks

from kspec_metrology.logging.log import get_logger

# find_peaks가 돌려주는 표의 컬럼. 모든 방법이 이 형식을 지킨다.
PEAK_COLUMNS = ('id', 'x_peak', 'y_peak', 'peak_value')


def _peak_table(im, xs, ys, snap=3):
    """검출 좌표를 find_peaks와 같은 형식의 표로 만든다.

    centroid를 돌려주는 방법(daofind, sep, segmentation)은 실수 좌표를 주므로
    그 근처 ±snap 픽셀에서 가장 밝은 픽셀로 옮겨 붙인다. find_peaks의
    x_peak/y_peak이 "peak 픽셀"이고 뒤 코드가 그것을 정수 인덱스로 쓰기
    때문이다 (findpeak의 crop 중심).
    """
    ny, nx = im.shape
    xs = np.clip(np.rint(np.asarray(xs, dtype=float)), 0, nx-1).astype(np.int64)
    ys = np.clip(np.rint(np.asarray(ys, dtype=float)), 0, ny-1).astype(np.int64)

    if snap > 0:
        for k in range(xs.size):
            i0, i1 = max(xs[k]-snap, 0), min(xs[k]+snap+1, nx)
            j0, j1 = max(ys[k]-snap, 0), min(ys[k]+snap+1, ny)
            sub = im[j0:j1, i0:i1]
            dj, di = np.unravel_index(np.argmax(sub), sub.shape)
            xs[k], ys[k] = i0+di, j0+dj

    # 같은 픽셀로 모인 검출은 하나로 (dedupe_peaks_kdtree가 거리 기준으로 한 번
    # 더 걸러주지만, 완전히 겹친 것은 여기서 정리해 둔다)
    _, keep = np.unique(np.stack((ys, xs)), axis=1, return_index=True)
    keep = np.sort(keep)
    xs, ys = xs[keep], ys[keep]

    order = np.lexsort((xs, ys))            # find_peaks처럼 위에서 아래로
    xs, ys = xs[order], ys[order]

    return Table([np.arange(1, xs.size+1), xs, ys, im[ys, xs]],
                 names=PEAK_COLUMNS)


#--- 방법들 -------------------------------------------------------------------
# 모두 (im, threshold, **options) -> find_peaks 형식 표

def _find_peaks(im, threshold, box_size=40, **kw):
    """photutils.find_peaks. 기존 방법이며 결과를 그대로 돌려준다."""
    table = _photutils_find_peaks(im, threshold=threshold, box_size=box_size, **kw)
    if table is None or len(table) == 0:
        return Table(names=PEAK_COLUMNS,
                     dtype=(int, np.int64, np.int64, float))
    return table


def _daofind(im, threshold, fwhm=8.0, **kw):
    """DAOStarFinder. PSF 모양(sharpness, roundness)까지 보므로 가깝게 붙은
    spot을 나누는 데 강하지만 full frame에서는 가장 느리다."""
    table = DAOStarFinder(threshold=threshold, fwhm=fwhm, **kw)(im)
    if table is None or len(table) == 0:
        return Table(names=PEAK_COLUMNS,
                     dtype=(int, np.int64, np.int64, float))
    return _peak_table(im, table['xcentroid'], table['ycentroid'])


def _sep_extract(im, threshold, minarea=5, **kw):
    """sep.extract. 가장 빠르다. float32 C-contiguous 배열을 요구한다."""
    import sep
    sep.set_extract_pixstack(int(kw.pop('pixstack', 10_000_000)))   # 큰 spot / 낮은 문턱에서 기본 30만은 넘친다
    data = np.ascontiguousarray(im, dtype=np.float32)
    obj = sep.extract(data, thresh=float(threshold), minarea=minarea, **kw)
    if len(obj) == 0:
        return Table(names=PEAK_COLUMNS,
                     dtype=(int, np.int64, np.int64, float))
    # peak 픽셀을 직접 주므로(xpeak, ypeak) snap이 필요 없다
    return _peak_table(im, obj['xpeak'], obj['ypeak'], snap=0)


def _segmentation(im, threshold, npixels=5, **kw):
    """연결 성분으로 찾는다. npixels보다 작은 잡티는 자동으로 빠진다."""
    from photutils.segmentation import SourceCatalog, detect_sources
    seg = detect_sources(im, threshold=threshold, npixels=npixels, **kw)
    if seg is None or seg.nlabels == 0:
        return Table(names=PEAK_COLUMNS,
                     dtype=(int, np.int64, np.int64, float))
    idx = np.atleast_2d(SourceCatalog(im, seg).maxval_index)
    return _peak_table(im, idx[:, 1], idx[:, 0], snap=0)


FINDERS = {
    'find_peaks': _find_peaks,
    'daofind': _daofind,
    'sep': _sep_extract,
    'segmentation': _segmentation,
}


def find(im, threshold, method='find_peaks', options=None):
    """method로 peak을 찾아 find_peaks 형식의 표를 돌려준다."""
    try:
        finder = FINDERS[method]
    except KeyError:
        raise ValueError(
            f"Unknown peak finder {method!r}. "
            f"Available: {', '.join(sorted(FINDERS))}") from None

    return finder(im, threshold, **(options or {}))


#--- background ---------------------------------------------------------------

def subtract_background(im, method='scalar', options=None, inplace=False):
    """전역 background를 빼고 (뺀 이미지, 설명 문자열)을 돌려준다.

    method:
        'scalar'        sigma clipped median 하나를 뺀다. 배경이 평평하면 충분
        'background2d'  photutils Background2D. 위치에 따라 변하는 배경까지
        'sep'           sep.Background. background2d와 같은 일을 더 빠르게
    """
    opts = dict(options or {})

    if method == 'scalar':
        # 전 픽셀을 다 보면 느리므로 격자로 솎아 통계만 낸다 (배경은 완만하다)
        step = opts.pop('step', 4)
        sigma = opts.pop('sigma', 3.0)
        _, median, std = sigma_clipped_stats(im[::step, ::step], sigma=sigma)
        bkg, desc = median, f"scalar median {median:.3f} (rms {std:.2f})"

    elif method == 'background2d':
        from photutils.background import Background2D, MedianBackground
        opts.setdefault('box_size', 256)
        opts.setdefault('filter_size', 3)
        sigma = opts.pop('sigma', 3.0)
        b = Background2D(im, sigma_clip=SigmaClip(sigma=sigma),
                         bkg_estimator=MedianBackground(), **opts)
        bkg = b.background
        desc = (f"Background2D box={opts['box_size']} "
                f"median {np.median(bkg):.3f} (rms {np.median(b.background_rms):.2f})")

    elif method == 'sep':
        import sep
        opts.setdefault('bw', 256)
        opts.setdefault('bh', 256)
        b = sep.Background(np.ascontiguousarray(im, dtype=np.float32), **opts)
        bkg = b.back().astype(im.dtype)
        desc = f"sep.Background bw={opts['bw']} globalback {b.globalback:.3f}"

    else:
        raise ValueError(
            f"Unknown background method {method!r}. "
            "Available: scalar, background2d, sep (또는 findpeak(background='crop'))")

    out = im if inplace else im.copy()
    out -= bkg
    get_logger().info("Background subtracted: %s", desc)

    return out, desc
