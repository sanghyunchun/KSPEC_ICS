"""인터넷이 없는 실험실 컴퓨터로 가져갈 묶음을 만든다.

패키지를 kspec_metrology_LabTest 라는 이름으로 복사해 (import 문까지 바꿔서) 그
컴퓨터에 이미 깔린 옛 kspec_metrology 와 섞이지 않게 한다. 노트북과 README 를
같이 넣고 zip 으로 묶는다.

    python -m kspec_metrology.make_labtest_bundle --out /어디/kspec_metrology_LabTest.zip

가져간 뒤에는 zip 을 풀고 노트북 첫 셀의 PKG_DIR 을 그 폴더로 맞추면 된다
(설치 없이 sys.path 로 쓴다).
"""

import argparse
import os
import re
import shutil
import zipfile

SRC_NAME = 'kspec_metrology'
DST_NAME = 'kspec_metrology_LabTest'
SKIP_DIRS = ('__pycache__', '.claude', 'tmp')
SKIP_EXT = ('.bak', '.pyc', '.fits', '.npz.bak')
EXTRA_FILES = ('LabTest_Metrology.ipynb', 'LabTest_README.md')   # 노트북은 패키지 폴더 옆(상위), README 는 패키지 안


def rename_text(text):
    return re.sub(rf'\b{SRC_NAME}\b', DST_NAME, text)


def build(out_zip):
    here = os.path.dirname(os.path.abspath(__file__))        # .../kspec_metrology
    parent = os.path.dirname(here)
    stage = os.path.join(os.path.dirname(os.path.abspath(out_zip)), '_labtest_stage')
    shutil.rmtree(stage, ignore_errors=True)
    dst = os.path.join(stage, DST_NAME)
    n = 0
    for root, dirs, files in os.walk(here):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        rel = os.path.relpath(root, here)
        for f in files:
            if f.endswith(SKIP_EXT) or f in (os.path.basename(__file__),) + EXTRA_FILES:
                continue
            s = os.path.join(root, f)
            d = os.path.join(dst, rel, f)
            os.makedirs(os.path.dirname(d), exist_ok=True)
            if f.endswith(('.py', '.md', '.txt', '.template', '.ipynb')):
                with open(s, encoding='utf-8') as fi:
                    txt = fi.read()
                with open(d, 'w', encoding='utf-8') as fo:
                    fo.write(rename_text(txt))
            else:
                shutil.copy2(s, d)
            n += 1
    # tmp/object.info 만 (mock 이미지는 뺀다)
    os.makedirs(os.path.join(dst, 'tmp'), exist_ok=True)
    for f in ('object.info', 'README.md'):
        p = os.path.join(here, 'tmp', f)
        if os.path.exists(p):
            shutil.copy2(p, os.path.join(dst, 'tmp', f))
    for f in EXTRA_FILES:
        p = os.path.join(parent, f)
        if not os.path.exists(p):
            p = os.path.join(here, f)
        if os.path.exists(p):
            with open(p, encoding='utf-8') as fi:
                txt = fi.read()
            with open(os.path.join(stage, f), 'w', encoding='utf-8') as fo:
                fo.write(rename_text(txt))
    with zipfile.ZipFile(out_zip, 'w', zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(stage):
            for f in files:
                p = os.path.join(root, f)
                z.write(p, os.path.relpath(p, stage))
    shutil.rmtree(stage)
    return n


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--out', default='kspec_metrology_LabTest.zip')
    a = ap.parse_args()
    n = build(a.out)
    print(f"{n} package files -> {a.out}")
