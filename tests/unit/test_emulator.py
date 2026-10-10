"""The offline emulator must drive the same Lambda code the way AWS would."""
import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from backend.handlers.api import Api
from backend.handlers.processor import Processor
from backend.local import emulator
from backend.storage.runs import RunsStore
from tests.conftest import jsonl, log


@pytest.fixture
def local_mode(monkeypatch, aws):
    monkeypatch.setenv("CLOUDLOG_LOCAL_MODE", "1")
    monkeypatch.setitem(emulator.NAMES, "bucket", aws.names["bucket"])
    return aws


def test_s3_bridge_invokes_the_processor_once_per_new_object(local_mode):
    aws = local_mode
    bridge = emulator.S3NotificationBridge(aws.s3, Processor(s3=aws.s3), delay=0)
    aws.s3.put_object(Bucket=aws.names["bucket"], Key="raw-logs/a.jsonl", Body=jsonl(log()).encode())
    aws.s3.put_object(Bucket=aws.names["bucket"], Key="raw-logs/ignore.txt", Body=b"x")
    bridge.tick()
    bridge.tick()  # already seen -> not processed again
    assert [r["s3_key"] for r in RunsStore().recent()] == ["raw-logs/a.jsonl"]


def test_s3_event_has_the_aws_shape():
    record = emulator.s3_event("b", "k.jsonl", 10)["Records"][0]
    assert record["eventSource"] == "aws:s3" and record["s3"]["object"]["key"] == "k.jsonl"


def test_gateway_translates_http_into_api_gateway_events(local_mode):
    emulator.Gateway.api = Api(s3=local_mode.s3)
    server = ThreadingHTTPServer(("127.0.0.1", 0), emulator.Gateway)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        me = urllib.request.Request(base + "/me", headers={"X-User-Role": "Analyst"})
        with urllib.request.urlopen(me) as r:
            assert json.loads(r.read())["role"] == "Analyst"
        sim = urllib.request.Request(base + "/simulator/runs?x=1", method="POST",
                                     data=json.dumps({"scenario": "oom-crash"}).encode(),
                                     headers={"X-User-Role": "Analyst", "Content-Type": "application/json"})
        with urllib.request.urlopen(sim) as r:
            assert r.status == 201 and json.loads(r.read())["scenario"] == "oom-crash"
    finally:
        server.shutdown()
