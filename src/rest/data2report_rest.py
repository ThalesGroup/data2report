# Copyright 2026 Thales
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#  https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import gzip
import json
import logging
import os
import queue
import tempfile
import threading
from logging.config import fileConfig

from flask import (
    Flask,
    jsonify,
    request,
    render_template,
    Response,
    stream_with_context,
)
from boto3.session import Session

from conf_utils import (
    validate_configuration,
    list_reports,
    get_report_config,
    save_report,
)
from tools.registry import list_tools as list_tool_registry
from data2report import run_report
from llm_utils import invoke_llm
from s3_utils import get_reports_bucket, get_data2report_prefix
from utils import (
    get_reports_folder,
    init_env_from_file,
    get_report_folder,
    get_final_report_name,
    get_current_day,
    is_s3_configured,
)

app = Flask(
    __name__,
    template_folder=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "templates"
    ),
    static_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)), "static"),
)

_progress_queues = {}  # key: (report_id, run_id) -> Queue
_stop_events = {}  # key: (report_id, run_id) -> threading.Event


def get_stop_event(report_id: str, run_id: str) -> threading.Event:
    key = (report_id, run_id)
    if key not in _stop_events:
        _stop_events[key] = threading.Event()
    return _stop_events[key]


def get_progress_queue(report_id, run_id):
    key = (report_id, run_id)
    if key not in _progress_queues:
        _progress_queues[key] = queue.Queue()
    return _progress_queues[key]


def _progress_cb_factory(report_id, run_id):
    q = get_progress_queue(report_id, run_id)

    def _cb(evt: dict):
        try:
            q.put_nowait(evt)
        except Exception:
            pass

    return _cb


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
    run_id_override = request.form.get("run_id")
    cfg = json.loads(config)
    val_errs = validate_configuration(cfg, cfg.get("id"))
    if val_errs:
        return jsonify({"errors": val_errs}), 400
    run_id = run_id_override or cfg.get("run_id") or get_current_day()
    progress_cb = _progress_cb_factory(cfg.get("id"), run_id)

    stop_ev = get_stop_event(cfg["id"], run_id)
    stop_ev.clear()

    try:
        with tempfile.NamedTemporaryFile(suffix=file.filename) as tmp_file:
            file.save(tmp_file.name)
            result = run_report(
                input_file=tmp_file.name,
                configuration=cfg,
                max_records=max_records,
                force=force,
                run_id=run_id,
                progress_cb=progress_cb,
                stop_event=stop_ev,
            )
        return jsonify(result)
    except Exception as e:
        logging.exception("Error during report run")
        return jsonify({"error": str(e)}), 400


@app.route("/validate", methods=["POST"])
def _validate_configuration():
    config = request.get_json(silent=True) or {}
    errors = validate_configuration(config, config.get("id"))
    return jsonify(errors)


@app.route("/reports", methods=["GET"])
def _get_reports():
    return jsonify(list_reports())


@app.route("/report-config", methods=["GET"])
def _get_report_config():
    report_id = request.args["id"]
    return jsonify(get_report_config(report_id))


@app.route("/save-report-config", methods=["POST"])
def _save_report_config():
    config = request.get_json()
    errors = validate_configuration(config, config.get("id"))
    if errors:
        return jsonify({"errors": errors}), 400
    save_report(config, session=Session())
    return jsonify({"status": "saved", "id": config.get("id")}), 201


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
    return Response(content, mimetype="text/plain")


@app.route("/progress/stream", methods=["GET"])
def progress_stream():
    report_id = request.args.get("report_id")
    run_id = request.args.get("run_id")
    if not report_id or not run_id:
        return jsonify({"error": "report_id and run_id required"}), 400
    q = get_progress_queue(report_id, run_id)

    def event_stream():
        yield f"event: hello\ndata: {json.dumps({'report_id':report_id,'run_id':run_id})}\n\n"
        while True:
            evt = q.get()
            yield f"event: progress\ndata: {json.dumps(evt)}\n\n"

    return Response(stream_with_context(event_stream()), mimetype="text/event-stream")


@app.post("/stop")
def stop_run():
    data = request.get_json(silent=True) or {}
    report_id = data.get("report_id")
    run_id = data.get("run_id")
    if not report_id or not run_id:
        return jsonify({"error": "report_id and run_id are required"}), 400
    ev = get_stop_event(report_id, run_id)
    ev.set()
    return jsonify({"status": "stopping", "report_id": report_id, "run_id": run_id})


