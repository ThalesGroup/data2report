import logging
import os
from logging.config import fileConfig

from flask import Flask, jsonify


app = Flask(__name__)


@app.route("/", methods=["GET"])
def _main():
    return _ping()


@app.route("/ping", methods=["GET"])
def _ping():
    return jsonify({"status": "UP"}), 200


def _init_logging():
    fileConfig(os.path.join(os.path.dirname(os.path.abspath(__file__)), "logging.conf"))
    logging.info("Logging initialized")


if __name__ == "__main__":
    _init_logging()
    logging.getLogger("werkzeug").setLevel("WARNING")
    port = os.environ.get("APP_PORT", 5000)
    logging.info(f"Going to start the app. Port: {port}")
    app.run(host="0.0.0.0", port=port)
