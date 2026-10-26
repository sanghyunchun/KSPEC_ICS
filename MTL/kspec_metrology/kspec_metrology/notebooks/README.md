# notebooks — 디버깅용 주피터 노트북

패키지 함수를 한 단계씩 부르며 결과를 표와 그림으로 본다. 운용에서는 `MetrologyRun`
(mtlrun.py) 을 스크립트에서 부르고, 문제가 생기면 여기서 같은 이미지를 다시 돌려 본다.

| 노트북 | 하는 일 |
|---|---|
| `Metrology_Debug.ipynb` | 한 trial 의 이미지(fiber 노출 + fiducial 전용 노출 0–2장)로 검출 → fiducial 매칭·변환 fit → fiber 매칭 → 각도 json / offset 표. 검출 점검 셀 포함 |
| `Calibration_Run.ipynb` | 모든 arm 을 같은 각도(또는 같은 offset)로 둔 배치의 측정. 목표 파일을 각도로 만들고 같은 흐름으로 |
| `Arm_Scan.ipynb` | alpha 를 돌리며 찍은 이미지들로 positioner 회전 중심(과 arm 길이) 을 원 fit 으로 구해 `Measured_Geometry` 형식으로 쓴다 |
| `run_trial.py` | metrology trial 을 명령 한 번에 하나씩: `--start` 로 Trial 0 json, 그 뒤 명령마다 촬영 + 계산 + json 저장. trial 번호는 `--out` 폴더의 json 에서 이어 가므로 매번 새 프로세스로 돌려도 된다 (`--no-expose` 는 계산만 다시) |
| `take_exposure.py` | 시험 촬영 스크립트: 원하는 노출시간으로 찍어 원하는 이름으로 저장 (`--help`). `--fiber 400 --fid 2 10` 으로 fiber 1장 + fiducial 2장을 한 세트로. fiducial 밝기 조정 때 노트북과 같이 쓴다 |
| `Exposure_Check.ipynb` | fiber 와 fiducial 을 모두 켠 한 장에서 peak 을 찾아 fiducial / fiber / sky·고정 / 기타로 나눠 밝기를 보고 노출시간을 정한다 (끊어진 fiber 는 기대하지 않음, 못 찾은 것·포화 표시, 노출 배율 제안) |
| `Fiducial_Brightness.ipynb` | 본 측정 전 fiducial 밝기 조정: fiducial 노출에서 peak 을 찾아 ID 와 peak 값을 그림에 적고 (포화 표시), 그룹별 요약표 |

노트북 모두 첫 셀에서 패키지 경로와 설정(끊어진 fiber, 고정된 positioner, sky fiber,
각도 부호, 배율 등)을 정한다. 설정 셀을 바꾸면 커널을 재시작한다 (표와 제외 목록은
import 때 읽힌다).
