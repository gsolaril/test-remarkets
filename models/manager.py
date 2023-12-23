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
from models.strategy import Strategy

#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████
#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████
#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████

class Manager:
    """
    Esta clase se encarga de gestionar las estrategias en el aspecto interno. Es decir: no interactua con los WebSockets. Al
    instanciarla, no se activa ningún sistema de trading en sí: de eso se encarga su clase heredera: "`Interface`". Comienza
    conectandose a la cuenta especificada a través de la biblioteca "`pyRofex`". Luego tiene dos grupos de funciones:
    - Aquellas que manipulan las estrategias: "`add_strategies`", "`toggle_strategies`", "`remove_strategies`".
    - Aquellas que enlistan los parámetros financieros de todos los instrumentos disponibles en Rofex:
    "`get_specs_derivs`" (para derivados) y "`get_specs_unders`" (para subyacentes).\n

    Inputs:
    * "`user`" ("`str`"): Cuenta de usuario de ReMarkets.
    * "`account`" ("`str`"): Cuenta de usuario de ReMarkets.
    * "`password`" ("`str`"): Clave de la cuenta de usuario de ReMarkets.
    * "`environment`" ("`pyRofex.Environment`"): Portal de acceso a Rofex: simulación ("`REMARKET`") o real ("`LIVE`")
    """
    # Directorios para archivos importantes...
    PATH_FILE_SPECS = PATH_FOLDER_DOCS + "specs.csv"
    PATH_FILE_CREDS = PATH_FOLDER_AUTH + "credentials.ini"
    SYMBOL_TICKS_GLOBAL_MAX = 100000 # Maxima cantidad de datos de mercado acumulados.
    # Regex para renombrar las columnas de los DataFrames, de "camelCase" a "snake_case".
    REGEX_CAMEL_TO_SNAKE = dict(pat = "(.)([A-Z][a-z]?)", repl = r"\1_\2", regex = True)
    
    # Datos de mercado a solicitar en el feed.
    MARKET_DATA_ENUMS = [
        MarketInfo.BIDS, MarketInfo.OFFERS, MarketInfo.LAST, MarketInfo.INDEX_VALUE,
        MarketInfo.TRADE_VOLUME, MarketInfo.NOMINAL_VOLUME, MarketInfo.OPEN_INTEREST]
    
    # Columnas normalmente adquiridas, en los datos de mercado.
    MARKET_DATA_COLUMNS = ["market", "symbol", "price_last", "size_last", "dms_last", "dms_event",
        "price_ask_l1", "size_ask_l1", "price_ask_l2", "size_ask_l2", "price_ask_l3", "size_ask_l3",
        "price_ask_l4", "size_ask_l4", "price_ask_l5", "size_ask_l5", "price_bid_l1", "size_bid_l1",
        "price_bid_l2", "size_bid_l2", "price_bid_l3", "size_bid_l3", "price_bid_l4", "size_bid_l4",
        "price_bid_l5", "size_bid_l5", "iv", "tv", "oi", "nv"]
    
    # Modelo de tabla para los datos de mercado acumulados.
    TEMPLATE_MARKET_DATA = DataFrame(columns = MARKET_DATA_COLUMNS).rename_axis("ts_local")

    # Columnas y renombrados, para los datos de mercado de los subyacentes.
    COLUMNS_SPECS_UNDERS = dict(marketCap = "shares", preMarketPrice = "pm_price",
        preMarketChangePercent = "pm_change", regularMarketPrice = "last_price",
        regularMarketChangePercent = "last_change", regularMarketVolume = "last_volume",
        regularMarketPreviousClose = "day_close_prev", regularMarketDayHigh = "day_high",
        regularMarketDayLow = "day_low", regularMarketOpen = "day_open", )
    
    # Columnas y renombrados, para los parámetros financieros ("specs") de los derivados.
    COLUMNS_SPECS_DERIVS = dict(market = "market", segment = "segment", cficode = "cfi",
        currency = "base", maturity_date = "maturity", min_price_increment = "step_price",
        low_limit_price = "price_min", high_limit_price = "price_max", min_trade_vol = "volume_min",
        max_trade_vol = "volume_max", instrument_price_precision = "decimals_price",
        instrument_size_precision = "decimals_size", contract_multiplier = "contract",
        order_types = "order_types", times_inforce = "order_tifs", )

    # Renombrado de algunos subyacentes, para que coincidan con Yahoo Finance.
    HC_UNDERLYING = dict(GGAL = "GGAL.BA", YPFD = "YPFD.BA", PAMP = "PAMP.BA",
              ORO = "GC=F", GOLD = "GC=F", DLR = "USDARS=X", USD = "USDARS=X")

    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    def __init__(self, **kwargs):

        # Modo "debug" printea los WebSockets con mayor detalle...
        # (ej: los datos de los feeds, y las órdenes una por una)
        self.debug = kwargs.pop("debug", False)

        if not kwargs:
            # Si no se proveen credenciales en la función, se toman
            # datos presentes en el archivo "auth/credentials.ini".
            kwargs = ConfigParser()
            kwargs.read(self.PATH_FILE_CREDS)
            # Por defecto se utiliza el mercado simulado ("REMARKET") para futuras pruebas.
            kwargs = dict(**kwargs["REMARKET"], environment = pyRofex.Environment.REMARKET)
            Log.info(f"Using \"{self.PATH_FILE_CREDS}\"")

        Log.info("Connecting to \"{user} - {account}\"", **kwargs)
        # Crear cliente de acceso a Rofex, en base a las credenciales.
        try: pyRofex.initialize(**kwargs), Log.success(f"Connected OK")
        except Exception as EXC: Log.error(f"Connection error: {repr(EXC)}")

        # Conservar datos de cuenta como atributos.
        self.user = kwargs.pop("user")
        self.account = kwargs.pop("account")
        self.password = kwargs.pop("password")
        self.environment = kwargs.pop("environment")

        # Crear dicts de almacenamiento de estrategias y datos.
        # - "strategies": tendrá todas las estrategias instanciadas.
        # - "symbol_feeds": tendrá la lista de instrumentos siendo actualizados en el feed.
        # - "symbol_ticks": tendrá el historial de ticks de cada instrumento en el feed.
        self.strategies, self.symbol_feeds = dict(), dict()
        self.symbol_ticks = self.TEMPLATE_MARKET_DATA.copy()

        # Si existe un archivo "docs/specs.csv" con especificaciones y,
        # parámetros financieros, usar este en lugar de re-descargarlo.
        if os.path.isfile(self.PATH_FILE_SPECS):
            self.specs_derivs: DataFrame = read_csv(self.PATH_FILE_SPECS)
            self.specs_derivs: DataFrame = self.specs_derivs.set_index("symbol")
        # En caso que no exista, re-descargar "specs" y almacenarlo como "csv".
        else: self.specs_derivs: DataFrame = self.get_specs_derivs(self.environment)
        
        # Obtener todos los subyacentes registrados.
        unders = self.specs_derivs["underlying"].unique()
        Log.info(f"Getting data for {len(unders)} underlyings.")
        # Frecuencia de actualización de datos de mercado para los subyacentes.
        freq_update_unders = kwargs.pop("freq_update_unders", 60)
        # Descargar un primer conjunto de datos recientes, para crear el modelo de tabla.
        self.specs_unders = self.get_specs_unders(unders)
        verbose = {"n_deriv": self.specs_derivs.shape[0], "n_under": self.specs_unders.shape[0]}
        Log.success("Got specs for {n_deriv} symbols and {n_under} underlyings.", **verbose)
        Log.warning(f"Underlying data set to update every {freq_update_unders} seconds.")
        
        # Crear gestor de tareas paralelas. Agregar la tarea "update_unders" que
        # descarga y actualiza periódicamente a los datos de mercado de los subyacentes.
        # Esto es necesario porque Remarkets no contiene información de ellos, por lo cual
        # no queda otra alternativa mas que solicitarlos cada cierto tiempo desde Yahoo.
        self.tasks = Scheduler(); self.tasks.add_job(
            name = "update_unders", func = self._update_unders,
            trigger = "interval", seconds = freq_update_unders)
        
        # Printear listado de tareas paralelas para chequeo.
        df_tasks = parse_tasks(self.tasks.get_jobs())
        Log.info(f"Scheduled tasks: \n{df_tasks}")
        # Iniciar tareas paralelas.
        self.tasks.start()

    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    @classmethod
    def get_specs_derivs(cls, environment: pyRofex.Environment):
        """
        Esta funcion se encarga de descargar los datos de especificaciones y parámetros financieros para los derivados.
        No es necesario actualizarlos periódicamente puesto que tienen constantes estandarizadas (ej: "decimales en el
        precio", "mínima operación permisible", "ticker del subyacente", etc.). Por lo tanto se descarga una sola vez
        al inicializar el "`Manager`" o simplemente se usa "`docs/specs.csv`" si este existe.

        Inputs:
        - "`environment`" ("`pyRofex.Environment`"): El entorno de trading (ej: "`REMARKETS`", "`LIVE`").\n
        Outputs:
        - "`specs`" ("`DataFrame`"): Los datos de especificaciones; una fila por instrumento.
        """
        # Descargar especificaciones en JSON desde API de Rofex.
        Log.warning(f"\"{cls.PATH_FILE_SPECS}\" not found. Downloading...")
        specs = DataFrame(pyRofex.get_detailed_instruments(environment))
        
        # Convertir el JSON en Series con dicts. Expandir dicts y crear columnas.
        specs = specs["instruments"].apply(Series)
        # Renombrar nombres de columnas, a "snake_case" (consistente con Python)
        columns = specs.columns.str.replace(**cls.REGEX_CAMEL_TO_SNAKE)
        specs.columns = columns.str.lower()

        # Expandir el JSON dentro del campo "instrument_id" y conservar "symbol".
        specs.index = specs.pop("instrument_id").apply(Series)["symbol"]
        # Expandir el JSON dentro del campo "segment"; una columna por cada dato.
        column = specs.pop("segment").apply(Series)
        specs["segment"] = column["marketSegmentId"]
        specs["market"] = column["marketId"]
        
        columns = cls.COLUMNS_SPECS_DERIVS.copy()
        # Renombrar columnas con los nombres dados mas arriba.
        specs = specs[[*columns]].rename(columns = columns, errors = "ignore")
        # Convertir fechas de vencimiento ("maturity"), de "str" a "Timestamp".
        specs["maturity"] = to_datetime(specs["maturity"], format = "%Y%m%d")
        # Convertir el contenido de "order_types"/"_tifs" de lista a "str" (tipo CSV)
        specs["order_types"] = specs["order_types"].map(", ".join)
        specs["order_tifs"] = specs["order_tifs"].map(", ".join)

        # Para adquirir los nombres de los subyacentes ("underlying"),
        # se debe parsear el nombre ("symbol") del derivado...
        # - Para los que tienen "-" ... ej: "MERV-XMEV-PAMP-CI" => "PAMP" (elemento 2)
        # - Para los que tienen "." ... ej: "TRI.ROS/ENE24" => "TRI" (elemento 0)
        # - Para los que tienen "/" ... ej: "GGAL/ENE24" => "GGAL" (elemento 0)
        specs["underlying"] = specs.index.copy()
        subset = specs["underlying"].str.contains(" - ")
        subset = specs.loc[subset, "underlying"].str.split(" - ")
        specs.loc[subset.index, "underlying"] = subset.str[2]
        subset = specs["underlying"].str.contains("/|\.")
        subset = specs.loc[subset, "underlying"].str.split("/|\.")
        specs.loc[subset.index, "underlying"] = subset.str[0]
        
        # Algunos subyacentes en Yahoo tienen otro nombre. Hacer reemplazos.
        specs["underlying"] = specs["underlying"].replace(cls.HC_UNDERLYING)
        Log.info(f"Replacements for underlying tickers: {cls.HC_UNDERLYING}")

        # Guardar especificaciones en CSV.
        specs.to_csv(cls.PATH_FILE_SPECS)
        verbose = {"n_specs": len(specs), "path": cls.PATH_FILE_SPECS}
        Log.success("Saved {n_specs} symbol specs (\"{path}\")", **verbose)
        return specs
    
    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    @classmethod
    def get_specs_unders(cls, unders: list):
        """
        Descarga de datos de mercado de subyacentes, desde Yahoo (puesto que Remarkets no posee información en vivo
        de ellos). Devuelve un DataFrame con precios recientes y máximos/mínimos diarios, entre otras cosas. (Nota:
        NO DEVUELVE BIDS/ASKS).

        Inputs:
        - "`unders`" ("`list`"): Lista de subyacentes (tickers) a descargar.\n
        Outputs:
        - "`df`" ("`DataFrame`"): DataFrame con la información de los subyacentes (tickers) solicitados.
        """
        # Crear "tickers" de Yahoo en base a lista de subyacentes.
        y_tickers = Ticker(" ".join(unders))
        # Descargar precios para todos los instrumentos de la lista.
        unders: Series = Series(y_tickers.price, name = "symbol")
        # Conservar tickers válidos (correctamente hallados en Yahoo),
        # Luego expandir JSON hacia la derecha, creando una DataFrame.
        unders = unders.loc[unders.map(type).eq(dict)].apply(Series)
        # Renombrar y conservar columnas específicas.
        unders: DataFrame = unders.rename(columns = cls.COLUMNS_SPECS_UNDERS)
        columns = unders.columns.intersection(cls.COLUMNS_SPECS_UNDERS.values())
        # Calcular "shares" (numero de acciones) como "market_cap / last_price".
        unders["shares"] = (unders["shares"] / unders["last_price"]).round()
        # Conservar instrumentos con precios de mercado válidos.
        return unders[columns].dropna(how = "all")
    
    def _update_unders(self):
        """
        Esta funcion se encarga de llamar a la anterior "`get_specs_unders`" de manera regular, solicitando los datos
        de subyacentes para únicamente los instrumentos que se ven activos en las estrategias y en los WebSockets (es
        decir, incluidos en "`symbol_feeds`").
        Actualiza los valores previamente guardados en "`specs_unders`" con los nuevos descargados. Nota: es una función
        "privada"; debería ser ejecutada únicamente de manera interna, por el "`Scheduler`". No debería usarse de manera
        aislada.
        """
        # No hacer nada si no hay feeds: no hay estrategias.
        if (len(self.symbol_feeds) == 0): return
        # Separar los nombres de subyacente, de los instrumentos de los feeds.
        unders = self.specs_derivs.loc[[*self.symbol_feeds.keys()]]
        # Muchas estrategias pueden estar usando un mismo instrumento...
        unders = unders["underlying"].unique() # ...remover duplicados.
        # Descargar los últimos datos de los subyacentes.
        try: unders = self.get_specs_unders(unders)
        # En caso de error, printear pero no hacer nada mas.
        # (La estrategia debería poder utilizar datos desactualizados
        # sin problema durante un tiempo acotado...)
        except Exception as EXC: Log.exception(EXC); return

        # Actualizar "specs_unders" con los datos mas recientes.
        self.specs_unders.loc[unders.index] = unders
        # Printear los nombres de subyacentes actualizados.
        updated = ", ".join("\"" + unders.index + "\"")
        if self.debug: Log.debug(f"Updated underlying data for: {updated}.")
        
    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    def load_strategies(self, strats: list):
        """
        Por medio de esta funcion, uno carga las instancias de estrategias al "`Manager`". Estas estrategias deben
        ser instancias de alguna clase descendiente de "`Strategy`". Una vez cargada, se agrega a la lista interna
        de "`strategies`", y se subscriben a los feeds correspondientes. En caso que alguna de las estrategias ya
        exista en la lista, se ignora y se pasa a la próxima.
        Nota: la estrategia no entra en funcionamiento hasta que luego se utilice la función "`toggle_strategies`"
        para comenzar su actividad.
        
        Inputs:
        - "`strats`" ("`list[Strategy]`"): Lista de instancias de estrategias a cargar.
        """
        if not isinstance(strats, list): strats = [strats]
        # Para cada una de las estrategias de la lista...
        for strat in strats:
            strat: Strategy = strat
            if strat.name in self.strategies: # Si ya estaba cargada...
                # No hacer nada y pasar a la próxima. Evitar duplicados.
                Log.warning(f"Strategy {strat.name} already loaded")
            else:
                # Tomar los derivados contemplados por la estrategia.
                symbols = strat.specs_derivs.index.to_list()
                verbose = {"strategy": strat.__class__.__name__,
                        "name": strat.name, "symbols": symbols}
                Log.info("Loading \"{strategy} - {name}\".", **verbose)
                # Suscribir el WebSocket a los feeds de dichos derivados.
                pyRofex.market_data_subscription(tickers = symbols,
                        entries = self.MARKET_DATA_ENUMS, depth = 5)
                Log.success("Subscribed to: " + ", ".join(symbols))
                # Proveer a la estrategia, de las especificaciones de los derivados.
                try: strat.specs_derivs = self.specs_derivs.loc[symbols]
                except KeyError: # En caso que algún derivado haya sido escrito mal...
                    error = "At least one of the symbols from \"{strategy} - {name}\""
                    error += "doesn't exist:\n{symbols}... aborting strategy activation."
                    Log.warning(error, **verbose); continue

                # Agregar la estrategia a la lista del "Manager"
                self.strategies[strat.name] = strat
                # Agregar los nombres de los derivados a la lista de feeds
                # aprobados por el WebSocket, que está dentro del "Manager".
                for symbol in strat.specs_derivs.index:
                    # "symbol_feeds" es un dict de listas, adonde el "key" es el nombre del
                    # derivado bajo feed, y el "value" es una lista con los nombres de las
                    # estrategias que operan dicho instrumento.
                    # ej: {"GGAL/ENE24": ["Alma_1", "Alma_2", ...]}
                    if (symbol not in self.symbol_feeds):
                        self.symbol_feeds[symbol] = list()
                    feed: list = self.symbol_feeds[symbol]
                    feed.append(strat.name)

            Log.info("Loaded \"{strategy} - {name}\"", **verbose)
        
        # Conviene actualizar los precios de los subyacentes de cada nueva estrategia,
        # para que ellas no tengan que esperar al Schedule y puedan comenzar a operar
        # si necesitan dichos datos.
        self._update_unders()

    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    def toggle_strategies(self, **kwargs):
        """
        Permite activar o desactivar las estrategias. Esto se hace usando a los argumentos de la función
        como un dict adonde a cada nombre de estrategia que quiera afectarse, le corresponde un "`True`"
        o un "`False`" que activa/desactiva la estrategia respectivamente.
        Por ejemplo: "`toggle_strategies(Alma_1 = True, Alma_2 = False}`" -> activa "`Alma_1`" y desactiva
        "`Alma_2`". En caso que por ejemplo "`Alma_1`" ya se encontrara activada, no ocurre nada. En caso
        de que alguno de los nombres provistos no esté asociado a ninguna estrategia dentro de la lista
        "`strategies`", se ignora y se pasa a la próxima. 

        Inputs:
        - `nombre de estrategia 1` = `bool[True, False]`
        - `nombre de estrategia 2` = `bool[True, False]`
        - `nombre de estrategia 3` = `bool[True, False]`
        - `...`
        - `nombre de estrategia N` = `bool[True, False]`
        """
        actions = {True: "Enabled", False: "Disabled"}
        # Iterar sobre los inputs de las estrategias.
        for name, value in kwargs.items():
            verbose = {"name": name}
            if name not in self.strategies:
                # Si la estrategia no existe, ignorar.
                Log.warning("Strategy \"{name}\" invalid.", **verbose)
            else:
                # Tomar la instancia de estrategia,
                strat: Strategy = self.strategies[name]
                # Cambiarle el valor del atributo "active".
                strat.active = value
                # Informar sobre el cambio de valor.
                verbose["action"] = actions[strat.active]
                verbose["strat"] = strat.__class__.__name__
                Log.warning("{action} \"{strat} - {name}\"", **verbose)

    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    def remove_strategies(self, names: list):
        """
        Permite desactivar permanentemente y borrar las estrategias cuyos nombres estan dados en la lista
        "`names`". Primero, se borra de la lista de feeds de cada derivado. Luego se extrae ("pop") de la
        lista de "`strategies`" misma, y despues de desactivarla ("`active = False`"), se borra ("`del`")
        de manera definitiva. Si el nombre no está presente en la lista "`strategies`", se ignora.

        Inputs:
        - "`names`" ("`list[str]`"): Los nombres de las estrategias a borrar.
        """
        if isinstance(names, str): names = [names]
        # Iterar sobre los nombres a borrar...
        for name in names:
            verbose = {"name": name}
            if name not in self.strategies:
                # Si la estrategia no existe, ignorar.
                Log.warning("Strategy {strat.name} invalid", **verbose)
            else:
                # Extraer la instancia de estrategia ("pop").
                strat: Strategy = self.strategies.pop(name)
                verbose["strat"] = strat.__class__.__name__
                # pyRofex.market_data_unsubscription() ?
                # Iterar sobre los derivados asociados a la estrategia.
                for symbol in strat.symbols.keys():
                    # Remover el nombre de la estrategia, de dichos feeds.
                    feed: list = self.symbol_feeds[symbol]
                    feed.remove(strat.name)
                # Desactivar y eliminar de manera definitiva.
                strat.active = False; strat.__del__()
                Log.warning("Removed \"{strat} - {name}\"", **verbose)

#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████
#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████
#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████
                
if (__name__ == "__main__"):

    manager = Manager(debug = True)