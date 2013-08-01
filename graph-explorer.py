#!/usr/bin/env python2

import os
from webapp.bottle import run, debug, PasteServer
import config

app_dir = os.path.dirname(__file__)
if app_dir:
    os.chdir(app_dir)

debug(True)
run('webapp.webapp', reloader=True, host=config.listen_host, port=config.listen_port, server=PasteServer)
