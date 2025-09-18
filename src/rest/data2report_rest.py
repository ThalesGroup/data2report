import json
import logging
import os
import tempfile
from logging.config import fileConfig

from flask import Flask, jsonify, request, render_template

from data2report import run_report
from utils import get_reports_folder, init_env_from_file

app = Flask(
    __name__,
    template_folder=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "templates"
    ),
)


@app.route("/ping", methods=["GET"])
def _ping():
    return jsonify({"status": "UP"}), 200


@app.route("/", methods=["GET"])
def _report_form():
    return render_template("run_report.html")


@app.route("/report", methods=["POST"])
def _report():
    if "file" not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files["file"]
    config = request.form["config"]
    max_records = request.form.get("max_records")
    force = request.form.get("force", "false").lower() == "true"
    print(f"Config: {config}")
    with tempfile.NamedTemporaryFile() as tmp_file:
        file.save(tmp_file.name)
        result = run_report(
            input_file=tmp_file.name,
            configuration=json.loads(config),
            max_records=max_records,
            force=force,
        )
    return jsonify(result)


def _init_logging():
    fileConfig(os.path.join(os.path.dirname(os.path.abspath(__file__)), "logging.conf"))
    logging.info("Logging initialized")


if __name__ == "__main__":
    _init_logging()
    logging.getLogger("werkzeug").setLevel("WARNING")
    port = os.environ.get("APP_PORT", 5000)
    logging.info(
        f"Going to start the app. Port: {port}. Reports folder: {get_reports_folder()}"
    )
    init_env_from_file()
    app.run(host="0.0.0.0", port=os.getenv("APP_PORT", port))
