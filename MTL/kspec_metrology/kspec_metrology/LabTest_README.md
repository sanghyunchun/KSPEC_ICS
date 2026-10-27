# kspec_metrology_LabTest — 실험실 시험용 묶음

인터넷이 없는 실험실 컴퓨터용. 설치하지 않고 폴더째 쓴다. 이미 깔린 옛
`kspec_metrology` 와 섞이지 않도록 패키지 이름이 `kspec_metrology_LabTest` 다
(import 문도 그 이름).

```
kspec_metrology_LabTest/     패키지 (analysis, exposure, lab, mtlrun ...)
LabTest_Metrology.ipynb      순서대로 실행하는 노트북 (한 배치를 한 번 측정)
LabTest_README.md            이 파일
```

## 쓰는 법

1. zip 을 아무 폴더에나 푼다 (예: `/home/lab/metrology/`).
2. `LabTest_Metrology.ipynb` 를 열고 첫 셀의 `PKG_DIR`(푼 폴더) 과 `OUT_DIR`(결과 폴더),
   2절의 목표 파일·이미지 경로를 바꾼다.
3. 셀을 순서대로 실행한다. 설정 셀(표)을 바꾸면 커널을 재시작한다.

필요한 파이썬 패키지: numpy, scipy, astropy, photutils, sep, matplotlib, pandas, jupyter
(옛 kspec_metrology 가 돌던 환경이면 있다).

## 입력

**fiber 표**: 패키지 기본 `analysis/Fiber_Configuration_config73.txt`
(positioner 73 + fiducial 30). 바깥 sky fiber 홀은 −9 로 표에서 빠져 있고,
켜져 있으면 `SKY_FIBERS` 에 그 홀 ID 를 적는다 (아래). 분광기에 연결된 fiber 만 켜진다
(2026-10 설치표: obj 37 + sky 6 = 43; G4 는 끊어져 대신 H3).

**목표 파일**: `object.info` 와 같은 json. 배열은 표의 positioner 순서(73개).

```json
{"xp": [...], "yp": [...]}              초점면 목표 [mm]
{"alpha": [...], "beta": [...]}         positioner 각도 [deg]
{"C4_a": ..., "C4_b": ..., ...}         각도 json (이 패키지의 출력 형식)
```

**이미지**: FITS 경로 1–3 개.

| 경우 | `FIBER_IMAGE` | `FID_IMAGES` |
|---|---|---|
| 한 노출에 fiber + fiducial | 그 이미지 | `[]` |
| fiducial 따로 (case 1) | fiber 노출 | `[fiducial 노출]` |
| fiducial 두 노출 (case 2) | fiber 노출 | `[t1_1, t1_2]` (fiducial 마다 포화 안 된 밝은 쪽) |

**못 쓰는 홀 (ID 만 적는다, 위치 불필요)**: 노트북 1절. 표와 목표 파일(73개)은 그대로 둔다.

| 목록 | 뜻 | 처리 |
|---|---|---|
| `BROKEN_FIBERS = ['G4', ...]` | 빛이 안 나는 positioner (분광기에 fiber 가 안 연결된 33 홀, 끊어진 G4 포함; 패키지 기본) | 이미지에서 찾지 않음. 결과 NaN, 회전량 0 |
| `FIXED_FIBERS = ['G7', 'H8', 'J6']` | 빛은 나오지만 고장나 움직이지 않는 positioner (sky fiber 가 꽂힘; 패키지 기본) | 그 홀의 arm 도달 범위 안이고 다른 목표에서 3 mm 넘게 떨어진 검출을 후보에서 뺌. 결과 NaN, 회전량 0 |
| `SKY_FIBERS = ['B7', 'H1', 'N7']` | 표에서 −9 인 홀의 sky fiber (패키지 기본) | 같은 방식으로 뺌 |

