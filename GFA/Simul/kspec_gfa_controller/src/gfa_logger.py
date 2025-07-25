#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# @Author: Mingyeong Yang (mmingyeong@kasi.re.kr)
# @Date: 2023-12-07
# @Filename: gfa_logger.py

import logging
import os
from datetime import datetime
from typing import Optional

__all__ = ["GFALogger"]


class GFALogger:
    """
    A custom logger for the GFA project that manages both stream (console)
    and file logging. Prevents multiple handlers from being added to the same logger.

    Log files are written to a daily file under the 'log/' directory by default.
    """

    _initialized_loggers: set[str] = set()
    """
    A class-level set to track already-initialized loggers and prevent
    duplicate handler attachments.
    """

    def __init__(
        self,
        file: str,
        stream_level: int = logging.DEBUG,
        log_dir: Optional[str] = None,
    ) -> None:
        """
        Initialize the logger.

        Parameters
        ----------
        file : str
            The path of the Python file requesting the logger (used to name the logger).
        stream_level : int, optional
            Logging level for the console output. Default is logging.DEBUG.
        log_dir : str, optional
            Directory to store log files. If None, defaults to 'log/' under the script path.
        """
        script_dir = os.path.dirname(os.path.abspath(__file__))
        if log_dir is None:
            log_dir = os.path.join(script_dir, "log")

        self.file_name = os.path.basename(file)
        self.logger = logging.getLogger(self.file_name)

        if self.file_name in GFALogger._initialized_loggers:
            return

        self.logger.setLevel(logging.DEBUG)
        os.makedirs(log_dir, exist_ok=True)

        log_filename = f"gfa_{datetime.now().strftime('%Y-%m-%d')}.log"
        log_file_path = os.path.join(log_dir, log_filename)

        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

        # Stream handler (console)
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        stream_handler.setLevel(stream_level)
        self.logger.addHandler(stream_handler)

        # File handler
        file_handler = logging.FileHandler(log_file_path, mode="a", encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.DEBUG)
        self.logger.addHandler(file_handler)

        GFALogger._initialized_loggers.add(self.file_name)

    def info(self, message: str) -> None:
        """
        Log a message at INFO level.

        Parameters
        ----------
        message : str
            Message to log.
        """
        self.logger.info(message)

    def debug(self, message: str) -> None:
        """
        Log a message at DEBUG level.

        Parameters
        ----------
        message : str
            Message to log.
        """
        self.logger.debug(message)

    def warning(self, message: str) -> None:
        """
        Log a message at WARNING level.

        Parameters
        ----------
        message : str
            Message to log.
        """
        self.logger.warning(message)

    def error(self, message: str) -> None:
        """
        Log a message at ERROR level.

        Parameters
        ----------
        message : str
            Message to log.
        """
        self.logger.error(message)
