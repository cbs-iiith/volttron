import subprocess
import time
import os

logFile         = "/home/bsrc-sam/volttron/volttron.log"
pathPython      = "/home/bsrc-sam/volttron/env/bin/python"
pathVolttron    = "/home/bsrc-sam/volttron/env/bin/volttron"
bindAddrs       = "tcp://192.168.1.61:8080"

MAX_LOG_SIZE = 500*1024*1024   # 500MB

if os.path.getsize(logFile) > MAX_LOG_SIZE:
    os.remove(logFile)

subprocess.Popen([pathPython, pathVolttron, "-vv", "-l", logFile])

while True:
    if os.path.getsize(logFile) > MAX_LOG_SIZE:
        os.remove(logFile)
    time.sleep(30)
