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
  q=urllib.request.Request(self.url+path,data=json.dumps(body).encode() if body is not None else None,headers={'X-API-Key':key,'Content-Type':'application/json'})
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
  self.assertEqual(json.loads(self.request('/api/latest')[1])['count'],0)
 def test_invalid_numbers_and_status(self):
  for changes in [{'ph':float('nan')},{'ph':15},{'temperature_c':0},{'seq':True},{'context':'unknown'},{'ph':None}]:
   self.assertEqual(self.request('/api/readings',{**BASE,**changes})[0],400)
 def test_missing_and_valid_temperature(self):
  for i,(t,status) in enumerate([(None,'missing'),(25.5,'ok')]):
   self.assertEqual(self.request('/api/readings',{**BASE,'seq':i,'temperature_c':t,'temperature_status':status})[0],201)
 def test_monitor_health_and_empty(self):
  self.assertEqual(self.request('/')[0],200);self.assertEqual(self.request('/health')[0],200)
  self.assertIsNone(json.loads(self.request('/api/latest')[1])['latest'])
if __name__=='__main__':unittest.main()
