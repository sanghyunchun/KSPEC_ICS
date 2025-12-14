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

import asyncio
from gfa_environment import create_environment
from gfa_controller import GFAController
from gfa_actions import GFAActions
from finder_actions import FinderGFAActions


async def test_gfa_controller():
    print("Testing GFAController (plate)...")
    controller = GFAController()
    controller.open_all_cameras()

    print("Status check:")
    status = controller.status()
    print(status)

    print("Pinging Cam1:")
    controller.ping(1)

    print("Retrieving Cam1 params:")
    param = controller.cam_params(1)
    print(param)

    print("Grabbing image from Cam1:")
    timeout = await controller.grabone(CamNum=1, ExpTime=0.5, Binning=2, packet_size=8192, ipd=360000, ftd_base=0)
    print("Timeout:", timeout)

    controller.close_all_cameras()


async def test_gfa_actions():
    print("\nTesting GFAActions...")
    env = create_environment(role="plate")
    actions = GFAActions(env)

    print("Grabbing from Cam all:")
    result = await actions.grab(CamNum=0, ExpTime=0.5, Binning=2)
    print(result)

    #print("Guiding test (simulate offset calc):")
    #result = await actions.guiding(ExpTime=0.5, save=True)
    #print(result)

    #print("Ping all:")
    #print(actions.ping())

    #print("Retrieve all cam params:")
    #print(actions.cam_params())


async def test_finder_actions():
    print("\nTesting FinderGFAActions...")
    env = create_environment(role="finder")
    actions = FinderGFAActions(env)

    print("Grab image:")
    result = await actions.grab(ExpTime=0.3)
    print(result)

    #print("Focusing (guiding) frame:")
    #result = await actions.guiding(ExpTime=0.3, save=True)
    #print(result)

    #print("Ping finder:")
    #print(actions.ping())

    #print("Cam params:")
    #print(actions.cam_params())


if __name__ == "__main__":
    #asyncio.run(test_gfa_controller())
    asyncio.run(test_gfa_actions())
    #asyncio.run(test_finder_actions())
