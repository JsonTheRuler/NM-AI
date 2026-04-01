"""Lightweight Flask dashboard for monitoring autoresearch progress."""

import json
import threading
import webbrowser
from pathlib import Path

from flask import Flask, render_template, jsonify


app = Flask(__name__)
_output_dir = None


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/results")
def results():
    if _output_dir is None:
        return jsonify({"status": "waiting", "message": "No run started yet"})

    results_path = Path(_output_dir) / "results.json"
    if not results_path.exists():
        return jsonify({"status": "waiting", "message": "Waiting for first iteration..."})

    with open(results_path) as f:
        return jsonify(json.load(f))


def start_dashboard(output_dir: str, port: int = 8501, open_browser: bool = True):
    """Start the dashboard server in a daemon thread.

    Args:
        output_dir: Path to the run's output directory
        port: Port to serve on (default 8501)
        open_browser: Whether to open the dashboard in a browser
    """
    global _output_dir
    _output_dir = output_dir

    def _run():
        app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    if open_browser:
        webbrowser.open(f"http://localhost:{port}")

    return thread


def update_output_dir(output_dir: str):
    """Update the output directory (called once optimizer creates its run dir)."""
    global _output_dir
    _output_dir = output_dir
