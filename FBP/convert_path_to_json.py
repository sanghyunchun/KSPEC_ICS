"""CSV 형식의 *.path.txt 파일을 alpha/beta JSON으로 분리한다."""

import argparse
import csv
import json
import math
from pathlib import Path


def convert_path_file(path_filename, output_dir=None):
    """하나의 *.path.txt 파일을 alpha/beta JSON 두 개로 변환한다.

    A2_a 열은 alpha JSON의 A2 키로, A2_b 열은 beta JSON의 A2 키로
    저장한다. 두 JSON의 step은 데이터 행 수에 따라 1부터 자동 생성한다.

    Args:
        path_filename: 변환할 *.path.txt 파일 경로.
        output_dir: 출력 디렉터리. 생략하면 입력 파일과 같은 디렉터리.

    Returns:
        생성한 (alpha_json_path, beta_json_path) Path 객체 tuple.
    """
    input_path = Path(path_filename).expanduser().resolve()

    if not input_path.is_file():
        raise FileNotFoundError(f"입력 파일을 찾을 수 없습니다: {input_path}")
    if not input_path.name.endswith(".path.txt"):
        raise ValueError(
            f"입력 파일명은 '.path.txt'로 끝나야 합니다: {input_path.name}"
        )

    with input_path.open("r", encoding="utf-8-sig", newline="") as file:
        first_line = file.readline()
        if not first_line:
            raise ValueError(f"입력 파일이 비어 있습니다: {input_path}")

        # 일반 파일은 쉼표로, improved 파일은 연속 공백으로 구분되어 있다.
        comma_separated = "," in first_line
        if comma_separated:
            headers = [
                header.strip()
                for header in next(csv.reader([first_line]))
            ]
            reader = csv.reader(file)
        else:
            headers = first_line.split()
            reader = (line.split() for line in file)

        if not headers or any(not header for header in headers):
            raise ValueError(f"CSV 헤더에 비어 있는 열 이름이 있습니다: {input_path}")
        if len(headers) != len(set(headers)):
            raise ValueError(f"CSV 헤더에 중복된 열 이름이 있습니다: {input_path}")

        rows = []
        for line_number, row in enumerate(reader, start=2):
            if not row or all(not value.strip() for value in row):
                continue
            if len(row) != len(headers):
                raise ValueError(
                    f"{input_path}:{line_number}: 열 개수가 다릅니다. "
                    f"{len(row)} != {len(headers)}"
                )

            try:
                values = [float(value.strip()) for value in row]
            except ValueError as error:
                raise ValueError(
                    f"{input_path}:{line_number}: 숫자가 아닌 값이 있습니다."
                ) from error

            if not all(math.isfinite(value) for value in values):
                raise ValueError(
                    f"{input_path}:{line_number}: NaN 또는 무한대 값이 있습니다."
                )
            rows.append(values)

    total_steps = len(rows)
    if total_steps == 0:
        raise ValueError(f"경로 데이터가 없습니다: {input_path}")
    if total_steps > 3500:
        raise ValueError(
            f"step 개수가 3500개를 초과했습니다: {total_steps}"
        )

    columns = dict(zip(headers, zip(*rows)))
    positioners = []
    seen_positioners = set()

    for header in headers:
        try:
            positioner, arm = header.rsplit("_", 1)
        except ValueError as error:
            raise ValueError(
                f"잘못된 헤더 형식입니다: {header}"
            ) from error

        if not positioner or arm not in ("a", "b"):
            raise ValueError(
                "헤더는 '<positioner>_a' 또는 '<positioner>_b' "
                f"형식이어야 합니다: {header}"
            )

        if positioner not in seen_positioners:
            seen_positioners.add(positioner)
            positioners.append(positioner)

    for positioner in positioners:
        for arm in ("a", "b"):
            required_header = f"{positioner}_{arm}"
            if required_header not in columns:
                raise ValueError(
                    f"alpha/beta 쌍을 이루는 열이 없습니다: {required_header}"
                )

    step = list(range(1, total_steps + 1))
    alpha_data = {"step": step}
    beta_data = {"step": step}

    for positioner in positioners:
        alpha_data[positioner] = list(columns[f"{positioner}_a"])
        beta_data[positioner] = list(columns[f"{positioner}_b"])

    destination = (
        input_path.parent
        if output_dir is None
        else Path(output_dir).expanduser().resolve()
    )
    destination.mkdir(parents=True, exist_ok=True)

    output_stem = input_path.name.removesuffix(".path.txt")
    alpha_path = destination / f"{output_stem}.alpha.json"
    beta_path = destination / f"{output_stem}.beta.json"

    for output_path, data in (
        (alpha_path, alpha_data),
        (beta_path, beta_data),
    ):
        with output_path.open("w", encoding="utf-8") as file:
            json.dump(
                data,
                file,
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
            file.write("\n")

    return alpha_path, beta_path


def convert_path_files(source, output_dir=None):
    """단일 파일 또는 디렉터리 안의 모든 *.path.txt 파일을 변환한다."""
    source_path = Path(source).expanduser().resolve()

    if source_path.is_file():
        input_files = [source_path]
    elif source_path.is_dir():
        input_files = sorted(source_path.glob("*.path.txt"))
        if not input_files:
            raise FileNotFoundError(
                f"'*.path.txt' 파일을 찾을 수 없습니다: {source_path}"
            )
    else:
        raise FileNotFoundError(f"입력 경로를 찾을 수 없습니다: {source_path}")

    return [
        convert_path_file(input_file, output_dir)
        for input_file in input_files
    ]


def main():
    parser = argparse.ArgumentParser(
        description=(
            "*.path.txt CSV를 positioner별 alpha/beta JSON 파일로 분리합니다."
        )
    )
    parser.add_argument(
        "source",
        help="변환할 *.path.txt 파일 또는 파일들이 있는 디렉터리",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        help="출력 디렉터리. 생략하면 각 입력 파일과 같은 디렉터리",
    )
    args = parser.parse_args()

    results = convert_path_files(args.source, args.output_dir)

    for alpha_path, beta_path in results:
        print(alpha_path)
        print(beta_path)

    print(f"{len(results)}개 path 파일을 JSON {len(results) * 2}개로 변환했습니다.")


if __name__ == "__main__":
    main()
