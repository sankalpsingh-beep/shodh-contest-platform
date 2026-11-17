import threading
import io
import tarfile
import time

import docker
from docker.types import LogConfig


class DockerPythonRunner:
    def __init__(
        self,
        image="python:3.12-alpine",
        output_limit_bytes=65536,
    ):
        self.client = docker.from_env()
        self.image = image
        self.output_limit_bytes = output_limit_bytes

    def _archive(self, source_code, input_data):
        buffer = io.BytesIO()

        with tarfile.open(fileobj=buffer, mode="w") as archive:
            files = {
                "main.py": source_code.encode("utf-8"),
                "input.txt": input_data.encode("utf-8"),
            }

            for name, content in files.items():
                info = tarfile.TarInfo(name=name)
                info.size = len(content)
                info.mode = 0o444
                archive.addfile(info, io.BytesIO(content))

        buffer.seek(0)
        return buffer

    def run(self, source_code, input_data, time_limit_ms, memory_limit_mb):
        container = None

        try:
            try:
                compile(source_code, "main.py", "exec")
            except SyntaxError as exc:
                return {
                    "verdict": "CE",
                    "stdout": "",
                    "stderr": str(exc),
                    "exit_code": None,
                    "duration_ms": 0,
                }

            try:
                self.client.images.get(self.image)
            except docker.errors.ImageNotFound:
                self.client.images.pull(self.image)

            container = self.client.containers.create(
                image=self.image,
                command=[
                    "python",
                    "-I",
                    "-c",
                    (
                        "import os,sys,io; "
                        "source=os.environ.pop('SHODH_SOURCE'); "
                        "data=os.environ.pop('SHODH_INPUT'); "
                        "sys.stdin=io.StringIO(data); "
                        "exec(compile(source,'main.py','exec'))"
                    ),
                ],
                environment={
                    "SHODH_SOURCE": source_code,
                    "SHODH_INPUT": input_data,
                },
                working_dir="/workspace",
                user="10001:10001",
                network_disabled=True,
                read_only=True,
                mem_limit=f"{memory_limit_mb}m",
                memswap_limit=f"{memory_limit_mb}m",
                nano_cpus=1_000_000_000,
                pids_limit=32,
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
                tmpfs={
                    "/workspace": "rw,noexec,nosuid,nodev,size=16m,mode=1777"
                },
                log_config=LogConfig(
                    type="json-file",
                    config={"max-size": "1m", "max-file": "1"},
                ),
                detach=True,
            )
            container.start()

            started = time.monotonic()
            deadline = started + (time_limit_ms / 1000)
            
            output_exceeded = threading.Event()
            stop_monitor = threading.Event()
            
            def monitor_output():
                while not stop_monitor.is_set():
                    try:
                        # Inspect accumulated Docker logs without returning them.
                        # Docker log rotation provides a separate disk-use safeguard.
                        logs = container.logs(
                            stdout=True,
                            stderr=True,
                            tail="all",
                        )
            
                        if len(logs) > self.output_limit_bytes:
                            output_exceeded.set()
                            try:
                                container.kill()
                            except docker.errors.APIError:
                                pass
                            return
            
                    except docker.errors.APIError:
                        return
            
                    stop_monitor.wait(0.05)
            
            monitor = threading.Thread(target=monitor_output, daemon=True)
            monitor.start()
            
            timed_out = False
            
            while time.monotonic() < deadline:
                if output_exceeded.is_set():
                    break
            
                container.reload()
            
                if container.status in ("exited", "dead"):
                    break
            
                time.sleep(0.05)
            else:
                if not output_exceeded.is_set():
                    timed_out = True
                    try:
                        container.kill()
                    except docker.errors.APIError:
                        pass
            
            stop_monitor.set()
            monitor.join(timeout=1)
            
            duration_ms = int((time.monotonic() - started) * 1000)
            
            result = container.wait(timeout=3)
            exit_code = result.get("StatusCode", 1)
            
            if output_exceeded.is_set():
                verdict = "OLE"
            elif timed_out:
                verdict = "TLE"
            elif exit_code != 0:
                verdict = "RE"
            else:
                verdict = "OK"
            
            stdout = container.logs(
                stdout=True, stderr=False
            ).decode("utf-8", errors="replace")[:self.output_limit_bytes]
            
            stderr = container.logs(
                stdout=False, stderr=True
            ).decode("utf-8", errors="replace")[:self.output_limit_bytes]

            return {
                "verdict": verdict,
                "stdout": stdout[:self.output_limit_bytes],
                "stderr": stderr[:self.output_limit_bytes],
                "exit_code": exit_code,
                "duration_ms": duration_ms,
            }

        except Exception as exc:
            return {
                "verdict": "JUDGE_ERROR",
                "stdout": "",
                "stderr": str(exc)[:2000],
                "exit_code": None,
                "duration_ms": 0,
            }

        finally:
            if container is not None:
                try:
                    container.remove(force=True)
                except docker.errors.NotFound:
                    pass

    def close(self):
        self.client.close()

