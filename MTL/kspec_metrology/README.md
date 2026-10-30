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

### 다른 컴퓨터에 처음 설치 (git clone)

```bash
git clone https://github.com/wheretogo33/kspec_metrology.git     # 또는 git@github.com:wheretogo33/kspec_metrology.git
cd kspec_metrology
pip install -e .                      # editable: 저장소의 코드를 그대로 쓴다 (git pull 이 바로 반영)
python -m kspec_metrology.check_env   # numpy, scipy, astropy, photutils, sep 확인
```

`pip install .` (editable 아님) 은 site-packages 에 복사본을 두므로 `git pull` 뒤에 다시
설치해야 하고, `fiber_config.py` 를 고쳐도 반영되지 않는다. editable 을 권한다.
poetry 를 쓰면 `poetry install`.

### 업데이트 (GitHub 에 올라온 변경만 받기)

```bash
cd kspec_metrology
git pull
```

추적되는 파일(예: `analysis/fiber_config.py` 의 `FIBER_EXCLUDE` 목록)을 그 컴퓨터에서 직접
고쳤으면 pull 이 충돌할 수 있다. 그런 설정은 파일 대신 환경변수(`KSPEC_FIBER_EXCLUDE`,
`KSPEC_FIBER_FIXED`, `KSPEC_SKY_FIBERS`, `KSPEC_ANGLE_SIGN` …)로 주거나, 고친 파일을
`git stash` → `git pull` → `git stash pop` 으로 넘긴다. 결과·이미지는 저장소 밖 폴더에 둔다.

### 시험 촬영 (fiducial 밝기 조정 등)

```bash
python kspec_metrology/notebooks/take_exposure.py --exptime 10 --out /data/fid_10ms.fits          # 노출 [ms]
python kspec_metrology/notebooks/take_exposure.py --exptime 2 10 --out '/data/{date}_fid_{ms}ms.fits'
python kspec_metrology/notebooks/take_exposure.py --fiber 400 --fid 2 10 --out /data/calib_t1   # 세트: fiber 1장 + fiducial 2장
```

세트 촬영은 `calib_t1_fib_400ms_0.fits`, `calib_t1_fid1_2ms_0.fits`, `calib_t1_fid2_10ms_0.fits` 로 저장하고
노트북에 붙여 넣을 `FIBER_IMAGE` / `FID_IMAGES` 줄을 끝에 찍어 준다.

MetrologyRun 과 같은 카메라 설정으로 찍어 원하는 이름으로 저장한다 (`{ms}`, `{date}`, `{time}`,
`{i}` 사용 가능; 분석 함수가 `...0.fits` 꼴을 기대하므로 `_0` 이 자동으로 붙는다). 찍은 뒤
최대 화소값과 포화 화소 수를 바로 보여 준다. `--dry-run` 은 이름만 확인.

### 의존성

| 패키지 | 최소 버전 |
|---|---|
| python | 3.11 |
| numpy | 1.24 |
| scipy | 1.11 |
| astropy | 5.3 |
| photutils | 1.9 |
| sep | 1.2 |

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
                   exptime=10., fid_exptime=[1., 10.], tolerance=10., max_trial=10)   # [ms]

move(run.start())                 # Trial 0 json = 관측 전 목표 각도

while run.should_continue:
    res = run.trial()             # 촬영 + 계산 + json 저장
    move(res.json)                # 이동은 외부에서

summary = run.result()
summary.converged                      # 허용 오차 안에 들어왔는가
summary.ntrial                         # 실제로 돈 trial 수
summary.err_max, summary.err_median    # 마지막 fiber 위치 오차 [um]
```

노출시간(`exptime`, `fid_exptime`)의 단위는 **ms** 다 (카메라 SDK 에는 µs 로 바꿔 넘긴다).

## 출력 형식

trial마다 `{json_dir}/{tile}_MetrologyTrial_{itrial}.json` 이 생긴다.
`itrial = 0` 은 관측 전 목표 각도다. 같은 자리에
`{tile}_MetrologyTrial_{itrial}_offset.txt` 도 생기는데, fiber 마다 남은 위치
오차 (측정 − 목표, µm) 와 이번 trial 의 회전량 (deg) 을 적은 표다
(`res.offsets`). positioner 를 옮기는 쪽이 "얼마나 더 가야 하는지" 를 바로
보려면 이 파일을 쓰고, 누적 각도는 json 을 쓴다.

```
# ID       dx[um]    dy[um]  dalpha[deg]   dbeta[deg]
  C4        -12.3      40.1       0.3121      -0.1180
