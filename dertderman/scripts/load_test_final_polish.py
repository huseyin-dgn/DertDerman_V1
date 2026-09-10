"""Local stepped load probe. Results are diagnostic, not production capacity claims."""
import asyncio
from html.parser import HTMLParser
import json
import math
import os
from pathlib import Path
import socketserver
import statistics
import sys
import tempfile
import threading
import time
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

import httpx
import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")


class CsrfParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.token = ""

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "input" and values.get("name") == "csrfmiddlewaretoken":
            self.token = values.get("value", "")


class QuietHandler(WSGIRequestHandler):
    def log_message(self, *args):
        pass


class ThreadingServer(socketserver.ThreadingMixIn, WSGIServer):
    daemon_threads = True
    request_queue_size = 2048


def percentile(values, ratio):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(len(ordered) * ratio) - 1)]


async def measure(origin, mode, concurrency, csrf_token="", csrf_cookie=""):
    total = max(20, concurrency * 2)
    timings, statuses, failures = [], [], []
    timeout_count = locked_count = 0
    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
    timeout = httpx.Timeout(20.0)
    process = psutil.Process()
    cpu_samples, rss_samples = [], []
    monitoring = True

    async def monitor():
        process.cpu_percent(None)
        while monitoring:
            cpu_samples.append(process.cpu_percent(None))
            rss_samples.append(process.memory_info().rss / 1024 / 1024)
            await asyncio.sleep(0.05)

    async with httpx.AsyncClient(limits=limits, timeout=timeout, follow_redirects=False) as client:
        semaphore = asyncio.Semaphore(concurrency)

        async def request(index):
            nonlocal timeout_count, locked_count
            async with semaphore:
                started = time.perf_counter()
                try:
                    if mode == "read":
                        response = await client.get(origin + "/sirketler/load-test-company/")
                    else:
                        response = await client.post(
                            origin + "/bize-ulasin/",
                            data={
                                "csrfmiddlewaretoken": csrf_token,
                                "name": f"Load User {concurrency}-{index}",
                                "email": f"load-{concurrency}-{index}@example.com",
                                "request_type": "TECHNICAL",
                                "subject": "Yerel yük testi",
                                "message": "DertDerman yerel write-heavy yük doğrulaması için test kaydı.",
                            },
                            cookies={"csrftoken": csrf_cookie},
                            headers={"Referer": origin + "/bize-ulasin/"},
                        )
                    statuses.append(response.status_code)
                    body = response.text.lower()
                    if "database is locked" in body or "database table is locked" in body:
                        locked_count += 1
                except (httpx.TimeoutException, asyncio.TimeoutError) as error:
                    timeout_count += 1
                    failures.append(type(error).__name__)
                except Exception as error:
                    failures.append(type(error).__name__)
                finally:
                    timings.append((time.perf_counter() - started) * 1000)

        monitor_task = asyncio.create_task(monitor())
        started = time.perf_counter()
        await asyncio.gather(*(request(index) for index in range(total)))
        elapsed = time.perf_counter() - started
        monitoring = False
        await monitor_task

    expected = 200 if mode == "read" else 302
    errors = len(failures) + sum(status != expected for status in statuses)
    return {
        "mode": mode,
        "concurrent_users": concurrency,
        "requests": total,
        "requests_per_second": round(total / elapsed, 2),
        "average_ms": round(statistics.mean(timings), 2),
        "median_ms": round(statistics.median(timings), 2),
        "p95_ms": round(percentile(timings, .95), 2),
        "p99_ms": round(percentile(timings, .99), 2),
        "error_rate_percent": round(errors * 100 / total, 2),
        "timeouts": timeout_count,
        "http_5xx": sum(status >= 500 for status in statuses),
        "sqlite_locked": locked_count,
        "peak_cpu_percent": round(max(cpu_samples, default=0), 1),
        "peak_ram_mb": round(max(rss_samples, default=0), 1),
        "failure_types": sorted(set(failures)),
    }


def run(directory):
    from django.conf import settings
    settings.DATABASES["default"]["NAME"] = Path(directory) / "load.sqlite3"
    settings.DEBUG = os.environ.get("DD_LOAD_DEBUG") == "1"
    import django
    django.setup()
    from django.core.management import call_command
    from django.core.wsgi import get_wsgi_application
    from accounts.models import User
    from companies.models import Company
    from complaints.models import Complaint

    call_command("migrate", verbosity=0)
    consumer = User.objects.create_user(username="load-consumer", email="load@example.com", user_type="USER", selected_avatar="avatar-1")
    company = Company.objects.create(name="Load Test Company", slug="load-test-company", is_verified=True)
    for index in range(12):
        Complaint.objects.create(
            user=consumer, company=company, title=f"Load test complaint {index}",
            description="Read-heavy yük testi için yeterli uzunlukta public şikayet açıklaması.",
            status=Complaint.Status.PUBLISHED,
        )

    server = make_server("127.0.0.1", 0, get_wsgi_application(), server_class=ThreadingServer, handler_class=QuietHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{server.server_port}"
    with httpx.Client() as client:
        response = client.get(origin + "/bize-ulasin/")
        parser = CsrfParser()
        parser.feed(response.text)
        csrf_token = parser.token
        csrf_cookie = client.cookies.get("csrftoken")
    if not csrf_token or not csrf_cookie:
        raise RuntimeError("CSRF bootstrap failed")

    results = []
    try:
        modes = tuple(filter(None, os.environ.get("DD_LOAD_MODES", "read,write").split(",")))
        steps = tuple(int(value) for value in os.environ.get("DD_LOAD_STEPS", "10,50,100,250,500,1000").split(","))
        for mode in modes:
            for concurrency in steps:
                result = asyncio.run(measure(origin, mode, concurrency, csrf_token, csrf_cookie))
                results.append(result)
                print(json.dumps(result, ensure_ascii=False))
                if concurrency >= 100 and result["error_rate_percent"] >= 25:
                    break
    finally:
        server.shutdown()
        server.server_close()

    report = {
        "environment": "Local Django WSGI + SQLite; CPU includes server and local load generator.",
        "results": results,
    }
    output = ROOT / "docs/final-polish-qa" / os.environ.get("DD_LOAD_OUTPUT", "load-results.json")
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved: {output}")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="dd-load-", ignore_cleanup_errors=True) as directory:
        run(directory)
