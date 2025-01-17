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

    def __init__(self, lookup_table="./ADC/Simul/kspec_adc_controller/src/etc/ADC_lookup.csv", method="pchip"):
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

        Raises
        ------
        FileNotFoundError
            If the ADC lookup table file does not exist at the given file name
        ValueError
            If the specified interpolation method is not valid.
        """
        if not os.path.isfile(lookup_table):
            raise FileNotFoundError(f"Lookup table cannot be found: {lookup_table}")

        try:
            adc_raw_data = np.genfromtxt(lookup_table, comments="#", delimiter=",")
            data_za, data_adc = adc_raw_data[:, 0], adc_raw_data[:, 1]
            self.za_min, self.za_max = data_za.min(), data_za.max()
        except Exception as e:
            raise ValueError(f"Failed to read lookup table: {e}")

        # Set interpolation function based on chosen method
        if method == "cubic":
            self.fn_za_adc = CubicSpline(data_za, data_adc)
        elif method == "pchip":
            self.fn_za_adc = PchipInterpolator(data_za, data_adc)
        elif method == "akima":
            self.fn_za_adc = Akima1DInterpolator(data_za, data_adc)
        else:
            raise ValueError(f"Invalid interpolation method: {method}")

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

        Raises
        ------
        ValueError
            If the zenith angle is out of bounds.
        TypeError
            If the input zenith angle type is not valid.
        """
        if isinstance(za, (int, float)):  # For single values
            if za < self.za_min or za > self.za_max:
                raise ValueError(f"Input zenith angle {za} is out of bounds.")
        elif hasattr(za, "min") and hasattr(za, "max"):  # For arrays
            if za.min() < self.za_min or za.max() > self.za_max:
                raise ValueError("Input zenith angle array is out of bounds.")
        else:
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

        # Log the conversion information

        return int(count)
