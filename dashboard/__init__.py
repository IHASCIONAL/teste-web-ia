"""Painel executivo de logística (Flask)."""

from __future__ import annotations

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

from . import data


def create_app() -> Flask:
    load_dotenv()
    app = Flask(__name__)
    app.json.ensure_ascii = False
    app.json.sort_keys = False

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/painel")
    def api_painel():
        try:
            payload = data.painel(
                periodo=request.args.get("periodo", "12m"),
                regiao=request.args.get("regiao", "todas"),
                segmento=request.args.get("segmento", "todos"),
            )
        except Exception as exc:  # noqa: BLE001 — devolve erro legível ao front
            app.logger.exception("Falha ao montar o painel")
            return jsonify({"erro": str(exc)}), 500
        return jsonify(payload)

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    return app
