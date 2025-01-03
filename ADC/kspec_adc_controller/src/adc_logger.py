#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# @Author: Mingyeong Yang (mmingyeong@kasi.re.kr)
# @Date: 2024-12-04
# @Filename: adc_logger.py

import logging
import os
import datetime


class LoggerInitializationError(Exception):
    """
    Custom exception: Raised when attempting to initialize a duplicate logger.
    """

    pass


class AdcLogger:
    """
    A logging utility class for managing console and file logging with distinct levels.

    This class ensures each logger is uniquely initialized based on the file name and timestamp.
    It supports simultaneous logging to the console and a file with configurable log levels.

    Attributes
    ----------
    file_name : str
        Name of the log file with a timestamp.
    log_path : str
        Absolute path to the generated log file.
    """

    _initialized_loggers = set()  # Prevent duplicate loggers

    def __init__(
        self,
        file,
        log_directory=".",
        stream_level=logging.DEBUG,
        file_level=logging.INFO,
    ):
        """
        Initialize the logger with specified file name, log directory, and log levels.

        Parameters
        ----------
        file : str
            Base name for the log file.
        log_directory : str, optional
            Directory where log files are stored. Defaults to the current directory.
        stream_level : int, optional
            Logging level for console output. Defaults to logging.DEBUG.
        file_level : int, optional
            Logging level for file output. Defaults to logging.INFO.

        Raises
        ------
        LoggerInitializationError
            If a logger for the specified file is already initialized.
        """
        base_name = os.path.splitext(os.path.basename(file))[0]
        current_time = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.file_name = f"{base_name}_{current_time}.log"
        self.log_path = os.path.join(log_directory, self.file_name)

        # Check for duplicate file paths (파일 핸들러가 없는 경우에도 절대 경로를 사용하여 중복을 체크할 수 있습니다)
        absolute_path = os.path.abspath(self.log_path)
        if absolute_path in AdcLogger._initialized_loggers:
            raise LoggerInitializationError(
                f"Logger for '{absolute_path}' has already been initialized."
            )

        # Create logger
        self.logger = logging.getLogger(self.file_name)
        self.logger.setLevel(logging.DEBUG)  # Set the lowest level

        # Configure formatter
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S"
        )

        # Console handler (파일 핸들러는 추가하지 않음)
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        stream_handler.setLevel(stream_level)
        self.logger.addHandler(stream_handler)

        # Add logger to initialized loggers to avoid reinitialization with the same file
        AdcLogger._initialized_loggers.add(absolute_path)

    def log(self, level, message):
        """
        Output log messages based on the specified level.

        Parameters
        ----------
        level : int
            The logging level (e.g., logging.INFO, logging.DEBUG).
        message : str
            The message to log.
        """
        self.logger.log(level, f"{message}")

    def info(self, message):
        """
        Log an informational message.

        Parameters
        ----------
        message : str
            The message to log.
        """
        self.log(logging.INFO, message)

    def debug(self, message):
        """
        Log a debug message.

        Parameters
        ----------
        message : str
            The message to log.
        """
        self.log(logging.DEBUG, message)

    def warning(self, message):
        """
        Log a warning message.

        Parameters
        ----------
        message : str
            The message to log.
        """
        self.log(logging.WARNING, message)

    def error(self, message):
        """
        Log an error message.

        Parameters
        ----------
        message : str
            The message to log.
        """
        self.log(logging.ERROR, message)

    def close(self):
        """
        Close handlers added to the logger and remove it from initialized loggers.

        This method ensures that file resources are properly released and prevents
        further logging to this logger instance.
        """
        for handler in self.logger.handlers[:]:
            handler.close()
            self.logger.removeHandler(handler)
        absolute_path = os.path.abspath(self.log_path)
        AdcLogger._initialized_loggers.discard(absolute_path)
