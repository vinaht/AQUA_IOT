import json,tempfile,threading,unittest,urllib.request,urllib.error,csv,io
from pathlib import Path
from server import make_server
BASE={'device_id':'AA:BB:CC:DD:EE:FF','boot_id':'abcdef0123456789','seq':0,'context':'calibration','ph_uptime_ms':1000,'temperature_uptime_ms':1000,'adc_voltage_v':0.534,'po_raw_v':1.068,'po_filtered_v':1.0676,'ph':9.193,'ph_status':'outside_calibration','temperature_c':None,'temperature_status':'disabled'}
class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'readings.sqlite3';self.s=make_server('127.0.0.1',0,'testkey',self.path);self.t=threading.Thread(target=self.s.serve_forever,daemon=True);self.t.start();self.url='http://127.0.0.1:'+str(self.s.server_port)
 def tearDown(self):
  self.s.shutdown();self.s.server_close();self.t.join();self.tmp.cleanup()
 def request(self,path,body=None,key='testkey'):
  headers={'Content-Type':'application/json'}
  if key is not None: headers['X-API-Key']=key
  q=urllib.request.Request(self.url+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
  try:
   with urllib.request.urlopen(q,timeout=3) as r:return r.status,r.read()
  except urllib.error.HTTPError as e:return e.code,e.read()
 def test_store_null_export_and_restart(self):
  self.assertEqual(self.request('/api/readings',BASE)[0],201)
  d=json.loads(self.request('/api/latest')[1]);self.assertEqual(d['count'],1);self.assertIsNone(d['latest']['temperature_c']);self.assertEqual(d['latest']['ph'],9.193)
  rows=list(csv.DictReader(io.StringIO(self.request('/export.csv')[1].decode('utf-8-sig'))));self.assertEqual(rows[0]['temperature_c'],'');self.assertEqual(rows[0]['context'],'calibration')
  from server import Store
  self.assertEqual(Store(self.path).latest()['count'],1)
 def test_duplicate_and_new_boot(self):
  self.request('/api/readings',BASE);self.assertEqual(self.request('/api/readings',BASE)[0],200)
  self.assertEqual(self.request('/api/readings',{**BASE,'boot_id':'newboot'})[0],201)
  self.assertEqual(json.loads(self.request('/api/latest')[1])['count'],2)
 def test_bad_auth(self):
  self.assertEqual(self.request('/api/readings',BASE,key='wrong')[0],401)
  self.assertEqual(self.request('/api/readings',BASE,key=None)[0],401)
  self.assertEqual(json.loads(self.request('/api/latest')[1])['count'],0)
 def test_browser_reads_without_key(self):
  self.assertEqual(self.request('/api/readings',BASE)[0],201)
  for path in ('/','/api/latest','/api/forecast','/export.csv','/forecasts.csv'):
   with self.subTest(path=path):
    self.assertEqual(self.request(path,key=None)[0],200)
  self.assertEqual(json.loads(self.request('/api/latest',key=None)[1])['latest']['ph'],BASE['ph'])
 def test_outside_thresholds_are_stored_and_shown(self):
  reading=dict(BASE, context='water', ph=9.5, temperature_c=40,
               temperature_status='ok', tds_ppm=800, tds_status='ok')
  self.assertEqual(self.request('/api/readings',reading)[0],201)
  latest=json.loads(self.request('/api/latest',key=None)[1])['latest']
  out=json.loads(self.request('/api/forecast',key=None)[1])['devices'][0]
  for field,current,value in [('ph','current_ph',9.5),('temperature_c','current_temperature_c',40),('tds_ppm','tds_ppm',800)]:
   self.assertEqual(latest[field],value)
   self.assertEqual(out[current],value)
  for warning in ('current_outside','temp_current_outside','tds_current_above'):
   self.assertIn(warning,out['warnings'])
 def test_invalid_numbers_and_status(self):
  for changes in [{'ph':float('nan')},{'ph':15},{'temperature_c':0},{'seq':True},{'context':'unknown'},{'ph':None}]:
   self.assertEqual(self.request('/api/readings',{**BASE,**changes})[0],400)
 def test_missing_and_valid_temperature(self):
  for i,(t,status) in enumerate([(None,'missing'),(25.5,'ok')]):
   self.assertEqual(self.request('/api/readings',{**BASE,'seq':i,'temperature_c':t,'temperature_status':status})[0],201)
 def test_monitor_health_and_empty(self):
  self.assertEqual(self.request('/')[0],200);self.assertEqual(self.request('/health')[0],200)
  self.assertIsNone(json.loads(self.request('/api/latest')[1])['latest'])
class ThreeChannelTests(unittest.TestCase):
    def test_alerts_missing_sensors_migration_and_export(self):
        from datetime import datetime, timedelta, timezone
        from forecast import analyze, database, Engine
        from server import Store
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        cfg = dict(ph_low=6.5, ph_high=7.5, temp_low=25, temp_high=35, tds_high=500)
        rows = [dict(BASE, seq=i, context="water", ph=7.1, ph_status="ok",
                     temperature_c=27, temperature_status="ok", tds_ppm=520, tds_status="ok",
                     received_at_utc=(start + timedelta(seconds=5*i)).isoformat())
                for i in range(46 * 12 + 1)]
        at = start + timedelta(minutes=15)
        first = rows[:181]
        out = analyze(first, at, cfg)
        self.assertEqual(out["forecast"]["target_utc"], (at+timedelta(minutes=30)).isoformat())
        self.assertAlmostEqual(out["forecast"]["tds_ppm"], 520)
        self.assertEqual(out["warnings"], ["tds_current_above", "tds_forecast_above"])
        self.assertIsNotNone(out["forecast"]["temperature_c"])
        outside = [dict(r, ph=9.5, ph_status="outside_calibration", temperature_c=40, tds_ppm=800) for r in first]
        outside_result = analyze(outside, at, cfg)
        for name in ("ph", "temperature_c", "tds_ppm"):
            self.assertIsNotNone(outside_result["forecast"][name])
            self.assertEqual(outside_result["channels"][name]["state"], "ready")
        forecast_only = first[:-1] + [dict(first[-1], tds_ppm=480)]
        self.assertEqual(analyze(forecast_only, at, cfg)["warnings"], ["tds_forecast_above"])
        exact = [dict(r, tds_ppm=500) for r in first]
        self.assertEqual(analyze(exact, at, cfg)["warnings"], [])
        invalid = [dict(r, tds_status="read_error", tds_ppm=None) for r in first]
        out = analyze(invalid, at, cfg)
        self.assertIsNone(out["forecast"]["tds_ppm"])
        self.assertIsNotNone(out["forecast"]["ph"])
        self.assertIsNotNone(out["forecast"]["temperature_c"])
        only_tds = [dict(r, ph_status="invalid_reading", ph=None) for r in first]
        self.assertAlmostEqual(analyze(only_tds, at, cfg)["forecast"]["tds_ppm"], 520)
        for context, now in (("calibration", at), ("water", at + timedelta(seconds=21))):
            self.assertIsNone(analyze(first[:-1]+[dict(first[-1], context=context)], now, cfg)["forecast"])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"fixture.sqlite"
            store = Store(path)
            with database(path) as c:
                c.execute("""CREATE TABLE forecasts(device TEXT,boot TEXT,origin TEXT,target TEXT,
                    predicted REAL,baseline REAL,issued TEXT,actual REAL, PRIMARY KEY(device,boot,origin))""")
            e = Engine(path, cfg)
            def insert(batch):
                with database(path) as c:
                    c.executemany("INSERT INTO readings(device,boot,seq,payload) VALUES(?,?,?,?)",
                                  [(r["device_id"],r["boot_id"],r["seq"],json.dumps(r)) for r in batch])
            insert(first)
            e.tick(at)
            e.tick(at)
            insert(rows[181:])
            scores = e.tick(start+timedelta(minutes=46))["evaluation"]["channels"]
            self.assertEqual(scores["tds_ppm"]["matched_count"], 1)
            self.assertAlmostEqual(scores["tds_ppm"]["mae"], 0)
            with database(path) as c:
                pred, actual = c.execute("SELECT tds_predicted,tds_actual FROM forecasts ORDER BY origin LIMIT 1").fetchone()
                self.assertEqual((pred, actual), (520,520))
            self.assertIn("tds_ppm",store.csv().decode("utf-8-sig"))

if __name__=='__main__':unittest.main()
