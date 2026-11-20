import unittest,tempfile,sqlite3,json
from pathlib import Path
from datetime import datetime,timezone,timedelta
from forecast import analyze,Engine,config_check
from server import Store
T=datetime(2026,1,1,tzinfo=timezone.utc)
CFG={'ph_low':6.5,'ph_high':8.5}
def rows(n=16,v=7.2):
 return [dict(received_at_utc=(T+timedelta(seconds=i*5)).isoformat(),device_id='a',boot_id='b',seq=i,context='water',ph=v,ph_status='ok') for i in range(n*12+1)]
class Tests(unittest.TestCase):
 def test_horizon_and_rolling(self):
  a=analyze(rows(15),T+timedelta(minutes=15),CFG);self.assertEqual(a['state'],'ready');self.assertAlmostEqual(a['forecast']['ph'],7.2);self.assertEqual(a['forecast']['target_utc'],'2026-01-01T00:45:00+00:00')
 def test_warmup_gaps_and_boot(self):
  self.assertEqual(analyze(rows(14),T+timedelta(minutes=14),CFG)['state'],'warming_up')
  r=rows(15);r=[x for x in r if not 60<=x['seq']<72];self.assertEqual(analyze(r,T+timedelta(minutes=15),CFG)['state'],'warming_up')
  r=rows(15);r[-1]['boot_id']='new';self.assertEqual(analyze(r,T+timedelta(minutes=15),CFG)['state'],'warming_up')
 def test_quality_stale_calibration(self):
  for changes,state in [({'context':'calibration'},'calibration'),({'ph_status':'outside_calibration'},'ph_quality')]:
   r=rows();r[-1].update(changes);self.assertEqual(analyze(r,T+timedelta(minutes=16),CFG)['state'],state)
  self.assertEqual(analyze(rows(),T+timedelta(minutes=17),CFG)['state'],'stale')
 def test_threshold_and_disabled(self):
  a=analyze(rows(v=9),T+timedelta(minutes=16),CFG);self.assertEqual(a['warnings'],['current_outside','forecast_outside'])
  a=analyze(rows(v=9),T+timedelta(minutes=16),{'ph_low':None,'ph_high':None});self.assertEqual(a['warnings'],[])
  with self.assertRaises(ValueError):config_check({'ph_low':8,'ph_high':7})
 def test_store_prediction_then_evaluate_unchanged(self):
  with tempfile.TemporaryDirectory() as temp:
   p=Path(temp)/'test.db';Store(p);e=Engine(p,CFG)
   r=rows(46)
   def insert(batch):
    with sqlite3.connect(p) as c:
     for x in batch:c.execute('INSERT INTO readings(device,boot,seq,payload) VALUES(?,?,?,?)',('a','b',x['seq'],json.dumps(x)))
   insert(r[:181]);e.tick(T+timedelta(minutes=15))
   with sqlite3.connect(p) as c:before=c.execute('SELECT predicted,actual FROM forecasts').fetchone()
   self.assertIsNone(before[1]);insert(r[181:]);out=e.tick(T+timedelta(minutes=46))
   self.assertEqual(out['evaluation']['matched_count'],1);self.assertAlmostEqual(out['evaluation']['mae'],0)
   with sqlite3.connect(p) as c:after=c.execute('SELECT predicted,actual FROM forecasts ORDER BY origin LIMIT 1').fetchone()
   self.assertEqual(before[0],after[0]);self.assertAlmostEqual(after[1],7.2)
if __name__=='__main__':unittest.main()
