import logging

# Keep test output quiet and never write log files into temp dirs.
_logger = logging.getLogger("ssb")
_logger.handlers = [logging.NullHandler()]
_logger.propagate = False
_logger._ssb_configured = True
