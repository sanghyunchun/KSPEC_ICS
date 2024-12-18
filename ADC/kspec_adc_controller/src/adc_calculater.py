#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# @Author: Mingyeong Yang (mmingyeong@kasi.re.kr)
# @Date: 2024-11-13
# @Filename: adc_calculater.py


__all__ = ["adc_calculater"]

class adc_calculater:
    def __init__(self):
        pass

    def zen_dist(self, alt, azim):
        """
        Calculate the zenith distance given the altitude.

        Parameters:
        altitude (float): Altitude in degrees

        Returns:
        float: Zenith distance in degrees
        """
        return 90 - alt

    def interpolation():
        pass

    def return_ang(self, z_dist:float):
        # input: z_dist
        # calculation...
        # dict = {
        #    [motor_1 : ang_1],
        #    [motor_2 : ang_2]    
        #}
        # return dict
        pass
    
    def ang_to_pos(self, ang: float) -> int:
        """
        Convert angle to target motor position in counts.

        Parameters:
        ang (float): Angle in degrees (+ for clockwise, - for counterclockwise)

        Returns:
        int: Target position in counts
        """
        # 16,200 counts correspond to 360 degrees
        counts_per_degree = 16200 / 360
        # Convert angle to counts
        target_position = int(round(ang * counts_per_degree))
        
        return target_position
