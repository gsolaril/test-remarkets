import os, sys
sys.path.append("./")
from loguru import logger as Log

# Directorios importantes.
PATH_FOLDER_AUTH = "./auth/"
PATH_FOLDER_DOCS = "./docs/"
PATH_FOLDER_LOGS = "./logs/"

# Formato "timedeltas". Ejemplo: "2d, 12:43:39"
TD_STR_FORMAT = "{0}d, {1:02d}:{2:02d}:{3:02d}"