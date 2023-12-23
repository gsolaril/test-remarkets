import os, sys
sys.path.append("./")

import numpy, pyRofex
from pandas import Series, DataFrame, merge
from pandas import Timestamp, DatetimeIndex
from models.strategy import *

#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████
#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████
#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████

class Alma(Strategy):
    """
    Estrategia de arbitraje spot/futuros basada en el ejercicio de prueba de AlmaGlobal. La derivación de fórmulas y del
    procedimiento se encuentra en "https://github.com/gsolaril/test-remarkets/blob/main/docs/rate_arb.md". En resumen:
    parte de suponer un precio marginalmente estable del subyacente, y la convergencia del valor futuro al valor spot
    al acercarse la fecha de expiración. Tomando una tasa de interés "constante" a través del tiempo, se supone que el
    valor futuro se valoriza/deprecia dependiendo de si parte de un valor mas bajo/alto que el spot respectivamente.
    Asumiendo esto, uno podría ejecutar una posición en largo/corto respectivamente según corresponda.

    Inputs:
    - "`name`" ("`str`"): Nombre de la instancia de la estrategia.
    - "`symbols`" ("`list`"): Lista de los derivados a operar.
    - "`thr_rate_taker`" ("`float`"): Mínimo de tasa "taker", positiva cuando el futuro está por debajo del subyacente.
    - "`thr_rate_payer`" ("`float`"): Mínimo de tasa "payer", positiva cuando el futuro está por encima del subyacente.
    - "`thr_spread_deriv`" ("`float`"): Mínimo de spread permisible. Cuando la diferencia bid-ask del futuro es mayor,
        se omite la operación.
    - "`risk_percentage`" ("`float`"): Porcentaje de riesgo a tomar. Por defecto, 1% del valor futuro. (en desuso actualmente).
    """
    # Renombrado de columnas de BBO ("Best bid and offer": bid y ask L1).
    COLUMNS_BBO = dict(price_ask_l1 = "deriv_ask", price_bid_l1 = "deriv_bid")
    # Columnas de variables requeridas para la operación.
    COLUMNS_CALC = ["maturity", "deriv_ask", "deriv_bid", "under_ask", "under_bid"]
    # Valores a incluir en formato JSON, dentro del "comment" de la señal.
    COLUMNS_COMMENT = dict(deriv_ask = "da", deriv_bid = "db", under_ask = "ua",
          rate_payer = "rp", rate_taker = "rt", profit = "pft", exp_days = "exp")

    def __init__(self, name: str, symbols: list,
                 thr_rate_taker: float = 0.0001,
                 thr_rate_payer: float = 0.0001,
                 thr_spread_deriv: float = 0.005,
                 risk_percentage: float = 0.01):

        super().__init__(name, symbols)
        self.thr_rate_taker = thr_rate_taker
        self.thr_rate_payer = thr_rate_payer
        self.thr_spread_deriv = thr_spread_deriv
        self.risk_percentage = risk_percentage
        # No hay "on_init" necesario...

