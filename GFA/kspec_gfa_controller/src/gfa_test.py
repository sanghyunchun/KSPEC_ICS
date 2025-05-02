#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# @Author: Mingyeong Yang (mmingyeong@kasi.re.kr)
# @Date: 2025-04-15
# @Filename: gfa_test.py

import asyncio
import os
import sys

# 프로젝트 루트 경로 기준 상대 경로 설정
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.join(current_dir, "kspec_gfa_controller", "src")

# 모듈 임포트를 위한 경로 추가
sys.path.append(project_root)

# 확인용 출력 (필요시 주석 처리 가능)
print(f"[INFO] sys.path includes project root: {project_root}")

# GFAActions 클래스 임포트
from gfa_actions import GFAActions


async def main():
    action = GFAActions()

    # 테스트용 액션 실행
    try:
        msg = await action.grab(0, 0.01)  # 예: 카메라 ID 1, 노출 시간 0.01초
        #msg = action.status()
        #print(f"[SUCCESS] status result: {msg}")
        #msg = action.ping()
        #print(f"[SUCCESS] ping result: {msg}")
        action.shutdown()
    except Exception as e:
        print(f"[ERROR] Exception occurred during grab: {e}")


if __name__ == "__main__":
    asyncio.run(main())
