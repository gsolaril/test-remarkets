import os, sys
sys.path.append("./")

import numpy, pyRofex
from configparser import ConfigParser
from pandas import Timestamp, Timedelta
from pandas import Series, DataFrame
from pandas import concat, merge
from loguru import logger as Log

from utils.constants import *
from manager import Manager
from strategy import *

#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████
#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████
#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████

class Interface(Manager):

    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    def __init__(self, **kwargs):

        super().__init__(**kwargs)

        pyRofex.init_websocket_connection(
            market_data_handler = self._on_update_market,
            order_report_handler = self._on_update_orders,
            error_handler = self._on_update_errors)

    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    @classmethod
    def parse_data_market(cls, msg: dict):

        ts_local = Timestamp.utcnow()
        ts_event = msg.pop("timestamp")
        data: dict = msg.pop("marketData")
        market, symbol = msg.pop("instrumentId").values()
        last_price, last_size, ts_last = data.pop("LA").values()
        iv, tv = data.pop("IV"), data.pop("TV")
        oi, nv = data.pop("OI"), data.pop("NV")
        ts_last = Timestamp(ts_last, unit = "ms", tz = "UTC")
        ts_event = Timestamp(ts_event, unit = "ms", tz = "UTC")
        dms_last = int((ts_local - ts_last).total_seconds() * 1000)
        dms_event = int((ts_local - ts_event).total_seconds() * 1000)

        book = concat(axis = "columns", objs = {
                "ask": DataFrame(data.pop("OF")),
                "bid": DataFrame(data.pop("BI"))
            })
        
        book = book.reindex(range(5)).unstack()
        index = book.index.to_frame(False)
        index.columns = ["side", "var", "level"]
        index["level"] = index["level"] + 1
        index_format = "{0[var]}_{0[side]}_l{0[level]}".format
        book.index = index.agg(index_format, axis = "columns")
        
        return {"ts": ts_local, "price_last": last_price, "size_last": last_size,
            "iv": iv, "tv": tv, "oi": oi, "nv": nv, **book, "dms_last": dms_last,
            "dms_event": dms_event, "market": market, "symbol": symbol, }
        
    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    def _run_strategies(self, symbols: set):

        for name in self.strategies:
            strat: Strategy = self.strategies[name]
            obj_symbols = set(strat.symbols) & symbols
            if not strat.active: continue

            ts_exec = Timestamp.utcnow()
            is_feed = self.symbol_ticks["symbol"].isin(obj_symbols)
            signals = strat.on_tick(self.symbol_ticks.loc[is_feed])
            strat.time_executed = Timestamp.utcnow()
            if not isinstance(signals, list): continue

            for signal in signals:
                ts_send = Timestamp.utcnow()
                if not isinstance(signal, Signal): continue
                ID, proprietary, status = self.execute(signal)
                ts_resp = Timestamp.utcnow()
                dms_send = int((ts_send - ts_exec).total_seconds() * 1000)
                dms_exec = int((ts_resp - ts_exec).total_seconds() * 1000)
                strat.signals.loc[ts_resp] = {**signal.dict, "id_order": ID,
                        "status": status, "proprietary": proprietary,
                        "dms_send": dms_send, "dms_exec": dms_exec}
            
            print(strat.signals)

    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    def execute(self, signal: Signal):

        try:
            response: dict = dict()
            if (signal.action == Signal.Action.CANCEL):
                response = pyRofex.cancel_order(signal.ID)
            elif (signal.action == Signal.Action.ORDER):
                response = pyRofex.send_order(**signal.form)
            else: return [None, None, "Not implemented"]
            
            status, response = response.values()
            return [*response.values(), status]

        except Exception as EXC:
            return [None, None, repr(EXC)]

    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    def _on_update_market(self, entry: dict):
        
        alert_symbols = set()
        entry = self.parse_data_market(entry)
        ts_local = entry.pop("ts")
        alert_symbols.add(entry["symbol"])
        self.symbol_ticks.loc[ts_local] = entry

        self._run_strategies(alert_symbols)
        n_ticks = self.symbol_ticks.shape[0]
        n_ticks_max = self.SYMBOL_TICKS_GLOBAL_MAX
        if (n_ticks > n_ticks_max):
            self.symbol_ticks = self.symbol_ticks.iloc[- n_ticks_max :]

    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    def _on_update_orders(self, entry: dict):

        print("update_orders:", entry)

    def _on_update_errors(self, entry: dict):

        print(entry)

#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████
#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████
#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████

if __name__ == "__main__":

    interface = Interface()
    test_symbols = ["YPFD/DIC23", "TRI.ROS/ENE24", "ORO/ENE24"]
    test_strategy = Strategy(name = "test", symbols = test_symbols)
    interface.load_strategies(test_strategy)
    interface.toggle_strategies(**{test_strategy.name: True})

    ts_stop = Timestamp.utcnow() + Timedelta(minutes = 20)
    while (Timestamp.utcnow() < ts_stop): pass

    pyRofex.close_websocket_connection()
    print(interface.symbol_ticks)