기대 검출 개수 = 73 − BROKEN 수 + SKY 수 (FIXED 는 73 안에 있다) = 73 − 33 + 3 = 43 (기본값). 빈 리스트 `[]` 는 패키지 기본값을 그대로 쓴다.
남은 목표와 검출은 1:1 assignment 로 매칭되고, 3 mm 넘게 떨어져 매칭된 fiber 는 ID 와 함께 경고가 난다.
`N_EXTRA` 는 이들 외의 여분 밝은 점(반사광 등)만 센다 (보통 0).
환경변수 `KSPEC_FIBER_EXCLUDE`, `KSPEC_FIBER_FIXED`, `KSPEC_SKY_FIBERS` 와 같다.

**각도 부호·영점**: 노트북 1절의 `ANGLE_SIGN`, `ANGLE_ZERO`. 명령각 = 부호 × 기하각 − 영점.
기본 부호 `(1, 1)`: alpha 는 초점면 +x 에서 반시계가 양, beta 는 elbow-down 으로 0 이상 (2026-10-23
실험실 배치로 확인). 기본 영점 `(30, 150)`: 기하각 (30, 150) 이 positioner 의 (0, 0) 초기 위치
(2026-10-27). 출력 json 과 각도 입력은 모두 명령각. 부호가 틀리면 fiber 가 목표에서 수 mm 떨어져 나온다
(`fiber - target` 중앙값이 mm 단위).

**포화**: fiducial 전용 노출에서 안 보이는 fiducial 은 fiber 노출(보통 포화)에서라도
가져온다. 포화된 것은 로그에 `saturated ... (used anyway)` 로 남는다. 촬영을 직접 하는
`MetrologyRun` 에는 `auto_exposure=True` 로 포화 시 노출을 줄여 다시 찍는 옵션이 있다.

**검출 점검**: `lab.check_peaks(fits, threshold, min_dist, finder_opts)` 로 이미지 한 장의
검출 개수·밝기·쪼개짐을 먼저 본다 (노트북 2절 뒤). `THRESHOLD` 는 시작값이고 본
패키지처럼 검출 개수가 기대 범위에 들도록 자동으로 올리고 내린다.

**목표 파일 만들기**: `lab.make_target(path, angles=(0, 0))` (모두 같은 명령각; (0, 0) = 초기 위치 = 기하각 (30, 150)),
`offset=(dx, dy)` (회전 중심에서 같은 offset), `xy=(xp, yp)` (개별).

**fiducial 밝기 조정**: 노트북 8절. `lab.fiducial_brightness(fits, groups={...})` 가 fiducial 노출에서
peak 을 찾아 ID 와 peak 값을 그림에 적고 (포화는 빨간 고리), 그룹별 요약표를 낸다.

## 반복 측정 (positioner 를 옮긴 뒤)

같은 `OUT_DIR`/`TILE` 로 `lab.measure(..., itrial=None)` 를 다시 부르면 다음 trial
번호가 되고, 누적 각도 = 직전 trial json + 이번 회전량 으로 쌓인다
(`_0.json` = 목표 각도). 노트북 5절. `lab.history(OUT_DIR, TILE)` 가 trial 별
오차를 표로 보여 준다. 같은 이미지로 **다시 계산만** 하려면 `itrial=1` 을 명시한다
(그러지 않으면 다음 trial 번호로 쌓인다).

## 출력 (`OUT_DIR`)

- `{TILE}_MetrologyTrial_1_offset.txt` — fiber 별 남은 위치 오차 dx, dy [µm] 와 회전량 dalpha, dbeta [deg]
- `{TILE}_MetrologyTrial_1.json` — 목표 각도 + 회전량 (positioner 로 보낼 누적 각도)
- `data/` — 분석에 쓴 이미지 링크, `{TILE}_target.info` — (x, y) 로 바꾼 목표

## 파이썬에서 직접

```python
from kspec_metrology_LabTest import lab
res = lab.measure(target_file, fiber_image, [fid1, fid2], out_dir='lab_out',
                  magnification=8.40, model='radial+affine')   # FIXED/SKY 는 환경변수 또는 cfg 목록으로
lab.offsets_table(res)      # fiber 별 표
lab.show_steps(res)         # 단계별 그림
```

자세한 인자 설명은 패키지 안 `README.md`.
