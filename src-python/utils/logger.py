"""src/utils/logger.py — loguru ベースのロガー設定"""
import sys
from loguru import logger as _logger


def get_logger(name: str):
    """モジュール名付きのロガーを返す"""
    _logger.remove()
    _logger.add(
        sys.stdout,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level:<8}</level> | <cyan>{name}</cyan> - {message}",
        level="DEBUG",
        colorize=True,
    )
    return _logger.bind(name=name)
