"""
Offline cloud emulator - run the whole CloudLog stack on a laptop, no AWS account.

    python -m backend.local.emulator --seed

What it emulates, and how:
  S3, DynamoDB, SNS   in-memory AWS APIs provided by `moto`
  API Gateway         an HTTP server that converts requests to the API Gateway v2
                      event format and invokes the *same* api.lambda_handler code
  S3 -> Lambda        a watcher thread that notices new .jsonl objects and invokes
                      the *same* processor code with a real-shaped S3 event
  Cognito             replaced by demo roles sent in an X-User-Role header
                      (only honoured when CLOUDLOG_LOCAL_MODE=1)

It also serves the built dashboard (frontend/dist) on the same port.
"""
import argparse
import json
import logging
import mimetypes
import os
import random
import signal
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

REGION = "ap-south-1"
NAMES = {
    "bucket": "cloudlog-local-raw",
    "events": "cloudlog_events",
    "incidents": "cloudlog_incidents",
    "runs": "cloudlog_pipeline_runs",
    "topic": "cloudlog-critical-alerts-local",
}
DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
LOCK = threading.RLock()  # moto's in-memory backends are not designed for concurrent writers
log = logging.getLogger("emulator")


def configure_environment() -> None:
    os.environ.update({
        "AWS_ACCESS_KEY_ID": "local", "AWS_SECRET_ACCESS_KEY": "local", "AWS_DEFAULT_REGION": REGION,
        "AWS_REGION": REGION, "EVENTS_TABLE_NAME": NAMES["events"],
        "INCIDENTS_TABLE_NAME": NAMES["incidents"], "RUNS_TABLE_NAME": NAMES["runs"],
        "S3_LOG_BUCKET": NAMES["bucket"], "CLOUDLOG_LOCAL_MODE": "1",
    })


def s3_event(bucket: str, key: str, size: int) -> dict:
    """The exact shape S3 sends to Lambda for s3:ObjectCreated:Put."""
    return {"Records": [{
        "eventSource": "aws:s3", "eventName": "ObjectCreated:Put", "awsRegion": REGION,
        "s3": {"bucket": {"name": bucket}, "object": {"key": key, "size": size}},
    }]}


class S3NotificationBridge(threading.Thread):
    """Polls the bucket and invokes the processor for each new .jsonl object."""

    def __init__(self, s3, processor, delay: float):
        super().__init__(daemon=True)
        self.s3, self.processor, self.delay = s3, processor, delay
        self.seen = set()

    def run(self) -> None:
        while True:
            try:
                self.tick()
            except Exception:
                log.exception("S3 notification bridge failed")
            time.sleep(0.4)

    def tick(self) -> None:
        with LOCK:
            pages = self.s3.get_paginator("list_objects_v2").paginate(Bucket=NAMES["bucket"])
            new = [o for page in pages for o in page.get("Contents", [])
                   if o["Key"] not in self.seen and o["Key"].endswith(".jsonl")]
        for obj in sorted(new, key=lambda o: o["LastModified"]):
            self.seen.add(obj["Key"])
            time.sleep(self.delay)  # emulate S3 event delivery + Lambda cold start latency
            with LOCK:
                try:
                    run = self.processor.process_file(NAMES["bucket"], obj["Key"])
                    log.info("S3 -> Lambda  %s  stored=%s rejected=%s detections=%s alerts=%s",
                             obj["Key"], run.get("stored"), run.get("rejected"),
                             len(run.get("detections", [])), len(run.get("alerts", [])))
                except Exception:
                    log.exception("Processor failed for %s (would go to the DLQ in AWS)", obj["Key"])


