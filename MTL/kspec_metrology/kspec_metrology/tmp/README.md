# tmp — mock metrology 데이터

카메라 없이 분석 전체를 돌려 볼 수 있는 mock 한 세트다.
K-SPEC 초점면을 그대로 본뜬 것으로, positioner 151개와 fiducial 30개가 들어 있다.

| 파일 | 크기 | 저장소 | 설명 |
|---|---|---|---|
| `object.info` | 6 KB | 포함 | fiber 목표 위치 (`xp`, `yp`) 151개. `tile_id="test"`, `zenith_angle=0` |
| `test_MetrologyTrial_1_0.fits` | 416 MB | **제외** | mock metrology 이미지 (8842 x 11760, int32). 용량 때문에 따로 공유한다 |

fits는 `.gitignore`로 빠져 있으니 따로 받아서 아무 폴더에나 두면 된다.
파일 이름은 바꾸지 말 것 (`naming.py`의 규칙에서 나온다).

## 돌려보기

```bash
# 이미지를 따로 받아 둔 경우 (가장 흔한 경우)
python -m kspec_metrology.run_mock --image-dir /이미지를/받은/폴더

# 두 파일을 한 폴더에 모아 둔 경우
python -m kspec_metrology.run_mock --data-dir /어디든/mock

# 이미지까지 이 tmp/ 에 넣어 둔 경우
python -m kspec_metrology.run_mock
```

`--target` 으로 `object.info` 경로를 파일째 지정할 수도 있고, `--out-dir` 로
결과를 다른 곳에 쓸 수도 있다. 전체 옵션은 `--help` 참고.

실제 운용 진입점인 `MetrologyRun` 으로도 (촬영만 건너뛰고) 같은 것을 돌릴 수
있다. 결과 json은 완전히 같다.

```bash
python -m kspec_metrology.run_mock --via metrologyrun --image-dir /받은/폴더
```

패키지를 이식할 때는 이쪽을 참고하면 된다 — 저장소 최상위 `README.md`의
"mock 데이터로 돌려보기" 절에 두 방법의 코드가 나란히 있다.

## 나오는 것

각도 json 두 개가 생긴다 (기본 위치는 `object.info`가 있는 폴더).

```
test_MetrologyTrial_0.json   관측 전 목표 각도
test_MetrologyTrial_1.json   보정각 (최종 산출물)
```

key는 `{hole ID}_a` (alpha arm), `{hole ID}_b` (beta arm), 값은 degree다.

## 기대값

이 mock은 positioner 위치 오차를 sigma = 40 um로 심어 두었다. 제대로 돌면

```
peak 검출        181 / 181
fiber 위치 오차  median 약 53 um, max 약 122 um
```

가 나온다. 위치 오차 median이 53um 근처면 정상이다 (주입한 sigma 40um의
Rayleigh median이 47um이고, 표본 151개의 산포가 더해진 값).

`object.info`의 `xp`, `yp`는 **목표(명령) 위치**이고, mtlcal이 보고하는
`dx`, `dy`는 "측정한 위치 - 목표"다. 분석에 필요한 참값은 이것이 전부다.

빛이 실제로 맺힌 자리(목표 + 위치오차 + 전역 offset)는 `object.info`에 없다.
그 값으로 결과를 대조해 보고 싶으면 생성기가 함께 만드는
`{tile}_MetrologyTrial_{itrial}_truth.npz` 를 보면 된다 (`xcalc`, `ycalc`가 실제
위치, `x`, `y`가 목표, `xoff`, `yoff`가 전역 offset). 분석에는 쓰이지 않으므로
저장소에는 넣지 않는다.

## mock을 다시 만들려면

생성기는 이 저장소가 아니라 image_simulation 쪽에 있다.

```
image_simulation/src/Total/Mock_Image_Generator_kspec_metrology.py
```

`fiber_config`와 `Fiber_Configuration_250415.txt`를 그대로 읽어 만들기 때문에,
fiber 구성을 바꾸면 mock도 같이 다시 만들어야 한다. 용량이 부담되면 생성기의
`COMPRESS = True`로 두면 RICE 무손실 압축이 걸려 92MB가 되고, 확장자가 `.fits`
그대로라 읽는 쪽 코드는 바꿀 필요가 없다.
