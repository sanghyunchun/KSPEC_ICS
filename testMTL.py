from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent
MTL_PACKAGE_ROOT = REPO_ROOT / "MTL" / "kspec_metrology"

if str(MTL_PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(MTL_PACKAGE_ROOT))

from kspec_metrology.exposure import mtlexp


def _data_dir_with_separator(path: Path) -> str:
    return str(path) + "/"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="MTL mtlexp.py를 RabbitMQ 없이 직접 호출한다."
    )
    parser.add_argument(
        "exptime",
        type=float,
        help="노출 시간. 단위는 second.",
    )
    parser.add_argument(
        "nexposure",
        type=int,
        help="반복 노출 횟수.",
    )
    parser.add_argument(
        "filename",
        help='저장할 FITS 파일 이름. 예: "test.fits"',
    )
    parser.add_argument(
        "--data-dir",
        default=str(REPO_ROOT / "MTL" / "data"),
        help="FITS 파일 저장 디렉토리. 기본값: MTL/data",
    )
    parser.add_argument("--readmode", type=int, default=1)
    parser.add_argument("--usb-traffic", type=int, default=40)
    parser.add_argument("--gain", type=int, default=10)
    parser.add_argument("--offset", type=int, default=30)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    data_dir = Path(args.data_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)

    status, message = mtlexp.mtlexp(
        args.exptime,
        args.filename,
        readmode=args.readmode,
        usb_traffic=args.usb_traffic,
        gain=args.gain,
        offset=args.offset,
        nexposure=args.nexposure,
        data_dir=_data_dir_with_separator(data_dir),
    )

    print(f"status: {status}")
    print(f"message: {message}")
    print(f"data_dir: {data_dir}")

    return 0 if status == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
