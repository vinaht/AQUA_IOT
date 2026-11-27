"""Local LAN receiver. HTTP, SQLite and 30-minute forecasts."""
import argparse,csv,hmac,io,json,math,re,secrets,sqlite3,threading
from datetime import datetime,timezone
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from forecast import Engine, database
ROOT=Path(__file__).resolve().parent
FIELDS=['received_at_utc','device_id','boot_id','seq','context','ph_uptime_ms','temperature_uptime_ms','adc_voltage_v','po_raw_v','po_filtered_v','ph','ph_status','temperature_c','temperature_status']

FIELDS += ["tds_ppm", "tds_status"]

def validate(d):
    if isinstance(d, dict) and "tds_ppm" not in d and "tds_status" not in d:
        d = {**d, "tds_ppm": None, "tds_status": "not_reported"}

    if not isinstance(d,dict) or set(d)!=set(FIELDS[1:]): raise ValueError('Incorrect fields')
    for key in ('device_id','boot_id'):
        if not isinstance(d[key],str) or not re.fullmatch(r'[A-Za-z0-9:_-]{1,64}',d[key]): raise ValueError(key)
    for key in ('seq','ph_uptime_ms','temperature_uptime_ms'):
        if type(d[key]) is not int or not 0<=d[key]<=4294967295: raise ValueError(key)
    if d['context'] not in ('calibration','water'): raise ValueError('context')
    for key,lo,hi in [('adc_voltage_v',0,3.3),('po_raw_v',0,6.6),('po_filtered_v',0,6.6),('ph',0,14),('temperature_c',-55,125)]:
        v=d[key]
        if v is not None and (type(v) not in (int,float) or not math.isfinite(v) or not lo<=v<=hi): raise ValueError(key)
    if d['ph_status'] not in ('ok','outside_calibration','invalid_reading'): raise ValueError('ph_status')
    if (d['ph'] is None)!=(d['ph_status']=='invalid_reading'): raise ValueError('pH/status mismatch')
    if d['temperature_status'] not in ('ok','disabled','missing','not_ds18b20','read_error'): raise ValueError('temperature_status')
    if (d['temperature_c'] is not None)!=(d['temperature_status']=='ok'): raise ValueError('temperature/status mismatch')
    ppm, status = d["tds_ppm"], d["tds_status"]
    if status not in ("ok", "not_reported", "no_temperature", "storage_error", "read_error"):
        raise ValueError("tds_status")
    if status == "ok":
        if (type(ppm) not in (int, float) or not math.isfinite(ppm)
                or ppm < 0 or d["temperature_status"] != "ok"):
            raise ValueError("tds_ppm")
    elif ppm is not None:
        raise ValueError("tds_ppm/status")
    return d