```

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

`analysis/Fiber_Configuration_config73.txt` 의 `FiducialFlag` 를 그대로 따른다.

| FiducialFlag | 쓰임 |
|---|---|
| `0` | positioner (fiber). `load_fibers()` 가 **표에 적힌 순서대로** 전부 읽는다 |
| `1` | fiducial. `FIDUCIAL_EXCLUDE` 에 적은 ID만 빼고 전부 쓴다 |
| `-9` | 쓰지 않음 |

즉 fiber를 넣고 빼려면 표의 `FiducialFlag` 를 고치면 되고, `fiber_config.py`
는 건드릴 필요가 없다. 현재 기본 구성(`config73`, 홀 간격 d = 19 mm)은
positioner 73개 + fiducial 30개 + 미장착 45개다.
positioner를 꽂지 않은 홀은 행을 지우지 말고 `-9` 로 두는 편이 낫다. 전체 홀
지도가 남아 어느 자리가 비었는지 보이고, `-9` 행은 positioner 목록
(`fiber_config.load_fibers`)과 fiducial 목록(`mtlcal.load_configuration`)
양쪽에서 걸러진다.

**표의 순서가 곧 `object.info` 의 `xp`, `yp` 순서**이고 출력 json의 key 순서도
같다. 표를 건드리면 target 파일도 같은 순서로 다시 만들어야 한다. `xp` 가
모자라면 바로 예외가 나지만, **남으면 앞에서 잘라 쓰면서 조용히 지나간다** —
positioner를 줄였는데 예전 target 파일을 그대로 쓰면 엉뚱한 fiber에 엉뚱한
목표가 붙는다.

### 설계값 대신 실측값 쓰기

실험으로 plate 중심 기준 실제 기하를 재면 세 가지를 설계값 대신 쓸 수 있다.

1. positioner 회전 중심 위치
2. fiducial 핀홀 위치
3. positioner arm 길이

셋을 `analysis/Measured_Geometry.txt` 한 파일에 홀 ID로 적는다. 아직 안 잰
값은 `-` 로 두면 **그 항목만** 설계값을 쓰므로, 측정이 끝나는 대로 한 줄씩
채워 나가면 된다. 같은 폴더의 `Measured_Geometry.txt.template` 을 복사해
쓰면 된다 (기본 표의 홀이 설계값 주석과 함께 들어 있다).

```
# ID     X          Y        arm1    arm2
C4      -9.4812    82.3105   5.23   11.57
D2       -          -        5.19   11.62     # arm만 쟀을 때
B3     -18.9771    98.7410   -      -         # fiducial 위치만
```

#### positioner arm 길이는 개체별 측정표가 따로 있다

제작된 positioner 전체(1~140번)를 잰 표가 `analysis/Positioner_Arm_Table.txt`
에 들어 있다 (`final_alpha`, `final_beta` 열을 쓴다. 설계값 대비 alpha 최대
58 um, beta 최대 79 um 차이). 어느 번호가 어느 홀에 꽂혔는지는 설치가 끝나야
알 수 있으므로 `analysis/Positioner_Map.txt` 에 따로 적는다
(`Positioner_Map.txt.template` 복사해서 사용).

```
# ID   positioner
C4     17
C5     42
D2     -        # 아직 모르는 홀
```

arm 길이의 우선순위는 뒤로 갈수록 높다.

1. 설계값 `DEFAULT_ARM` / `ARM_OVERRIDES`
2. **개체 측정표** (`Positioner_Arm_Table` + `Positioner_Map`)
3. `Measured_Geometry.txt` 의 `arm1`, `arm2` 열 (손으로 적는 최종 보정)

설치 맵이 없거나 그 홀이 `-` 면 설계값을 그대로 쓴다. 두 파일 모두
`KSPEC_POSITIONER_ARM_TABLE` / `KSPEC_POSITIONER_MAP` 로 경로를 바꿀 수 있다.

**기본은 켜져 있다** (2026-10 부터). 패키지에 든 `Measured_Geometry.txt` 에는
새 plate(d = 19 mm) 의 fiducial 핀홀 위치 30개가 들어 있다
(`Fiducial_Pinhole_261017.txt`, plate 영상에서 측정, 1σ 약 20 µm). 끄는 방법은
두 가지다.

```bash
KSPEC_USE_MEASURED=0 python ...          # 환경변수
```
```python
mtlcal(..., use_measured=False)          # 호출 인자 (환경변수보다 우선)
```

파일 경로는 `KSPEC_MEASURED_GEOMETRY` 로 바꿀 수 있다. 파일이 없으면 인자로
명시해 켠 경우(`use_measured=True`)에만 예외가 나고, 기본 상태에서는 경고만
남기고 설계값을 쓴다. 표에 없는 홀이 적혀 있으면 경고만 남기고 무시한다. 몇 개가
교체됐는지는 로그에 남는다.

실측 좌표가 설계 좌표에서 1 mm (`fiber_config.MEASURED_MAX_DEV`) 넘게 떨어져
있으면 **다른 plate 의 파일로 보고 예외를 낸다.** 표를 바꿔도 fiducial ID 가
상당수 겹쳐서 옛 plate 의 값이 조용히 적용될 수 있기 때문이다. 옛 표
(`Fiber_Configuration_250415.txt` 등) 로 mock 을 돌릴 때는 이 검사에 걸리므로
`use_measured=False` (run_mock 은 기본이 꺼져 있다) 로 돌린다.

```
INFO Measured geometry /경로/Measured_Geometry.txt: 2/103 holes replaced
```

실측 위치를 적은 fiducial 에는 핀홀 오프셋을 **더하지 않는다** (이중 계산이
되므로). 위치를 아직 안 잰 fiducial 에만 오프셋이 적용된다.

### 각도 부호·영점과 positioner 규약

계산은 반시계(CCW) 기준으로 theta ∈ [0°, 360°), elbow-down 으로 phi ∈ [0°, 180°] 인
**기하각**을 구하고, 이 패키지가 내보내고 받는 각도는 모두 positioner **명령각**이다.

    명령각 = ANGLE_SIGN × 기하각 − ANGLE_ZERO

- `fiber_config.ANGLE_SIGN` 기본 `(-1, -1)` (2026-10-27 본 장비에서 확인): positioner 는 기하각의
  반대 방향으로 돈다. ICS `fbpoffset` 으로 trial 1 → 2 → 3 을 움직였을 때 오차가 0.8 → 1.6 → 2.9 mm
  로 늘었고, 측정 위치에서 json 의 −1 배를 돌린 예측만 실측과 0.2 mm 안에서 맞았다.
  2026-10-23 실험실(다른 제어 소프트웨어)에서는 `(1, 1)` 이었다.
- `fiber_config.ANGLE_ZERO` 기본 `(-30, -150)`: 기하학적으로 (alpha, beta) = (30°, 150°) 인 자세가
  positioner 제어의 **(0, 0) 초기 위치**다 (부호가 −1 이므로 영점은 −30, −150). json 의 누적각,
  offset 표, `lab.xy2ab` 의 출력과 target 파일의 alpha/beta, 각도 json, `lab.make_target(angles=)`
  의 입력은 모두 명령각이다 (초기 위치 = `angles=(0, 0)`). 이번 trial 회전량(dalpha, dbeta)은
  차이라서 영점과 무관하다.
- 출력하는 **절대** alpha(Trial 0, `lab.xy2ab`)는 기하각을 [0°, 360°) 로 둔 뒤 명령각으로 바꾼다
  (`fiber_config.command_alpha`; 명령 alpha 는 (−330°, 30°], FBP 경로 끝각과 같은 범위). 회전량(dalpha)은 차이라서
  (−180°, 180°]. 2026-10-29 이전에는 (−180°, 180°] 로 접어 기하각 210..360° 인 자세가 +30..+180° 로 나갔고,
  fbpoffset 은 절대각으로 움직이므로 그 positioner 가 반대 방향으로 한 바퀴 돌았다 (KSPEC_ICS 836ea99 에서 수정).
- **리밋 여유와 alpha 해 선택** (2026-10-30, `fiber_config.ALPHA_MARGIN`/`BETA_MARGIN`; `KSPEC_ALPHA_MARGIN`="90,90",
  `KSPEC_BETA_MARGIN`="30,30"): positioner 리밋을 한 바퀴 범위에 여유를 더한 alpha (−420°, 120°], beta [−60°, 180°] 로
  둔다 (`alpha_cmd_range`, `BETA_RANGE`; FBP 쪽 리밋과 같아야 한다). alpha 는 360° 돌면 같은 위치라 한 xy 에 해가 여럿이므로
  (5 = 365 = −355), 누적 alpha 는 직전 각도에서 **가장 적게 도는 해**를 고르고, 그 해가 리밋 밖이면 리밋에서 자른다
  (`alpha_cum_in_range`, 경고; offset 표의 dalpha 는 실제 보낸 회전량). 반대로 도는 해(회전 180° 이상)를 대신 쓰는 선택은
  `KSPEC_ALPHA_OTHER_WAY=1` 로 켤 수 있지만 FBP 의 45° 이동 제한에 걸리므로 기본은 끔. 이전에는 누적 alpha 를
  (−330°, 30°] 로 wrap 해서 리밋을 조금만 넘어도 (tile01 J4: 16.50 + 13.98 = 30.48 → −329.52) positioner 가 반대로 한 바퀴
  도는 명령이 되었고 FBP 의 45° 이동 제한에도 걸렸다. Trial 0 의 절대 alpha(`command_alpha`, `lab.xy2ab`)는 그대로
  (−330°, 30°] 이므로 여유 구간에는 보정으로만 들어가고, 집으로 갈 때는 온 길대로 0 으로 간다.
- beta 명령각은 positioner raw −180..0 에 FBP 영점 150 을 더한 −30..150 이고, 이 패키지의 elbow-down 해(기하각
  0..180°)가 그대로 그 범위다. 여유를 더한 150..180 은 팔이 곧게 펴진 자세를 지나 elbow-up 으로 접히는 것이라
  elbow-down 목표에 도움이 되지 않는다. 위쪽 여유는 0 으로 두는 것이 안전하다 (`KSPEC_BETA_MARGIN`="30,0"); 아니면 아래
  도달 한계 보호가 그 쪽으로 가는 보정을 막아야 한다.
- **도달 한계 보호** (`fiber_config.REACH_MARGIN`, 기본 0.3 mm; `KSPEC_REACH_MARGIN`): 목표나 측정 위치가 회전
  중심에서 a₁+a₂−0.3 mm 보다 멀면 완전히 편 자세(beta 끝, alpha 는 그 방향)로 푼다. 거의 편 자세에서는 반지름이
  beta 에 둔감해서(phi 6° 에서 7 µm/°) 수백 µm 오차가 수십 도의 beta 보정이 되고, 표의 arm 길이와 실제가
  0.1–0.3 mm 만 달라도 trial 마다 보정이 커져 beta 가 범위를 넘고 positioner 가 날아간다 (2026-10-29 9111 의
  G3, M3, L5: 목표가 한계 22–108 µm 안쪽). 누적 beta 는 `BETA_RANGE` (기본 [−60, 180]) 로 잘라 둔다. 한계 근처 목표는
  남는 radial 오차(실제 arm 과 표의 차이, 0.1–0.2 mm)를 받아들여야 하며, tile 배정 때 도달 한계에서 0.5 mm 이상
  여유를 두는 것이 낫다.
- 부호가 틀리면 positioner 가 trial 마다 목표에서 **멀어진다** (오차가 1, 2, 3 배로 는다). 영점이
  틀리면 Trial 0 json 이 (0, 0) 이 아니다. 다른 규약이면 `KSPEC_ANGLE_SIGN`, `KSPEC_ANGLE_ZERO`
  또는 `fiber_config` 의 값.

### positioner 회전 중심 실측값 (arm scan) 쓰기 -- 별개 스위치

`analysis/Measured_Geometry.txt` 에는 fiducial 핀홀 실측 위치(2026-10-17)와 positioner 회전 중심
실측값(2026-10-27 arm scan, 37 개; 설계와의 차 중앙값 131 µm, 최대 298 µm, 원 fit rms 중앙값 11 µm)
이 함께 들어 있다. 둘은 **별개 스위치** 로 켠다.

| 항목 | 스위치 | 기본 |
|---|---|---|
| fiducial 핀홀 실측 위치, arm 길이 측정표 | `use_measured` / `KSPEC_USE_MEASURED` | 켜짐 |
| positioner 회전 중심 실측값 | `use_measured_positioners` / `KSPEC_USE_MEASURED_POSITIONERS` / `fiber_config.USE_MEASURED_POSITIONERS` | 켜짐 (2026-10-27 부터) |

끄는 방법: `MetrologyRun(..., use_measured_positioners=False)`, `mtlcal(..., use_measured_positioners=False)`,
`lab.measure(..., use_measured_positioners=False)`, 환경변수 `KSPEC_USE_MEASURED_POSITIONERS=0`, 노트북 설정 셀의
`MEASURED_POSITIONERS = False`, 또는 ICS `mtlstart` 메시지의 `use_measured_positioners: false`. 기본값을 바꾸려면
`fiber_config.USE_MEASURED_POSITIONERS` 한 줄. 로그 `Measured geometry ...: 67/103 holes replaced (positioner
centres ON)` 이면 켜진 것이고, `30/103 ... (positioner centres OFF, 37 measured but not used)` 이면 꺼진 것이다.

켜면 Trial 0 의 목표 각도와 각 trial 의 회전량이 실측 중심 기준으로 계산되므로, 첫 trial 의 fiber−target
오차가 설계 중심일 때보다 작아야 한다. 비교해 보려면 같은 배치를 꺼짐으로 한 번 더 돌린다.

### fiducial 찾기 (기준 칩 좌표)

fiducial 은 초점면에 고정되어 있고 카메라도 고정이므로 칩 좌표가 trial 사이에 거의 변하지
않는다. 그래서 2026-10-27 부터 fiducial 식별은 두 단계다.

1. **기준 칩 좌표가 있으면** (`{json_dir}/{tile}_MetrologyTrial_{k-1}_fid.npy`, 없으면 run 과 무관한
   `{json_dir}/Fiducial_Chip_Positions.npy`; `KSPEC_FIDUCIAL_CHIP_REF` 로 경로 변경) 세 노출(1 ms,
   10 ms, fiber 30 ms) 각각에서 fiducial 마다 기준 자리 반경 60 px (약 2 mm) 안의 **가장 가까운**
   검출을 그 fiducial 로 본다 (`measure_fiducials_ref`). 밝기는 쓰지 않으므로 fiber 나 sky 점이
   창에 들어와도 자리가 다르면 안 잡힌다. 카메라가 조금 움직였으면 검출 전체의 공통 이동량을
   먼저 빼므로 fiducial 간격(15 mm) 보다 작은 이동은 그대로 처리된다. 패턴 매칭·배율 초기값·검출
   수 상한이 모두 필요 없다.
2. **기준이 없거나 절반도 못 찾으면** 패턴 매칭 (`measure_fiducials`: 배율 초기값으로 옮긴 검출을
   설계 패턴에 회전·offset 격자 탐색으로 맞추고 affine 재적합) 으로 처음부터 찾는다. 성공하면
   그 좌표가 기준 파일로 저장되어 다음부터 1 로 간다.

어느 경로든 그 뒤는 같다. fiducial 마다 포화되지 않은 가장 밝은 노출을 고르고 (전용 노출 우선,
fiber 노출은 예비), 찾은 fiducial 로 왜곡 변환을 맞춘다. **fiducial 이 30 개 중 20 개
(`MIN_FIDUCIALS`) 이상 보이면 trial 은 계속 진행**하고 못 찾은 것은 경고와 함께 NaN 으로 둔다
(2026-10-27 이전에는 하나라도 없으면 실패였다). fit 잔차가 0.3 mm (`FID_RESID_MAX`) 를 넘는
fiducial 은 잘못 붙인 것(fiber 점 등)으로 보고 빼고 다시 맞춘다 (정상 잔차는 50 µm 수준).
그 뒤 매칭된 fiber 자리를 지우고 fiducial 을 한 번 더 찾아 변환을 다듬는데(cross_exclude), 이
2차 탐색이 실패하면 1차 결과를 그대로 쓴다.

실기 trial 3 영상으로 확인한 것: 기준이 없을 때와 있을 때 같은 좌표(0.00 px 차), 한 fiducial 을
세 노출에서 모두 지우면 29/30 으로 계속 진행, 그 자리 1.2 mm 옆에 가짜 점을 넣으면 잔차 850 µm
로 걸러짐, 기준을 40 px 옮겨 놓으면 공통 이동량으로 보정.

### 포화와 노출 자동 조정

`MetrologyRun(..., auto_exposure=True)` 면 찍은 이미지에 포화 화소가
`sat_max_pixels`(기본 0) 보다 많을 때 노출을 `exposure_factor`(0.5) 배로 줄여 다시
찍는다 (최대 `max_retry` 번; fiber 노출과 fiducial 세트 각각). 줄인 노출은 다음
trial 에도 쓴다. 분석 쪽에서는 fiducial 전용 노출에 안 보이는 fiducial 을 fiber
노출(포화되어 있어도)에서 가져오고(`fid_fallback_fiber`, 기본 True), 세트가
fiducial 을 일부만 담아도 된다 (가장 잘 맞은 세트의 affine 변환으로 다른 세트에서
다시 붙인다).

### calibration run (모든 arm 을 같은 각도로)

target 파일(object.info) 에 `xp`/`yp` 대신 각도를 적어도 된다: `{"alpha": [...], "beta": [...]}`
(positioner 순서, deg, 출력 규약) 또는 이 패키지의 각도 json 형식 (`"C4_a": ..`).
`load_configuration` 이 회전 중심(실측)과 arm 길이로 (x, y) 를 만든다. 따라서 모든 arm 을
같은 각도로 두는 calibration run 은 target 파일만 바꿔 끼우면 된다
(`lab.make_target(path, angles=(0, 0))` 으로 만들 수 있다; 명령각 (0, 0) = 초기 위치 = 기하각 (30, 150)).

### 어느 positioner 가 켜지는가 (분광기에 연결된 fiber, sky fiber, 고장난 positioner)

홀 ID 만 알면 된다. 2026-10-26 에 설치표(Positioner mapping_20261012 의 obj / sky 열)로 확정한
값이 패키지 기본값이다. **분광기에 연결된 fiber 는 43 개(obj 37 + sky 6)뿐이고 back-illumination
은 분광기에서 나오므로 이 43 개만 켜진다.** 설치표의 obj 가운데 G4 는 fiber 가 끊어져 그 대신 H3 를
쓴다. 나머지 positioner 30 개(고장나 고정된 25 + fiber 가 안 꽂힌 8)는 빛이 나지 않는다.

```python
# analysis/fiber_config.py (기본값)
FIBER_OBJ     = ['C4', 'C5', 'D2', 'D3', 'D4', 'D5', 'D7', 'E8', 'E9', 'F8', 'F9', 'G3', 'G5', 'G6',
                 'G9', 'H3', 'H4', 'H5', 'H6', 'H7', 'I3', 'I5', 'I6', 'I7', 'I8', 'J2', 'J3', 'J4', 'J5',
                 'K2', 'K3', 'K4', 'L3', 'L5', 'L6', 'L7', 'M3']     # 분광기 obj fiber 홀 (37, G4 대신 H3)