@app.get("/api/tools")
def _get_tools():
    return jsonify(list_tool_registry())


_COMPARE_MAX_TOKENS = 4096
_COMPARE_TEMPERATURE = 0.3
_COMPARE_SYSTEM_PROMPT = (
    "You are a data analyst reviewing two runs of the same LLM reporting pipeline on the same data. "
    "Be brief and direct. Structure your response with exactly three short sections:\n"
    "1. **Config changes** — list only the configuration parameters that differ between the two runs.\n"
    "2. **Result changes** — what changed in the output (new findings, dropped findings, different values or trends). Skip anything that stayed the same.\n"
    "3. **Recommendation** — which run produced the better result and why, in 1–2 sentences."
)


def _read_report_content(report_id: str, run_id: str) -> str:
    report_file = os.path.join(
        get_report_folder(report_id, run_id), get_final_report_name()
    )
    if not os.path.exists(report_file):
        raise FileNotFoundError(f"Report file not found: {report_file}")
    with gzip.open(report_file, "rt") as f:
        return f.read()


@app.get("/api/compare/available")
def compare_available():
    return jsonify({"available": bool(os.environ.get("COMPARE_MODEL_ID"))})


@app.post("/api/compare")
def compare_reports():
    data = request.get_json(silent=True) or {}
    run_a = data.get("run_a") or {}
    run_b = data.get("run_b") or {}
    report_id_a, run_id_a = run_a.get("report_id"), run_a.get("run_id")
    report_id_b, run_id_b = run_b.get("report_id"), run_b.get("run_id")
    if not all([report_id_a, run_id_a, report_id_b, run_id_b]):
        return (
            jsonify({"error": "run_a and run_b must each have report_id and run_id"}),
            400,
        )
    try:
        content_a = _read_report_content(report_id_a, run_id_a)
        content_b = _read_report_content(report_id_b, run_id_b)
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404

    config_a = run_a.get("config") or {}
    config_b = run_b.get("config") or {}

    def _fmt_config(cfg: dict) -> str:
        lines = [
            f"- model: {cfg.get('model_id', '—')}",
            f"- temperature: {cfg.get('temperature', '—')}",
            f"- max_tokens: {cfg.get('max_tokens', '—')}",
            f"- chunk_size: {cfg.get('chunk_size', '—')}",
            f"- mode: {'incremental' if cfg.get('incremental') else 'parallel'}",
            f"- workers: {cfg.get('max_workers', '—')}",
            f"- tools: {', '.join(cfg['tools']) if cfg.get('tools') else 'none'}",
        ]
        return "\n".join(lines)

    label_a = f"{report_id_a} / {run_id_a}"
    label_b = f"{report_id_b} / {run_id_b}"
    user_prompt = (
        f"## Run A — {label_a}\n\n### Config\n{_fmt_config(config_a)}\n\n### Output\n{content_a}\n\n"
        f"## Run B — {label_b}\n\n### Config\n{_fmt_config(config_b)}\n\n### Output\n{content_b}"
    )
    model_id = os.environ.get("COMPARE_MODEL_ID")
    if not model_id:
        return jsonify({"error": "COMPARE_MODEL_ID is not configured"}), 503
    try:
        result = invoke_llm(
            system_prompt=_COMPARE_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            model_id=model_id,
            max_tokens=_COMPARE_MAX_TOKENS,
            temperature=_COMPARE_TEMPERATURE,
            session=Session(),
        )
    except Exception as e:
        logging.exception("Error during compare LLM call")
        return jsonify({"error": str(e)}), 500
    return jsonify({"comparison": result["content"], "usage": result["usage"]})


@app.get("/example-config")
def _example_config():
    resource_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "resources",
        "example_config.json",
    )
    if not os.path.exists(resource_path):
        return jsonify({"error": "example_config.json not found"}), 404
    with open(resource_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    return jsonify(cfg)


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
    if is_s3_configured():
        logging.info(
            f"S3 configured. Reports Bucket: {get_reports_bucket()}. Prefix: {get_data2report_prefix()}"
        )
    init_env_from_file()
    app.run(host="0.0.0.0", port=os.getenv("APP_PORT", port))