class Store:
    def __init__(self,path):
        self.path=path
        path.parent.mkdir(parents=True,exist_ok=True)
        with database(path) as c:
            c.execute('CREATE TABLE IF NOT EXISTS readings (id INTEGER PRIMARY KEY, device TEXT, boot TEXT, seq INTEGER, payload TEXT, UNIQUE(device,boot,seq))')
    def add(self,d):
        row={'received_at_utc':datetime.now(timezone.utc).isoformat(timespec='milliseconds'),**d}
        with database(self.path) as c:
            cur=c.execute('INSERT OR IGNORE INTO readings(device,boot,seq,payload) VALUES(?,?,?,?)',(d['device_id'],d['boot_id'],d['seq'],json.dumps(row,allow_nan=False)))
            return cur.rowcount==1
    def latest(self):
        with database(self.path) as c:
            row=c.execute('SELECT payload FROM readings ORDER BY id DESC LIMIT 1').fetchone()
            count=c.execute('SELECT COUNT(*) FROM readings').fetchone()[0]
        return {'count':count,'latest':json.loads(row[0]) if row else None}
    def csv(self):
        out=io.StringIO(newline='');w=csv.DictWriter(out,fieldnames=FIELDS);w.writeheader()
        with database(self.path) as c:
            for (p,) in c.execute('SELECT payload FROM readings ORDER BY id'): w.writerow(json.loads(p))
        return out.getvalue().encode('utf-8-sig')

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def setup(self):
        super().setup();self.connection.settimeout(5)
    def send(self,code,obj,ctype='application/json'):
        body=json.dumps(obj,allow_nan=False).encode() if ctype=='application/json' else obj
        self.send_response(code);self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body)
    def authorized(self):
        key=self.headers.get('X-API-Key','')
        if not hmac.compare_digest(key.encode('utf-8'),self.server.key.encode('utf-8')):
            self.send(401,{'error':'Invalid API key'});return False
        return True
    def do_GET(self):
        if self.path=='/':
            self.send(200,(ROOT/'monitor.html').read_bytes(),'text/html; charset=utf-8');return
        if self.path=='/health': self.send(200,{'status':'ok'});return
        if self.path not in ('/api/latest','/export.csv','/api/forecast','/forecasts.csv'): self.send(404,{'error':'Not found'});return
        if self.path=='/api/forecast':
            with self.server.forecast_lock: result=self.server.engine.tick()
            self.send(200,result);return
        if self.path=='/forecasts.csv':
            out=io.StringIO(newline='');w=csv.writer(out)
            with database(self.server.store.path) as c:
                cur=c.execute('SELECT * FROM forecasts ORDER BY origin');w.writerow([d[0] for d in cur.description]);w.writerows(cur)
            self.send(200,out.getvalue().encode('utf-8-sig'),'text/csv; charset=utf-8');return
        if self.path=='/api/latest': self.send(200,self.server.store.latest())
        else: self.send(200,self.server.store.csv(),'text/csv; charset=utf-8')
    def do_POST(self):
        if self.path!='/api/readings': self.send(404,{'error':'Not found'});return
        if not self.authorized(): return
        try:
            if self.headers.get('Content-Type','').split(';')[0]!='application/json': raise ValueError('JSON required')
            n=int(self.headers.get('Content-Length','0'))
            if not 0<n<=4096: raise ValueError('Invalid body length')
            d=validate(json.loads(self.rfile.read(n)))
        except (ValueError,TypeError,UnicodeError,TimeoutError):
            self.send(400,{'error':'Invalid measurement payload'});return
        try: added=self.server.store.add(d)
        except sqlite3.Error:
            self.send(503,{'error':'Storage failed'});return
        self.send(201 if added else 200,{'status':'saved' if added else 'duplicate'})
        if added: print(f"Saved {d['context']} pH={d['ph']} temp={d['temperature_c']} TDS={d['tds_ppm']}",flush=True)

def make_server(host,port,key,path):
    s=ThreadingHTTPServer((host,port),Handler);s.key=key;s.store=Store(path);s.engine=Engine(path,json.loads((ROOT/'alert_config.json').read_text()));s.forecast_lock=threading.Lock();return s

def main():
    p=argparse.ArgumentParser();p.add_argument('--host',default='0.0.0.0');p.add_argument('--port',type=int,default=8000);a=p.parse_args()
    config=ROOT/'server_config.json'
    if not config.exists(): config.write_text(json.dumps({'api_key':secrets.token_hex(24)},indent=2))
    key=json.loads(config.read_text())['api_key']
    s=make_server(a.host,a.port,key,ROOT/'data/readings.sqlite3')
    print('Monitor: http://127.0.0.1:'+str(a.port),flush=True)
    print('Monitor connects automatically; no API key required in the browser.',flush=True)
    print('API_KEY (ESP32 config.h only): '+key,flush=True)
    print('Use the PC LAN IPv4 address for SERVER_URL. Ctrl+C to stop.',flush=True)
    stop=threading.Event()
    def background():
        while not stop.is_set():
            try:
                with s.forecast_lock:s.engine.tick()
            except Exception as e: print('Forecast worker error:',e,flush=True)
            stop.wait(5)
    worker=threading.Thread(target=background,daemon=True);worker.start()
    try:s.serve_forever()
    except KeyboardInterrupt: pass
    finally:stop.set();worker.join(timeout=6);s.server_close()
if __name__=='__main__':main()
