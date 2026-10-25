"""이 컴퓨터에서 패키지를 쓸 수 있는지 확인한다 (필요한 파이썬 패키지, import, 데이터 파일).

    python -m kspec_metrology.check_env          # zip 을 푼 폴더에서
"""
import importlib
import os
import sys


def main():
    print(f"python {sys.version.split()[0]}  ({sys.executable})")
    if sys.version_info < (3, 11):
        print("  [!] python 3.11 이상이 필요하다")
    ok = True
    for name, minver in (('numpy', '1.24'), ('scipy', '1.11'), ('astropy', '5.3'),
                         ('photutils', '1.9'), ('sep', '1.2'), ('matplotlib', None),
                         ('pandas', None), ('jupyter_client', None)):
        try:
            m = importlib.import_module(name)
            print(f"  {name:15s} {getattr(m, '__version__', '?'):10s}" + (f" (>= {minver} 필요)" if minver else ""))
        except ImportError:
            print(f"  {name:15s} 없음" + ("  <- 필수" if minver else "  <- 노트북/표에 필요"))
            ok &= minver is None
    pkg = os.path.basename(os.path.dirname(os.path.abspath(__file__)))   # -m 으로 돌면 __name__ 이 __main__
    try:
        cfg = importlib.import_module(f'{pkg}.analysis.fiber_config')
        importlib.import_module(f'{pkg}.lab')
        importlib.import_module(f'{pkg}.mtlrun')
        print(f"\n{pkg} import OK: {os.path.dirname(os.path.abspath(__file__))}")
        print(f"  fiber table   : {os.path.basename(cfg.FIBER_TABLE_PATH)} ({len(cfg.fiber_ids())} positioners)")
        print(f"  measured file : {os.path.basename(cfg.MEASURED_GEOMETRY_PATH)} "
              f"({'있음' if os.path.exists(cfg.MEASURED_GEOMETRY_PATH) else '없음'}), use_measured={cfg.USE_MEASURED}")
    except Exception as e:
        ok = False
        print(f"\n[!] {pkg} import 실패: {e!r}")
    print("\n결과:", "사용 가능" if ok else "쓸 수 없다 (위 [!] 참고)")
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
