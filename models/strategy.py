import os, sys
sys.path.append("./")

from enum import Enum
from uuid import uuid4
from pandas import Series, DataFrame, Timestamp, DatetimeIndex
from pyRofex import Side as OrderSide, OrderType, TimeInForce
from utils.constants import *

#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████
#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████
#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████

class Signal:

    class Action(Enum): ORDER, MODIFY, CANCEL = range(3)

    RESPONSE_COLUMNS = ["id_signal", "id_order", "status", "proprietary", "symbol", "size",
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

    def __init__(self, name: str, symbols: list):

        self.name = name
        self.active = False
        self.symbols = symbols
        self.time_created = Timestamp.utcnow()
        self.time_executed = self.time_activated = Timestamp("NaT")
        self.signals = self.TEMPLATE_SIGNALS.copy()
        self.last_order = Signal.test(symbols[0])

    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    def on_tick(self, data: DataFrame) -> list:
        
        self.last_order.flip()
        print("Strategy", self.name, "on_tick")
        print(), print(data)
        return [self.last_order]
