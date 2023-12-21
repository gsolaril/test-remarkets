import os, sys, json
sys.path.append("./")

import warnings
from enum import Enum
from uuid import uuid4
from pandas import Series, DataFrame, Timestamp, Timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from pyRofex import Side as OrderSide, OrderType, TimeInForce
from utils.constants import *
from yfinance import Ticker

# Suppress FutureWarning messages
warnings.simplefilter(action = "ignore", category = FutureWarning)

#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████
#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████
#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████

class Signal:

    class Action(Enum): ORDER, MODIFY, CANCEL = range(3)

    RESPONSE_COLUMNS = ["id_signal", "id_order", "status", "prop", "symbol", "size",
         "price", "type", "side", "oper", "tif", "SL", "TP", "dms_send", "dms_exec"]
    
    @staticmethod
    def get_uid(n: int = 8):
        uid = str(uuid4()).upper()
        return uid.replace("-", "")[: n]
        
    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    def __init__(self, **kwargs):

        self.action = kwargs.pop("oper")
        assert isinstance(self.action, self.Action)
        self.comment = kwargs.pop("comment", "")
        assert isinstance(self.comment, str)
        self.id_signal = kwargs.pop("uid", self.get_uid())

        if (self.action == self.Action.ORDER):
            self.size = kwargs.pop("size")
            self.side = kwargs.pop("side")
            self.symbol = kwargs.pop("symbol")
            self.price = kwargs.pop("price", None)
            self.type = kwargs.pop("type", OrderType.LIMIT)
            if not self.price: self.type = OrderType.MARKET
            self.tif = kwargs.pop("tif", TimeInForce.DAY)
            self.SL = kwargs.pop("SL", None)
            self.TP = kwargs.pop("TP", None)
            self._type_check_basic()
            self._type_check_place()
            self.ID = None
        else:
            self.ID = kwargs.pop("ID")
            assert isinstance(self.ID, str)
            if (self.action == self.Action.MODIFY):
                self.price = kwargs.pop("price")
                self.SL = kwargs.pop("SL", None)
                self.TP = kwargs.pop("TP", None)
                self.size = kwargs.pop("size")
                self._type_check_basic()

    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    def _type_check_basic(self):
        assert isinstance(self.size, (int, float))
        assert isinstance(self.SL, (int, float)) or (self.SL is None)
        assert isinstance(self.TP, (int, float)) or (self.TP is None)
        assert isinstance(self.price, (int, float)) or (self.SL is None)

    def _type_check_place(self):
        assert isinstance(self.symbol, str)
        assert isinstance(self.type, OrderType)
        assert isinstance(self.side, OrderSide)
        assert isinstance(self.tif, TimeInForce)
        if (self.type == OrderType.LIMIT):
            assert self.price is not None

    def flip(self):
        self.side = {
            OrderSide.BUY: OrderSide.SELL,
            OrderSide.SELL: OrderSide.BUY
        }[self.side]
    
    @property
    def dict(self):
        return {
            "id_signal": self.id_signal, "symbol": self.symbol,
            "size": self.size, "price": self.price,
            "type": self.type.name, "side": self.side.name,
            "oper": self.action.name, "tif": self.tif.name,
            "SL": self.SL, "TP": self.TP, "id_order": self.ID}
    
    @property
    def form(self):
        return {
            "ticker": self.symbol, "size": self.size,
            "order_type": self.type, "side": self.side,
            "time_in_force": self.tif, "price": self.price}
    
    def __dict__(self):
        return self.dict
    
    def __repr__(self):
        return ("Signal(%s)" % ", ".join(["%s: %s"
                % KV for KV in self.dict.items()]))

    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    @classmethod
    def test(cls, symbol):
        return cls(symbol = symbol, side = OrderSide.SELL,
                    size = 1, oper = Signal.Action.ORDER)

#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████
#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████
#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████

class Strategy:

    TEMPLATE_SIGNALS = DataFrame(columns = Signal.RESPONSE_COLUMNS).rename_axis("ts_resp")

    FREQ_UPD_UNDERS = Timedelta(minutes = 1)
    COLUMNS_UNDERLYING = ["currency", "exchange", "open", "shares", "day_high",
                      "day_low", "previous_close", "last_price", "last_volume"]

    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    def __init__(self, name: str, symbols: list, tasks: dict = dict()):

        strat_class = self.__class__.__name__
        Log.configure(extra = {"obj": "Strategy"})

        self.name, self.active = name, False
        self.time_executed = Timestamp("NaT")
        self.time_activated = Timestamp("NaT")
        self.time_created = Timestamp.utcnow()
        self.signals = self.TEMPLATE_SIGNALS.copy()
        self.specs_derivs = DataFrame(index = symbols)
        self.last_order = Signal.test(symbols[0])
        self.tasks = BackgroundScheduler()

        verbose = {"name": name, "strat": strat_class}

        tasks = {self.update_unders: self.FREQ_UPD_UNDERS, **tasks}
        for task, freq in tasks.items():
            freq: Timedelta = freq.total_seconds()
            self.tasks.add_job(func = task, seconds = freq,
                trigger = "interval", name = task.__name__)
            
        Log.info("Tasks for \"{strat} - {name}\":", **verbose)
        self.tasks.print_jobs()

    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    def update_derivs(self, specs: DataFrame):
        self.specs_derivs = specs.copy()
        unders = self.specs_derivs["underlying"].unique()
        self.specs_unders = DataFrame(index = unders,
                    columns = self.COLUMNS_UNDERLYING)
        self.update_unders()

    # FIXME: MOVE UNDERLYING DATA RETRIEVAL AND SCHEDULE TO MANAGER

    def update_unders(self): 
        if self.specs_derivs.empty: return
        unders = Series(self.specs_unders.index)
        specs_unders = unders.map(Ticker).map(self._parse_yf)
        specs_unders = specs_unders.apply(Series).set_index(unders)
        self.specs_unders = specs_unders

    @classmethod
    def _parse_yf(cls, ticker: Ticker):
        data = ticker.fast_info
        try: data = data.toJSON()
        except: data = "{}"
        return json.loads(data)

    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    def on_tick(self, data: DataFrame) -> list:
        
        self.last_order.flip()
        print("Strategy", self.name, "on_tick")
        print(), print(data)
        return [self.last_order]