class Gateway(BaseHTTPRequestHandler):
    """Plays the role of API Gateway HTTP API (payload format 2.0)."""
    api = None
    server_version = "CloudLogEmulator/1.0"

    def log_message(self, fmt, *args):  # quieter than the default stderr access log
        log.debug(fmt, *args)

    def _invoke(self) -> None:
        url = urlsplit(self.path)
        if self.command == "GET" and self._serve_static(url.path):
            return
        length = int(self.headers.get("Content-Length") or 0)
        event = {
            "version": "2.0",
            "rawPath": url.path,
            "rawQueryString": url.query,
            "headers": {k.lower(): v for k, v in self.headers.items()},
            "queryStringParameters": dict(parse_qsl(url.query)) or None,
            "requestContext": {"http": {"method": self.command, "path": url.path}},
            "body": self.rfile.read(length).decode("utf-8") if length else None,
        }
        with LOCK:
            response = self.api.handle(event)
        body = response.get("body", "").encode("utf-8")
        self.send_response(response["statusCode"])
        for k, v in response.get("headers", {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_static(self, path: str) -> bool:
        if not DIST.exists():
            return False
        target = (DIST / ("index.html" if path in ("/", "") else path.lstrip("/"))).resolve()
        if DIST not in target.parents or not target.is_file():
            return False
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
        return True

    do_GET = do_POST = do_PATCH = do_OPTIONS = _invoke


def background_traffic(s3, every: float) -> None:
    """Drip-feed normal traffic so the charts move during a demo."""
    from backend.simulator.scenarios import render
    while True:
        time.sleep(every * random.uniform(0.7, 1.3))
        key = f"raw-logs/traffic/{time.strftime('%Y/%m/%d')}/traffic-{int(time.time() * 1000)}.jsonl"
        with LOCK:
            s3.put_object(Bucket=NAMES["bucket"], Key=key, Body="\n".join(render("healthy-traffic")).encode())


def _stop(*_):
    raise KeyboardInterrupt


def main() -> None:
    parser = argparse.ArgumentParser(description="Run CloudLog offline with emulated AWS services")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", 8000)))
    parser.add_argument("--host", default=os.getenv("HOST", "127.0.0.1"))
    parser.add_argument("--seed", action="store_true", help="load a few scenarios at start-up")
    parser.add_argument("--traffic", type=float, default=0, metavar="SECONDS",
                        help="upload normal traffic every N seconds (0 = off)")
    parser.add_argument("--delay", type=float, default=0.8, metavar="SECONDS",
                        help="emulated S3 -> Lambda trigger latency")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(name)-9s %(message)s", datefmt="%H:%M:%S")

    configure_environment()
    from moto import mock_aws
    mock_aws().start()

    from backend.alerts.sns import AlertPublisher
    from backend.handlers.api import Api
    from backend.handlers.processor import Processor
    from backend.local.resources import provision

    handles = provision(REGION, NAMES)
    os.environ["SNS_ALERT_TOPIC_ARN"] = handles["topic_arn"]
    processor = Processor(alerts=AlertPublisher(topic_arn=handles["topic_arn"]))
    S3NotificationBridge(handles["s3"], processor, args.delay).start()
    Gateway.api = Api()

    if args.seed:
        for scenario in ("healthy-traffic", "db-outage", "healthy-traffic", "brute-force", "payment-timeouts"):
            event = {"rawPath": "/simulator/runs", "requestContext": {"http": {"method": "POST"}},
                     "headers": {"x-user-role": "Admin"}, "body": json.dumps({"scenario": scenario})}
            with LOCK:
                Gateway.api.handle(event)
    if args.traffic > 0:
        threading.Thread(target=background_traffic, args=(handles["s3"], args.traffic), daemon=True).start()

    server = ThreadingHTTPServer((args.host, args.port), Gateway)
    # Containers stop processes with SIGTERM; treat it like Ctrl+C.
    signal.signal(signal.SIGTERM, _stop)
    url = f"http://{'localhost' if args.host in ('0.0.0.0', '127.0.0.1') else args.host}:{args.port}"
    log.info("Emulated S3 bucket   s3://%s", NAMES["bucket"])
    log.info("Emulated DynamoDB    %s, %s, %s", NAMES["events"], NAMES["incidents"], NAMES["runs"])
    log.info("Emulated SNS topic   %s", handles["topic_arn"])
    log.info("API Gateway (local)  %s", url)
    if DIST.exists():
        log.info("Dashboard            %s", url)
    else:
        log.info("Dashboard            run `npm run dev` in frontend/ and open http://localhost:5173")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Stopped. All emulated data was in memory and is now gone.")


if __name__ == "__main__":
    main()
