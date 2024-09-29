import sys
from loguru import logger
from config import config


def setup_logger():
    """
    Configure and set up the logger with custom formatting.

    :return: Configured logger instance
    """
    # Remove the default logger
    logger.remove()

    # Add a new sink to stdout with a custom format
    logger.add(
        sys.stdout,
        colorize=True,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
        level=config.LOG_LEVEL
    )

    return logger


# Create and configure the logger
logger = setup_logger()
