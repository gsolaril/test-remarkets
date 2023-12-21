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
    def parse_data_market(cls, entry: dict):

        ts_local = Timestamp.utcnow()
        ms_event = entry.pop("timestamp")
        data: dict = entry.pop("marketData")
        iv, tv = data.pop("IV"), data.pop("TV")
        oi, nv = data.pop("OI"), data.pop("NV")
        last_price, last_size, ms_last = data.pop("LA").values()
        market, symbol = entry.pop("instrumentId").values()

        ms_local = ts_local.timestamp() * 1000
        dms_event = int(ms_local - ms_event)
        dms_last = int(ms_local - ms_last)

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

        Log.configure(extra = {"obj": "Interface"})

        new_signals = dict()
        for name in self.strategies:
            strat: Strategy = self.strategies[name]
            strat_symbols = set(strat.specs_derivs.index)
            strat_symbols = symbols & strat_symbols
            if not strat.active: continue

            ms_exec = Timestamp.utcnow().timestamp() * 1000
            is_feed = self.symbol_ticks["symbol"].isin(strat_symbols)
            signals = strat.on_tick(self.symbol_ticks.loc[is_feed])
            strat.time_executed = Timestamp.utcnow()
            if not isinstance(signals, list): continue
            strat_class = strat.__class__.__name__
            new_signals[name] = list()

            for signal in signals:

                if not isinstance(signal, Signal): continue
                ms_send = Timestamp.utcnow().timestamp() * 1000
                ID, proprietary, status = self.execute(signal)
                ts_resp = Timestamp.utcnow()
                ms_resp = ts_resp.timestamp() * 1000

                strat.signals.loc[ts_resp] = {
                    **signal.dict, "status": status,
                    "id_order": ID, "prop": proprietary,
                    "dms_send": int((ms_send - ms_exec)),
                    "dms_exec": int((ms_resp - ms_exec))}
                
                new_signals[name].append({
                    "strat_class": strat_class,
                    "time_since": ts_resp, **signal.dict,
                    "status": status, "id_order": ID})
            
        index_labels = ["strat_class", "strat_name", "time_since"]
        new_signals = DataFrame(new_signals).rename_axis("strat_name")
        new_signals["time_since"] = Timestamp.utcnow() - new_signals["time_since"]
        new_signals = new_signals.reset_index().set_index(index_labels).sort_index()
        Log.info(f"Recent signals ({new_signals.shape[0]}):"), print(new_signals)

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
        ts_local: Timestamp = entry.pop("ts")
        self.symbol_ticks.loc[ts_local] = entry
        alert_symbols.add(entry["symbol"])

        # self._run_strategies(alert_symbols)
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
    test_symbols = ["YPFD/DIC23", "PAMP/DIC23", "GGAL/DIC23"]
    test_strategy = Strategy(name = "test", symbols = test_symbols)
    interface.load_strategies(test_strategy)
    interface.toggle_strategies(**{test_strategy.name: True})

    ts_stop = Timestamp.utcnow() + Timedelta(minutes = 20)
    while (Timestamp.utcnow() < ts_stop): pass

    pyRofex.close_websocket_connection()
    print(interface.symbol_ticks)