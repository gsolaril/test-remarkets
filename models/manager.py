import os, sys, json
sys.path.append("./")

import pyRofex
from apscheduler.schedulers.background \
    import BackgroundScheduler as Scheduler
from pandas import Series, DataFrame, to_datetime, read_csv
from pyRofex import MarketDataEntry as MarketInfo
from configparser import ConfigParser
from yahooquery import Ticker

from utils.functions import *
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

    COLUMNS_SPECS_UNDERS = dict(marketCap = "shares", preMarketPrice = "pm_price",
        preMarketChangePercent = "pm_change", regularMarketPrice = "last_price",
        regularMarketChangePercent = "last_change", regularMarketVolume = "last_volume",
        regularMarketPreviousClose = "day_close_prev", regularMarketDayHigh = "day_high",
        regularMarketDayLow = "day_low", regularMarketOpen = "day_open", )
    
    COLUMNS_SPECS_DERIVS = dict(market = "market", segment = "segment", cficode = "cfi",
        currency = "base", maturity_date = "maturity", min_price_increment = "step_price",
        low_limit_price = "price_min", high_limit_price = "price_max", min_trade_vol = "volume_min",
        max_trade_vol = "volume_max", instrument_price_precision = "decimals_price",
        instrument_size_precision = "decimals_size", contract_multiplier = "contract",
        order_types = "order_types", times_inforce = "order_tifs", )

    HC_UNDERLYING = dict(GGAL = "GGAL.BA", YPFD = "YPFD.BA", PAMP = "PAMP.BA",
              ORO = "GC=F", GOLD = "GC=F", DLR = "USDARS=X", USD = "USDARS=X")

    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    def __init__(self, **kwargs):
        self.debug = kwargs.pop("debug", False)

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
            self.specs_derivs: DataFrame = read_csv(self.PATH_FILE_SPECS)
            self.specs_derivs: DataFrame = self.specs_derivs.set_index("symbol")
        else: self.specs_derivs: DataFrame = self.get_specs_derivs(self.environment)
        
        unders = self.specs_derivs["underlying"].unique()
        Log.info(f"Getting data for {len(unders)} underlyings.")
        freq_update_unders = kwargs.pop("freq_update_unders", 60)
        self.specs_unders = self.get_specs_unders(unders)
        verbose = {"n_deriv": self.specs_derivs.shape[0], "n_under": self.specs_unders.shape[0]}
        Log.success("Got specs for {n_deriv} symbols and {n_under} underlyings.", **verbose)
        Log.warning(f"Underlying data set to update every {freq_update_unders} seconds.")
        
        self.tasks = Scheduler(); self.tasks.add_job(
            name = "update_unders", func = self._update_unders,
            trigger = "interval", seconds = freq_update_unders)
        
        df_tasks = parse_tasks(self.tasks.get_jobs())
        Log.info(f"Scheduled tasks: \n{df_tasks}")
        self.tasks.start()

    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    @classmethod
    def get_specs_derivs(cls, environment: pyRofex.Environment):

        Log.warning(f"\"{cls.PATH_FILE_SPECS}\" not found. Downloading...")
        specs = DataFrame(pyRofex.get_detailed_instruments(environment))
        
        specs = specs["instruments"].apply(Series)
        columns = specs.columns.str.replace(**cls.REGEX_CAMEL_TO_SNAKE)
        specs.columns = columns.str.lower()

        specs.index = specs.pop("instrument_id").apply(Series)["symbol"]
        column = specs.pop("segment").apply(Series)
        specs["segment"] = column["marketSegmentId"]
        specs["market"] = column["marketId"]
        
        columns = cls.COLUMNS_SPECS_DERIVS.copy()
        specs = specs[[*columns]].rename(columns = columns, errors = "ignore")
        specs["maturity"] = to_datetime(specs["maturity"], format = "%Y%m%d")
        specs["order_types"] = specs["order_types"].map(", ".join)
        specs["order_tifs"] = specs["order_tifs"].map(", ".join)
        specs["underlying"] = specs.index.copy()

        subset = specs["underlying"].str.contains(" - ")
        subset = specs.loc[subset, "underlying"].str.split(" - ")
        specs.loc[subset.index, "underlying"] = subset.str[2]
        subset = specs["underlying"].str.contains("/|\.")
        subset = specs.loc[subset, "underlying"].str.split("/|\.")
        specs.loc[subset.index, "underlying"] = subset.str[0]
        
        specs["underlying"] = specs["underlying"].replace(cls.HC_UNDERLYING)
        Log.info(f"Replacements for underlying tickers: {cls.HC_UNDERLYING}")

        specs.to_csv(cls.PATH_FILE_SPECS)
        verbose = {"n_specs": len(specs), "path": cls.PATH_FILE_SPECS}
        Log.success("Saved {n_specs} symbol specs (\"{path}\")", **verbose)
        return specs
    
    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    @classmethod
    def get_specs_unders(cls, unders: list):

        y_tickers = Ticker(" ".join(unders))
        unders: Series = Series(y_tickers.price, name = "symbol")
        unders = unders.loc[unders.map(type).eq(dict)].apply(Series)
        unders: DataFrame = unders.rename(columns = cls.COLUMNS_SPECS_UNDERS)
        columns = unders.columns.intersection(cls.COLUMNS_SPECS_UNDERS.values())
        unders["shares"] = (unders["shares"] / unders["last_price"]).round()
        return unders[columns].dropna(how = "all")
    
    def _update_unders(self):
        
        if (len(self.symbol_feeds) == 0): return
        symbols = [*self.symbol_feeds.keys()]
        unders = self.specs_derivs.loc[symbols]
        unders = unders["underlying"].unique()        
        try: unders = self.get_specs_unders(unders)
        except Exception as EXC:
            Log.exception(EXC); return

        self.specs_unders.loc[unders.index] = unders
        updated = ", ".join("\"" + unders.index + "\"")
        if self.debug: Log.debug(f"Updated underlying data for: {updated}.")
        
    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    def load_strategies(self, strats: list):

        if not isinstance(strats, list): strats = [strats]
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
                try: strat.specs_derivs = self.specs_derivs.loc[symbols]
                except KeyError:
                    error = "At least one of the symbols from \"{strategy} - {name}\""
                    error += "doesn't exist:\n{symbols}... aborting strategy activation."
                    Log.warning(error, **verbose); continue

                self.strategies[strat.name] = strat
                for symbol in strat.specs_derivs.index:
                    if (symbol not in self.symbol_feeds):
                        self.symbol_feeds[symbol] = list()
                    feed: list = self.symbol_feeds[symbol]
                    feed.append(strat.name)

            Log.info("Loaded \"{strategy} - {name}\"", **verbose)
        
        self._update_unders()

    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    def toggle_strategies(self, **kwargs):
        
        actions = {True: "Enabled", False: "Disabled"}

        for name, value in kwargs.items():
            verbose = {"name": name}
            if name not in self.strategies:
                Log.warning("Strategy \"{name}\" invalid.", **verbose)
            else:
                strat: Strategy = self.strategies[name]
                strat.active = value
                verbose["action"] = actions[strat.active]
                verbose["strat"] = strat.__class__.__name__
                Log.warning("{action} \"{strat} - {name}\"", **verbose)

    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    def remove_strategies(self, names: list):

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

#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████
#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████
#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████
                
if (__name__ == "__main__"):

    manager = Manager(debug = True)