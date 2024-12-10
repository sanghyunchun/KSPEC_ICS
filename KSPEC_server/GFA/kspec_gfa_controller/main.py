#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# @Author: Mingyeong Yang (mmingyeong@kasi.re.kr)
# @Date: 2024-08-01
# @Filename: main.py

import asyncio
import os
import sys

# Add the parent directory of the script to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.gfa_actions import gfa_actions

async def main():
    camnum = 0
    # ping()
    #status()
    #cam_params()
    await gfa_actions.grab()
    #await grab_loop()
    #is_grab_loop_running()


if __name__ == "__main__":
    asyncio.run(main())
