import os, sys
sys.path.append("../")

import pyRofex
from Loguru import logger as Log
from pandas import Series, DataFrame
from pandas import to_datetime, read_csv
from configparser import ConfigParser

from utils.constants import *
from models.strategy import Strategy

#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████
#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████
#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████

class Manager:

    PATH_FILE_SPECS = PATH_FOLDER_DOCS + "specs.csv"
    PATH_FILE_CREDS = PATH_FOLDER_AUTH + "credentials.ini"
    SYMBOL_TICKS_GLOBAL_MAX = 100000
    REGEX_CAMEL_TO_SNAKE = dict(regex = True,
        pat = "(.)([A-Z][a-z]?)", repl = r"\1_\2")

    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    def __init__(self, **kwargs):

        if not kwargs:
            kwargs = ConfigParser()
            kwargs.read(self.PATH_FILE_CREDS)
            kwargs = dict(**kwargs["REMARKET"],
                environment = pyRofex.Environment.REMARKET)

        pyRofex.initialize(**kwargs)
        self.user = kwargs["user"]
        self.account = kwargs["account"]
        self.password = kwargs["password"]
        self.environment = kwargs["environment"]

        self.strategies = dict()
        self.symbol_feeds = dict()
        self.symbol_ticks = DataFrame()

        if os.path.isfile(self.PATH_FILE_SPECS):
            self.specs = read_csv(self.PATH_FILE_SPECS)
            self.specs = self.specs.set_index("symbol")
        else: self.specs = self._get_specs(self.environment)

    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    @classmethod
    def _get_specs(cls, environment: pyRofex.Environment):

        specs = DataFrame(pyRofex.get_detailed_instruments(environment))
        specs = specs["instruments"].apply(Series)

        columns = specs.columns.str.replace(**cls.REGEX_CAMEL_TO_SNAKE)
        specs.columns = columns.str.lower()

        specs.index = specs.pop("instrument_id").apply(Series)["symbol"]
        column = specs.pop("segment").apply(Series)
        specs["segment"] = column["marketSegmentId"]
        specs["market"] = column["marketId"]

        columns = dict(
            market = "market", segment = "segment",
            cficode = "cfi", currency = "base",
            maturity_date = "maturity",
            min_price_increment = "step_price",
            low_limit_price = "price_min",
            high_limit_price = "price_max",
            contract_multiplier = "contract",
            min_trade_vol = "volume_min",    
            max_trade_vol = "volume_max",
            instrument_price_precision = "decimals_price",
            instrument_size_precision = "decimals_size",
            order_types = "order_types",
            times_in_force = "order_tifs",
        )
        specs = specs[[*columns]].rename(columns = columns, errors = "ignore")
        specs["maturity"] = to_datetime(specs["maturity"], format = "%Y%m%d")
        specs["order_types"] = specs["order_types"].map(", ".join)
        specs["order_tifs"] = specs["order_tifs"].map(", ".join)
        specs.to_csv(cls.PATH_FILE_SPECS)
        return specs
    
    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    def load_strategies(self, strats: list):

        if isinstance(strats, Strategy): strats = [strats]
        for strat in strats:
            strat: Strategy = strat
            if strat.name in self.strategies:
                print(f"Strategy {strat.name} already loaded")
            else:
                self.strategies[strat.name] = strat
                pyRofex.market_data_subscription(**strat.feeds)
                for symbol in strat.feeds.keys():
                    feed: list = self.symbol_feeds[symbol]
                    feed.append(strat.name)
                strat.active = True

    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    def toggle_strategies(self, **kwargs):

        for name, value in kwargs:
            if name not in self.strategies:
                print(f"Strategy {name} not loaded")
            else:
                strat: Strategy = self.strategies[name]
                strat.active = bool(value)

    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    def remove_strategies(self, names: list):

        if isinstance(names, str): names = [names]
        for name in names:
            if name not in self.strategies:
                print(f"Strategy {strat.name} not loaded")
            else:
                strat: Strategy = self.strategies.pop(name)
                # pyRofex.market_data_unsubscription() ?
                for symbol in strat.feeds.keys():
                    feed: list = self.symbol_feeds[symbol]
                    feed.remove(strat.name)
                strat.active = False; strat.__del__()