FIBER_FIXED   = ['G7', 'H8', 'J6']   # sky fiber 가 꽂힌 고장난 positioner: 켜져 있지만 움직이지 않음 (3)
SKY_FIBERS    = ['B7', 'H1', 'N7']   # 표에서 -9 인 홀의 sky fiber (3)
FIBER_EXCLUDE = (obj 도 FIXED 도 아닌 positioner 33 개, G4 포함)   # 빛이 안 나는 홀 (33)
```
(환경변수 `KSPEC_FIBER_EXCLUDE`, `KSPEC_FIBER_FIXED`, `KSPEC_SKY_FIBERS` 로 바꿀 수 있다.)
켜진 점 기대 수 = obj 37 + FIXED 3 + SKY 3 = 43 (fiducial 30 을 더하면 73), 매칭하는 fiber = 37.

- `FIBER_EXCLUDE` 의 positioner 는 이미지에서 찾지 않고 매칭에서 빠진다 (오차 NaN, 회전량 0,
  누적 각도는 직전 값). 표·object.info·json 의 73 개 순서는 그대로다.
- `FIBER_FIXED` 의 positioner 는 object.info 와 json 에 그대로 들어 있되(순서 유지) 목표
  매칭에서 빠진다 (오차 NaN, 회전량 0). 이미지에서는 켜져 있다고 보고 검출 개수에 센다.
- 매칭은 살아 있는 fiber 의 목표와 검출을 거리 합이 최소가 되게 일대일로 붙인다(할당 문제).
  목표에서 9 mm (`3*max_dist`) 안에 검출이 없는 fiber 는 이번 trial 에 못 잰 것으로 두고
  (NaN, 회전량 0) 경고한다. 할당하고 남은 검출 가운데 고정/sky 홀 중심에서 arm 길이 + 1 mm 안의
  것을 그 점으로 본다. 목표에서 3 mm 넘게 떨어진 매칭은 ID 와 함께 경고가 난다 (그 검출이
  고정/sky 홀 범위 안이면 그것도 적힌다).
- **첫 trial 뒤에 고정 점 자리를 파일로 적어 두는 것이 좋다.** 고정 positioner 와 sky fiber 는
  움직이지 않으므로 `lab.find_fixed_spots(res, out_path=cfg.FIXED_SPOTS_PATH)` 로
  `analysis/Fixed_Spots.txt` (`name X Y`) 를 만들면 그 자리 1.5 mm 안의 검출은 fiber 후보에서
  바로 빠지고, 살아 있는 fiber 가 목표에서 몇 mm 벗어나 있어도 고정 점과 헷갈리지 않는다
  (`Calibration_Run.ipynb` 2b 절). 파일을 패키지 밖에 두면 `KSPEC_FIXED_SPOTS` 로 가리킨다.
- 파일이 없을 때 남는 위험: 고정된 점이 어떤 살아 있는 fiber 의 목표에 그 fiber 의 진짜 spot
  보다 가까울 때 (첫 trial 에서 fiber 가 목표에서 mm 단위로 벗어나 있으면 생길 수 있다).
  `fiber - target` 이 큰 fiber 의 경고를 확인한다.

### 끊어진 fiber

fiber 가 끊어져 불이 안 들어오면 (또는 분광기에 연결되지 않아 back-illumination 이
안 되면) 표와 target 파일, json key 순서는 그대로 두고 그 fiber 만 제외한다 (positioner 는 그대로 꽂혀 있으므로 표에서 지우면 target
파일과 json 순서가 다 바뀐다).

가장 간단한 방법은 `analysis/fiber_config.py` 의 한 줄이다.

```python
FIBER_OBJ.remove('G4')                        # 끊어진 fiber 의 홀 ID 를 obj 목록에서 빼면 FIBER_EXCLUDE 에 들어간다
```

코드를 안 고치려면 환경변수로도 된다 (환경변수가 있으면 그것이 우선).

```bash
KSPEC_FIBER_EXCLUDE="C4,D2" python ...        # 환경변수
```
```python
from kspec_metrology.analysis import fiber_config as cfg
cfg.FIBER_EXCLUDE = ['C4', 'D2']              # import 뒤에 바꿔도 된다
```

제외된 fiber 는 이미지에서 찾지 않고(검출 기대 개수가 줄어든다) 매칭에서 빠진다.
결과에서는 위치 오차가 NaN, 회전량이 0 이고 누적 각도는 직전 값을 유지한다.
offset 표에는 `nan` 으로 적힌다. 표에 없는 ID 를 적으면 예외가 난다.

### 설정이 여러 개일 때

표의 기본 위치는 패키지 안(`analysis/Fiber_Configuration_config73.txt`)이다.
같이 들어 있는 표로 `Fiber_Configuration_250415.txt`(d = 16.8 mm, positioner
151개)와 `Fiber_Configuration_config55.txt`(d = 16.8 mm, 55개)가 있다.
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

기본은 실측값이다 (`use_measured` 기본 on). `analysis/Positioner_Map.txt` 에 어느 홀에 몇 번
positioner 가 꽂혔는지(2026-10-12 설치표) 적혀 있고, `analysis/Positioner_Arm_Table.txt` 의
그 번호 행(final_alpha, final_beta)이 arm1, arm2 가 된다. 73 개 모두 측정값이 있다.
positioner 를 바꿔 꽂으면 `Positioner_Map.txt` 의 번호만 고친다. 우선순위는
설계값 < Positioner_Map + Arm_Table < `Measured_Geometry.txt` 의 arm 열 (손으로 적는 최종 보정).

설계값은 `DEFAULT_ARM = (5.2, 11.6)` mm 이고, `use_measured=False` (또는 `KSPEC_USE_MEASURED=0`)
이면 그것을 쓴다 (`ARM_OVERRIDES` 에 ID 별로 적은 값이 있으면 그 값).

### Fiducial 핀홀 위치

fiducial은 홀 한가운데가 아니라 조금 치우쳐 박혀 있다. 그 치우친 양을 따로 재서
두 파일로 들고 있고, `load_configuration` 이 fiducial 기준 좌표를
**표의 홀 좌표 + (dx, dy)** 로 만든다. 이 좌표가 `fitdistortion` 의 기준이므로
빼먹으면 그만큼 왜곡 fit에 그대로 들어간다.

| 파일 | 내용 |
|---|---|
| `analysis/Fiducial_pinhole_loc.npz` | `index`, `dx`, `dy` [mm]. 측정값 |
| `analysis/Fiducial_pinhole_map.txt` | `index` 가 어느 Hole ID인지. **현장에서 손으로 고치는 파일** |

map 파일은 `index  ID` 두 칸이고 `#` 뒤는 주석이다. 핀홀을 옮기면 ID만 고치면
되고 코드는 건드릴 필요가 없다. 쓰지 않는 index는 ID를 `-` 로 두거나 줄을
지운다. 두 파일 중 하나라도 없으면 경고를 남기고 홀 좌표를 그대로 쓴다.

