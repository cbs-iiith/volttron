# -*- coding: utf-8 -*- {{{
# vim: set fenc=utf-8 ft=python sw=4 ts=4 sts=4 et:
#
# Copyright (c) 2020, Sam Babu, Godithi.
# All rights reserved.
#
#
# IIIT Hyderabad

# }}}

# Sam

import os
import shutil
import subprocess
import time

logFile = "/home/bsrc-sam/volttron/volttron.log"
pathPython = "/home/bsrc-sam/volttron/env/bin/python"
pathVolttron = "/home/bsrc-sam/volttron/env/bin/volttron"

MAX_LOG_SIZE = 500 * 1024 * 1024  # 500MB

if os.path.getsize(logFile) > MAX_LOG_SIZE:
    os.remove(logFile)

subprocess.Popen([pathPython, pathVolttron, "-vv", "-l", logFile])

while True:
    if os.path.getsize(logFile) > MAX_LOG_SIZE:
        shutil.move(logFile, logFile + '.bak')
        os.remove(logFile)
    time.sleep(30)
