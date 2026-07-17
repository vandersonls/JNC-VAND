import mysql.connector
from mysql.connector import pooling

_pool = None


def init_pool(config):
    global _pool
    _pool = pooling.MySQLConnectionPool(
        pool_name="bmt_pool",
        pool_size=5,
        host=config.get("DB_HOST", "localhost"),
        port=int(config.get("DB_PORT", 3306)),
        user=config.get("DB_USER", "root"),
        password=config.get("DB_PASSWORD", "root"),
        database=config.get("DB_NAME", "bmt"),
        charset="utf8mb4",
    )


def get_conn():
    return _pool.get_connection()


def query_all(sql, params=None):
    conn = get_conn()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, params or ())
        rows = cursor.fetchall()
        cursor.close()
        return rows
    finally:
        conn.close()


def query_one(sql, params=None):
    rows = query_all(sql, params)
    return rows[0] if rows else None


def execute(sql, params=None):
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute(sql, params or ())
        conn.commit()
        last_id = cursor.lastrowid
        cursor.close()
        return last_id
    finally:
        conn.close()