```
# index  ID
      1  A0     # X  -58.8000  Y  101.8446   dx  -0.0829  dy  +0.0112
      2  A6     ...
```

경로는 `KSPEC_FIDUCIAL_PINHOLE_MAP` / `KSPEC_FIDUCIAL_PINHOLE_LOC` 로 바꿀 수
있다.

**기본값은 `apply_pinhole_offset=False` 로 꺼져 있다.** 핀홀 위치는 plate마다
다시 재야 하는데, 표를 바꿔도 fiducial ID는 상당수 그대로라서 옛 plate의 값이
경고 없이 적용될 수 있기 때문이다 (지금 들어 있는 파일은 d = 16.8 mm plate
기준이고, 기본 표 `config73` 과는 fiducial 30개 중 25개가 ID만 겹친다).
쓰는 plate에서 측정한 파일로 갈아 끼운 뒤 켜면 된다.

```python
mtlcal(..., apply_pinhole_offset=True)
```

### fiber 와 fiducial 의 노출을 나눠 찍기

fiber 와 fiducial 의 밝기 차이가 커서 한 노출로는 한쪽이 포화되거나 안 보일 때
쓴다. `fid_exptime` 을 주면 fiber 노출(`exptime`) 뒤에 fiducial 전용 세트를
이어 찍고, 분석도 둘을 나눠 한다. **두 노출 사이에 카메라와 plate, positioner 가
움직이지 않았다고 가정한다.**

```python
# case 1: fiber t2, fiducial t1
run = MetrologyRun(..., exptime=2.0, fid_exptime=0.5)        # [ms]

# case 2: fiber t2, fiducial 을 두 노출로 (밝기 차이가 심한 fiducial 들)
run = MetrologyRun(..., exptime=2.0, fid_exptime=[0.5, 2.0])
```

분석 순서는 `mtlcal(..., fid_head=...)` 에 있다.

1. fiducial 세트마다 peak 을 찾아 설계 패턴에 매칭한다 (fiber 가 보이면
   fiber 목표까지 넣은 전체 패턴으로; fiducial 수 .. 전체 수 사이의 검출을
   받아들인다). 세트가 여럿이면 fiducial 마다 **포화되지 않은 것 중 가장 밝은
   세트** 를 쓰고, 전부 포화면 포화 화소가 가장 적은 세트를 쓴다 (`sat_level`,
   기본 65000; `fid_min_peak` 보다 어두운 검출은 피한다). 어느 세트를 몇 개
   썼는지 로그에 남는다.
2. 그 fiducial 로 camera → focal 변환을 맞춘다.
3. fiber 노출의 peak 을 그 변환으로 옮겨 목표 위치에 가장 가까운 것을 그 fiber
   로 본다.

이미지 이름은 fiber 가 `{tile}_MetrologyTrial_{i}_{j}.fits`, fiducial 세트가
`{tile}_MetrologyTrial_{i}_fid{k}_{j}.fits` 다 (`naming.fid_image_head`).
이미 찍어 둔 이미지로 계산만 하려면 `mtlcal(..., head=..., fid_head=[...])`
에 head 를 직접 준다. 한 이미지로 찍은 경우에도 fiducial 이 포화되어 있으면
경고가 나오므로, 그때 나눠 찍는 것을 고려하면 된다.

