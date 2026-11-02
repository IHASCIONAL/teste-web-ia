"""Ponto de entrada: `uv run app.py` (dev) ou `uv run flask --app app run`."""

import os

from dashboard import create_app

app = create_app()

if __name__ == "__main__":
    # 0.0.0.0: necessário para o navegador do Windows alcançar o app dentro do WSL2
    app.run(host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("PORT", 5000)), debug=True)
