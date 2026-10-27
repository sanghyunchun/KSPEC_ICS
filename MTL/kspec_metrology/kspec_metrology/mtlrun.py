"""노출(mtlexp)과 계산(mtlcal)을 묶어 metrology를 한 바퀴씩 돌린다.

metrology 한 바퀴(trial)는

    1. 카메라로 nexposure장 촬영              (mtlexp)
       (fiducial 을 다른 노출시간으로 따로 찍으면 fid_exptime 세트만큼 더 찍는다)
    2. 이미지에서 fiber 위치를 재고 각도 계산   (mtlcal)
    3. 각도 json 과 fiber 이동량 표 저장

이고, 외부 컴퓨터는 그 json으로 positioner를 옮긴 뒤 다음 trial을 부른다. 실제로
fiber를 옮기는 일은 이 패키지 밖의 일이므로, 여기서는 trial 하나를 온전히 돌리고
"각도 json 경로"와 "지금 위치 오차가 얼마인지"만 돌려준다.

쓰는 법 (외부 컴퓨터에서):

    from kspec_metrology.mtlrun import MetrologyRun

    run = MetrologyRun(target_file='/path/to/target.info',
                       data_dir='./MTL/data/', json_dir='./MTL/json/',
                       exptime=30., fid_exptime=[1., 10.], tolerance=10., max_trial=10)   # [ms]

    move(run.start())                 # Trial 0 json = 관측 전 목표 각도

    while run.should_continue:
        res = run.trial()             # 촬영 + 계산 + json 저장
        move(res.json)                # 이동은 외부에서

    summary = run.result()
    summary.converged                 # 허용 오차 안에 들어왔는가
    summary.ntrial                    # 실제로 돈 trial 수
    summary.err_max, summary.err_median   # 마지막 fiber 위치 오차 [um]

파일 이름은 타일 이름과 trial 번호로 정해지므로(naming 참고), 어느 trial의
이미지를 어느 계산이 읽었고 그 결과가 어느 json인지가 항상 짝이 맞는다.
"""

from dataclasses import dataclass, field

import numpy as np

from kspec_metrology.analysis.mtlcal import mtlcal, save_initial_angles, json_path
from kspec_metrology.analysis.target_info import read_target, tile_name
from kspec_metrology.analysis import fiber_config as cfg
from kspec_metrology.exposure.mtlexp import mtlexp
from kspec_metrology import naming
from kspec_metrology.logging.log import get_logger


@dataclass
class TrialResult:
    """trial 한 번의 결과."""
    itrial: int
    json: str               # positioner를 옮길 누적 각도 json 경로
    offsets: str            # fiber 별 남은 오차와 이번 회전량 표 (ID, dx, dy, dalpha, dbeta)
    err_max: float          # fiber 위치 오차 최대값 [um]
    err_median: float       # fiber 위치 오차 중앙값 [um]
    converged: bool         # 이 trial에서 허용 오차 안에 들어왔는가
    dx: np.ndarray          # 목표 대비 위치 오차 [mm]. fiber + fiducial 전체
    dy: np.ndarray
    images: list            # 이 trial이 찍은 이미지 경로


@dataclass
class RunResult:
    """metrology run 전체의 결과."""
    tile: str
    converged: bool
    ntrial: int
    json: str               # 마지막으로 저장한 각도 json 경로
    err_max: float
    err_median: float
    history: list = field(default_factory=list)   # TrialResult 리스트


