import os, sys
sys.path.append("../")

from enum import Enum
from pandas import Series, DataFrame, Timestamp, DatetimeIndex
from pyRofex import Side as OrderSide, OrderType, TimeInForce
from utils.constants import *

#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████
#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████
#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████

class Signal:

    class Oper(Enum): ORDER, MODIFY, CANCEL = range(3)
        
    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    def __init__(self, **kwargs):

        self.oper = kwargs.pop("oper")
        assert isinstance(self.oper, self.Oper)
        self.comment = kwargs.pop("comment", "")
        assert isinstance(self.comment, str)

        if (self.oper == self.Oper.ORDER):
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
            if (self.oper == self.Oper.MODIFY):
                self.price = kwargs.pop("price")
                self.SL = kwargs.pop("SL", None)
                self.TP = kwargs.pop("TP", None)
                self.size = kwargs.pop("size")
                self._type_check_basic()
                
    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    def _type_check_basic(self):
        assert isinstance(self.size, (int, float))
        assert isinstance(self.price, (int, float))
        assert isinstance(self.SL, (int, float)) or (self.SL is None)
        assert isinstance(self.TP, (int, float)) or (self.TP is None)

    def _type_check_place(self):
        assert isinstance(self.symbol, str)
        assert isinstance(self.type, OrderSide)
        assert isinstance(self.side, OrderType)
        assert isinstance(self.tif, TimeInForce)

    def flip(self):
        if self.side == OrderSide.BUY:
            self.side = OrderSide.SELL
        else: self.side = OrderSide.BUY
        return self
    
    @property
    def dict(self):
        return {"size": self.size, "price": self.price,
            "type": self.type.name, "side": self.side.name,
            "oper": self.oper.name, "tif": self.tif.name,
            "SL": self.SL, "TP": self.TP, "ID": self.ID}
    
    @property
    def form(self):
        return {
            "ticker": self.symbol, "size": self.size,
            "order_type": self.type, "side": self.side,
            "time_in_force": self.tif, "price": self.price}
    
    def __dict__(self):
        return self.dict

    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    @classmethod
    def test(cls):
        return cls(oper = Signal.Oper.ORDER,
            size = 1, side = OrderSide.SELL)

#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████
#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████
#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████

class Strategy:

    def __init__(self, name: str, feeds: dict):

        self.name = name
        self.feeds = feeds
        self.active = False
        self.signals: DataFrame = DataFrame()
        self.time_created = Timestamp.utcnow()
        self.time_executed: Timestamp = None
        self.time_activated: Timestamp = None
        self.last_order: Signal = None

    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    def on_tick(self, data: DataFrame) -> list:
        
        print("Base model for strategy running...")
        print("Received data: "), print(data)
        if self.last_order is not None: 
            return [self.last_order.flip()]
        else: return [Signal.test()]
