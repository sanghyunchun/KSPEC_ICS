#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# @Author: Sungwook E. Hong (swhong@kasi.re.kr)
# @Date: 2024-12-06
# @Filename: adc_calc_angle.py

import os
import numpy as np

from scipy.interpolate import CubicSpline
from scipy.interpolate import PchipInterpolator
from scipy.interpolate import Akima1DInterpolator

from .adc_logger import AdcLogger


def _get_default_lookup_path() -> str:
    """
    Returns the default ADC lookup CSV file path based on the location of this script.
    Raises FileNotFoundError if the file does not exist.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    default_path = os.path.join(script_dir, "etc", "ADC_lookup.csv")
    if not os.path.isfile(default_path):
        raise FileNotFoundError(
            f"Default ADC lookup file not found at: {default_path}. "
            "Please place ADC_lookup.csv in the 'etc' folder or adjust `_get_default_lookup_path()`."
        )
    return default_path


class ADCCalc:
    """
    A class to calculate the ADC angle from the input zenith angle and
    given lookup table.

    Attributes
    ----------
    fn_za_adc : object
        Interpolation function
    za_min : float
        Minimum value of zenith angle in the lookup table (degree)
    za_max : float
        Maximum value of zenith angle in the lookup table (degree)
    """

    def __init__(self, lookup_table=None, method="pchip"):
        """
        Parameters
        ----------
        logger : logging.Logger
            A logger instance for debug/info/error outputs.
        lookup_table : str, optional
            A path to the ADC lookup CSV. If None, a default path is used.
        method : {'cubic', 'pchip', 'akima'}, optional
            The interpolation method to be used.
        """
        self.logger = AdcLogger(__file__)

        # 1) lookup_table이 None이면 _get_default_lookup_path()로 자동 설정
        if lookup_table is None:
            lookup_table = _get_default_lookup_path()

        # 2) 주어진(혹은 기본) lookup_table 경로로 Interpolation Function 생성
        self.create_interp_func(lookup_table, method)

    def create_interp_func(self, lookup_table, method):
        """
        Create the interpolation function using the given lookup table.

        Parameters
        ----------
        lookup_table : str
            File name of the ADC lookup table in CSV format.
            Column 1: zenith angle (degree) / Column 2: ADC angle (degree)

        method : str
            Interpolation method from the ADC lookup table
            It should be either 'cubic', 'pchip', or 'akima'.
        """
        # 경로 유효성 확인
        if not os.path.isfile(lookup_table):
            self.logger.error(f"Lookup table cannot be found: {lookup_table}")
            raise FileNotFoundError(f"Lookup table cannot be found: {lookup_table}")

        self.logger.info(f"Lookup table found: {lookup_table}")

        try:
            adc_raw_data = np.genfromtxt(lookup_table, comments="#", delimiter=",")
            data_za, data_adc = adc_raw_data[:, 0], adc_raw_data[:, 1]
            self.za_min, self.za_max = data_za.min(), data_za.max()
        except Exception as e:
            self.logger.error(f"Failed to read lookup table: {e}")
            raise ValueError(f"Failed to read lookup table: {e}")

        # Set interpolation function based on chosen method
        if method == "cubic":
            self.fn_za_adc = CubicSpline(data_za, data_adc)
        elif method == "pchip":
            self.fn_za_adc = PchipInterpolator(data_za, data_adc)
        elif method == "akima":
            self.fn_za_adc = Akima1DInterpolator(data_za, data_adc)
        else:
            self.logger.error(f"Invalid interpolation method: {method}")
            raise ValueError(f"Invalid interpolation method: {method}")

        self.logger.info(f"Interpolation function using {method} method created.")

    def calc_from_za(self, za):
        """
        Calculate the ADC angle from the input zenith angle using the interpolation function.

        Parameters
        ----------
        za : float or array-like
            Input zenith angle(s) in degrees.

        Returns
        -------
        float or array-like
            The corresponding ADC angle(s) in degrees.
        """
        if isinstance(za, (int, float)):  # For single values
            if za < self.za_min or za > self.za_max:
                self.logger.error(
                    f"Input zenith angle {za} is out of bounds ({self.za_min}, {self.za_max})"
                )
                raise ValueError(f"Input zenith angle {za} is out of bounds.")
        elif hasattr(za, "min") and hasattr(za, "max"):  # For numpy arrays, etc.
            if za.min() < self.za_min or za.max() > self.za_max:
                self.logger.error(
                    f"Input zenith angle array is out of bounds ({self.za_min}, {self.za_max})"
                )
                raise ValueError("Input zenith angle array is out of bounds.")
        else:
            self.logger.error(f"Invalid type for zenith angle: {type(za)}")
            raise TypeError(f"Invalid type for zenith angle: {type(za)}")

        return self.fn_za_adc(za)

    def degree_to_count(self, degree):
        """
        Convert a degree value to a corresponding count value.

        Parameters
        ----------
        degree : float
            The degree value to be converted. Should be between 0 and 360 (inclusive).

        Returns
        -------
        int
            The corresponding count value for the given degree.
        """
        count_per_degree = 16200 / 360  # 360 degrees = 16200 counts
        count = degree * count_per_degree

        self.logger.debug(f"Converted {degree} degrees to {int(count)} counts.")
        return int(count)
