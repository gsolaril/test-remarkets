import os, sys
sys.path.append("./")
from models.interface import *
from strategies.alma import *
from argparse import ArgumentParser

#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████
#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████

args: ArgumentParser = ArgumentParser(prog = "Remarkets' trading interface", epilog = "AlmaGlobal test",
    description = "Simple strategy formulation framework and executor for trading strategies in Remarkets")

args.add_argument("-s", "--symbols", type = str, help = "Symbols to be traded, separated by commas")
args.add_argument("-d", "--debug", action = "store_false", default = True, help = "Disable debug mode")
args.add_argument("-rt", "--thr_rate_taker", type = float, default = 0.0001, help = "Minimum taker rate to place long trade")
args.add_argument("-rp", "--thr_rate_payer", type = float, default = 0.0001, help = "Minimum payer rate to place short trade")
args.add_argument("-t", "--timeout", type = float, default = 60.0, help = "Amount of time for strategy to run, in seconds")

values = args.parse_args()
debug = values.debug
symbols = values.symbols
thr_rate_taker = values.thr_rate_taker
thr_rate_payer = values.thr_rate_payer
timeout = values.timeout

if symbols is None: symbols = [
    "YPFD/DIC23", "PAMP/DIC23", "GGAL/DIC23"
]

#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████
#███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████

if (__name__ == "__main__"):

    interface = Interface(debug = debug)
    test_strategy = Alma(name = "Alma_test",
        symbols = dict.fromkeys(symbols),
        thr_rate_payer = thr_rate_payer,
        thr_rate_taker = thr_rate_taker,
        thr_spread_deriv = 0.005)
    
    interface.load_strategies(test_strategy)
    interface.toggle_strategies(**{test_strategy.name: True})

    ts_stop = Timestamp.utcnow() + Timedelta(seconds = timeout)
    while (Timestamp.utcnow() < ts_stop):
        try: pass
        except KeyboardInterrupt:
            interface.shutdown_manual(); break
    
    interface.shutdown()