### 실험실 광학계에서 쓰기

렌즈가 몇 개 빠진 실험실 광학계에서는 왜곡이 단순하고 PSF 도 대칭에 가깝다.
두 가지만 바꾸면 같은 과정(촬영 → fiber/fiducial 위치 → 변환 fit → 보정각)
을 그대로 쓸 수 있다.

| 인자 | 뜻 |
|---|---|
| `magnification` | camera → focal 배율 초기값 (부호 포함; 본 장비는 `utils.CAMERA2FOCAL_M` ≈ −8.47). fiber 매칭은 이 값으로 투영해서 하므로 몇 % 안으로 맞아야 한다. 대략 `초점면 거리 / (픽셀 거리 × 3.76e-3)` 로 한 번 재서 넣는다 |
| `model` | 왜곡 다항식에서 풀 항. `'full'` (15개, 본 장비) / `'optics'` (PSF 항 없이 11개) / `'radial'` (배율·회전·offset + r², r⁴, 6개) / `'similarity'` (배율·회전·offset, 4개). 이름 뒤에 `+affine` 을 붙이면 축별 배율 차·전단 항 2개(b1, b2)를 더 푼다 (plate 가 카메라 축에 기울어 있을 때 필요). fiducial 이 `항 수 / 2` 개 이상 있어야 하고, 30개로는 항이 많을수록 과적합이 난다 (아래) |

```python
run = MetrologyRun(target_file=..., data_dir=..., json_dir=...,
                   magnification=-5.2, model='radial',
                   nwindow=30, threshold=1e3,
                   exptime=2., fid_exptime=0.5)
```

`nwindow` (무게중심 창 반폭) 와 `threshold` 는 그 광학계의 PSF 크기와 밝기에
맞춘다 (아래 "peak 측정 창" 참고). 어떤 모델을 썼고 fiducial 잔차가 얼마인지는
로그에 남는다.

모델은 **fit 잔차가 아니라 leave-one-out 잔차**(fiducial 하나를 빼고 맞춰 그
fiducial 을 예측한 오차)로 고른다. fiducial 30개에 15–17개 항을 풀면 잔차는
줄지만 예측은 나빠진다. 실측값으로 본 예:

| 자료 (fiducial 30개) | affine (6) | radial+affine (8) | optics+affine (13) | full (15) | full+affine (17) |
|---|---|---|---|---|---|
| 본 장비 2026-10-17, 핀홀 edge 위치 | 64 | 36 | **11** | 15 | **9** |
| 실험실 2026-10-19, 무게중심 | **78** | **78** | 92 | 159 | 104 |

(leave-one-out rms, µm). 본 장비에서는 `full+affine` 또는 `optics+affine`,
렌즈가 빠진 실험실에서는 `radial+affine` 이 맞았다. affine 항은 plate 기울기
1.3°(본 장비) / 약 3°(실험실)에 해당하는 축별 배율 차를 받는다. 참고로 본 장비 mock 에서는 `optics` 와 `radial` 이 `full` 과
거의 같은 fiber 오차를 내지만 `similarity` 는 1 mm 가까이 틀린다 — 그 광학계의
왜곡이 어느 정도인지 fiducial 잔차로 확인하고 모델을 고른다.

```
INFO Distortion fit (radial, 6 coefficients, 30 fiducials): fiducial residual rms 10.8 um, max 20.2 um; magnification -8.4915
```

#### 인터넷이 없는 실험실 컴퓨터로 가져가기

```bash
python -m kspec_metrology.make_labtest_bundle --out dist/kspec_metrology_LabTest.zip
```

패키지를 `kspec_metrology_LabTest` 라는 이름으로 (import 문까지 바꿔서) 복사하고
노트북 `LabTest_Metrology.ipynb`, `LabTest_README.md` 와 함께 zip 으로 묶는다.
그 컴퓨터에 깔린 옛 `kspec_metrology` 와 섞이지 않는다. 풀어서 노트북 첫 셀의
경로만 맞추면 되고 설치는 필요 없다. 실험실용 도우미(목표 파일 변환, fiber 표
줄이기, 단계별 확인 그림)는 `kspec_metrology/lab.py` 에 있다.

