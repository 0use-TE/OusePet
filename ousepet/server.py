"""Run private management and a separate public, read-only listener."""
import os
import signal
import subprocess
import sys
import time
from urllib.request import urlopen


def main():
    children=[];stopping=False
    def stop(*_):
        nonlocal stopping
        stopping=True
        for child in children:
            if child.poll() is None:child.terminate()
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    try:
        children.append(subprocess.Popen([sys.executable,'-m','uvicorn','ousepet.api:app','--host','0.0.0.0','--port','8766']))
        for _ in range(300):
            if stopping or children[0].poll() is not None:return
            try:
                with urlopen('http://127.0.0.1:8766/api/health',timeout=1):break
            except OSError:time.sleep(.2)
        else:raise RuntimeError('Management service did not become ready')
        if stopping:return
        children.append(subprocess.Popen([sys.executable,'-m','uvicorn','ousepet.sharing:public_app','--host','0.0.0.0',
            '--port',os.environ.get('OUSEPET_SHARE_PORT','8767'),'--no-proxy-headers']))
        while not stopping and all(child.poll() is None for child in children):time.sleep(.5)
    finally:
        stop()
        for child in children:
            try:child.wait(timeout=35)
            except subprocess.TimeoutExpired:child.kill();child.wait()


if __name__=='__main__':main()
