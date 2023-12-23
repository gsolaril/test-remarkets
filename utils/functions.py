import os, sys
sys.path.append("./")
from loguru import logger as Log
from apscheduler.job import Job
from pandas import DataFrame, Timestamp, Timedelta
from utils.constants import *

#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████

# Variables de configuración y formato de Loguru.
LOG_FORMAT_TS = "{time:YYYY-MM-DD HH:mm:ss!UTC}"
LOG_FORMAT_ENTRY = "[<level>" + LOG_FORMAT_TS + " | {name}.{function} @ L{line}</level>] {message}"
LOG_FILENAME = PATH_FOLDER_LOGS + "{time:MM-DD HH.mm}.log"

Log.remove(0)
# Logger a ser printeado en consola.
Log.add(format = LOG_FORMAT_ENTRY, sink = sys.stdout, 
    colorize = True, level = "DEBUG", backtrace = False)
# Logger a ser guardado en archivos ".log".
Log.add(format = LOG_FORMAT_ENTRY, sink = LOG_FILENAME, 
    colorize = True, level = "DEBUG", backtrace = False)
Log.info(f"Log files stored in \"{PATH_FOLDER_LOGS}\"")


#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████

def parse_tasks(tasks: list):
    """
    Printea en consola, un DataFrame con una fila por "`task`", y sus respectivos datos. El "`trigger`" es la condición de
    ejecución del task (ej: "cada una hora"), y "`next_run_in`" es el tiempo que falta para que el task vuelva a correrse.
    Cuando el "`Scheduler`" todavía no inició su actividad mediante "`Scheduler.start`", este va a ser "`None`".
    name        | trigger               | next_run_in
    ------------|-----------------------|------------
    `my_task_1` | interval[01:00:00]    | 00:51:39
    `my_task_2` | interval[00:01:00]    | 00:00:39
    \nInputs:
    * "`tasks`": ("`list`"): Lista de "`Jobs`" (como la provista por "`Scheduler.get_jobs`")
    \nOutputs:
    * "`df`" ("`DataFrame`"): El DataFrame mencionado.
    """
    columns = ["trigger", "next_run_in"]
    # Crear DataFrame vacía a llenar.
    df = DataFrame(columns = columns)
    for task in tasks:
        task: Job = task
        try: # Puede que "task.next_run_time" no exista todavía,
            # si es que el Scheduler todavía no ha sido iniciado.
            next_run = Timestamp(task.next_run_time)
            next_run_in: Timedelta = next_run - Timestamp.utcnow()
            next_run_in = TD_STR_FORMAT.format(*next_run_in.components)
        # Cuando el Scheduler todavía no ha iniciado su actividad...
        except Exception as EXC: next_run = next_run_in = None
        # Insertar datos en el DataFrame.
        fields = [task.trigger, next_run_in]
        df.loc[task.name] = dict(zip(columns, fields))

    return df