### 카메라 배율

`analysis/utils.py` 의 `camera2focal_coeff` 가 camera -> focal 변환(배율, 회전, offset,
왜곡)의 초기값이고 `CAMERA2FOCAL_M` 이 그 배율이다. 2026-10-26 부터 **2026-01 commissioning
때 실카메라를 fit 한 값**(`camera2focal_coeff_comm`, 배율 -8.86) 을 기본으로 쓴다.

`matchfiber` 는 회전과 offset 만 훑고 배율은 맞추지 않으므로 초기 배율이 실제와 몇 %
어긋나면 매칭이 통째로 깨진다 (실측: 5% 차이면 fiducial 30 개 중 1 개만 맞는다).
다른 광학계의 영상은 `magnification` 인자로 그 값을 준다. 설치 전 시험 셋업(2026-10-17)
영상은 +8.40, mock 이미지는 `CAMERA2FOCAL_M_MOCK` (-8.4675) 이다. 부호는 180° 회전과
같아서 매칭에는 영향이 없다.

### peak 검출 방법

`finder` 로 고른다. 어느 것을 쓰든 뒤 단계(중복 제거, center of mass, fiber
매칭)는 같고, mock 이미지에서 네 방법 모두 **완전히 같은 각도 json**을 냈다.
full frame(8842 x 11760, spot 181개) 기준 소요 시간은 다음과 같다.

| finder | 시간 | 특징 |
|---|---|---|
| `sep` (기본) | 1.5 s | 가장 빠르다 |
| `segmentation` | 2.5 s | 연결 성분. `npixels` 로 잡티를 거른다 |
| `find_peaks` | 6.1 s | 국소 최대만 본다. 기존 방법 |
| `daofind` | 23 s | PSF 모양까지 본다. 붙어 있는 spot에 강하다 |

```python
mtlcal(..., finder='sep', finder_opts={'minarea': 5})
```

방법별 인자는 `finder_opts` 로 넘긴다 — `sep`은 `minarea`, `segmentation`은
`npixels`, `daofind`는 `fwhm`, `find_peaks`는 `boxsize` 인자를 쓴다.
`threshold` 와 `niter_max` 는 방법과 무관하게 공통이다.

### background 제거

| `background` | 시간 | 하는 일 |
|---|---|---|
| `'crop'` (기본) | — | centroid를 잴 때 창마다 sigma clipped median을 빼고 음수는 0으로. `background_opts={'sigma': 5.0}` |
| `'scalar'` | 0.9 s | 전체에서 sigma clipped median 하나를 뺀다 |
| `'sep'` | 0.6 s | 위치에 따라 변하는 배경을 뺀다 |
| `'background2d'` | 6 s | 같은 일을 photutils로 |
| `None` | — | 빼지 않는다 |

기본 `'crop'` 은 창(2 × nwindow) 안의 화소로 배경을 재므로 기울어진 배경에도
맞고, spot 은 sigma clipping 에 걸려 배경 추정에서 빠진다. 창에 비해 spot 이
크면(꼬리가 창을 채우면) 배경이 높게 잡히므로 그때는 `'sep'` 처럼 이미지
전체에서 빼는 방법을 쓴다. 전체에서 빼는 방법에서는 `threshold` 가 배경을 뺀
뒤 기준이고, `'crop'` 에서는 peak 검출이 원본 이미지에서 되므로 배경을 포함한
값 기준이다.

### peak 측정 창

`nwindow` (기본 40) 는 center of mass를 잴 crop 반폭 [pixel] 이다. 이 창 안에
이웃 spot이 들어오면 무게중심이 끌려가므로 fiber 최소 이격 거리에 맞춰야 한다.

```
nwindow  <  최소이격[mm] / (2 x 3.76e-3 [mm/px] x |배율|)
```

최소 이격 3 mm 기준이면 `nwindow <= 40` 이다. `mtlcal()` 과 `MetrologyRun()`
양쪽에 인자로 열려 있다.

**창을 무게중심으로 옮겨 다시 재기** (`niter_recenter`, 기본 0). PSF가
비대칭이면 peak 픽셀과 무게중심이 어긋나서, peak을 중심으로 자른 창은 한쪽
꼬리만 자르고 그만큼 치우친다. 창을 무게중심으로 옮겨 다시 재면 양쪽을 고르게
잘라 치우침이 사라진다. PSF가 창에 비해 클수록 효과가 크다.

```python
mtlcal(..., nwindow=40, niter_recenter=2)
```

창이 이웃 spot 쪽으로 끌려가는 것을 막기 위해 처음 peak에서 `max_shift`
(기본 `nwindow//2`) 픽셀 넘게 움직이면 그 spot은 peak 중심 결과로 되돌리고
경고를 남긴다. 실제 이동량은 로그에 찍히므로 그걸 보고 `max_shift`를 정하면
된다 (정상 spot의 최대 이동량보다 조금 크게).

```
INFO Recentering shift [px]: median 3.2, 95% 7.1, max 8.5 (limit 20)
```

### target 파일 경로

`fiber_config.TARGET_INFO_PATH` 의 기본값은 관측 시스템 경로
(`/home/kspecmtl/work/KSPEC_ICS/MTL/target/object.info`) 이므로, 다른
환경에서는 `target_file` 인자로 직접 넘겨야 한다.

## 디버깅용 노트북

`kspec_metrology/notebooks/` 에 세 개가 들어 있다 (`notebooks/README.md`).
`Metrology_Debug.ipynb` (한 trial 을 단계별로), `Calibration_Run.ipynb` (모든 arm 을 같은
각도로 둔 배치), `Arm_Scan.ipynb` (회전 중심·arm 길이), `Fiducial_Brightness.ipynb` (본 측정 전
fiducial 밝기 조정: peak 검출 → ID·peak 값을 그림에 표시, 그룹별 요약). 운용 스크립트가 쓰는 함수를 그대로
부르므로 같은 이미지로 같은 결과가 나온다.

## Predict mode (오차가 작아진 뒤의 빠른 측정)

