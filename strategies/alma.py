import os, sys
sys.path.append("../")

import numpy, pyRofex
from pandas import Series, DataFrame
from pandas import Timestamp, DatetimeIndex
from models.strategy import *

#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████
#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████
#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████

class Alma(Strategy):

    def __init__(self, **kwargs):

        super().__init__(**kwargs)

#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████

    def exec(self, data: DataFrame) -> list:

