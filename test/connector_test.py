import os, sys
sys.path.append("../")
import pyRofex, json
from pyRofex import MarketDataEntry as MarketSide
from pyRofex import Side as OrderSide, OrderType, TimeInForce
from pandas import Series, DataFrame, Timestamp, Timedelta
from pandas import Index, to_datetime, DatetimeIndex, RangeIndex
from pandas import concat
from configparser import ConfigParser

creds = ConfigParser()
creds.read("./auth/credentials.ini")
pyRofex.initialize(**creds["REMARKET"],
    environment = pyRofex.Environment.REMARKET)

all_data = DataFrame(columns = [
    'market', 'symbol', 'price_last', 'size_last', 'dms_last', 'dms_event',
    'price_ask_l1', "size_ask_l1", 'price_ask_l2', 'size_ask_l2', 'price_ask_l3', 'size_ask_l3',
    'price_ask_l4', 'size_ask_l4', 'price_ask_l5', 'size_ask_l5', 'price_bid_l1', 'size_bid_l1',
    'price_bid_l2', 'size_bid_l2', 'price_bid_l3', 'size_bid_l3', 'price_bid_l4', 'size_bid_l4',
    'price_bid_l5', 'size_bid_l5', 'iv', 'tv', 'oi', 'nv'])

#####################################################################

def on_data_market(message: dict):

    ts_local = Timestamp.utcnow()
    ts_event = message.pop("timestamp")
    data: dict = message.pop("marketData")
    market, symbol = message.pop("instrumentId").values()
    last_price, last_size, ts_last = data.pop("LA").values()
    iv, tv = data.pop("IV"), data.pop("TV")
    oi, nv = data.pop("OI"), data.pop("NV")
    ts_last = Timestamp(ts_last, unit = "ms", tz = "UTC")
    ts_event = Timestamp(ts_event, unit = "ms", tz = "UTC")
    dms_last = int((ts_local - ts_last).total_seconds() * 1000)
    dms_event = int((ts_local - ts_event).total_seconds() * 1000)

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
    
    result = {"market": market, "symbol": symbol, 
        "price_last": last_price, "size_last": last_size,
        **book, "iv": iv, "tv": tv, "oi": oi, "nv": nv,
        "dms_last": dms_last, "dms_event": dms_event}
    
    all_data.loc[ts_last] = result
    print("New tick at:", ts_last, "\n", result)

def on_data_orders(message):

    print(message)

def on_errors(message):

    print(message)

#####################################################################

if (__name__ == "__main__"):

    tickers = ["YPFD/DIC23", "TRI.ROS/ENE24", "ORO/ENE24"]
    ts_stop = Timestamp.utcnow() + Timedelta(minutes = 5)

    pyRofex.init_websocket_connection(on_data_market, on_data_orders, on_errors)
    pyRofex.market_data_subscription(tickers = tickers, depth = 5, entries = [
        MarketSide.BIDS, MarketSide.OFFERS, MarketSide.LAST, MarketSide.INDEX_VALUE,
        MarketSide.TRADE_VOLUME, MarketSide.NOMINAL_VOLUME, MarketSide.OPEN_INTEREST])

    while (Timestamp.utcnow() < ts_stop): pass
    all_data.to_csv("market_data_test.csv")
    pyRofex.close_websocket_connection()
    print(all_data)
