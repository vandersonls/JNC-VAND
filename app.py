from flask import Flask, render_template, jsonify
from flask_cors import CORS
import mysql.connector

app = Flask(__name__)
CORS(app)


def conectar():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        passwd="root",
        database="bmt",
        charset="utf8mb4"
    )


@app.route("/")
def index():
    return render_template('index.html')


@app.route("/listamatrix")
def consultar_materiais():
    try:
        print("🔄 Conectando ao MySQL...")
        conn = conectar()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT * FROM listamatrix")
        materiais = cursor.fetchall()

        cursor.close()
        conn.close()

        # 🔥 CORREÇÃO: Remove o BOM dos nomes das colunas
        if materiais:
            # Pega o primeiro item e corrige as chaves
            primeiro = materiais[0]
            chaves_corrigidas = {}
            for chave in primeiro.keys():
                # Remove o BOM e espaços extras
                chave_limpa = chave.replace('\ufeff', '').strip()
                chaves_corrigidas[chave] = chave_limpa

            # Recria a lista com as chaves corrigidas
            materiais_corrigidos = []
            for item in materiais:
                novo_item = {}
                for chave_original, chave_limpa in chaves_corrigidas.items():
                    novo_item[chave_limpa] = item[chave_original]
                materiais_corrigidos.append(novo_item)

            print(f"✅ Colunas corrigidas: {list(materiais_corrigidos[0].keys())}")
            return jsonify(materiais_corrigidos)

        return jsonify(materiais)

    except mysql.connector.Error as e:
        print(f"❌ Erro MySQL: {e}")
        return jsonify({"erro": f"MySQL: {str(e)}"}), 500
    except Exception as e:
        print(f"❌ Erro Geral: {e}")
        return jsonify({"erro": f"Geral: {str(e)}"}), 500


if __name__ == "__main__":
    app.run(port=5000, debug=True)