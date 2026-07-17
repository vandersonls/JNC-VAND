import mysql.connector
from mysql.connector import pooling

_pool = None
_config = None


def init_pool(config):
    """Apenas guarda a config. A conexão real só acontece na primeira query
    (lazy), para não derrubar o processo caso o banco ainda não esteja
    acessível no momento do boot do container."""
    global _config
    _config = config


def _criar_pool():
    global _pool
    _pool = pooling.MySQLConnectionPool(
        pool_name="bmt_pool",
        pool_size=5,
        host=_config.get("DB_HOST", "localhost"),
        port=int(_config.get("DB_PORT", 3306)),
        user=_config.get("DB_USER", "root"),
        password=_config.get("DB_PASSWORD", "root"),
        database=_config.get("DB_NAME", "bmt"),
        charset="utf8mb4",
    )


def get_conn():
    if _pool is None:
        _criar_pool()
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
