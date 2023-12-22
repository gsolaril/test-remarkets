import os, sys, json
sys.path.append("./")

import warnings
from enum import Enum
from uuid import uuid4
from pandas import Series, DataFrame, Timestamp, Timedelta
from pyRofex import Side as OrderSide, OrderType, TimeInForce
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.date import DateTrigger
from utils.constants import *
from utils.functions import *
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
            "SL": self.SL, "TP": self.TP, "id_order": self.ID,
            "comment": self.comment}
    
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

        self.strat_class = self.__class__.__name__
        verbose = {"name": name, "strat": self.strat_class}

        self.name, self.active = name, False
        self.time_stopped = Timestamp("NaT")
        self.time_executed = Timestamp("NaT")
        self.time_activated = Timestamp("NaT")
        self.time_created = Timestamp.utcnow()
        self.signals = self.TEMPLATE_SIGNALS.copy()
        self.specs_derivs = DataFrame(index = symbols)
        self.last_order = Signal.test(symbols[0])
        self.tasks = BackgroundScheduler()

        if not tasks:
            Log.info("No parallel tasks for \"{strat} - {name}\"", **verbose)
        else:
            for task, trigger in tasks.items():
                self.tasks.add_job(trigger = trigger,
                    func = task, name = task.__name__)
            
            verbose["tasks"] = parse_tasks(self.tasks.get_jobs())
            Log.info("Tasks for \"{strat} - {name}\": \n{tasks}", **verbose)

        self.tasks.start(paused = True)

    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    def __setattr__(self, name, value):

        if (name == "active"):
            now = Timestamp.utcnow()
            is_active = getattr(self, "active", False)
            assert isinstance(value, bool), "\"active\" flag must be bool!"
            if not is_active and value:
                setattr(self, "time_activated", now)
                self.tasks.resume()
            elif is_active and not value:
                setattr(self, "time_stopped", now)
                self.tasks.pause()
            
        super().__setattr__(name, value)

    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    def __del__(self):

        self.tasks.shutdown(wait = False)
        verbose = {"name": self.name, "strat": self.strat_class}
        Log.info("Deleting \"{strat} - {name}\"...", **verbose)
        del self

    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    def on_tick(self, data_deriv: DataFrame, data_under: DataFrame) -> list:
        
        self.last_order.flip()
        return [self.last_order]

if (__name__ == "__main__"):

    Strategy("test", symbols = ["YPFD/ENE24", "GGAL/ENE24"])

