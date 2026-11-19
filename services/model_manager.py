"""Starts, health-checks and stops the model worker processes.

The webapp is the only thing you launch. Each model family (audio
classifier, voice cloning, image generation) runs in its own child process
(workers/*.py), started the first time a game needs it and stopped again
when idle - or, with `models.exclusive`, when another worker starts (unless
both have `share_gpu`, so two small models can serve two games played at the
same time) - so GPU memory is only held while a game is actually using it.

Why child processes rather than loading models inside the webapp:
- stopping a process is the only reliable way to give all GPU memory back;
- a model crash or OOM kills one worker, never the webapp;
- the webapp stays responsive while a model loads (can take minutes on CPU).

Children are started with PR_SET_PDEATHSIG so they die with the webapp,
even if it is killed with SIGKILL - no orphan processes holding the GPU.
PDEATHSIG fires when the *thread* that forked the child exits, not the
process, so every spawn goes through one dedicated long-lived thread
(self._spawner) rather than whichever request thread happened to ask.

State lives in this process's memory, which is why gunicorn must run with
exactly one worker (configs/app.yaml: server.workers).
"""

import ctypes
import logging
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import os
import signal
import subprocess
import sys
import threading
import time

import requests

log = logging.getLogger(__name__)

STATUS_STOPPED = "stopped"
STATUS_STARTING = "starting"
STATUS_READY = "ready"
STATUS_FAILED = "failed"

_PR_SET_PDEATHSIG = 1


def _die_with_parent():
    """preexec_fn: ask the kernel to SIGTERM the child when the webapp dies."""
    libc = ctypes.CDLL("libc.so.6", use_errno=True)
    libc.prctl(_PR_SET_PDEATHSIG, signal.SIGTERM)


class WorkerUnavailable(Exception):
    """The worker is not ready (still starting, stopped, or failed)."""


class _Worker:
    def __init__(self, name, cfg, app_root, log_dir):
        self.name = name
        self.cfg = cfg
        self.app_root = app_root
        self.log_path = os.path.join(log_dir, f"worker-{name}.log")
        self.process = None
        self.status = STATUS_STOPPED
        self.error = ""
        self.started_at = None
        self.last_used = 0.0
        # Requests in progress + explicit holds (multi-request jobs such as
        # voice clip generation). A busy worker is never stopped to make
        # room for another one, nor by the idle reaper.
        self.busy = 0

    @property
    def base_url(self):
        return f"http://{self.cfg.host}:{self.cfg.port}"

    def python_executable(self):
        return sys.executable if self.cfg.python == "self" else self.cfg.python


