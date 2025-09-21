import gzip
import json
import logging
import os
import tempfile
from logging.config import fileConfig

from flask import Flask, jsonify, request, render_template

from conf_utils import validate_configuration, list_reports, get_report_config
from data2report import run_report
from utils import (
    get_reports_folder,
    init_env_from_file,
    get_report_folder,
    get_final_report_name,
)

app = Flask(
    __name__,
    template_folder=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "templates"
    ),
    static_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)), "static"),
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
    max_records = (
        int(request.form["max_records"]) if request.form.get("max_records") else None
    )
    force = request.form.get("force", "false").lower() == "true"
    print(f"Config: {config}")
    with tempfile.NamedTemporaryFile(suffix=file.filename) as tmp_file:
        file.save(tmp_file.name)
        result = run_report(
            input_file=tmp_file.name,
            configuration=json.loads(config),
            max_records=max_records,
            force=force,
        )
    return jsonify(result)


@app.route("/validate", methods=["POST"])
def _validate_configuration():
    config = request.json()
    errors = validate_configuration(config, None)
    return jsonify(errors)


@app.route("/reports", methods=["GET"])
def _get_reports():
    return jsonify({list_reports()})


@app.route("/report-config", methods=["GET"])
def _get_report_config():
    report_id = request.args["id"]
    return jsonify(get_report_config(report_id))


@app.route("/report", methods=["GET"])
def _get_report():
    report_id = request.args.get("id")
    run_id = request.args.get("run_id")
    report_file_name = os.path.join(
        get_report_folder(report_id, run_id), get_final_report_name()
    )
    if not os.path.exists(report_file_name):
        return (
            jsonify({"error": f"Report file '{report_file_name}' does not exist"}),
            404,
        )
    with gzip.open(report_file_name, "rt") as report_file:
        content = report_file.read()
    return jsonify({"report": content})


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
