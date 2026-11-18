import time

import docker
from docker.types import LogConfig, Ulimit


class DockerPythonRunner:
    def __init__(
        self,
        image="python:3.12-alpine",
        output_limit_bytes=65536,
    ):
        self.client = docker.from_env()
        self.image = image
        self.output_limit_bytes = output_limit_bytes

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

            wrapper = r"""
import io
import os
import sys

source = os.environ.pop("SHODH_SOURCE")
data = os.environ.pop("SHODH_INPUT")
limit = int(os.environ.pop("SHODH_OUTPUT_LIMIT"))

total_output = 0


class LimitedWriter:
    def __init__(self, original):
        self.original = original

    def write(self, text):
        global total_output

        size = len(text.encode("utf-8", errors="replace"))

        if total_output + size > limit:
            self.original.flush()
            os._exit(86)

        total_output += size
        result = self.original.write(text)
        self.original.flush()
        return result

    def flush(self):
        return self.original.flush()

    def __getattr__(self, name):
        return getattr(self.original, name)


sys.stdout = LimitedWriter(sys.stdout)
sys.stderr = LimitedWriter(sys.stderr)
sys.stdin = io.StringIO(data)

exec(compile(source, "main.py", "exec"))
"""

            container = self.client.containers.create(
                image=self.image,
                command=["python", "-I", "-c", wrapper],
                environment={
                    "SHODH_SOURCE": source_code,
                    "SHODH_INPUT": input_data,
                    "SHODH_OUTPUT_LIMIT": str(
                        self.output_limit_bytes
                    ),
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
                    "/workspace": (
                        "rw,noexec,nosuid,nodev,"
                        "size=16m,mode=1777"
                    ),
                    "/tmp": (
                        "rw,noexec,nosuid,nodev,"
                        "size=8m,mode=1777"
                    ),
                },
                ulimits=[
                    Ulimit(name="core", soft=0, hard=0),
                ],
                log_config=LogConfig(
                    type="json-file",
                    config={
                        "max-size": "1m",
                        "max-file": "1",
                    },
                ),
                detach=True,
            )

            container.start()

            started = time.monotonic()
            deadline = started + (time_limit_ms / 1000)
            timed_out = False

            while time.monotonic() < deadline:
                container.reload()

                if container.status in ("exited", "dead"):
                    break

                time.sleep(0.025)

            else:
                timed_out = True

                try:
                    container.kill()
                except docker.errors.APIError:
                    pass

            try:
                result = container.wait(timeout=3)
                exit_code = result.get("StatusCode", 1)
            except Exception:
                exit_code = 1

            duration_ms = int(
                (time.monotonic() - started) * 1000
            )

            stdout = container.logs(
                stdout=True,
                stderr=False,
            ).decode("utf-8", errors="replace")

            stderr = container.logs(
                stdout=False,
                stderr=True,
            ).decode("utf-8", errors="replace")

            if timed_out:
                verdict = "TLE"
            elif exit_code == 86:
                verdict = "OLE"
            elif exit_code != 0:
                verdict = "RE"
            else:
                verdict = "OK"

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
                except docker.errors.APIError:
                    pass

    def close(self):
        self.client.close()
