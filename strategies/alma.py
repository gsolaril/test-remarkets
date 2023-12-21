import os, sys
sys.path.append("./")

import numpy, pyRofex
from pandas import Series, DataFrame
from pandas import Timestamp, DatetimeIndex
from models.strategy import *

#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████
#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████
#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████

class Alma(Strategy):

    def __init__(self, **kwargs):

        super().__init__(**kwargs)
        self.specs_under = DataFrame()

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

    def exec(self, data: DataFrame) -> list:

        return list()


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