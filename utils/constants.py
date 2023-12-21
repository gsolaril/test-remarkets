import os, sys
sys.path.append("./")
from loguru import logger as Log

PATH_FOLDER_AUTH = "./auth/"
PATH_FOLDER_DOCS = "./docs/"
PATH_FOLDER_LOGS = "./logs/"

LOG_FORMAT_TS = "{time:YYYY-MM-DD HH:mm:ss!UTC}"
LOG_FORMAT_COLORS = dict(DEBUG = "gray", WARNING = "yellow", ERROR = "red", CRITICAL = "bold_red")
LOG_FORMAT_ENTRY = "[<level>" + LOG_FORMAT_TS + " | {extra[obj]} | {function} @ L{line}</level>] {message}"
LOG_FILENAME = PATH_FOLDER_LOGS + "{time:MM-DD HH.mm}.log"

Log.remove(0)

Log.add(format = LOG_FORMAT_ENTRY, sink = sys.stdout, 
    colorize = True, level = "DEBUG", backtrace = False)
Log.add(format = LOG_FORMAT_ENTRY, sink = LOG_FILENAME, 
    colorize = True, level = "DEBUG", backtrace = False)

Log.configure(extra = {"obj": "startup"})
Log.info(f"Log files stored in \"{PATH_FOLDER_LOGS}\"")

def bind(func):
    def wrapper(*args, **kwargs):
        obj = func.__call__.__self__
        name = obj.__class__.__name__
        Log.configure(extra = {"obj": name})
        return func(*args, **kwargs)
    return wrapper