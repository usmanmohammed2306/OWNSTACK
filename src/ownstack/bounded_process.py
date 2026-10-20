"""Fixed-command capture with bounded retained output and process-group cleanup."""
import os
import signal
import subprocess
import tempfile
import time
import selectors


def capture(command: list[str], payload: bytes, *, timeout: float, limit: int, **kwargs) -> dict:
    with tempfile.TemporaryFile() as incoming:
        incoming.write(payload)
        incoming.seek(0)
        process = subprocess.Popen(command, stdin=incoming, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   start_new_session=True, **kwargs)
        failure = ""
        deadline = time.monotonic() + timeout
        streams = selectors.DefaultSelector()
        retained = {'stdout': bytearray(), 'stderr': bytearray()}
        for name, pipe in [('stdout', process.stdout), ('stderr', process.stderr)]:
            os.set_blocking(pipe.fileno(), False)
            streams.register(pipe, selectors.EVENT_READ, name)
        try:
            while streams.get_map() or process.poll() is None:
                if time.monotonic() > deadline:
                    failure = "Local check deadline exceeded"
                    break
                for key, _ in streams.select(min(.05, max(0, deadline-time.monotonic()))):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        streams.unregister(key.fileobj)
                        continue
                    target = retained[key.data]
                    target.extend(chunk[:max(0,limit+1-len(target))])
                    if len(target) > limit:
                        failure = 'Candidate output limit exceeded'
                        break
                if failure:
                    break
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)
            streams.close()
            process.stdout.close()
            process.stderr.close()
        stdout, stderr = bytes(retained['stdout']), bytes(retained['stderr'])
        return {"stdout_bytes": stdout, "stderr": stderr[-4000:].decode("utf-8", errors="replace"),
                "exit_code": process.returncode, "failure": failure}
