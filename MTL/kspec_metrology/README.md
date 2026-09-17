# kspec_metrology

KSPEC 초점면 metrology. QHY 카메라로 촬영해 fiber 위치를 재고, positioner를
목표 위치로 옮기기 위한 보정 각도를 계산한다.

metrology 한 바퀴(trial)는

1. 카메라로 `nexposure`장 촬영 (`exposure/mtlexp`)
2. 이미지에서 fiber 위치를 재고 각도 계산 (`analysis/mtlcal`)
3. 각도 json 저장

이고, positioner를 실제로 옮기는 일은 이 패키지 밖에서 한다.

## 설치

Python **3.11 이상**이 필요하다.

```bash
poetry install
```

poetry를 쓰지 않는다면:

```bash
pip install .
```

### 의존성

| 패키지 | 최소 버전 |
|---|---|
| python | 3.11 |
| numpy | 1.24 |
| scipy | 1.11 |
| astropy | 5.3 |
| photutils | 1.9 |

상한은 두지 않았다. 쓰는 API가 오래 안정적인 코어뿐이라
numpy 1↔2, astropy 7↔8, photutils 2↔3 경계에서 모두 동작을 확인했다.

### 카메라 SDK

`kspec_metrology/lib/libqhyccd.so` 는 QHY가 제공하는 SDK 바이너리이고
저장소에 함께 들어 있다. `exposure/qhyccd.py` 가 패키지 기준 상대경로로
로드하므로 별도 설정은 필요 없다.

카메라 없이 분석만 할 경우 `exposure/` 를 쓰지 않으면 되고, 이때 SDK도
필요 없다.

## 사용법

```python
from kspec_metrology.mtlrun import MetrologyRun

run = MetrologyRun(target_file='/path/to/target.info',
                   data_dir='./MTL/data/', json_dir='./MTL/json/',
                   exptime=0.1, tolerance=10., max_trial=5)

move(run.start())                 # Trial 0 json = 관측 전 목표 각도

while run.should_continue:
    res = run.trial()             # 촬영 + 계산 + json 저장
    move(res.json)                # 이동은 외부에서

summary = run.result()
summary.converged                      # 허용 오차 안에 들어왔는가
summary.ntrial                         # 실제로 돈 trial 수
summary.err_max, summary.err_median    # 마지막 fiber 위치 오차 [um]
```

## 출력 형식

trial마다 `{json_dir}/{tile}_MetrologyTrial_{itrial}.json` 이 생긴다.
`itrial = 0` 은 관측 전 목표 각도다.

key는 **`{hole ID}_{arm}`** 이다. `_a` 는 alpha arm, `_b` 는 beta arm이고,
hole ID는 `Fiber_Configuration` 표의 ID다. 값은 degree이며 부호는
positioner 제어 규약에 맞춰 뒤집혀 있다 (출력 각도 = -계산각).

```json
{
  "A1_a": -110.2651,
  "A1_b": -143.6884,
  "A2_a": -136.8461,
  "A2_b": -102.0370,
  "A3_a": -252.4821,
  "A3_b": -57.0641
}
```

순서는 `Fiber_Configuration` 표에 positioner가 적힌 순서, 즉 target 파일의
fiber 순서를 따른다.

> **0.3.0에서 바뀐 점** — 이전에는 key가 `axis1`, `axis2`, ... 형식이었고
> 순서도 axis 번호 순이었다. axis 번호 매칭은 완전히 제거되었으므로
> 0.2.x가 만든 json은 읽을 수 없다. Trial 0부터 다시 시작해야 한다.

## 설정

fiber 구성은 `analysis/fiber_config.py` 에서 정한다. fiber 개수와 arm 길이,
출력 key가 모두 여기서 나온다.

### 어떤 홀을 쓰는가

`analysis/Fiber_Configuration_250415.txt` 의 `FiducialFlag` 를 그대로 따른다.

| FiducialFlag | 쓰임 |
|---|---|
| `0` | positioner (fiber). `load_fibers()` 가 **표에 적힌 순서대로** 전부 읽는다 |
| `1` | fiducial. `FIDUCIAL_EXCLUDE` 에 적은 ID만 빼고 전부 쓴다 |
| `-9` | 쓰지 않음 |

즉 fiber를 넣고 빼려면 표의 `FiducialFlag` 를 고치면 되고, `fiber_config.py`
는 건드릴 필요가 없다. 현재 구성은 positioner 151개 + fiducial 30개다.
positioner를 꽂지 않은 홀은 행을 지우지 말고 `-9` 로 두는 편이 낫다. 전체 홀
지도가 남아 어느 자리가 비었는지 보이고, `-9` 행은 positioner 목록
(`fiber_config.load_fibers`)과 fiducial 목록(`mtlcal.load_configuration`)
양쪽에서 걸러진다.

**표의 순서가 곧 `object.info` 의 `xp`, `yp` 순서**이고 출력 json의 key 순서도
같다. 표를 건드리면 target 파일도 같은 순서로 다시 만들어야 한다. `xp` 가
모자라면 바로 예외가 나지만, **남으면 앞에서 잘라 쓰면서 조용히 지나간다** —
positioner를 줄였는데 예전 target 파일을 그대로 쓰면 엉뚱한 fiber에 엉뚱한
목표가 붙는다.

### 설정이 여러 개일 때

표의 기본 위치는 패키지 안(`analysis/Fiber_Configuration_250415.txt`)이다.
설정을 바꿔 가며 쓸 거면 표를 패키지 밖에 이름 붙여 따로 두고
`KSPEC_FIBER_TABLE` 로 고르는 편이 낫다.

