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

    COLUMNS_BBO = dict(price_ask_l1 = "deriv_ask", price_bid_l1 = "deriv_bid")
    COLUMNS_CALC = ["maturity", "deriv_ask", "deriv_bid", "under_ask", "under_bid"]
    COLUMNS_COMMENT = dict(deriv_ask = "da", deriv_bid = "db", under_ask = "ua",
                           rate_payer = "rp", rate_taker = "rt", exp_days = "exp")

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

#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████
        
    @staticmethod
    def calc_daily_rates(maturity: Timestamp,
            deriv_ask: float, deriv_bid: float,
            under_ask: float, under_bid: float):
        """
        If you are buying the future (@ "deriv_ask") and selling the spot (@ "under_bid"), you are effectively borrowing money
        at the spot rate and investing it in the future contract. The difference between the spot and the future rate is known
        as the "carry" (@ "under_bid / deriv_ask"). Therefore, you are taking advantage of the interest rate difference, hence
        would be considered as "taking" the interest rate of the future.
        """
        remaining = maturity - Timestamp.utcnow()
        remaining_days = remaining.total_seconds() / 86400
        rate_taker = numpy.log(under_bid / deriv_ask) / remaining_days
        rate_payer = numpy.log(deriv_bid / under_ask) / remaining_days
        under_spread = under_ask - under_bid
        deriv_spread = deriv_ask - deriv_bid

        pft_taker = deriv_spread * rate_taker - under_spread
        pft_payer = deriv_spread * rate_payer - under_spread
        
        return DataFrame(dtype = float, data = {
            "payer": {"rate": rate_payer, "profit": pft_payer},
            "taker": {"rate": rate_taker, "profit": pft_taker},
        })

    #▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬

    def on_tick(self, data_deriv: DataFrame, data_under: DataFrame) -> list:

        def calc_daily_rates(row):
            df = self.calc_daily_rates(**row).stack()
            df.index = df.index.map("_".join)
            return df.to_dict()

        columns = [*self.COLUMNS_BBO.keys(), "symbol"]
        data = data_deriv[columns].groupby("symbol").last()
        data = data.rename(columns = self.COLUMNS_BBO)
        
        data_deriv = self.specs_derivs.loc[data.index].copy()
        data_deriv = data_deriv[["contract", "underlying", "maturity"]]
        data_under = merge(left = data_deriv, right = data_under,
                          left_on = "underlying", right_index = True)
        ctr_price = data_under["last_price"] * 1.0 # data_under["contract"]
        data_under["under_ask"] = data_under["under_bid"] = ctr_price
        data_under["maturity"] = DatetimeIndex(data_under["maturity"], tz = "UTC")
        data = merge(data, data_under, left_index = True, right_index = True)

        data = data[self.COLUMNS_CALC].sort_index()
        rates = data.apply(dict, axis = "columns")
        rates = rates.map(calc_daily_rates).apply(Series)
        data = merge(data, rates, left_index = True, right_index = True)

        data["exp_days"] = data["maturity"] - Timestamp.utcnow()
        data["exp_days"] = data["exp_days"].dt.total_seconds() / 86400

        order_columns = ["side", "price", "SL"]
        original_width = data.shape[1]
        data[order_columns] = numpy.nan

        is_deriv_buy = data["rate_taker"].gt(self.thr_rate_taker) & data["rate_payer"].lt(0)
        data.loc[is_deriv_buy, "side"] = OrderSide.BUY
        data.loc[is_deriv_buy, "price"] = data["deriv_ask"]
        data.loc[is_deriv_buy, "SL"] = data["deriv_bid"]
        data.loc[is_deriv_buy, "TP"] = data.eval("price * (1 + rate_taker)")

        is_deriv_sell = data["rate_payer"].gt(self.thr_rate_payer) & data["rate_taker"].lt(0)
        data.loc[is_deriv_sell, "side"] = OrderSide.SELL
        data.loc[is_deriv_sell, "price"] = data["deriv_bid"]
        data.loc[is_deriv_sell, "SL"] = data["deriv_ask"]
        data.loc[is_deriv_sell, "TP"] = data.eval("price * (1 - rate_payer)")

        #data["size"] = data["price"] * self.risk_percentage
        #data["size"] /= (data["price"] - data["SL"]).abs()
        #data["size"] = data["size"].astype(int)        
        data["size"] = 1.0

        data["type"] = OrderType.MARKET
        data["oper"] = Signal.Action.ORDER
        data["symbol"] = data.index.copy()
        data = data.dropna(subset = "side")
        
        comment = data[[*self.COLUMNS_COMMENT.keys()]].round(4)
        comment = comment.rename(columns = self.COLUMNS_COMMENT)
        comment = comment.apply(dict, axis = "columns").astype(str)
        comment = comment.str.replace("(\"|'|{|})", "", regex = True)
        data = data.iloc[:, original_width :]
        data["comment"] = comment
        
        data["order"] = data.apply(dict, axis = "columns")
        data["order"] = data["order"].apply(lambda row: Signal(**row))
        return data["order"].to_list()

#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████
#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████
#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████
    
if (__name__ == "__main__"):

    under, premium, spread = 100, +4, 2
    args = dict(deriv_bid = under + premium,
        deriv_ask = under + premium + spread,
        under_bid = under, under_ask = under)
    
    print(args)
    exp = Timestamp("2024/01/31 00:00:00", tz = "UTC")
    df = Alma.calc_daily_rates(**args, maturity = exp)
    print(df)