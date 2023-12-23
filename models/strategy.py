import os, sys, json
sys.path.append("./")

import warnings
from enum import Enum
from uuid import uuid4
from pandas import Series, DataFrame, Timestamp, Timedelta
from pyRofex import Side as OrderSide, OrderType, TimeInForce
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers import SchedulerNotRunningError
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
    """
    Objeto que representa una senal de trading. Puede realizarse una nueva orden ("`Action.ORDER`"), una
    modificación ("`Action.MODIFY`") o una cancelación ("`Action.CANCEL`") de una órden preexistente.
    
    Inputs: (Todos son opcionales excepto sea aclarado...)
    * "`symbol`" ("`str`"): Instrumento/derivado a operar - NECESARIO.
    * "`size`" ("`float`"): Cantidad de contratos a operar. - NECESARIO.
    * "`oper`" ("`Action`"): Operación a realizar... "`.ORDER`", "`.MODIFY`", "`.CANCEL`". - NECESARIO.
    * "`ID`" ("`str`"): ID de orden preexistente. NECESARIO solo en caso de "`.MODIFY`" y "`.CANCEL`".
    * "`type`" ("`OrderType`"): Ejecución de orden... "`.LIMIT`" (pendiente), "`.MARKET`" (inmediata).
        ... NECESARIO en caso de "`.ORDER`".
    * "`side`" ("`OrderSide`"): Sentido de la operación. "`.BUY`" (compra/long), "`.SELL`" (venta/short).
        ... NECESARIO en caso de "`.ORDER`".
    * "`tif`" ("`TimeInForce`"): Condición de ejecución temporal. "`.DAY`", "`.GTC`", "`.IOC`"
    * "`price`" ("`float`"): Precio de ejecución a establecer.
        * Solo aplicable al caso de "`.LIMIT`". (".MARKET" usa el valor de mercado presente).
        * Solo aplicable al caso de ".`ORDER`" y ".MODIFY". (...para órdenes pendientes).
    * "`SL`" y "`TP`" ("`float`"): "Stop Loss" y "Take Profit". No válidos en "`pyRofex`", pero probablemente a
        futuro pueda desarrollarse un feature local como tal, con órdenes combinadas para lograr el mismo efecto.
    * "`comment`" ("`str`"): Comentario de la operación. Útil para agregar detalles de su origen/causa.

    *Nota: leer concepto de UUIDs y docstring de "`Signal.get_uid`" debajo.*
    """
    class Action(Enum): ORDER, MODIFY, CANCEL = range(3) # Enum para establecer objetivo de la señal.

    # Columnas a conservar en DataFrame para historial de señales dentro de las estrategias.
    RESPONSE_COLUMNS = ["id_signal", "id_order", "status", "prop", "symbol", "size",
         "price", "type", "side", "oper", "tif", "SL", "TP", "dms_send", "dms_exec"]
    
    @staticmethod
    def get_uid(n: int = 8):
        """
        Funcion para generar UUIDs aleatorios de "N" dígitos hex aleatorios. Útil para identificar señales de una misma
        ejecución de estrategia. Por ejemplo: Una estrategia de arbitraje realiza una compra y una venta en simultaneo,
        luego ambas tendrán órdenes con distintos IDs, pero como son parte de una misma posición, conviene que se puedan
        identificar con un mismo string.)

        Inputs:
        * "`n`" ("`int`"): Cantidad de dígitos hex aleatorios a generar. Por defecto, 8 (4.3 billones de alternativas).
        """
        uid = str(uuid4()).upper()
        return uid.replace("-", "")[: n]
        
    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    def __init__(self, **kwargs):

        # "oper": argumento necesario. Debe ser un enum/Action.
        self.action = kwargs.pop("oper")
        assert isinstance(self.action, self.Action)
        # "comment" no es necesario. Por defecto, vacío.
        self.comment = kwargs.pop("comment", "")
        assert isinstance(self.comment, str)
        # "id_signal" es generado aleatoriamente por defecto.
        self.id_signal = kwargs.pop("uid", self.get_uid())

        if (self.action == self.Action.ORDER):
            # Extraer y definir argumentos para señales de órden nueva.
            # TODO: Limitar "size" según min/max size en "specs_derivs"...
            self.size = kwargs.pop("size")
            self.side = kwargs.pop("side")
            self.symbol = kwargs.pop("symbol")
            assert isinstance(self.size, (int, float))
            # Por defecto, la órden es de ejecución inmediata.
            self.type = kwargs.pop("type", OrderType.MARKET)
            # Ante ejecución inmediata, no se provee precio.
            self.price = kwargs.pop("price", None)
            if not self.price: self.type = OrderType.MARKET
            # Por defecto, la orden es de tipo DAY.
            self.tif = kwargs.pop("tif", TimeInForce.DAY)
            # Por defecto, la orden no tiene SL o TP definidos.
            self.SL = kwargs.pop("SL", None)
            self.TP = kwargs.pop("TP", None)
            # Verificar que los tipos de datos para cada argumento
            # de la órden son afines a los requeridos por pyRofex.
            self._type_check_basic()
            self._type_check_place()
            # El ID de la órden será devuelto por la API de pyRofex
            # luego de la ejecución de la órden. Para un ID establecido
            # por mi sistema, sirve justamente el "UUID" aleatorio.
            self.ID = None
        else:
            # Para una modificación o cancelación, se
            # requiere el ID de la órden preexistente.
            self.ID = kwargs.pop("ID")
            assert isinstance(self.ID, str)
            if (self.action == self.Action.MODIFY):
                # Pueden modificarse los siguientes datos:
                self.price = kwargs.pop("price", None)
                self.SL = kwargs.pop("SL", None)
                self.TP = kwargs.pop("TP", None)
                self.size = kwargs.pop("size", None)
                # Verificar que los tipos de datos son correctos.
                self._type_check_basic()

    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    def _type_check_basic(self):
        """
        Verificación de tipos de datos para todas las señales en general.
        """
        assert isinstance(self.size, (int, float)) or (self.SL is None)
        assert isinstance(self.SL, (int, float)) or (self.SL is None)
        assert isinstance(self.TP, (int, float)) or (self.TP is None)
        assert isinstance(self.price, (int, float)) or (self.SL is None)

    def _type_check_place(self):
        """
        Verificación de tipos de datos específicos para nuevas órdenes.
        """
        assert isinstance(self.symbol, str)
        assert isinstance(self.type, OrderType)
        assert isinstance(self.side, OrderSide)
        assert isinstance(self.tif, TimeInForce)
        if (self.type == OrderType.LIMIT):
            assert self.price is not None

    def flip(self):
        """
        Invertir señal: de "`BUY`" a "`SELL`" o viceversa. Útil para testeos.
        """
        self.side = {
            OrderSide.BUY: OrderSide.SELL,
            OrderSide.SELL: OrderSide.BUY
        }[self.side]
    
    @property
    def dict(self):
        """
        Formato de datos de señal para DataFrames/bases de datos, y/o logging.
        """
        return {
            "id_signal": self.id_signal, "symbol": self.symbol,
            "size": self.size, "price": self.price,
            "type": self.type.name, "side": self.side.name,
            "oper": self.action.name, "tif": self.tif.name,
            "SL": self.SL, "TP": self.TP, "id_order": self.ID,
            "comment": self.comment}
    
    @property
    def form(self):
        """
        Formato de datos de señal para envío de mensajes a la API de "`pyRofex`".
        """
        return {
            "ticker": self.symbol, "size": self.size,
            "order_type": self.type, "side": self.side,
            "time_in_force": self.tif, "price": self.price}
    
    def __dict__(self):
        return self.dict
    
    def __repr__(self):
        """
        Representación de señal con la forma:
        "`Signal(size = 0.1, price = 1234.56, ...)`"
        """
        return ("Signal(%s)" % ", ".join(["%s: %s"
                % KV for KV in self.dict.items()]))

    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    @classmethod
    def test(cls, symbol):
        """
        Crear señal para testeo, con datos simples.
        """
        return cls(symbol = symbol, side = OrderSide.SELL,
                    size = 1, oper = Signal.Action.ORDER)

