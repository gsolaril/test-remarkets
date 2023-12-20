import os, sys
sys.path.append("./")

import pyRofex
from pyRofex import MarketDataEntry as MarketInfo
from pandas import Series, DataFrame
from pandas import to_datetime, read_csv
from configparser import ConfigParser
from loguru import logger as Log

from utils.constants import *
from strategy import Strategy

#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████
#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████
#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████

class Manager:

    PATH_FILE_SPECS = PATH_FOLDER_DOCS + "specs.csv"
    PATH_FILE_CREDS = PATH_FOLDER_AUTH + "credentials.ini"
    SYMBOL_TICKS_GLOBAL_MAX = 100000
    REGEX_CAMEL_TO_SNAKE = dict(pat = "(.)([A-Z][a-z]?)", repl = r"\1_\2", regex = True)
    
    MARKET_DATA_ENUMS = [
        MarketInfo.BIDS, MarketInfo.OFFERS, MarketInfo.LAST, MarketInfo.INDEX_VALUE,
        MarketInfo.TRADE_VOLUME, MarketInfo.NOMINAL_VOLUME, MarketInfo.OPEN_INTEREST]
    
    MARKET_DATA_COLUMNS = ["market", "symbol", "price_last", "size_last", "dms_last", "dms_event",
        "price_ask_l1", "size_ask_l1", "price_ask_l2", "size_ask_l2", "price_ask_l3", "size_ask_l3",
        "price_ask_l4", "size_ask_l4", "price_ask_l5", "size_ask_l5", "price_bid_l1", "size_bid_l1",
        "price_bid_l2", "size_bid_l2", "price_bid_l3", "size_bid_l3", "price_bid_l4", "size_bid_l4",
        "price_bid_l5", "size_bid_l5", "iv", "tv", "oi", "nv"]
    
    TEMPLATE_MARKET_DATA = DataFrame(columns = MARKET_DATA_COLUMNS).rename_axis("ts_local")

    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    def __init__(self, **kwargs):

        if not kwargs:
            kwargs = ConfigParser()
            kwargs.read(self.PATH_FILE_CREDS)
            kwargs = dict(**kwargs["REMARKET"],
                environment = pyRofex.Environment.REMARKET)

        pyRofex.initialize(**kwargs)
        self.user = kwargs.pop("user")
        self.account = kwargs.pop("account")
        self.password = kwargs.pop("password")
        self.environment = kwargs.pop("environment")

        self.strategies, self.symbol_feeds = dict(), dict()
        self.symbol_ticks = self.TEMPLATE_MARKET_DATA.copy()

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
                pyRofex.market_data_subscription(
                    tickers = strat.symbols, depth = 5,
                    entries = self.MARKET_DATA_ENUMS)
                for symbol in strat.symbols:
                    if (symbol not in self.symbol_feeds):
                        self.symbol_feeds[symbol] = list()
                    feed: list = self.symbol_feeds[symbol]
                    feed.append(strat.name)

    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    def toggle_strategies(self, **kwargs):

        for name, value in kwargs.items():
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
                for symbol in strat.symbols:
                    feed: list = self.symbol_feeds[symbol]
                    feed.remove(strat.name)
                strat.active = False; strat.__del__()