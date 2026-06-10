"""QBTS 历史数据获取与清洗模块。

使用 yfinance 拉取 QBTS 过去 2 年的 1 小时级别和日线级别 OHLCV 数据，
并保存为标准化的 Pandas DataFrame。
"""

from pathlib import Path

import pandas as pd
import yfinance as yf

DATA_DIR = Path(__file__).resolve().parent / "data"
DATA_DIR.mkdir(exist_ok=True)


def clean_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """标准化 OHLCV 数据，统一列名，排序并处理缺失值。"""
    if df.empty:
        return df

    df = df.copy()
    df.index = pd.to_datetime(df.index, utc=True)

    df = df.rename(
        columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Adj Close": "adj_close",
            "Volume": "volume",
        }
    )

    expected_cols = ["open", "high", "low", "close", "volume"]
    df = df[[col for col in expected_cols if col in df.columns]]

    df = df[~df.index.duplicated(keep="first")]
    df = df.sort_index()

    # 价格列使用前向填充+后向填充，成交量缺失补 0
    price_cols = [col for col in ["open", "high", "low", "close"] if col in df.columns]
    if price_cols:
        df[price_cols] = df[price_cols].ffill().bfill()

    if "volume" in df.columns:
        df["volume"] = df["volume"].fillna(0).astype("int64")

    return df


def fetch_qbts_history(ticker: str = "QBTS", period: str = "2y", interval: str = "1h") -> pd.DataFrame:
    """下载指定周期和级别的 QBTS OHLCV 历史数据。"""
    ticker_obj = yf.Ticker(ticker)
    df = ticker_obj.history(period=period, interval=interval, auto_adjust=False, actions=False)
    return clean_ohlcv(df)


def save_dataframe(df: pd.DataFrame, path: Path) -> None:
    """将 DataFrame 保存为 Parquet 文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)


def load_dataframe(path: Path) -> pd.DataFrame:
    """从 Parquet 文件加载标准化 DataFrame。"""
    return pd.read_parquet(path)


def build_qbts_dataset() -> dict[str, pd.DataFrame]:
    """构建并保存 QBTS 的小时级和日线级数据集。"""
    hourly = fetch_qbts_history(interval="1h")
    daily = fetch_qbts_history(interval="1d")

    save_dataframe(hourly, DATA_DIR / "qbts_hourly.parquet")
    save_dataframe(daily, DATA_DIR / "qbts_daily.parquet")

    return {"hourly": hourly, "daily": daily}


def main() -> None:
    datasets = build_qbts_dataset()
    print("QBTS 数据已获取并保存：")
    print(f"  hourly: {datasets['hourly'].shape} -> {DATA_DIR / 'qbts_hourly.parquet'}")
    print(f"  daily:  {datasets['daily'].shape} -> {DATA_DIR / 'qbts_daily.parquet'}")


if __name__ == "__main__":
    main()
