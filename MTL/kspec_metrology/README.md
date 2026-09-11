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
  "B5_a": -243.0083,
  "B5_b": -40.9696,
  "C2_a": -214.8802,
  "C2_b": -82.1976,
  "D0_a": -56.4390,
  "D0_b": -122.4306
}
```

순서는 `fiber_config.FIBERS` 표 순서, 즉 target 파일의 fiber 순서를 따른다.

> **0.3.0에서 바뀐 점** — 이전에는 key가 `axis1`, `axis2`, ... 형식이었고
> 순서도 axis 번호 순이었다. axis 번호 매칭은 완전히 제거되었으므로
> 0.2.x가 만든 json은 읽을 수 없다. Trial 0부터 다시 시작해야 한다.

## 설정

fiber 구성이 바뀌면 `analysis/fiber_config.py` 의 `FIBERS` 표만 고치면 된다.
fiber 개수와 arm 길이, 출력 key가 모두 이 표에서 나온다.

```python
FIBERS = (
    # ID     arm1    arm2
    ("B5",   5.13,  11.35),
    ...
)
```

행의 순서는 target 파일(`object.info`, tile assign 파일)의 fiber 순서와
같아야 한다.

`fiber_config.TARGET_INFO_PATH` 의 기본값은 관측 시스템 경로
(`/home/kspecmtl/work/KSPEC_ICS/MTL/target/object.info`) 이므로, 다른
환경에서는 `target_file` 인자로 직접 넘겨야 한다.

## 구조

```
kspec_metrology/
  mtlrun.py            trial 한 바퀴 묶기 (MetrologyRun)
  naming.py            이미지/json 파일 이름 규칙
  exposure/            QHY 카메라 제어와 촬영
  analysis/            peak 찾기, fiber 매칭, 왜곡 보정, 각도 계산
  logging/             로거
  lib/                 libqhyccd.so
```
