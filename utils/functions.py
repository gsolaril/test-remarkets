import os, sys
sys.path.append("./")
from loguru import logger as Log
from apscheduler.job import Job
from pandas import DataFrame, Timestamp, Timedelta
from utils.constants import *

#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████

LOG_FORMAT_TS = "{time:YYYY-MM-DD HH:mm:ss!UTC}"
LOG_FORMAT_COLORS = dict(DEBUG = "blue", WARNING = "yellow", ERROR = "red", CRITICAL = "bold_red")
LOG_FORMAT_ENTRY = "[<level>" + LOG_FORMAT_TS + " | {name}.{function} @ L{line}</level>] {message}"
LOG_FILENAME = PATH_FOLDER_LOGS + "{time:MM-DD HH.mm}.log"

Log.remove(0)

Log.add(format = LOG_FORMAT_ENTRY, sink = sys.stdout, 
    colorize = True, level = "DEBUG", backtrace = False)
Log.add(format = LOG_FORMAT_ENTRY, sink = LOG_FILENAME, 
    colorize = True, level = "DEBUG", backtrace = False)
Log.info(f"Log files stored in \"{PATH_FOLDER_LOGS}\"")


#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████

def parse_tasks(tasks: list):

    columns = ["trigger", "next_run_in"]
    df = DataFrame(columns = columns)
    for task in tasks:
        task: Job = task
        try:
            next_run = Timestamp(task.next_run_time)
            next_run_in: Timedelta = next_run - Timestamp.utcnow()
            next_run_in = TD_STR_FORMAT.format(*next_run_in.components)
        except Exception as EXC: next_run = next_run_in = None
        fields = [task.trigger, next_run_in]
        df.loc[task.name] = dict(zip(columns, fields))

    return df