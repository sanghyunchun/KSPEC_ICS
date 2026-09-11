"""노출(mtlexp)과 계산(mtlcal)을 묶어 metrology를 한 바퀴씩 돌린다.

metrology 한 바퀴(trial)는

    1. 카메라로 nexposure장 촬영              (mtlexp)
    2. 이미지에서 fiber 위치를 재고 각도 계산   (mtlcal)
    3. 각도 json 저장

이고, 외부 컴퓨터는 그 json으로 positioner를 옮긴 뒤 다음 trial을 부른다. 실제로
fiber를 옮기는 일은 이 패키지 밖의 일이므로, 여기서는 trial 하나를 온전히 돌리고
"각도 json 경로"와 "지금 위치 오차가 얼마인지"만 돌려준다.

쓰는 법 (외부 컴퓨터에서):

    from kspec_metrology.mtlrun import MetrologyRun

    run = MetrologyRun(target_file='/path/to/target.info',
                       data_dir='./MTL/data/', json_dir='./MTL/json/',
                       exptime=0.1, tolerance=10., max_trial=5)

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
        mode        : findpeak의 peak 검출 방식. 'Predict' 또는 'Raw'
        threshold   : 'Raw' mode의 검출 문턱값
        exptime, gain, offset, readmode, usb_traffic : 카메라 설정
        tile        : 파일 이름에 쓸 타일 이름. None이면 target 파일에서 읽는다
    """

    def __init__(self
                 , target_file=None
                 , data_dir='./MTL/data/'
                 , json_dir='./MTL/json/'
                 , tolerance=10.
                 , metric='max'
                 , max_trial=5
                 , nexposure=1
                 , mode='Predict'
                 , threshold=3e3
                 , exptime=0.1
                 , gain=10
                 , offset=30
                 , readmode=1
                 , usb_traffic=40
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

        self.camera = dict(exptime=exptime, gain=gain, offset=offset,
                           readmode=readmode, usb_traffic=usb_traffic)

        self.nfib = len(cfg.fiber_ids())

        self.history = []
        self.itrial = 0          # 지금까지 끝낸 trial 번호

    #---경로-------------------------------------------------------------------
    def image_head(self, itrial):
        """이 trial 이미지의 head. mtlexp와 mtlcal에 같은 값이 들어간다."""
        return naming.image_head(self.tile, itrial)

    def image_paths(self, itrial):
        return naming.image_paths(self.data_dir, self.tile, itrial, self.nexposure)

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

        save_initial_angles(self.json_dir, self.tile, self.target_file)

        return self.json_path(0)

    def expose(self, itrial):
        """이 trial의 이미지를 찍는다."""
        return mtlexp(data_dir=self.data_dir
                      , head=self.image_head(itrial)
                      , nexposure=self.nexposure
                      , extra_header={'TILE': (self.tile, 'metrology tile'),
                                      'MTLTRIAL': (itrial, 'metrology trial number')}
                      , **self.camera)

    def analyze(self, itrial):
        """이 trial 이미지를 읽어 위치 오차와 각도를 구하고 json에 저장한다."""
        return mtlcal(data_dir=self.data_dir
                      , head=self.image_head(itrial)
                      , mode=self.mode
                      , threshold=self.threshold
                      , nexposure=self.nexposure
                      , target_file=self.target_file
                      , json_dir=self.json_dir
                      , target_name=self.tile
                      , itrial=itrial)

    def error(self, dx, dy):
        """fiber(앞쪽 nfib개)의 위치 오차 (max, median) [um]."""
        dist = np.sqrt(dx[:self.nfib]**2 + dy[:self.nfib]**2)*1e3
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