`mode='Raw'`(기본)는 threshold 를 조절해 가며 peak 을 검출하고 패턴에 매칭한다. 어떤 배치에서도
돌지만 검출·매칭이 들어간다. `mode='Predict'` 는 이미 맞춘 변환으로 각 목표의 칩 좌표를 예측해
그 창(`nwindow`) 안의 가장 밝은 픽셀에서 무게중심을 재고 매칭을 하지 않는다.

- 노출을 나눠 찍으면(`fid_exptime`) fiducial 은 Raw 로 찾아 변환을 맞추고, fiber 만 그 변환으로 Predict 한다.
- 한 벌 이미지면 직전 trial 이 저장한 변환(`{tile}_MetrologyTrial_{i}_coeff.npy`)을 쓴다. 없으면(첫 trial)
  그 trial 은 자동으로 Raw 로 돌고 경고를 남긴다.
- 끊어진 fiber(`FIBER_EXCLUDE`), 고정된 positioner(`FIBER_FIXED`), sky fiber(`SKY_FIBERS`) 처리는 Raw 와
  같다 (목록의 자리는 보지 않는다). 창 안에 threshold 이상의 화소가 없는 fiber 는 그 trial 에 못 잰
  것으로 두고(NaN, 회전 0) ID 를 경고한다.
- 한계: 창 반폭은 초점면에서 `nwindow × 3.76 µm × 배율` ≈ 1.3 mm (nwindow 40, 배율 8.4) 다. 목표에서
  이보다 멀리 있는 fiber 는 창에 spot 이 없거나 꼬리만 들어와 틀린 값이 나올 수 있다. 예측 위치에서
  창 반폭의 80 % 보다 멀리 잰 fiber 는 ID 와 함께 경고하므로 그때는 Raw 로 확인한다.
  **첫 trial 과 오차가 ~1 mm 를 넘는 배치는 Raw 로, 오차가 그 안으로 들어온 뒤(보통 trial 2 부터) Predict 로.**

```python
run = MetrologyRun(..., mode='Raw')        # trial 1
...
run.mode = 'Predict'                        # 오차가 작아진 뒤
```

2026-10-23 실험실 영상(노출 분리)으로 같은 이미지를 Raw 와 Predict 로 재면 오차 1.3 mm 안의 fiber 는
위치가 0.000 µm 차이로 같고, 2.0 mm·2.1 mm·3.6 mm 벗어난 fiber 셋은 Predict 가 못 재거나(NaN) 경고를 낸다.

## fiducial 밝기 조정

fiducial 은 4개 그룹으로 밝기를 조정한다. 본 측정 전에 fiducial 전용 노출을 한 장 찍어

```python
from kspec_metrology import lab
T, S = lab.fiducial_brightness('fid_10ms_0.fits', threshold=1e3, min_dist=80, magnification=8.40,
                               groups=cfg.FIDUCIAL_GROUPS)     # 밝기 조정 그룹 4개 (fiber_config)
```

로 보면 fiducial 마다 ID 와 peak 값이 영상 위에 적히고 (포화는 빨간 고리), 같은 색 눈금의 crop 과
표(peak, flux, nsat) 가 나온다. `groups` 를 주면 그룹별 요약표 `S` 가 함께 나온다. fiber 가 같이
찍힌 이미지면 `target_file=` 로 object.info 를 줘야 fiducial 라벨이 바르게 붙는다 (fiber 와 fiducial 이
같은 격자라 fiducial 패턴만으로는 회전이 정해지지 않는다). 노트북 `notebooks/Fiducial_Brightness.ipynb`.

## 노출시간 정하기 (fiber + fiducial 을 같이 켠 한 장)

```python
T, S, missing = lab.spot_brightness('fib_400ms_0.fits', 'object.info', threshold=1e3, min_dist=80, magnification=8.40)
```

peak 을 찾아 fiducial / fiber / sky·고정 positioner / 기타 로 나눠 종류별 peak 범위·포화 수를 낸다. 끊어진
fiber(`FIBER_EXCLUDE`) 는 기대하지 않고, 기대했는데 못 찾은 ID 는 `missing` 에, 어디에도 안 붙은 검출은
`other` 에 가장 가까운 fiber 와 거리를 붙여 준다. 가장 밝은 것이 포화의 절반에 오도록 노출 배율을 제안한다
(포화된 종류는 하한만). 노트북 `notebooks/Exposure_Check.ipynb`.

## positioner 회전 중심 · arm 길이 측정 (arm scan)

`analysis/armcal.py`. beta 를 고정하고 alpha 를 한 바퀴 돌리며 찍은 이미지들에서
positioner 마다 fiber 끝의 궤적에 원을 맞춘다 (중심 = 회전 중심, 반지름
R = |a₁ + a₂e^{iφ}|). beta = 0 과 180 두 번이면 `fit_arms` 로 a₁, a₂ 를 따로 구한다.

```python
from kspec_metrology.analysis import armcal
# alpha 단계마다 take_exposure.py --fiber 30 --fid 1 10 --out /data/scan_b0/alpha_{각도} 로 찍은 세트
SCAN = armcal.scan_sets('/data/scan_b0/alpha_*')     # [(fiber 30 ms, [fid 1 ms, fid 10 ms]), ...]
res = armcal.arm_calibration(SCAN, model='full+affine', threshold=1e3, min_dist=80,
                             finder_opts={'minarea': 9, 'deblend_cont': 1.0})
res.table                      # id, x0, y0, R, rms, n, dx, dy (설계 중심과의 차)
armcal.plot_arm_calibration(res)
armcal.write_measured_geometry(res, 'Measured_Geometry_scan.txt',
                               template='analysis/Measured_Geometry.txt')
```

프레임마다 본 metrology 와 같은 방법으로 fiducial 을 찾는다 (노출별로 포화되지 않은 가장 밝은 것;
첫 프레임은 패턴 매칭, 그 뒤는 직전 프레임의 fiducial 자리 주변) 고 변환을 새로 맞추므로 scan 중
카메라가 흘러가도 된다. 경로 목록만 주면 (`arm_calibration(images, fid_images=[...])`) 모든 프레임에
같은 fiducial 전용 노출을 쓴다. 각
positioner 중심에서 arm 길이 + 1 mm 안의 검출 중 중심에 가장 가까운 것을 그 궤적
점으로 본다 (이웃 positioner 가 같은 자리를 지나는 순간은 원 fit 의 robust 가중치가
거른다). 점이 5개 미만이면 그 positioner 는 비워 둔다.

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
