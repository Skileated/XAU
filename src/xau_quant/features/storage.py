"""Parquet storage and DuckDB analytical querying for the market feature engine."""

import csv
import hashlib
import tempfile
from datetime import timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import duckdb

from xau_quant.common.paths import project_paths
from xau_quant.features.registry import FeatureRegistry


class FeatureParquetStorage:
    """Manages partitioned Parquet persistence and analytical inspection of feature datasets."""

    def __init__(
        self,
        registry: Optional[FeatureRegistry] = None,
        base_dir: Optional[Path] = None,
    ) -> None:
        self.registry = registry or FeatureRegistry()
        self.base_dir = base_dir or project_paths.data_features

    def get_partition_dir(
        self,
        year: int,
        month: int,
        venue: str = "binance",
        market_type: str = "spot",
        instrument: str = "BTCUSDT",
        timeframe: str = "5m",
        feature_set_version: str = "v2.0.0",
    ) -> Path:
        """Construct the partitioned directory path for year/month."""
        return (
            self.base_dir
            / venue
            / market_type
            / instrument.upper()
            / timeframe
            / f"feature_set={feature_set_version}"
            / f"year={year:04d}"
            / f"month={month:02d}"
        )

    def get_partition_path(
        self,
        year: int,
        month: int,
        venue: str = "binance",
        market_type: str = "spot",
        instrument: str = "BTCUSDT",
        timeframe: str = "5m",
        feature_set_version: str = "v2.0.0",
    ) -> Path:
        """Construct the full Parquet file path for a monthly partition."""
        pdir = self.get_partition_dir(
            year=year,
            month=month,
            venue=venue,
            market_type=market_type,
            instrument=instrument,
            timeframe=timeframe,
            feature_set_version=feature_set_version,
        )
        fname = (
            f"{instrument.lower()}_{timeframe}_features_"
            f"{feature_set_version}_{year:04d}{month:02d}.parquet"
        )
        return pdir / fname

    def save_partition(
        self,
        rows: List[Dict[str, Any]],
        year: int,
        month: int,
        venue: str = "binance",
        market_type: str = "spot",
        instrument: str = "BTCUSDT",
        timeframe: str = "5m",
        feature_set_version: str = "v2.0.0",
        destination_path: Optional[Path] = None,
    ) -> Tuple[Path, int, str]:
        """Save a single month's feature rows to a compressed Parquet partition.

        Returns:
            Tuple of (output_path, row_count, sha256_hash).
        """
        if not rows:
            raise ValueError(f"Cannot save empty feature partition for {year:04d}-{month:02d}.")

        out_path = destination_path or self.get_partition_path(
            year=year,
            month=month,
            venue=venue,
            market_type=market_type,
            instrument=instrument,
            timeframe=timeframe,
            feature_set_version=feature_set_version,
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)

        column_specs = self.registry.get_full_schema_column_specs()

        # Fast staged TSV write via csv.writer
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".tsv", delete=False, newline="", encoding="utf-8"
        ) as tsv_file:
            tsv_path = Path(tsv_file.name)
            writer = csv.writer(tsv_file, delimiter="\t", lineterminator="\n")
            for row in rows:
                writer.writerow([row.get(col.name) for col in column_specs])

        # DuckDB ingestion and Parquet writing
        con = duckdb.connect(":memory:")
        try:
            # Build CREATE TABLE DDL
            col_ddl_parts = [f'"{col.name}" {col.duckdb_type}' for col in column_specs]
            create_ddl = f"CREATE TABLE features ({', '.join(col_ddl_parts)});"
            con.execute(create_ddl)

            sql_tsv = tsv_path.as_posix()
            con.execute(
                f"COPY features FROM '{sql_tsv}' (DELIMITER '\t', HEADER FALSE, NULL '')"
            )

            sql_dest = out_path.as_posix()
            con.execute(f"COPY features TO '{sql_dest}' (FORMAT PARQUET, COMPRESSION ZSTD)")
        finally:
            con.close()
            if tsv_path.exists():
                tsv_path.unlink()

        file_bytes = out_path.read_bytes()
        file_hash = hashlib.sha256(file_bytes).hexdigest()
        return out_path, len(rows), file_hash

    def save_dataset(
        self,
        rows: List[Dict[str, Any]],
        venue: str = "binance",
        market_type: str = "spot",
        instrument: str = "BTCUSDT",
        timeframe: str = "5m",
        feature_set_version: str = "v2.0.0",
    ) -> List[Dict[str, Any]]:
        """Group rows by monthly partition and persist all partitions efficiently via DuckDB.

        Returns:
            List of partition metadata dictionaries sorted by year and month.
        """
        if not rows:
            raise ValueError("Cannot persist empty feature dataset.")

        column_specs = self.registry.get_full_schema_column_specs()
        col_names = [col.name for col in column_specs]

        # Fast staged TSV write via csv.writer
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".tsv",
            delete=False,
            newline="",
            encoding="utf-8",
            buffering=4 * 1024 * 1024,
        ) as tsv_file:
            tsv_path = Path(tsv_file.name)
            writer = csv.writer(tsv_file, delimiter="\t", lineterminator="\n")
            for row in rows:
                writer.writerow([row.get(c) for c in col_names])

        results: List[Dict[str, Any]] = []
        con = duckdb.connect(":memory:")
        try:
            col_ddl_parts = [f'"{col.name}" {col.duckdb_type}' for col in column_specs]
            create_ddl = f"CREATE TABLE features ({', '.join(col_ddl_parts)});"
            con.execute(create_ddl)

            sql_tsv = tsv_path.as_posix()
            con.execute(
                f"COPY features FROM '{sql_tsv}' (DELIMITER '\t', HEADER FALSE, NULL '')"
            )

            # Discover all distinct partitions and their boundaries strictly in UTC
            summary_query = """
                SELECT
                    year(timestamp_utc AT TIME ZONE 'UTC') AS y,
                    month(timestamp_utc AT TIME ZONE 'UTC') AS m,
                    COUNT(*) AS cnt,
                    MIN(timestamp_utc) AS min_ts,
                    MAX(timestamp_utc) AS max_ts
                FROM features
                GROUP BY 1, 2
                ORDER BY 1, 2
            """
            partitions_meta = con.execute(summary_query).fetchall()

            for y, m, cnt, min_ts, max_ts in partitions_meta:
                out_path = self.get_partition_path(
                    year=y,
                    month=m,
                    venue=venue,
                    market_type=market_type,
                    instrument=instrument,
                    timeframe=timeframe,
                    feature_set_version=feature_set_version,
                )
                out_path.parent.mkdir(parents=True, exist_ok=True)

                sql_dest = out_path.as_posix()
                copy_query = (
                    f"COPY (SELECT * FROM features "
                    f"WHERE year(timestamp_utc AT TIME ZONE 'UTC') = {y} "
                    f"AND month(timestamp_utc AT TIME ZONE 'UTC') = {m} "
                    f"ORDER BY timestamp_utc ASC) "
                    f"TO '{sql_dest}' (FORMAT PARQUET, COMPRESSION ZSTD)"
                )
                con.execute(copy_query)

                file_bytes = out_path.read_bytes()
                file_hash = hashlib.sha256(file_bytes).hexdigest()

                if hasattr(min_ts, "astimezone"):
                    first_ts = min_ts.astimezone(timezone.utc).isoformat()
                elif hasattr(min_ts, "isoformat"):
                    first_ts = min_ts.isoformat()
                else:
                    first_ts = str(min_ts)

                if hasattr(max_ts, "astimezone"):
                    last_ts = max_ts.astimezone(timezone.utc).isoformat()
                elif hasattr(max_ts, "isoformat"):
                    last_ts = max_ts.isoformat()
                else:
                    last_ts = str(max_ts)

                results.append(
                    {
                        "year": y,
                        "month": m,
                        "path": out_path.as_posix(),
                        "relative_path": out_path.relative_to(project_paths.root).as_posix(),
                        "row_count": cnt,
                        "sha256": file_hash,
                        "first_timestamp_utc": first_ts,
                        "last_timestamp_utc": last_ts,
                        "size_bytes": out_path.stat().st_size,
                    }
                )
        finally:
            con.close()
            if tsv_path.exists():
                tsv_path.unlink()

        return results

    def discover_partitions(
        self,
        venue: str = "binance",
        market_type: str = "spot",
        instrument: str = "BTCUSDT",
        timeframe: str = "5m",
        feature_set_version: str = "v2.0.0",
    ) -> List[Path]:
        """Discover all monthly Parquet partition files sorted deterministically."""
        base_search = (
            self.base_dir
            / venue
            / market_type
            / instrument.upper()
            / timeframe
            / f"feature_set={feature_set_version}"
        )
        if not base_search.exists():
            return []
        found = list(base_search.glob("year=*/month=*/*.parquet"))
        return sorted(found)

    def inspect_partition(self, path: Path) -> Dict[str, Any]:
        """Inspect a saved Parquet partition via DuckDB."""
        if not path.exists():
            raise FileNotFoundError(f"Partition file not found: {path}")

        con = duckdb.connect(":memory:")
        try:
            sql_path = path.as_posix()
            count_res = con.execute(f"SELECT COUNT(*) FROM '{sql_path}'").fetchone()
            row_count = int(count_res[0]) if count_res else 0

            ts_res = con.execute(
                f"SELECT MIN(timestamp_utc), MAX(timestamp_utc) FROM '{sql_path}'"
            ).fetchone()
            first_ts = ts_res[0].isoformat() if (ts_res and ts_res[0]) else None
            last_ts = ts_res[1].isoformat() if (ts_res and ts_res[1]) else None

            schema_info = con.execute(f"DESCRIBE SELECT * FROM '{sql_path}'").fetchall()

            return {
                "path": path.as_posix(),
                "row_count": row_count,
                "first_timestamp_utc": first_ts,
                "last_timestamp_utc": last_ts,
                "columns": [row[0] for row in schema_info],
                "types": {row[0]: row[1] for row in schema_info},
            }
        finally:
            con.close()