#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████
        
    @staticmethod
    def calc_daily_rates(maturity: Timestamp,
            deriv_ask: float, deriv_bid: float,
            under_ask: float, under_bid: float):
        """
        Calcula la tasa de interés "payer" o "taker" de un determinado arbitraje spot/futuro. Se calcula con
        proyección "diaria". Es decir: proyectando que durante el día, dicha tasa se mantendrá constante. Las
        expresiones de cálculo en el código se basan en las ecuaciones 2A y 2B del documento README adjunto...
        (https://github.com/gsolaril/test-remarkets/blob/main/docs/rate_arb.md).

        Inputs:
        - "`maturity`" ("`Timestamp`"): Fecha de expiración del futuro. Se obtiene de "deriv_specs".
        - "`deriv_ask`" ("`float`"): Precio ask (L1) mas reciente del futuro.
        - "`deriv_bid`" ("`float`"): Precio bid (L1) mas reciente del futuro.
        - "`under_ask`" ("`float`"): Precio ask (L1) mas reciente del subyacente.
        - "`under_bid`" ("`float`"): Precio bid (L1) mas reciente del subyacente.
        Outputs:
        - "rates" ("`DataFrame`"): Tabla con la siguiente estructura:

               | payer   | taker   | ...
        -------|---------|---------|-----------------------
        rate   | ... ... | ... ... | => rate: es la tasa de cada caso
        profit | ... ... | ... ... | => profit: es el movimiento esperado del futuro hacia el subyacente (TP)
        """
        remaining = maturity - Timestamp.utcnow()
        # Días restantes hasta la fecha de expiración dada.
        remaining_days = remaining.total_seconds() / 86400
        # Formulas 2A y 2B del archivo "spot/rate_arb.md".
        rate_taker = numpy.log(under_bid / deriv_ask) / remaining_days
        rate_payer = numpy.log(deriv_bid / under_ask) / remaining_days
        # Bid-ask spreads.
        under_spread = under_ask - under_bid
        deriv_spread = deriv_ask - deriv_bid
        # Ganancias/pérdidas proyectadas.
        pft_taker = deriv_spread * rate_taker - under_spread
        pft_payer = deriv_spread * rate_payer - under_spread
        # Armado de tabla de output.
        return DataFrame(dtype = float, data = {
            "payer": {"rate": rate_payer, "profit": pft_payer},
            "taker": {"rate": rate_taker, "profit": pft_taker},
        })

    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬

    def on_tick(self, data_deriv: DataFrame, data_under: DataFrame) -> list:
        """
        Función de ejecución de estrategia. Esquema heredado de "`Strategy.on_tick`".
        """
        # Función auxiliar para convertir la tabla de "rates" en un dict, para
        # poder añadir como filas a cada derivado dentro de los DataFrames de datos.
        def calc_daily_rates(row):
            # Calcular tabla y apilar valores.
            df = self.calc_daily_rates(**row).stack()
            # Unir keys como "{index}_{column}".
            df.index = df.index.map("_".join)
            return df.to_dict() # Devolver como dict.

        # Conservar solo los BBO (bid/ask L1) de cada derivado asociado.
        columns = [*self.COLUMNS_BBO.keys(), "symbol"]
        data = data_deriv[columns].groupby("symbol").last()
        data = data.rename(columns = self.COLUMNS_BBO)
        
        # Reordenar la tabla de "specs" en base a la de datos bid/ask.
        data_deriv = self.specs_derivs.loc[data.index].copy()
        # Hallar los tickers de los subyacentes ("underlying") para cada derivado.
        # También se requieren las fechas de vencimiento ("maturity").
        data_deriv = data_deriv[["contract", "underlying", "maturity"]]
        data_under = merge(left = data_deriv, right = data_under,
                          left_on = "underlying", right_index = True)
        # Variable auxiliar, por si la escala de los precios de los derivados difieren de
        # los de sus subyacentes por una cuestión de tamaño de contrato (no es este caso).
        ctr_price = data_under["last_price"] * 1.0 # data_under["contract"]
        # Suponer "bid" y "ask" iguales (spread nulo) para los precios del subyacente.
        # Al menos hasta que se cuente con algo "mejor" que Yahoo Finance.
        data_under["under_ask"] = data_under["under_bid"] = ctr_price
        # Convertir fechas de vencimiento en "`Timestamp`" para futuros cálculos.
        data_under["maturity"] = DatetimeIndex(data_under["maturity"], tz = "UTC")
        # Unir tabla de especificaciones con datos de mercado, en base a los tickers.
        data = merge(data, data_under, left_index = True, right_index = True)

        # Conservar solamente las columnas útiles para los cálculos de tasas.
        data = data[self.COLUMNS_CALC].sort_index()
        # Convertir cada fila del DataFrame en un dict, para poder desarmar
        # (unpack) dentro de la función "calc_daily_rates" a modo de argumentos.
        rates = data.apply(dict, axis = "columns")
        rates = rates.map(calc_daily_rates).apply(Series)
        # Unir tabla de datos de mercado con la de tasas y profits resultantes.
        data = merge(data, rates, left_index = True, right_index = True)

        # Conservar el número de dias restantes de la fecha de vencimiento.
        # Útil para el "comment", para tener memoria de cada operación.
        data["exp_days"] = data["maturity"] - Timestamp.utcnow()
        data["exp_days"] = data["exp_days"].dt.total_seconds() / 86400

        # Crear columnas para las señales.
        data["profit"] = numpy.nan
        order_columns = ["side", "price", "SL", "TP"]
        # Ancho de tabla original = numero de columna adonde empiezan las
        original_width = data.shape[1] # columnas con datos de las señales
        data[order_columns] = numpy.nan

        # Cálculo de las señales para cada fila dependiendo del signo y valor de la tasa.
        is_deriv_buy = data["rate_taker"].gt(self.thr_rate_taker) & data["rate_payer"].lt(0)
        data.loc[is_deriv_buy, "side"] = OrderSide.BUY 
        data.loc[is_deriv_buy, "price"] = data["deriv_ask"] # Se entra comprando en "ask".
        data.loc[is_deriv_buy, "SL"] = data["deriv_bid"] # Y se sale vendiendo en "bid".
        # Se prevee que el valor actual subirá en proporción a la tasa "taker".
        data.loc[is_deriv_buy, "TP"] = data.eval("price * (1 + rate_taker)").round(6)

        is_deriv_sell = data["rate_payer"].gt(self.thr_rate_payer) & data["rate_taker"].lt(0)
        data.loc[is_deriv_sell, "side"] = OrderSide.SELL
        data.loc[is_deriv_sell, "price"] = data["deriv_bid"] # Se entra vendiendo en "bid".
        data.loc[is_deriv_sell, "SL"] = data["deriv_ask"] # Y se sale comprando en "ask".
        # Se prevee que el valor actual bajará en proporción a la tasa "payer".
        data.loc[is_deriv_sell, "TP"] = data.eval("price * (1 - rate_payer)").round(6)

        # Para calcular la ganancia proyectada.
        data["profit"] = (data["TP"] - data["price"]).abs()

        # TODO: Futuras lineas que suponen al spread inicial como el stop loss, y dimensionan
        # la operación para que el spread sea equivalente a un X % del tamaño de operación. 
        #data["size"] = data["price"] * self.risk_percentage
        #data["size"] /= (data["price"] - data["SL"]).abs()
        #data["size"] = data["size"].astype(int)        
        data["size"] = 1.0

        # Serán órdenes de ejecución inmediata.
        data["type"] = OrderType.MARKET
        data["oper"] = Signal.Action.ORDER
        data["symbol"] = data.index.copy()
        data = data.dropna(subset = "side")
        
        # Se unen las columnas conservadas para el comment, para crear
        # un dict de cada fila. Ej: "bid: 123, ask: 124, und: 120, etc"
        comment = data[[*self.COLUMNS_COMMENT.keys()]].round(4)
        comment = comment.rename(columns = self.COLUMNS_COMMENT)
        comment = comment.apply(dict, axis = "columns").astype(str)
        comment = comment.str.replace("(\"|'|{|})", "", regex = True)
        # Descartar columnas que no pertenecen al bloque de "señales"
        data = data.iloc[:, original_width :]
        data["comment"] = comment
        
        # Crear dict con datos de cada señal, y aplicar "Signal" a cada uno.
        data["order"] = data.apply(dict, axis = "columns")
        data["order"] = data["order"].apply(lambda row: Signal(**row))
        # Devolver lista de objetos "Signal".
        return data["order"].to_list()

#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████
#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████
#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████
    
if (__name__ == "__main__"):

    under, premium, spread = 100, +4, 2
    print(dict(deriv_bid = under + premium,
        deriv_ask = under + premium + spread,
        under_bid = under, under_ask = under))
    args = dict(deriv_bid = under + premium,
        deriv_ask = under + premium + spread,
        under_bid = under, under_ask = under)
    
    print(args)
    exp = Timestamp("2024/01/31 00:00:00", tz = "UTC")
    df = Alma.calc_daily_rates(**args, maturity = exp)
    print(df)