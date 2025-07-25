#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# @Author: Mingyeong Yang (mmingyeong@kasi.re.kr)
# @Date: 2025-04-29
# @Filename: gfa_test_ipd_ftd_matrix_allcams.py

import asyncio
import os
import sys
import time
import pandas as pd

# 프로젝트 루트 경로 지정
project_root = os.path.join(os.getcwd(), "kspec_gfa_controller", "src")
sys.path.append(project_root)

from gfa_actions import GFAActions


# ------------------------------------------------------------------------------
async def test_ipd_ftd_matrix(
    action, ipd_list, ftd_base_list, packet_size=8192, repeat=3, binning=4
):
    """
    IPD와 FTD_base 조합을 스윕하면서 모든 카메라의
    평균 FPS 및 timeout 횟수를 측정하고, 최적 조합을 탐색함.
    """
    results = []
    NUM_CAMERAS = 6

    for ipd in ipd_list:
        for ftd_base in ftd_base_list:
            fps_per_cam = {f"Cam{i}": [] for i in range(1, NUM_CAMERAS + 1)}
            timeout_per_cam = {f"Cam{i}": 0 for i in range(1, NUM_CAMERAS + 1)}

            print(f"\n[TEST] IPD={ipd}, FTD_base={ftd_base} (×{repeat} trials)")
            for trial in range(1, repeat + 1):
                start = time.time()
                tasks = []
                for cam in range(1, NUM_CAMERAS + 1):
                    tasks.append(
                        action.env.controller.grabone(
                            CamNum=cam,
                            ExpTime=0.01,
                            Binning=binning,
                            output_dir="test",
                            packet_size=packet_size,
                            ipd=ipd,
                            ftd_base=ftd_base,
                        )
                    )
                res = await asyncio.gather(*tasks, return_exceptions=True)
                end = time.time()

                # timeout 카메라 집계
                timeout_cams = [
                    cam for sub in res if isinstance(sub, list) for cam in sub
                ]

                # FPS 계산
                elapsed = end - start
                fps = NUM_CAMERAS / elapsed if elapsed > 0 else 0
                print(f"  - Trial {trial}/{repeat}: {elapsed:.3f}s, FPS {fps:.2f}")

                # per-camera FPS, timeout count 업데이트
                for i in range(1, NUM_CAMERAS + 1):
                    fps_per_cam[f"Cam{i}"].append(fps / NUM_CAMERAS)
                for cam_num in timeout_cams:
                    timeout_per_cam[f"Cam{cam_num}"] += 1

            for i in range(1, NUM_CAMERAS + 1):
                cam = f"Cam{i}"
                avg_fps = sum(fps_per_cam[cam]) / repeat
                results.append(
                    {
                        "Camera": cam,
                        "IPD": ipd,
                        "FTD_base": ftd_base,
                        "PacketSize": packet_size,
                        "Avg_FPS": round(avg_fps, 2),
                        "Timeout_Count": timeout_per_cam[cam],
                    }
                )

    return results


# ------------------------------------------------------------------------------
async def main():
    action = GFAActions()
    try:
        ipd_list = [35000, 36000, 38000, 39000, 40000]
        ftd_base_list = [0]
        data = await test_ipd_ftd_matrix(action, ipd_list, ftd_base_list)

        df = pd.DataFrame(data)
        df = df[["Camera", "IPD", "FTD_base", "PacketSize", "Avg_FPS", "Timeout_Count"]]
        df.sort_values(by=["Camera", "IPD", "FTD_base"], inplace=True)

        # 전체 결과 저장
        df.to_csv("ipd_ftd_all_camera_results.csv", index=False)
        print(
            "\n[SAVED] 전체 결과가 'ipd_ftd_all_camera_results.csv'에 저장되었습니다."
        )

        # Timeout 없는 조합 중 최고 FPS인 조합만 추출
        df_no_timeout = df[df["Timeout_Count"] == 0]
        best_combinations = (
            df_no_timeout.sort_values(by=["Camera", "Avg_FPS"], ascending=[True, False])
            .groupby("Camera")
            .head(1)
        )
        best_combinations.to_csv("best_combinations_per_camera.csv", index=False)
        print(
            "[SAVED] 카메라별 최적 조합이 'best_combinations_per_camera.csv'에 저장되었습니다."
        )

        # Timeout 발생 조합도 별도 저장
        unstable = df[df["Timeout_Count"] > 0]
        unstable.to_csv("unstable_combinations.csv", index=False)
        print(
            "[SAVED] Timeout 발생 조합이 'unstable_combinations.csv'에 저장되었습니다."
        )

    finally:
        action.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