#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████
#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████
#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████

class Strategy:
    """
    Clase para desarrollar estrategias. Cada clase de estrategia debe ser descendiente de esta, y tiene que consistir de
    2 componentes fundamentales (necesariamente sujetos a "overloading"):
    - Inicialización, "`def on_init`" con cualquier tarea que debe ocurrir durante su concepción, antes de operar.
    - Ejecución, "`on_tick`" con cualquier secuencia de operaciones realizadas sobre los datos de mercado, para devolver
        (o no) las señales "`Signal`" de orden/modificación/cierre correspondientes.

    A modo de ejemplo:
    ```
    class MySuperStrategy(Strategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
        def other_function(self, ...) -> None:
            ...
        def on_init(self, ...) -> None:
            ...
        def on_tick(self, data_deriv, data_under) -> list[Signal]:
            ...
            return ...
    ```
    Para instanciarla, los argumentos naturales necesarios de la clase "`Strategy`" son:

    Inputs
    * "`name`" ("`str`"): Nombre de la estrategia.
    * "`symbols`" ("`dict[str, dict]`"): Activos a operar (keys), con cualquier tipo de especificación
        necesaria (values) que requiera la estrategia para funcionar. Luego será utilizado dentro de
        "`on_tick`" para procesar los datos de mercado a su debida forma.
    * "`tasks`" ("`dict[function, Trigger]`"): Tareas (funciones) adicionales a realizar en la estrategia.
        La idea es que el usuario pueda ejecutar tareas paralelas de manera regular y preprogramada bajo
        una determinada frecuencia, bajo el uso de "`tasks`". Por ejemplo, suponer que se desea correr
        la función "`other_function`" ejemplificada en el código arriba, cada 30 segundos. Luego, tasks
        podría ser: "`{other_function: IntervalTrigger(seconds = 30)}`."
    
    Cualquier otro input debe ser un elemento especifico de cada subclase de estrategia, acorde a las
    necesidades del modelo. Deben ser reconocidos y almacenados como atributos dentro de "`__init__`".
    """
    # Modelo de DataFrame para almacenar historial de señales operadas.
    TEMPLATE_SIGNALS = DataFrame(columns = Signal.RESPONSE_COLUMNS).rename_axis("ts_resp")
    # Columnas de DataFrame para almacenar datos de subyacentes.
    COLUMNS_UNDERLYING = ["currency", "exchange", "open", "shares", "day_high",
                      "day_low", "previous_close", "last_price", "last_volume"]

    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    def __init__(self, name: str, symbols: dict, tasks: dict = dict()):

        self.strat_class = self.__class__.__name__
        verbose = {"name": name, "strat": self.strat_class}

        self.symbols = symbols.copy()
        # Inicialmente, todas las estrategias comienzan pausadas.
        self.name, self.active = name, False
        # Algunos timestamps importantes a monitorear.
        self.time_stopped = Timestamp("NaT")
        self.time_executed = Timestamp("NaT")
        self.time_activated = Timestamp("NaT")
        self.time_created = Timestamp.utcnow()
        # Para almacenar historial de senales operadas.
        self.signals = self.TEMPLATE_SIGNALS.copy()
        # Para tener especificaciónes de derivados "a mano".
        self.specs_derivs = DataFrame(index = [*symbols])
        # Para tener "a mano" la última señal realizada.
        self.last_order = Signal.test([*symbols][0])
        # "Scheduler", para ejecutar tareas paralelas.
        self.tasks = BackgroundScheduler()

        if not tasks: # Ante la ausencia de tareas paralelas preestablecidas...
            Log.info("No parallel tasks for \"{strat} - {name}\"", **verbose)
        else: # Iterar sobre las especificaciones de las tareas paralelas,
            for task, trigger in tasks.items():
                # Y crear los "Jobs" correspondientes.
                self.tasks.add_job(trigger = trigger,
                    func = task, name = task.__name__)
            
            # Printear DataFrame con las especificaciones de los "Jobs".
            verbose["tasks"] = parse_tasks(self.tasks.get_jobs())
            Log.info("Tasks for \"{strat} - {name}\": \n{tasks}", **verbose)

        self.tasks.start(paused = True) # Inicializar el Scheduler, pero...
        # ...inicialmente pausado. Será resumido por "Manager.load_strategies"
        # ...al asociar la estrategia con el sistema de gestión mismo.
        self.on_init()

    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    def __setattr__(self, name, value):
        """
        Esta función es necesaria para que cada vez que se modifica "active", también se pausen o reanuden las tareas
        correspondientes de manera automática. Es decir: "`strat.active = True`" provoca que "`self.tasks.resume()`".
        """
        if (name == "active"):
            now = Timestamp.utcnow()
            # Tomar valor de "active"
            is_active = getattr(self, "active", False)
            # Verificar valor de "active", que sea booleano.
            assert isinstance(value, bool), "\"active\" flag must be bool!"
            if not is_active and value: # "active era False y ahora es True"...
                setattr(self, "time_activated", now) # ...registrar timestamp,
                self.tasks.resume() # ...y reactivar estrategia,
            elif is_active and not value: # "active era True y ahora es False"...
                setattr(self, "time_stopped", now) # ...registrar timestamp,
                self.tasks.pause() # ...y pausar estrategia,
            
        # Para cualquier caso, se sobreescribe el atributo.
        super().__setattr__(name, value)

    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    def __del__(self):
        """
        Al eliminar una estrategia, primero se desactivan sus tareas paralelas.
        Luego, se borra el objeto. No sin antes notificar de la operación.
        """
        try: self.tasks.shutdown(wait = False) # Desactivar scheduler.
        except SchedulerNotRunningError: Log.warning("No tasks to shutdown")
        verbose = {"name": self.name, "strat": self.strat_class}
        Log.info("Deleting \"{strat} - {name}\"...", **verbose)
        del self # Destruir estrategia.

    #███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████

    def on_init(self):
        """
        A sobreescribir (overload) por cada estrategia.
        """
        return

    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
    def on_tick(self, data_deriv: DataFrame, data_under: DataFrame) -> list:
        """
        A sobreescribir (overload) por cada estrategia.
        En este ejemplo, solo se crea una órden de prueba, y por cada ejecución de estrategia, se
        realiza la órden inversa a la anteriormente ejecutada.
        """
        self.last_order.flip()
        return [self.last_order]

if (__name__ == "__main__"):

    Strategy("test", symbols = ["YPFD/ENE24", "GGAL/ENE24"])

