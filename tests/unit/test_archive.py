"""Unit tests for the Binance Vision Archive provider components."""

import tempfile
import zipfile
from pathlib import Path

from xau_quant.data.archive import BinanceVisionArchiveProvider


def test_archive_csv_parsing_and_normalization() -> None:
    row1 = (
        "1696118400000,26962.57,26962.57,26960.13,26960.13,3.112,"
        "1696118459999,83920.02,356,1.079,29101.78,0"
    )
    row2 = (
        "1696118460000,26960.13,26960.14,26957.54,26957.54,3.781,"
        "1696118519999,101934.43,369,0.405,10939.47,0"
    )
    csv_content = f"{row1}\n{row2}\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as tmp_csv:
        tmp_csv.write(csv_content)
        csv_path = Path(tmp_csv.name)

    try:
        candles = BinanceVisionArchiveProvider.parse_archive_csv(
            csv_path, symbol="BTCUSDT", timeframe="1m"
        )
        assert len(candles) == 2
        c0 = candles[0]
        assert c0.instrument == "BTCUSDT"
        assert c0.timeframe == "1m"
        assert c0.open == 26962.57
        assert c0.high == 26962.57
        assert c0.low == 26960.13
        assert c0.close == 26960.13
        assert c0.volume == 3.112
        assert c0.trade_count == 356
        assert c0.is_complete is True
    finally:
        if csv_path.exists():
            csv_path.unlink()


def test_archive_zip_extraction() -> None:
    csv_content = (
        "1696118400000,26962.57,26962.57,26960.13,26960.13,3.112,"
        "1696118459999,83920.02,356,1.079,29101.78,0\n"
    )
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp_zip:
        zip_path = Path(tmp_zip.name)

    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp_dest_csv:
        dest_csv_path = Path(tmp_dest_csv.name)

    try:
        # Create a real zip with a csv inside
        with zipfile.ZipFile(zip_path, "w") as z:
            z.writestr("BTCUSDT-1m-2023-10.csv", csv_content)

        extracted = BinanceVisionArchiveProvider.extract_csv(zip_path, dest_csv_path)
        assert extracted.exists()
        assert extracted.read_text().strip() == csv_content.strip()
    finally:
        if zip_path.exists():
            zip_path.unlink()
        if dest_csv_path.exists():
            dest_csv_path.unlink()
