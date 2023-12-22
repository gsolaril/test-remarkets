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
from models.strategy import *
from strategies.alma import Alma

from pyRofex.components.globals import environment_config as ENV

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
            error_handler = self._on_update_errors,
            exception_handler = self._on_exception)

        self.websocket = ENV.get("ws_client")
        print("websocket:", self.websocket)

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

        new_signals = dict()
        for name in self.strategies:
            strat: Strategy = self.strategies[name]
            if not strat.active: continue
            strat_class = strat.__class__.__name__
            strat_derivs = list(symbols & set(strat.specs_derivs.index))
            strat_unders = self.specs_derivs.loc[strat_derivs, "underlying"].unique()
            ms_exec = (ts_exec := Timestamp.utcnow()).timestamp() * 1000
            is_feed = self.symbol_ticks["symbol"].isin(strat_derivs)
            data_deriv = self.symbol_ticks.loc[is_feed]
            data_under = self.specs_unders.loc[strat_unders]
            if self.debug: Log.debug(f"\"{strat_class} - {name}\" executed")
            try: signals = strat.on_tick(data_deriv, data_under)
            except Exception as EXC: Log.exception(EXC); continue
            strat.time_executed = Timestamp.utcnow()
            if not isinstance(signals, list): continue
            strat_class = strat.__class__.__name__
            new_signals = list()

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
                
                new_signals.append({"strat_name": name, "strat_class": strat_class,
                    "ts_resp": ts_resp, **signal.dict, "status": status, "id_order": ID})
        
        if not new_signals: return
        new_signals = DataFrame(new_signals)
        index_labels = ["ts_resp", "strat_class", "strat_name"]
        new_signals["ms_ago"] = Timestamp.utcnow() - new_signals["ts_resp"]
        new_signals["ms_ago"] = new_signals["ms_ago"].dt.total_seconds()
        new_signals["ms_ago"] = (new_signals["ms_ago"] * 1000).astype(int)
        new_signals["ts_resp"] = new_signals["ts_resp"].dt.strftime("%X.%f")
        new_signals["ts_resp"] = new_signals["ts_resp"].str[: -3]
        new_signals = new_signals.set_index(index_labels).sort_index()
        if self.debug: Log.debug(
            f"Recent {new_signals.shape[0]} signals: \n{new_signals}")

    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    def execute(self, signal: Signal):

        try:
            response: dict = dict()
            Log.info(f"Exec. signal: \n{repr(signal)}")
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

        if self.debug: Log.debug(f"Tick:\n{entry}")

        self._run_strategies(alert_symbols)
        n_ticks = self.symbol_ticks.shape[0]
        n_ticks_max = self.SYMBOL_TICKS_GLOBAL_MAX
        if (n_ticks > n_ticks_max):
            self.symbol_ticks = self.symbol_ticks.iloc[- n_ticks_max :]

    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    def _on_update_orders(self, entry: dict):
        print("update_orders:", entry)

    def _on_update_errors(self, entry: dict):
        print("update error:", entry)

    def _on_exception(self, entry: dict):
        if isinstance(entry, KeyboardInterrupt):
            self.shutdown_manual()
        else: Log.exception(entry)

    def shutdown_manual(self):
        Log.info("Keyboard interrupt: Manual exit requested.")
        self.shutdown(), Log.info("Goodbye. Come back soon :)")

    def shutdown(self):
        Log.warning("Shutting down interface & strats...")
        self.remove_strategies([*self.strategies.keys()])
        pyRofex.close_websocket_connection(self.environment)
        Log.success("Connection closed, strategies stopped.")

#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████
#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████
#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████

if __name__ == "__main__":

    interface = Interface(debug = False)
    test_strategy = Alma(name = "test",
        symbols = ["YPFD/DIC23", "PAMP/DIC23", "GGAL/DIC23"],
        thr_rate_payer = 0.0001,
        thr_rate_taker = 0.0001,
        thr_spread_deriv = 0.005)
    
    interface.load_strategies(test_strategy)
    interface.toggle_strategies(**{test_strategy.name: True})

    ts_stop = Timestamp.utcnow() + Timedelta(minutes = 20)
    while (Timestamp.utcnow() < ts_stop):
        try: pass
        except KeyboardInterrupt:
            interface.shutdown_manual(); break
    
    interface.shutdown()
        