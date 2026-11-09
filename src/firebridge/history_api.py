"""Private bounded historical preparation service, called only by the app worker."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import logging
import os
import signal
import threading
from uuid import UUID

from .config import Settings
from .db import connect
from .history_query import STAGE, prepare, status, submit


def serve(settings, host='0.0.0.0', port=8090):
    token=os.environ.get('FIREBRIDGE_HISTORY_TOKEN','')
    stop=threading.Event();wake=threading.Event()
    def work():
        while not stop.is_set():
            try:
                with connect(settings) as db:
                    row=db.execute("SELECT id FROM pipeline_runs WHERE stage=%s AND status IN ('queued','running') ORDER BY started_at NULLS FIRST,id LIMIT 1",(STAGE,)).fetchone()
                if row:
                    result=prepare(settings,str(row['id']),max_selected=int(os.environ.get('FIREBRIDGE_HISTORY_MAX_ROWS','1000000')))
                    if result:continue
            except Exception as exc:
                logging.error('Historical worker operation failed: %s',type(exc).__name__)
            wake.wait(2);wake.clear()
    class Handler(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.1'
        def log_message(self,*args):pass
        def setup(self):
            super().setup();self.connection.settimeout(10)
        def reply(self,code,value):
            body=json.dumps(value,default=str).encode()
            self.send_response(code);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        def authorized(self):
            return len(token)>=32 and hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+token)
        def do_GET(self):
            if self.path=='/health':
                try:
                    with connect(settings) as db:db.execute('SELECT 1')
                    return self.reply(200,{'status':'healthy'})
                except Exception:return self.reply(503,{'status':'unhealthy'})
            if not self.authorized():return self.reply(401,{'error':'unauthorized'})
            try:
                if not self.path.startswith('/jobs/'):return self.reply(404,{'error':'not_found'})
                return self.reply(200,status(settings,str(UUID(self.path.removeprefix('/jobs/')))))
            except ValueError:return self.reply(400,{'error':'invalid_job'})
            except Exception:return self.reply(503,{'error':'history_unavailable'})
        def do_POST(self):
            if not self.authorized():return self.reply(401,{'error':'unauthorized'})
            if self.path!='/jobs':return self.reply(404,{'error':'not_found'})
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=1024:return self.reply(413,{'error':'invalid_body_size'})
                body=json.loads(self.rfile.read(length))
                if not isinstance(body,dict) or set(body)!={'analysis_id'}:raise ValueError('Invalid body')
                result=submit(settings,str(UUID(body['analysis_id'])));wake.set()
                return self.reply(200,result)
            except (ValueError,TypeError):return self.reply(400,{'error':'invalid_historical_selection'})
            except Exception:return self.reply(503,{'error':'history_unavailable'})
    server=ThreadingHTTPServer((host,port),Handler);server.daemon_threads=True
    worker=threading.Thread(target=work,daemon=True);worker.start()
    def shutdown(*_):
        stop.set();wake.set();threading.Thread(target=server.shutdown,daemon=True).start()
    signal.signal(signal.SIGTERM,shutdown);signal.signal(signal.SIGINT,shutdown)
    server.serve_forever(poll_interval=.5);server.server_close();worker.join(timeout=20)


if __name__=='__main__':serve(Settings.load())
