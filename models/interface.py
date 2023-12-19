import os, sys
sys.path.append("../")

import numpy, pyRofex
from Loguru import logger as Log
from configparser import ConfigParser
from pandas import Series, DataFrame
from pandas import to_datetime, read_csv
from pandas import Timestamp

from models.manager import Manager
from models.strategy import *
from utils.constants import *

#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████
#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████
#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████

class Interface(Manager):

    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    def _run_strategies(self, symbols: set):

        for name in self.strategies:
            strat: Strategy = self.strategies[name]
            obj_symbols = set(strat.feeds) & symbols
            if not strat.active: continue

            ts_exec = Timestamp.utcnow()
            is_feed = self.symbol_ticks["symbol"].isin(obj_symbols)
            orders = strat.on_tick(self.symbol_ticks.loc[is_feed])
            strat.time_executed = Timestamp.utcnow()
            if not isinstance(orders, list): continue

            for order in orders:
                ts_send = Timestamp.utcnow()
                if not isinstance(order, Signal): continue
                ID, ts_resp, response = self.send(order)
                dms_send = int((ts_send - ts_exec).total_seconds() * 1000)
                dms_exec = int((ts_resp - ts_exec).total_seconds() * 1000)
                strat.signals.loc[ts_resp] = {"ID": ID, "response": response, 
                    **order.dict, "dms_send": dms_send, "dms_exec": dms_exec}

    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    def send(self, order: Signal):

        try:
            if (order.oper == Signal.Oper.CANCEL):
                response = pyRofex.cancel_order(order.ID)
            elif (order.oper == Signal.Oper.ORDER):
                response = pyRofex.send_order(order.form)
            else: return None, "Not implemented"
            return response["id"], "OK"

        except Exception as EXC:
            return None, EXC.__repr__()

    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    def _on_update_market(self, entry: dict):
        
        alert_symbols = set()
        ts_local = Timestamp.utcnow()
        for ts_event, data in entry.items():
            _, ts_fetch, symbol, data = data.values()
            ts_event: Timestamp = Timestamp(ts_event, tz = "UTC")
            ts_fetch = Timestamp(ts_fetch, unit = "ms", tz = "UTC")
            market, symbol, ask, bid = *symbol.values(), *data.values()
            dms_event = int((ts_local - ts_event).total_seconds() * 1000)
            dms_fetch = int((ts_local - ts_fetch).total_seconds() * 1000)
            alert_symbols.add(symbol)
            self.symbol_ticks.loc[ts_local] = {"market": market, "symbol": symbol,
                "dms_event": dms_event, "dms_fetch": dms_fetch, "ask": ask, "bid": bid}

        self._run_strategies(alert_symbols)
        n_ticks = self.symbol_ticks.shape[0]
        n_ticks_max = self.SYMBOL_TICKS_GLOBAL_MAX
        if (n_ticks > n_ticks_max):
            self.symbol_ticks = self.symbol_ticks.iloc[- n_ticks_max :]

    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    def _on_update_orders(self, entry: dict):

        print(entry)

    def _on_update_errors(self, entry: dict):

        print(entry)