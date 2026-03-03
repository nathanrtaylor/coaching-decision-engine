# extraction/scripts/presto_runner.py

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
import urllib3


@dataclass
class PrestoConnInfo:
    username: str
    password: str
    address: str
    port: str
    dbname: str
    schema: str


def _repo_root() -> Path:
    # presto_runner.py -> extraction/scripts -> extraction -> repo root
    return Path(__file__).resolve().parents[2]


def load_presto_conn_from_env() -> PrestoConnInfo:
    """
    Load Presto connection parameters from .env in repo root.
    Mirrors the working notebook engine builder exactly.
    """
    root = _repo_root()
    dotenv_path = root / ".env"

    if dotenv_path.exists():
        load_dotenv(dotenv_path=dotenv_path, override=False)

    username = os.getenv("HIVE_SVC_USER")
    password = os.getenv("HIVE_SVC_PASS")
    address = os.getenv("HIVE_SVC_ADDRESS")
    port = os.getenv("HIVE_SVC_PORT")
    dbname = os.getenv("HIVE_SVC_DBNAME")
    schema = os.getenv("HIVE_SVC_SCHEMA")

    if not all([username, password, address, port, dbname, schema]):
        raise EnvironmentError(
            "Missing one or more DB connection environment variables. "
            "Check HIVE_SVC_USER, HIVE_SVC_PASS, HIVE_SVC_ADDRESS, "
            "HIVE_SVC_PORT, HIVE_SVC_DBNAME, HIVE_SVC_SCHEMA."
        )

    return PrestoConnInfo(
        username=username,
        password=password,
        address=address,
        port=port,
        dbname=dbname,
        schema=schema,
    )


def _build_engine(conn: PrestoConnInfo) -> Engine:
    """
    Build SQLAlchemy engine exactly as working notebook does.
    """
    sql_url = (
        f"presto://{conn.username}:{conn.password}"
        f"@{conn.address}:{conn.port}"
        f"/{conn.dbname}/{conn.schema}"
    )

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    engine = create_engine(
        sql_url,
        connect_args={
            "protocol": "https",
            "requests_kwargs": {"verify": False},
        },
        pool_pre_ping=True,
    )

    return engine


def run_query_to_df(sql: str, conn: PrestoConnInfo) -> Tuple[pd.DataFrame, dict]:
    """
    Execute SQL via SQLAlchemy Presto engine.
    """
    engine = _build_engine(conn)

    started = time.time()

    with engine.connect() as connection:
        result = connection.execute(text(sql))
        rows = result.fetchall()
        cols = list(result.keys())

    df = pd.DataFrame(rows, columns=cols)

    runtime = time.time() - started

    meta = {
        "runtime_seconds": round(runtime, 3),
        "row_count": int(len(df)),
        "columns": cols,
    }

    return df, meta