```bash
KSPEC_FIBER_TABLE=~/configs/Fiber_Configuration_phase1.txt \
    python -m kspec_metrology.run_mock --image-dir /받은/폴더
```

패키지 안의 파일을 덮어쓰면 `pip install` 때 날아가고, 지금 어느 설정으로 돌고
있는지도 보이지 않는다. 지정한 파일이 없으면 import 시점에 바로 예외가 난다.

어느 표가 실제로 쓰였는지는 `mtlcal` 이 로그에 남긴다.

```
INFO Fiber table /경로/Fiber_Configuration_phase1.txt: 51 positioners + 30 fiducials
```

> mock 생성기(`image_simulation`)와 분석이 **같은 표**를 봐야 한다. 둘이 다른
> 표를 보면 spot 개수가 어긋나 fiber 매칭이 깨진다. 패키지가 pip으로 설치돼
> 있으면 `sys.path` 순서에 따라 설치본 표가 먼저 잡힐 수 있으니,
> `cfg.FIBER_TABLE_PATH` 를 찍어 확인하거나 `KSPEC_FIBER_TABLE` 로 양쪽을
> 못박아 두는 것이 안전하다.

### arm 길이

측정값이 없는 positioner는 설계값 `DEFAULT_ARM = (5.2, 11.6)` mm 를 쓴다.
측정된 것만 `ARM_OVERRIDES` 에 ID별로 적어 주면 그 값이 우선한다.

```python
DEFAULT_ARM = (5.2, 11.6)

ARM_OVERRIDES = {
    "B5": (5.13, 11.35),
    "C2": (5.29, 11.36),
}
```

### 카메라 배율

`analysis/utils.py` 의 `CAMERA2FOCAL_M` 이 camera -> focal 배율 초기값이다.
`matchfiber` 는 회전과 offset만 훑고 배율은 맞추지 않으므로, 이 값이 실제와
몇 % 이상 어긋나면 시야 가장자리에서 fiber 매칭이 어긋난다. 지금은 mock
이미지(Zemax 설계 광학계) 기준인 `-8.4675` 로 맞춰져 있으니, 실카메라 배율이
확정되면 이 상수를 바꿔야 한다.

### peak 측정 창

`nwindow` (기본 40) 는 center of mass를 잴 crop 반폭 [pixel] 이다. 이 창 안에
이웃 spot이 들어오면 무게중심이 끌려가므로 fiber 최소 이격 거리에 맞춰야 한다.

```
nwindow  <  최소이격[mm] / (2 x 3.76e-3 [mm/px] x |배율|)
```

최소 이격 3 mm 기준이면 `nwindow <= 40` 이다. `mtlcal()` 과 `MetrologyRun()`
양쪽에 인자로 열려 있다.

### target 파일 경로

`fiber_config.TARGET_INFO_PATH` 의 기본값은 관측 시스템 경로
(`/home/kspecmtl/work/KSPEC_ICS/MTL/target/object.info`) 이므로, 다른
환경에서는 `target_file` 인자로 직접 넘겨야 한다.

## mock 데이터로 돌려보기

카메라 없이 분석 전체를 돌려 볼 수 있는 mock 한 세트가 `kspec_metrology/tmp/`
에 들어 있다.

```bash
python -m kspec_metrology.run_mock --image-dir /이미지를/받은/폴더
```

붙여 쓰는 방법은 두 층이고 `--via` 로 둘 다 돌려볼 수 있다. 나오는 각도 json은
완전히 같다.

**`--via mtlcal` (기본)** — 이미지 한 벌을 분석하는 최소 단위.

```python
from kspec_metrology.analysis.mtlcal import mtlcal
from kspec_metrology import naming

dx, dy, angle_rot, angle_cum = mtlcal(
    data_dir='/fits가_있는_폴더/',
    head=naming.image_head('test', 1),      # test_MetrologyTrial_1_
    target_file='/경로/object.info',
    json_dir='./out', target_name='test', itrial=1)
```

**`--via metrologyrun`** — 실제 운용 진입점. 이식할 때는 이 형태를 그대로 두고
`expose=True` 로만 바꾸면 된다 (그때부터 카메라로 직접 찍는다).

```python
from kspec_metrology.mtlrun import MetrologyRun

run = MetrologyRun(target_file='/경로/object.info',   # 폴더가 아니라 파일 경로
                   data_dir='/fits가_있는_폴더/',
                   json_dir='./out')
run.start()                        # Trial 0 = 관측 전 목표 각도
res = run.trial(expose=False)      # 촬영 생략. 운용에서는 expose=True
res.err_max, res.err_median        # fiber 위치 오차 [um]
```

`tile`은 `object.info`의 `tile_id`에서 자동으로 읽고, `mode`/`nwindow` 등은
기본값이 mock에 맞게 되어 있어 따로 줄 필요가 없다.

mock 이미지(`.fits`)는 416 MB라 저장소에 넣지 않고 따로 공유하고,
`object.info`는 저장소에 함께 있다. 자세한 것은
`kspec_metrology/tmp/README.md` 참고.

## 구조

```
kspec_metrology/
  mtlrun.py            trial 한 바퀴 묶기 (MetrologyRun)
  naming.py            이미지/json 파일 이름 규칙
  run_mock.py          mock 데이터로 분석 전체를 돌려 보는 예제
  exposure/            QHY 카메라 제어와 촬영
  analysis/            peak 찾기, fiber 매칭, 왜곡 보정, 각도 계산
  logging/             로거
  lib/                 libqhyccd.so
  tmp/                 mock 데이터 (이미지는 별도 공유)
```