class MetrologyRun:
    """한 타일의 metrology trial을 관리한다.

    반복 자체는 외부 컴퓨터가 돈다 (trial 사이에 positioner를 옮겨야 하므로).
    이 객체는 trial 번호와 파일 이름, 수렴 판정을 맡는다.

    인자:
        target_file : 타일/목표 위치 파일. None이면 fiber_config.TARGET_INFO_PATH
        data_dir    : 이미지를 저장하고 다시 읽을 디렉터리
        json_dir    : 각도 json을 저장할 디렉터리
        tolerance   : 수렴 판정 기준 [um]. fiber 위치 오차가 이보다 작으면 끝
        metric      : 수렴을 판정할 통계. 'max' (기본) 또는 'median'
        max_trial   : 최대 반복 횟수. None이면 제한 없음
        nexposure   : trial 한 번에 찍을 이미지 장수
        mode        : findpeak의 peak 검출 방식. 'Raw'(기본) 또는 'Predict'.
                      'Predict'는 이미 맞춘 변환(노출을 나눴으면 이번 trial 의
                      fiducial fit, 한 벌이면 직전 trial 의 _coeff.npy)으로
                      예측한 자리의 창 안에서만 잰다 (매칭 없음). 첫 trial 이나
                      오차가 창 반폭(~1.3 mm)보다 크면 Raw 를 쓴다 (mtlcal 참고)
        threshold   : 'Raw' mode의 검출 문턱값
        nwindow     : center of mass를 잴 crop 반폭 [pixel]. fiber 사이 최소
                      이격 거리에 맞춰야 한다 (mtlcal 참고)
        use_measured : 설계 좌표와 arm 길이를 실측값으로 바꿀지. None이면
                      fiber_config.USE_MEASURED (기본 True; KSPEC_USE_MEASURED=0 으로 끈다)
        apply_pinhole_offset : fiducial 기준 좌표에 핀홀 오프셋을 더할지.
                      기본 False. 쓰는 plate에서 측정한 핀홀 파일을 넣은 뒤
                      True로 켠다 (load_configuration 참고)
        niter_recenter : 창을 무게중심으로 옮겨 다시 재는 횟수 (findpeak 참고)
        finder      : peak 검출 방법. 'find_peaks'(기본), 'daofind', 'sep',
                      'segmentation' (peakfind 참고)
        finder_opts : 방법별 추가 인자 dict
        background  : 배경 제거. 'crop'(기본, 창마다 뺌) | 'scalar' | 'background2d' | 'sep' | None
        background_opts : 배경 추정 인자 dict
        exptime, gain, offset, readmode, usb_traffic : 카메라 설정. exptime 은 [ms]
        fid_exptime : fiducial 전용 노출시간 [ms]. None(기본)이면 fiber 와 같은 이미지에서
                      fiducial 도 찾는다. 숫자 하나면 그 노출로 fiducial 세트를 한 번
                      더 찍고 (case 1: fiber t2, fiducial t1), 리스트면 세트를 여러 번
                      찍어 fiducial 마다 포화되지 않은 가장 밝은 것을 쓴다
                      (case 2: fiber t2, fiducial t1_1, t1_2). 두 노출 사이에 아무것도
                      움직이지 않아야 한다 (mtlcal 참고)
        fid_nexposure : fiducial 세트당 장수. None 이면 nexposure
        model       : 왜곡 다항식에서 풀 항 ('full', 'optics', 'radial', 'similarity';
                      utils.DISTORTION_MODELS). 실험실의 단순한 광학계는 'radial'
        magnification : camera -> focal 배율 초기값 (부호 포함). 본 장비와 다른
                      광학계(실험실)에서는 꼭 준다 (utils.CAMERA2FOCAL_M 참고)
        sat_level   : 포화 판정 수준 [ADU]
        fid_min_peak : fiducial 노출을 고를 때 이보다 어두운 검출은 피한다 [ADU]
        n_extra     : 표에 없는데 이미지에 보이는 밝은 점의 수. FIBER_FIXED / SKY_FIBERS 에
                      적은 것은 자동으로 세므로, 그 밖의 점(반사광 등)만 적는다
        min_dist    : 가까운 검출을 하나로 합치는 거리 [px] (findpeak 참고)
        auto_exposure : 찍은 이미지에 포화 화소가 sat_max_pixels 보다 많으면 노출을
                      exposure_factor 배로 줄여 다시 찍는다 (최대 max_retry 번). 줄인 노출은
                      다음 trial 에도 그대로 쓴다. fiber 노출과 fiducial 세트 각각에 적용
        tile        : 파일 이름에 쓸 타일 이름. None이면 target 파일에서 읽는다
    """

    def __init__(self
                 , target_file=None
                 , data_dir='./MTL/data/'
                 , json_dir='./MTL/json/'
                 , tolerance=10.
                 , metric='max'
                 , max_trial=10
                 , nexposure=1
                 , mode='Raw'
                 , threshold=3e3
                 , nwindow=40
                 , niter_recenter=0
                 , apply_pinhole_offset=False
                 , use_measured=None
                 , use_measured_positioners=None
                 , finder='sep'
                 , finder_opts=None
                 , background='crop'
                 , background_opts=None
                 , exptime=30.
                 , gain=10
                 , offset=30
                 , readmode=1
                 , usb_traffic=40
                 , fid_exptime=None
                 , fid_nexposure=None
                 , model='full'
                 , magnification=None
                 , sat_level=65000.
                 , fid_min_peak=0.
                 , n_extra=0
                 , min_dist=40
                 , auto_exposure=False
                 , sat_max_pixels=0
                 , exposure_factor=0.5
                 , max_retry=3
                 , tile=None):

        if metric not in ('max', 'median'):
            raise ValueError("metric must be 'max' or 'median'")
        if max_trial is not None and max_trial < 1:
            raise ValueError("max_trial must be at least 1")

        self.log = get_logger()

        self.target_file = target_file
        self.target = read_target(target_file)
        self.tile = tile or tile_name(self.target, target_file)

        self.data_dir = data_dir
        self.json_dir = json_dir

        self.tolerance = float(tolerance)
        self.metric = metric
        self.max_trial = max_trial

        self.nexposure = nexposure
        self.mode = mode
        self.threshold = threshold
        self.nwindow = nwindow
        self.niter_recenter = niter_recenter
        self.apply_pinhole_offset = apply_pinhole_offset
        self.use_measured = use_measured
        self.use_measured_positioners = use_measured_positioners
        self.finder = finder
        self.finder_opts = finder_opts
        self.background = background
        self.background_opts = background_opts

        self.camera = dict(exptime=exptime, gain=gain, offset=offset,
                           readmode=readmode, usb_traffic=usb_traffic)
        if fid_exptime is None:
            self.fid_exptimes = []
        elif np.isscalar(fid_exptime):
            self.fid_exptimes = [float(fid_exptime)]
        else:
            self.fid_exptimes = [float(t) for t in fid_exptime]
        self.fid_nexposure = nexposure if fid_nexposure is None else int(fid_nexposure)
        self.model = model
        self.magnification = magnification
        self.sat_level = sat_level
        self.fid_min_peak = fid_min_peak
        self.n_extra = n_extra
        self.min_dist = min_dist
        self.auto_exposure = auto_exposure
        self.sat_max_pixels = int(sat_max_pixels)
        self.exposure_factor = float(exposure_factor)
        self.max_retry = int(max_retry)

        self.nfib = len(cfg.fiber_ids())

        self.history = []
        self.itrial = 0          # 지금까지 끝낸 trial 번호

    #---경로-------------------------------------------------------------------
    def image_head(self, itrial):
        """이 trial 이미지의 head. mtlexp와 mtlcal에 같은 값이 들어간다."""
        return naming.image_head(self.tile, itrial)

    def fid_image_heads(self, itrial):
        """fiducial 전용 노출 세트들의 head (없으면 빈 리스트)."""
        return [naming.fid_image_head(self.tile, itrial, k)
                for k in range(len(self.fid_exptimes))]

    def image_paths(self, itrial):
        paths = naming.image_paths(self.data_dir, self.tile, itrial, self.nexposure)
        for k in range(len(self.fid_exptimes)):
            paths += naming.fid_image_paths(self.data_dir, self.tile, itrial, k,
                                            self.fid_nexposure)
        return paths

    def offset_path(self, itrial):
        return naming.offset_path(self.json_dir, self.tile, itrial)

    def json_path(self, itrial):
        return json_path(self.json_dir, self.tile, itrial)

    #---상태-------------------------------------------------------------------
    @property
    def converged(self):
        """마지막 trial이 허용 오차 안에 들어왔는가."""
        return bool(self.history) and self.history[-1].converged

    @property
    def should_continue(self):
        """trial을 한 번 더 돌아야 하는가 (아직 수렴 전이고 횟수도 남았는가)."""
        if self.converged:
            return False
        return self.max_trial is None or self.itrial < self.max_trial

    #---한 단계씩-------------------------------------------------------------
    def start(self):
        """관측 전 목표 각도를 Trial 0 json으로 저장하고 그 경로를 돌려준다."""
        self.history = []
        self.itrial = 0

        self.log.info("Metrology run for tile %s: tolerance %.1f um (%s), "
                      "max_trial %s", self.tile, self.tolerance, self.metric,
                      self.max_trial if self.max_trial is not None else 'none')

        save_initial_angles(self.json_dir, self.tile, self.target_file,
                            use_measured=self.use_measured,
                            use_measured_positioners=self.use_measured_positioners)

        return self.json_path(0)

    def _expose_set(self, head, nexposure, exptime, header):
        """한 세트를 찍는다. auto_exposure 면 포화를 보고 노출을 줄여 다시 찍는다.
        반환: (경로들, 실제로 쓴 노출시간)"""
        from astropy.io import fits
        for attempt in range(self.max_retry + 1):
            cam = dict(self.camera); cam.pop('exptime', None)
            paths = mtlexp(exptime, data_dir=self.data_dir, head=head, nexposure=nexposure,
                           extra_header=header, **cam)
            if not self.auto_exposure:
                return paths, exptime
            nsat = max(int((fits.getdata(p) >= self.sat_level).sum()) for p in paths)
            if nsat <= self.sat_max_pixels or attempt == self.max_retry:
                if nsat > self.sat_max_pixels:
                    self.log.warning("%s: still %d saturated pixel(s) at %.4g ms after %d retries",
                                     head, nsat, exptime, attempt)
                return paths, exptime
            self.log.info("%s: %d saturated pixel(s) at %.4g ms -> re-exposing at %.4g ms",
                          head, nsat, exptime, exptime*self.exposure_factor)
            exptime *= self.exposure_factor
        return paths, exptime

    def expose(self, itrial):
        """이 trial의 이미지를 찍는다. fiber 노출 뒤에 fiducial 전용 세트를 이어 찍는다."""
        header = {'TILE': (self.tile, 'metrology tile'),
                  'MTLTRIAL': (itrial, 'metrology trial number')}
        paths, self.camera['exptime'] = self._expose_set(
            self.image_head(itrial), self.nexposure, self.camera['exptime'], header)
        for k, (head, texp) in enumerate(zip(self.fid_image_heads(itrial), self.fid_exptimes)):
            p, self.fid_exptimes[k] = self._expose_set(
                head, self.fid_nexposure, texp, dict(header, FIDSET=(k, 'fiducial exposure set')))
            paths += p
        return paths

    def analyze(self, itrial):
        """이 trial 이미지를 읽어 위치 오차와 각도를 구하고 json에 저장한다."""
        return mtlcal(data_dir=self.data_dir
                      , head=self.image_head(itrial)
                      , mode=self.mode
                      , threshold=self.threshold
                      , nwindow=self.nwindow
                      , niter_recenter=self.niter_recenter
                      , apply_pinhole_offset=self.apply_pinhole_offset
                      , use_measured=self.use_measured
                      , use_measured_positioners=self.use_measured_positioners
                      , finder=self.finder
                      , finder_opts=self.finder_opts
                      , background=self.background
                      , background_opts=self.background_opts
                      , nexposure=self.nexposure
                      , fid_head=self.fid_image_heads(itrial) or None
                      , fid_nexposure=self.fid_nexposure
                      , model=self.model
                      , magnification=self.magnification
                      , sat_level=self.sat_level
                      , fid_min_peak=self.fid_min_peak
                      , n_extra=self.n_extra
                      , min_dist=self.min_dist
                      , target_file=self.target_file
                      , json_dir=self.json_dir
                      , target_name=self.tile
                      , itrial=itrial)

    def error(self, dx, dy):
        """fiber(앞쪽 nfib개)의 위치 오차 (max, median) [um]."""
        dist = np.sqrt(dx[:self.nfib]**2 + dy[:self.nfib]**2)*1e3
        dist = dist[np.isfinite(dist)]                          # 끊어진 fiber (NaN) 는 뺀다
        return float(dist.max()), float(np.median(dist))

    def trial(self, expose=True):
        """다음 trial 한 번: 촬영 + 계산 + json 저장.

        expose=False면 이미 찍혀 있는 같은 이름의 이미지로 계산만 다시 한다.
        """
        itrial = self.itrial + 1

        if self.max_trial is not None and itrial > self.max_trial:
            self.log.warning("Trial %d exceeds max_trial %d", itrial, self.max_trial)

        images = self.expose(itrial) if expose else self.image_paths(itrial)
        dx, dy, _, _ = self.analyze(itrial)

        err_max, err_median = self.error(dx, dy)
        err = err_max if self.metric == 'max' else err_median

        result = TrialResult(itrial=itrial
                             , json=self.json_path(itrial)
                             , offsets=self.offset_path(itrial)
                             , err_max=err_max
                             , err_median=err_median
                             , converged=err <= self.tolerance
                             , dx=dx, dy=dy
                             , images=list(images))

        self.itrial = itrial
        self.history.append(result)

        self.log.info("Trial %d: fiber error max %.1f um, median %.1f um -> %s",
                      itrial, err_max, err_median,
                      "converged" if result.converged else "one more trial")

        return result

    def result(self):
        """지금까지의 history로 run 전체 결과를 만든다."""
        last = self.history[-1] if self.history else None

        out = RunResult(tile=self.tile
                        , converged=self.converged
                        , ntrial=self.itrial
                        , json=last.json if last else self.json_path(0)
                        , err_max=last.err_max if last else float('nan')
                        , err_median=last.err_median if last else float('nan')
                        , history=list(self.history))

        if out.converged:
            self.log.info("Tile %s converged after %d trial(s): "
                          "max %.1f um, median %.1f um",
                          out.tile, out.ntrial, out.err_max, out.err_median)
        else:
            self.log.warning("Tile %s did NOT converge in %d trial(s): "
                             "max %.1f um, median %.1f um (tolerance %.1f um)",
                             out.tile, out.ntrial, out.err_max, out.err_median,
                             self.tolerance)

        return out
