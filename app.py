from flask import Flask, render_template, request, jsonify, redirect, url_for
import mysql.connector

app = Flask(__name__)


# CONEXÃO
def conectar():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        passwd="root",
        database="btm",
        charset="utf8mb4"
    )


# carregar html
@app.route("/")
def index():
    return render_template('index.html')


# CONSULTA DE MATERIAIS (JSON)
@app.route("/listamatrix")
def consultar_materiais():
    conn = conectar()
    cur = conn.cursor(dictionary=True)

    cur.execute("""
        SELECT
            codigo,
            descricao,
            dimensao,
            unidade
        FROM materiais
        ORDER BY descricao
    """)

    materiais = cur.fetchall()

    cur.close()
    conn.close()

    return jsonify(materiais)


if __name__ == "__main__":
    app.run(debug=True)
