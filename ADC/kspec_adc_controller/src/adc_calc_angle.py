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

    def __init__(self, logger, lookup_table="./etc/ADC_lookup.csv", method="pchip"):
        self.logger = logger
        self.create_interp_func(lookup_table, method)

    def create_interp_func(self, lookup_table, method):
        """
        Create the interpolation function using the given lookup table

        Parameters
        ----------
        lookup_table : str
            File name of the ADC lookup table in CSV format.
            Column 1: zenith angle (degree) / Column 2: ADC angle (degree)

        method : str
            Interpolation method from the ADC lookup table
            It should be either 'cubic','pchip', or 'akima'.

        Raises
        ------
        FileNotFoundError
            If the ADC lookup table file does not exist at the given file name
        """

        if not os.path.isfile(lookup_table):
            self.logger.error(f"Lookup table cannot be found: {lookup_table}")
            raise FileNotFoundError(f"Lookup table cannot be found: {lookup_table}")

        self.logger.info(f"Lookup table found: {lookup_table}")

        try:
            adc_raw_data = np.genfromtxt(lookup_table, comments="#", delimiter=",")
            data_za, data_adc = adc_raw_data[:, 0], adc_raw_data[:, 1]
            self.za_min, self.za_max = data_za.min(), data_za.max()
        except Exception as e:
            self.logger.error(f"Lookup table cannot be read well: {str(e)}")
            raise ValueError(f"Lookup table cannot be read well: {str(e)}")

        self.fn_za_adc = ""
        if method == "cubic":
            self.fn_za_adc = CubicSpline(data_za, data_adc)
        elif method == "pchip":
            self.fn_za_adc = PchipInterpolator(data_za, data_adc)
        elif method == "akima":
            self.fn_za_adc = Akima1DInterpolator(data_za, data_adc)
        else:
            self.logger.error(
                f"Cannot find the corresponding interpolation method: {method}"
            )
            raise ValueError(
                f"Cannot find the corresponding interpolation method: {method}"
            )

        self.logger.info("Zenith angle-ADC angle interpolation function created")

    def calc_from_za(self, za):
        """
        Calculate the ADC angle from the input zenith angle
        by using the interpolation function

        Parameters
        ----------
        za_angle : float or array(float)
            Input zenith angle (degree)

        Returns
        -------
        float or array(float)
            The corresponding ADC angle (degree)

        """
        if isinstance(za, (int, float)):  # za가 정수나 실수인 경우
            if za < self.za_min or za > self.za_max:
                self.logger.error(f"Input zenith angle is out of bound: {za}")
                raise ValueError(f"Input zenith angle is out of bound: {za}")
        elif hasattr(za, "min") and hasattr(
            za, "max"
        ):  # za가 배열(리스트 또는 Numpy 배열 등)인 경우
            if za.min() < self.za_min or za.max() > self.za_max:
                self.logger.error(f"Input zenith angle is out of bound: {za}")
                raise ValueError(f"Input zenith angle is out of bound: {za}")
        else:
            self.logger.error(f"Invalid type for zenith angle: {type(za)}")
            raise TypeError(f"Invalid type for zenith angle: {type(za)}")

        return self.fn_za_adc(za)

    def degree_to_count(self, degree):
        """
        Convert a degree value to a corresponding count value.

        This function uses a proportional relationship where 360 degrees corresponds to 16200 counts.
        It returns the count value as an integer based on the given degree.

        Parameters
        ----------
        degree : float
            The degree value to be converted. Should be between 0 and 360 (inclusive).

        Returns
        -------
        int
            The corresponding count value for the given degree.

        Examples
        --------
        >>> degree_to_count(180)
        8100

        >>> degree_to_count(90)
        4050
        """
        # 360 degrees = 16200 counts
        count_per_degree = 16200 / 360

        # Calculate the count for the given degree
        count = degree * count_per_degree

        # Log the conversion information
        self.logger.debug(f"Converted {degree} degrees to {int(count)} counts.")

        return int(count)  # Return the count as an integer