class ModelManager:
    def __init__(self, config, app_root, config_path):
        self.config = config
        self.app_root = app_root
        self.config_path = os.path.abspath(config_path)
        self.lock = threading.RLock()
        log_dir = os.path.join(app_root, "logs")
        os.makedirs(log_dir, exist_ok=True)
        # Config is dict-like; indexing by the (dynamic) worker name still raises on a missing key.
        self.workers = {
            name: _Worker(name, config.models.workers[name], app_root, log_dir)
            for name in config.models.workers.keys()
        }
        self._spawner = ThreadPoolExecutor(max_workers=1, thread_name_prefix="model-spawner")
        self._reaper = threading.Thread(target=self._reap_idle_loop, name="model-reaper", daemon=True)
        self._reaper.start()

    # ------------------------------------------------------------------ status

    def status(self, name):
        worker = self.workers[name]
        with self.lock:
            self._refresh(worker)
            return {
                "name": name,
                "status": worker.status,
                "error": worker.error,
                "device": worker.cfg.device,
                "pid": worker.process.pid if worker.process else None,
                "uptime_seconds": int(time.time() - worker.started_at) if worker.started_at else 0,
                "idle_seconds": int(time.time() - worker.last_used) if worker.last_used else 0,
                "busy": worker.busy > 0,
            }

    def all_status(self):
        return [self.status(name) for name in self.workers]

    def _refresh(self, worker):
        """Update worker.status from the process state and /health."""
        if worker.process is None:
            return
        exit_code = worker.process.poll()
        if exit_code is not None:
            if worker.status != STATUS_STOPPED:
                worker.status = STATUS_FAILED
                worker.error = f"exited with code {exit_code} - see logs/worker-{worker.name}.log"
            worker.process = None
            worker.started_at = None
            return
        if worker.status == STATUS_STARTING:
            if self._healthy(worker):
                worker.status = STATUS_READY
                worker.last_used = time.time()
                log.info("Worker %s ready", worker.name)
            elif time.time() - worker.started_at > worker.cfg.startup_timeout_seconds:
                worker.error = f"not ready after {worker.cfg.startup_timeout_seconds}s"
                self._kill(worker)
                worker.status = STATUS_FAILED

    @staticmethod
    def _healthy(worker):
        try:
            return requests.get(f"{worker.base_url}/health", timeout=2).status_code == 200
        except requests.RequestException:
            return False

    # --------------------------------------------------------------- lifecycle

    def ensure_started(self, name):
        """Start the worker if it is not running. Returns immediately - poll status()."""
        worker = self.workers[name]
        with self.lock:
            self._refresh(worker)
            if worker.status in (STATUS_STARTING, STATUS_READY):
                worker.last_used = time.time()
                return
            if self.config.models.exclusive:
                for other in self.workers.values():
                    if other is worker or other.process is None:
                        continue
                    if worker.cfg.share_gpu and other.cfg.share_gpu:
                        continue
                    if other.busy:
                        # Killing it would lose work in progress (e.g. clips
                        # being generated); both run until it goes idle.
                        log.warning("Not stopping busy worker %s for %s", other.name, name)
                        continue
                    log.info("Stopping %s to make room for %s", other.name, name)
                    self._stop(other)
            self._spawn(worker)

    def stop(self, name):
        with self.lock:
            self._stop(self.workers[name])

    def stop_all(self):
        with self.lock:
            for worker in self.workers.values():
                self._stop(worker)

    def _spawn(self, worker):
        env = dict(os.environ)
        env["AI_GAMES_WORKER"] = worker.name
        env["AI_GAMES_CONFIG_PATH"] = self.config_path
        env["PYTHONUNBUFFERED"] = "1"
        log_file = open(worker.log_path, "ab")  # noqa: SIM115 - handed to the child, closed below
        try:
            worker.process = self._spawner.submit(
                subprocess.Popen,
                [worker.python_executable(), os.path.join(self.app_root, worker.cfg.script)],
                cwd=self.app_root,
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                preexec_fn=_die_with_parent,
            ).result()
        finally:
            log_file.close()
        worker.status = STATUS_STARTING
        worker.error = ""
        worker.started_at = time.time()
        worker.last_used = time.time()
        log.info("Started worker %s (pid %s)", worker.name, worker.process.pid)

    def _stop(self, worker):
        if worker.process is not None:
            self._kill(worker)
            log.info("Stopped worker %s", worker.name)
        worker.status = STATUS_STOPPED
        worker.error = ""
        worker.started_at = None

    @staticmethod
    def _kill(worker):
        process = worker.process
        worker.process = None
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)

    def _reap_idle_loop(self):
        while True:
            time.sleep(self.config.models.reaper_interval_seconds)
            idle_limit = self.config.models.idle_minutes * 60
            with self.lock:
                for worker in self.workers.values():
                    self._refresh(worker)
                    if worker.status == STATUS_READY and not worker.busy and time.time() - worker.last_used > idle_limit:
                        log.info("Stopping idle worker %s", worker.name)
                        self._stop(worker)

    # ----------------------------------------------------------------- calling

    @contextmanager
    def hold(self, name):
        """Mark a worker busy for a multi-request job so it isn't stopped
        between requests (exclusive mode or idle reaper)."""
        worker = self.workers[name]
        with self.lock:
            worker.busy += 1
        try:
            yield
        finally:
            with self.lock:
                worker.busy -= 1
                worker.last_used = time.time()

    def post(self, name, path, *, data=None, files=None, json=None):
        """POST to a ready worker. Raises WorkerUnavailable if it isn't ready,
        requests.HTTPError on a 4xx/5xx from the worker."""
        worker = self.workers[name]
        with self.lock:
            self._refresh(worker)
            if worker.status != STATUS_READY:
                raise WorkerUnavailable(worker.status)
            worker.last_used = time.time()
        with self.hold(name):
            response = requests.post(
                f"{worker.base_url}{path}",
                data=data,
                files=files,
                json=json,
                timeout=worker.cfg.request_timeout_seconds,
            )
        if response.status_code >= 400:
            raise requests.HTTPError(_error_message(response), response=response)
        return response


def _error_message(response):
    if response.headers.get("Content-Type", "").startswith("application/json"):
        return response.json()["error"]
    return f"HTTP {response.status_code}"
