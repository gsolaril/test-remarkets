import os, sys
sys.path.append("./")

import numpy, pyRofex
from configparser import ConfigParser
from pandas import Timestamp, Timedelta
from pandas import Series, DataFrame
from pandas import concat, merge
from loguru import logger as Log

from utils.constants import *
from models.manager import Manager
from models.strategy import *
from strategies.alma import Alma

from pyRofex.components.globals import environment_config as ENV

#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████
#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████
#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████

class Interface(Manager):
    """
    Esta clase extiende a "`Manager`" para incluir no solo la gestión de estrategias, sino también de recepción
    y envío de datos. Todas las funciones excepto "`shutdown`" estan encapsuladas, siendo de uso exclusivamente
    interno, exceptuando testeos.

    Inputs:
    * "`user`" ("`str`"): Cuenta de usuario de ReMarkets.
    * "`account`" ("`str`"): Cuenta de usuario de ReMarkets.
    * "`password`" ("`str`"): Clave de la cuenta de usuario de ReMarkets.
    * "`environment`" ("`pyRofex.Environment`"): Portal de acceso a Rofex: simulación ("`REMARKET`") o real ("`LIVE`")
    """

    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    def __init__(self, **kwargs):
        
        super().__init__(**kwargs)

        pyRofex.init_websocket_connection(
            market_data_handler = self._on_update_market,
            order_report_handler = self._on_update_orders,
            error_handler = self._on_update_errors,
            exception_handler = self._on_exception)

        self.websocket = ENV.get("ws_client")

    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    @classmethod
    def parse_data_market(cls, entry: dict):
        """
        Esta función recibe los JSONs provistos por el WebSocket con contenido de datos de mercado, y los reformula para
        que sean compatibles con la estructura de "`Manager.symbol_data`" (ver "`Manager.MARKET_DATA_COLUMNS`"). Siendo un
        "`classmethod`" puede testearse con dicts de prueba.
        
        Inputs:
        * "`entry`" ("`dict`"): Entrada de datos de mercado. Para ver el formato,
        leer página 41 de: "https://apihub.primary.com.ar/assets/docs/Primary-API.pdf"
        """
        ts_local = Timestamp.utcnow()
        # Extraer timestamp de tick, dada en milisegundos.
        ms_event = entry.pop("timestamp")
        # "marketData" contiene los datos de mercado mismos.
        market_data: dict = entry.pop("marketData")
        # Extraer campos ajenos al "bid/ask" (ej: open interest)
        iv, tv = market_data.pop("IV"), market_data.pop("TV")
        oi, nv = market_data.pop("OI"), market_data.pop("NV")
        # Extraer campos relacionados a la última operación ("last")
        last_price, last_size, ms_last = market_data.pop("LA").values()
        # Extraer nombre de derivado y de portal de mercado.
        market, symbol = entry.pop("instrumentId").values()

        # Medir "delays" en milisegundos, como el tiempo transcurrido desde
        # el evento de tick o desde la última operación, hasta el presente.
        ms_local = ts_local.timestamp() * 1000
        dms_event = int(ms_local - ms_event)
        dms_last = int(ms_local - ms_last)

        # Unir bids y asks en un solo DataFrame, acoplados
        # según el nivel del book. Incluye precios y volúmenes.
        book = concat(axis = "columns", objs = {
                "ask": DataFrame(market_data.pop("OF")), # Ask/Offer
                "bid": DataFrame(market_data.pop("BI"))  # Bid
            })
        # Apilar valores en una sola columna, indexados según el origen, nivel y el side
        # (ej: "price ask 1", "vol ask 1", "price bid 1", "vol bid 1, price ask 2", etc.)
        book = book.reindex(range(5)).unstack()
        index = book.index.to_frame(False)
        index.columns = ["side", "var", "level"]
        # El primer nivel debe ser el 1, no el 0.
        index["level"] = index["level"] + 1
        index_format = "{0[var]}_{0[side]}_l{0[level]}".format
        # Aplicar formato de indexación para poder acoplar al dict resultante.
        book.index = index.agg(index_format, axis = "columns")
        
        return {"ts": ts_local, "price_last": last_price, "size_last": last_size,
            "iv": iv, "tv": tv, "oi": oi, "nv": nv, **book, "dms_last": dms_last,
            "dms_event": dms_event, "market": market, "symbol": symbol, }
        
    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    def _run_strategies(self, symbols: set):
        """
        Funcion interna que ejecuta la función principal ("`Strategy.on_tick`") de cada estrategia dentro
        de "`strategies`". Toma la lista de derivados ("`symbols`") que supuestamente fueron actualizados
        mediante WebSocket hace unos instantes, y provee los datos de mercado de dichos derivados a las
        estrategias que los estan operando corrientemente. Luego las estrategias según el caso, pueden o
        no devolver instancias de "`Signal`" que contienen órdenes de trading a realizar en el mercado.
        Dichas señales pueden ser de 3 tipos:
        - "`Signal.ORDER`" (nueva órden de compra/venta),
        - "`Signal.MODIFY`" (modificación de órden ya existente - todavía no probada),
        - "`Signal.CANCEL`" (cancelación de órden ya existente - todavía no probada).
        """
        # Preparar una lista para guardar datos de las
        # nuevas órdenes a generar durante esta ronda.
        new_signals = list()
        for name in self.strategies:
            # Tomar la estrategia correspondiente.
            strat: Strategy = self.strategies[name]
            # Omitir si no está actualmente activa.
            if not strat.active: continue
            strat_class = strat.__class__.__name__
            # Tomar los derivados "necesarios":
            # "Recientemente actualizados" + "operados por la estrategia".
            strat_derivs = list(symbols & set(strat.specs_derivs.index))
            strat_unders = self.specs_derivs.loc[strat_derivs, "underlying"].unique()
            # Medir timestamp actual, para futuro cálculo de delay de estrategia.
            ms_exec = (ts_exec := Timestamp.utcnow()).timestamp() * 1000
            is_feed = self.symbol_ticks["symbol"].isin(strat_derivs)
            # Copiar historial de los derivados necesarios y de sus subyacentes.
            data_deriv = self.symbol_ticks.loc[is_feed] # derivados
            data_under = self.specs_unders.loc[strat_unders] # subyacentes
            if self.debug:
                Log.debug(f"Strategy\"{strat_class} - {name}\" executed")
            # Ejecutar función principal de estrategia, "Strategy.on_tick".
            try: signals = strat.on_tick(data_deriv, data_under)
            except Exception as EXC: Log.exception(EXC); continue
            strat.time_executed = Timestamp.utcnow()
            # Si la estrategia no devolvió señales, pasar a la próxima.
            if not isinstance(signals, list): continue
            strat_class = strat.__class__.__name__

            for signal in signals:

                # Evitar errores si la función no devuelve señales.
                if not isinstance(signal, Signal): continue
                # Medir timestamp actual, para futuro cálculo de delay de envío.
                ms_send = Timestamp.utcnow().timestamp() * 1000
                # Enviar orden/señal, y recibir respuesta de API, y resultado.
                ID, proprietary, status = self.execute(signal)
                # Medir timestamp actual, (instante final de ejecución de estrategia).
                ts_resp = Timestamp.utcnow()
                ms_resp = ts_resp.timestamp() * 1000

                # Agregar datos al DataFrame interno de señales de la estrategia.
                strat.signals.loc[ts_resp] = {
                    **signal.dict, "status": status,
                    "id_order": ID, "prop": proprietary,
                    # Delays de envío y respuesta.
                    "dms_send": int((ms_send - ms_exec)),
                    "dms_exec": int((ms_resp - ms_exec))}
                
                # Agregar datos a la lista de nuevas órdenes de esta ronda.
                new_signals.append({"strat_name": name, "strat_class": strat_class,
                    "ts_resp": ts_resp, **signal.dict, "status": status, "id_order": ID})
        
        # Si no hubieron señales, no hacer nada.
        if not new_signals: return
        # Convertir la lista en DataFrame para printear.
        new_signals = DataFrame(new_signals)
        index_labels = ["ts_resp", "strat_class", "strat_name"]
        # Calcular hace cuantos milisegundos se efectuó cada órden.
        new_signals["ms_ago"] = Timestamp.utcnow() - new_signals["ts_resp"]
        new_signals["ms_ago"] = new_signals["ms_ago"].dt.total_seconds()
        new_signals["ms_ago"] = (new_signals["ms_ago"] * 1000).astype(int)
        # Formatear timestamp de respuesta de la API como "HH:MM:SS.fff".
        new_signals["ts_resp"] = new_signals["ts_resp"].dt.strftime("%X.%f")
        new_signals["ts_resp"] = new_signals["ts_resp"].str[: -3]
        # Indexar por estrategia y timestamp de respuesta de la API.
        new_signals = new_signals.set_index(index_labels).sort_index()
        if self.debug: Log.debug( # Printear en consola.
            f"Recent {new_signals.shape[0]} signals: \n{new_signals}")

    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    def execute(self, signal: Signal):

        try:
            response: dict = dict()
            Log.info(f"Exec. signal: \n{repr(signal)}")
            # Ante una cancelación, enviar solo el ID a cancelar.
            if (signal.action == Signal.Action.CANCEL):
                response = pyRofex.cancel_order(signal.ID)
            # Ante nueva órden, enviar sus datos en formato API ("form").
            elif (signal.action == Signal.Action.ORDER):
                response = pyRofex.send_order(**signal.form)
            # "modify" todavía pendiente (no hay tal función en "pyRofex").
            else: return [None, None, "Not implemented"]
            
            status, response = response.values()
            # Devolver ID, prop ID y status (devolución de la API)
            return [*response.values(), status]

        # En caso de error...
        except Exception as EXC:
            Log.exception(EXC)
            # Devolver excepción como status de la respuesta.
            return [None, None, repr(EXC)]

    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    def _on_update_market(self, entry: dict):
        """
        Esta función recibe el tick de mercado desde el WebSocket. Lo formatea con "`parse_data_market`" de modo que
        pueda ser guardado en "`symbol_ticks`" y luego pueda ser procesado por la estrategia. Además, toma nota del
        derivado "`symbol`" recientemente actualizado para notificar a la estrategia mediante "`run_strategies`".
        Finalmente mantiene el tamaño de "`symbol_ticks`" por debajo de un límite de filas para no sobrecargar el
        sistema.

        Inputs:
        - "`entry`" ("`dict`"): Tick de mercado provisto por el WebSocket.
        """
        alert_symbols = set()
        # Comprobar que es un tick valido.
        is_valid_ask = len(entry["marketData"]["OF"]) > 0
        is_valid_bid = len(entry["marketData"]["BI"]) > 0
        if not (is_valid_ask or is_valid_bid): return
        # Formatear tick de mercado, afin a "symbol_ticks".
        entry = self.parse_data_market(entry)
        # Extraer y usar timestamp como índice en "symbol_ticks".
        ts_local: Timestamp = entry.pop("ts")
        self.symbol_ticks.loc[ts_local] = entry
        # Agregar ticker de tick a la lista de derivados actualizados.
        alert_symbols.add(entry["symbol"])

        if self.debug: Log.debug(f"Tick:\n{entry}")

        # Ejecutar estrategias para los tickers actualizados.
        self._run_strategies(alert_symbols)
        n_ticks = self.symbol_ticks.shape[0]
        n_ticks_max = self.SYMBOL_TICKS_GLOBAL_MAX
        if (n_ticks > n_ticks_max): # Limitar tamaño de "symbol_ticks".
            self.symbol_ticks = self.symbol_ticks.iloc[- n_ticks_max :]

    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    def _on_update_orders(self, entry: dict):
        """
        Función de WebSocket para recepción de respuestas ante órdenes.
        Todavía no implementada: actualmente, las órdenes se envían por API, no WebSocket.
        """
        print("update_orders:", entry)

    def _on_update_errors(self, entry: dict):
        """
        Función de WebSocket para recepción de respuestas ante errores de ejecución.
        Todavía no implementada: todavía no se han visto tales para las estrategias programadas.
        """
        print("update error:", entry)

    def _on_exception(self, entry: dict):
        """
        Función de printeo de excepciones, con traceback completo provisto por Loguru.
        Si la excepción es un "`KeyboardInterrupt`", no se lo considera un error, sino un cierre manual.
        """
        if isinstance(entry, KeyboardInterrupt):
            # "Control + C" = interrupción manual.
            self.shutdown_manual()
        # Printear excepción detallada sin interrumpir.
        else: Log.exception(entry)

    def shutdown_manual(self): # FIXME: Por algun motivo, esto no está interrumpiendo la actividad...
        """
        Ante interrupción manual, ejecutar función "`shutdown`" y notificar del evento.
        """
        Log.info("Keyboard interrupt: Manual exit requested.")
        self.shutdown(), Log.info("Goodbye. Come back soon :)")

    def shutdown(self):
        """
        Función de terminación del sistema. Primero elimina todas las estrategias con "`remove_strategies`",
        luego cierra la aplicación WebSocket y finaliza la instancia. Se notifica del evento de terminación.
        """
        Log.warning("Shutting down interface & strats...")
        # Desactivar y remover todas las estrategias.
        self.remove_strategies([*self.strategies.keys()])
        # Cerrar la conexión y todos los feeds del WebSocket.
        pyRofex.close_websocket_connection(self.environment)
        Log.success("Connection closed, strategies stopped.")

#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████
#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████
#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████

if (__name__ == "__main__"):

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
        