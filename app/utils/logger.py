"""Centralized logging configuration for production deployment.

Provides structured logging with:
- Rotating file handlers (prevents disk overflow)
- Separate logs for queries, indexing, and general app
- Query analytics tracking (usage, performance, results)
- Clean console output for development
"""
import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler
from datetime import datetime
from typing import Optional

# Create logs directory
LOGS_DIR = Path(__file__).parent.parent.parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)

# Log file paths
APP_LOG = LOGS_DIR / "app.log"
QUERY_LOG = LOGS_DIR / "query.log"
INDEXER_LOG = LOGS_DIR / "indexer.log"

# Formatters
DETAILED_FORMAT = logging.Formatter(
    fmt='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

SIMPLE_FORMAT = logging.Formatter(
    fmt='%(levelname)-8s | %(message)s'
)


def get_logger(name: str, log_file: Optional[Path] = None) -> logging.Logger:
    """Get or create a logger with file and console handlers.
    
    Args:
        name: Logger name (usually __name__)
        log_file: Optional specific log file (defaults to app.log)
    
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    
    # Avoid duplicate handlers
    if logger.handlers:
        return logger
    
    logger.setLevel(logging.INFO)
    logger.propagate = False
    
    # File handler with rotation (10MB max, keep 5 backups)
    file_path = log_file or APP_LOG
    file_handler = RotatingFileHandler(
        file_path,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(DETAILED_FORMAT)
    logger.addHandler(file_handler)
    
    # Console handler (only warnings and errors in production)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(SIMPLE_FORMAT)
    logger.addHandler(console_handler)
    
    return logger


def get_query_logger() -> logging.Logger:
    """Get specialized logger for query analytics."""
    logger = logging.getLogger("query_analytics")
    
    if logger.handlers:
        return logger
    
    logger.setLevel(logging.INFO)
    logger.propagate = False
    
    # Dedicated query log file
    query_handler = RotatingFileHandler(
        QUERY_LOG,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding='utf-8'
    )
    query_handler.setLevel(logging.INFO)
    
    # Custom format for query analytics
    query_format = logging.Formatter(
        fmt='%(asctime)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    query_handler.setFormatter(query_format)
    logger.addHandler(query_handler)
    
    return logger


def get_indexer_logger() -> logging.Logger:
    """Get specialized logger for indexing operations."""
    return get_logger("indexer", INDEXER_LOG)


def log_query_analytics(
    query: str,
    model_id: str,
    code_snippets_count: int,
    db_entities_found: int,
    response_time_ms: float,
    success: bool,
    error: Optional[str] = None
):
    """Log query analytics in structured format.
    
    Format: timestamp | query | model | snippets | db_entities | time_ms | success | error
    """
    query_logger = get_query_logger()
    
    # Truncate query for readability
    query_short = query[:100] + "..." if len(query) > 100 else query
    
    log_line = (
        f"QUERY={query_short} | "
        f"MODEL={model_id} | "
        f"CODE_SNIPPETS={code_snippets_count} | "
        f"DB_ENTITIES={db_entities_found} | "
        f"TIME_MS={response_time_ms:.2f} | "
        f"SUCCESS={success}"
    )
    
    if error:
        log_line += f" | ERROR={error}"
    
    query_logger.info(log_line)


# Pre-configured loggers for common use
app_logger = get_logger("app")
github_logger = get_logger("github_retriever")
indexer_logger = get_indexer_logger()
