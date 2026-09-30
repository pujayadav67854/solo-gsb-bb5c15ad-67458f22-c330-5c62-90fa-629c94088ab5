"""SQLite 持久化。

输入保存时 version 自增；任何输入变化都会产生新版本，
而方案记录的 input_version 指向它生成时的版本——
当前 version != 方案版本即视为失效（stale），导出会被拒绝。
"""

from __future__ import annotations

import json
import os
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    inputs_json TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    w INTEGER NOT NULL,
    h INTEGER NOT NULL,
    qty INTEGER NOT NULL,
    rotatable INTEGER NOT NULL CHECK (rotatable IN (0, 1))
);

CREATE TABLE IF NOT EXISTS solution (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    input_version INTEGER NOT NULL,
    input_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    payload_json TEXT NOT NULL
);
"""


def get_db_path():
    return os.environ.get("CUTTER_DB", "/data/cutter.db")


def connect(db_path=None):
    db_path = db_path or get_db_path()
    parent = os.path.dirname(db_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path=None):
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def get_state(conn):
    """返回当前输入（含 version/hash）与当前有效方案，无则字段为 None。"""
    row = conn.execute("SELECT * FROM meta WHERE id = 1").fetchone()
    inputs = None
    if row is not None:
        inputs = {
            "version": row["version"],
            "input_hash": row["input_hash"],
            **json.loads(row["inputs_json"]),
        }
        prod_rows = conn.execute(
            "SELECT name, w, h, qty, rotatable FROM products ORDER BY id"
        ).fetchall()
        inputs["products"] = [
            {
                "name": r["name"],
                "w": r["w"],
                "h": r["h"],
                "qty": r["qty"],
                "rotatable": bool(r["rotatable"]),
            }
            for r in prod_rows
        ]
    sol_row = conn.execute("SELECT * FROM solution WHERE id = 1").fetchone()
    solution = None
    if sol_row is not None:
        solution = {
            "input_version": sol_row["input_version"],
            "input_hash": sol_row["input_hash"],
            "created_at": sol_row["created_at"],
            "payload": json.loads(sol_row["payload_json"]),
            "stale": inputs is None or sol_row["input_version"] != inputs["version"],
        }
    return {"inputs": inputs, "solution": solution}


def save_inputs(conn, clean, input_hash):
    """保存输入并使旧方案失效（无论内容是否实际变化都自增版本）。"""
    products = clean.pop("products")
    payload = json.dumps(clean, ensure_ascii=False, sort_keys=True)
    with conn:  # 事务：版本自增与清除旧方案同时生效
        row = conn.execute("SELECT version FROM meta WHERE id = 1").fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO meta (id, inputs_json, input_hash, version) VALUES (1, ?, ?, 1)",
                (payload, input_hash),
            )
            version = 1
        else:
            version = row["version"] + 1
            conn.execute(
                "UPDATE meta SET inputs_json = ?, input_hash = ?, version = ? WHERE id = 1",
                (payload, input_hash, version),
            )
        conn.execute("DELETE FROM products")
        conn.executemany(
            "INSERT INTO products (name, w, h, qty, rotatable) VALUES (?, ?, ?, ?, ?)",
            [(p["name"], p["w"], p["h"], p["qty"], 1 if p["rotatable"] else 0) for p in products],
        )
        # 任一输入修改都使旧方案失效
        conn.execute("DELETE FROM solution")
    clean["products"] = products
    return version


def save_solution(conn, version, input_hash, payload):
    with conn:
        conn.execute("DELETE FROM solution WHERE id = 1")
        conn.execute(
            "INSERT INTO solution (id, input_version, input_hash, payload_json) VALUES (1, ?, ?, ?)",
            (version, input_hash, json.dumps(payload, ensure_ascii=False)),
        )
