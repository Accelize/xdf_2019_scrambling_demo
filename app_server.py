#! /usr/bin/env python3
# coding=utf-8
"""Application web server"""
from http.server import HTTPServer, BaseHTTPRequestHandler
from subprocess import run, Popen, PIPE, STDOUT
from urllib.parse import urlparse, parse_qs
import json
import sys
import os
import psutil

class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    """Server that run Video Streamer Application"""

    def _set_headers(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()

    def get_process_pid(self, patterns):
        pids=[]
        for proc in psutil.process_iter():
            try:
                pinfo = proc.as_dict(attrs=['pid', 'name', 'cmdline'])
                for p in patterns:
                    if p in pinfo['cmdline']:
                        pids.append(str(pinfo['pid']))
            except (psutil.NoSuchProcess, psutil.AccessDenied , psutil.ZombieProcess) :
                pass
        return pids
        
    def start_streaming_process(self):
        print('Starting Streaming...')
        log=open('app_server.log', 'w+', 1)
        Popen(['./run.sh'], universal_newlines=True, stdout=log)

    def kill_streaming_process(self):
        pids = self.get_process_pid(['run.sh','ffmpeg', 'video_streamer.py'])
        print(f"Killing process with pid={' '.join(pids)}")
        os.system(f"kill -9 {' '.join(pids)}")

    def do_GET(self):
        """GET"""
        self._set_headers()
        txt=''
        if os.path.exists('app_server.log'):
            with open('app_server.log', 'r') as f:
                txt += f.read()
        else:
            txt = 'No log file available'
        self.wfile.write(txt.encode('utf-8'))

    def do_PUT(self):
        self.do_POST()

    def do_POST(self):
        """POST"""
        self._set_headers()
        length    = int(self.headers["Content-Length"])
        post_body = self.rfile.read(length)
        post_body = post_body.decode('ascii')
        fields    = parse_qs(post_body)
        print(fields)
        for key, val in fields.items():
            if key == 'cmd' and val[0]=='start':
                self.start_streaming_process()
            if key == 'cmd' and val[0]=='stop':
                print('Stopping Streaming...')
                self.kill_streaming_process()
            if key == 'cmd' and val[0]=='exit':
                print('Exiting Application...')
                self.kill_streaming_process()
                sys.exit(0)

HTTPServer(('0.0.0.0', 8080), SimpleHTTPRequestHandler).serve_forever()
        
