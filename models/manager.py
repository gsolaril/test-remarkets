import os, sys
sys.path.append("./")

import pyRofex
from pyRofex import MarketDataEntry as MarketInfo
from pandas import Series, DataFrame
from pandas import to_datetime, read_csv
from configparser import ConfigParser

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

    HC_UNDERLYING = dict(YPFD = "YPF", ORO = "XAUUSD=X")

    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    def __init__(self, **kwargs):

        Log.configure(extra = {"obj": "Manager"})

        if not kwargs:
            kwargs = ConfigParser()
            kwargs.read(self.PATH_FILE_CREDS)
            kwargs = dict(**kwargs["REMARKET"],
                environment = pyRofex.Environment.REMARKET)
            
            Log.info(f"Using \"{self.PATH_FILE_CREDS}\"")

        Log.info("Connecting to \"{user} - {account}\"", **kwargs)

        try: pyRofex.initialize(**kwargs), Log.success(f"Connected OK")
        except Exception as EXC: Log.error(f"Connection error: {repr(EXC)}")

        self.user = kwargs.pop("user")
        self.account = kwargs.pop("account")
        self.password = kwargs.pop("password")
        self.environment = kwargs.pop("environment")

        self.strategies, self.symbol_feeds = dict(), dict()
        self.symbol_ticks = self.TEMPLATE_MARKET_DATA.copy()

        if os.path.isfile(self.PATH_FILE_SPECS):
            self.specs: DataFrame = read_csv(self.PATH_FILE_SPECS)
            self.specs: DataFrame = self.specs.set_index("symbol")
        else: self.specs: DataFrame = self._get_specs(self.environment)

        verbose = {"n_specs": len(self.specs), "path": self.PATH_FILE_SPECS}
        Log.success("Got {n_specs} symbol specs (\"{path}\")", **verbose)

    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    @classmethod
    def _get_specs(cls, environment: pyRofex.Environment):

        Log.warning(f"\"{cls.PATH_FILE_SPECS}\" not found. Downloading...")
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

        specs["underlying"] = specs.index.copy()
        is_line = specs.index.str.contains(" - ")
        is_point = specs.index.str.contains(".")
        is_slash = specs.index.str.contains("/")
        specs.loc[is_line, "underlying"] = specs.index.str.split(" - ").str[2]
        specs.loc[is_slash, "underlying"] = specs.index.str.split("/").str[0]
        specs.loc[is_point, "underlying"] = specs.index.str.split(".").str[0]
        Log.debug(f"Replacements for underlying tickers: {cls.HC_UNDERLYING}")

        for replace in cls.HC_UNDERLYING:
            specs["underlying"] = specs["underlying"].replace(**replace)

        specs.to_csv(cls.PATH_FILE_SPECS)
        verbose = {"n_specs": len(specs), "path": cls.PATH_FILE_SPECS}
        Log.success("Saved {n_specs} symbol specs (\"{path}\")", **verbose)
        return specs
    
    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    def load_strategies(self, strats: list):

        Log.configure(extra = {"obj": "Manager"})

        if isinstance(strats, Strategy): strats = [strats]
        for strat in strats:
            strat: Strategy = strat
            if strat.name in self.strategies:
                Log.warning(f"Strategy {strat.name} already loaded")
            else:
                symbols = strat.specs_derivs.index.to_list()
                verbose = {"strategy": strat.__class__.__name__,
                        "name": strat.name, "symbols": symbols}
                Log.info("Loading \"{strategy} - {name}\".", **verbose)
                pyRofex.market_data_subscription(tickers = symbols,
                        entries = self.MARKET_DATA_ENUMS, depth = 5)
                Log.success("Subscribed to: " + ", ".join(symbols))
                self.strategies[strat.name] = strat
                
                strat_specs = self.specs.loc[symbols]
                strat.update_derivs(strat_specs.copy())
                # strat.tasks.start()
                for symbol in strat.specs_derivs.index:
                    if (symbol not in self.symbol_feeds):
                        self.symbol_feeds[symbol] = list()
                    feed: list = self.symbol_feeds[symbol]
                    feed.append(strat.name)

            Log.info("Loaded \"{strategy} - {name}\"", **verbose)

    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    def toggle_strategies(self, **kwargs):

        Log.configure(extra = {"obj": "Manager"})
        actions = {True: "Enabled", False: "Disabled"}

        for name, value in kwargs.items():
            verbose = {"name": name}
            if name not in self.strategies:
                Log.warning("Strategy \"{name}\" invalid.", **verbose)
            else:
                strat: Strategy = self.strategies[name]
                verbose["strat"] = strat.__class__.__name__
                verbose["action"] = actions[value]
                strat.active = bool(value)
                Log.warning("{action} \"{strat} - {name}\"", **verbose)

    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    def remove_strategies(self, names: list):

        Log.configure(extra = {"obj": "Manager"})

        if isinstance(names, str): names = [names]
        for name in names:
            verbose = {"name": name}
            if name not in self.strategies:
                Log.warning("Strategy {strat.name} invalid", **verbose)
            else:
                strat: Strategy = self.strategies.pop(name)
                verbose["strat"] = strat.__class__.__name__
                # pyRofex.market_data_unsubscription() ?
                for symbol in strat.specs_derivs:
                    feed: list = self.symbol_feeds[symbol]
                    feed.remove(strat.name)
                strat.active = False; strat.__del__()
                Log.warning("Removed \"{strat} - {name}\"", **verbose)