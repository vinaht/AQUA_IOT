"""python check_csv.py "water_readings (1)(1).csv""" 
import csv,json,sys,statistics
from collections import Counter
from datetime import datetime
rows=list(csv.DictReader(open(sys.argv[1],encoding='utf-8-sig',newline='')))
if not rows:raise SystemExit('CSV khong co du lieu')
required={'received_at_utc','device_id','boot_id','seq','context','ph','ph_status','temperature_c'}
if not required<=rows[0].keys():raise SystemExit('Thieu cot: '+str(required-rows[0].keys()))
times=[];bad_time=0;ph=[]
for r in rows:
 try:times.append(datetime.fromisoformat(r['received_at_utc']))
 except ValueError:bad_time+=1
 if r['context']=='water':
  try:ph.append(float(r['ph']))
  except ValueError:pass
times.sort();gaps=[(b-a).total_seconds() for a,b in zip(times,times[1:])]
keys=[(r['device_id'],r['boot_id'],r['seq']) for r in rows]
print(json.dumps({'records':len(rows),'context':dict(Counter(r['context'] for r in rows)),'ph_status':dict(Counter(r['ph_status'] for r in rows)), 'invalid_times':bad_time,'duplicate_keys':len(keys)-len(set(keys)), 'start':str(times[0]) if times else None,'end':str(times[-1]) if times else None,'span_minutes':(times[-1]-times[0]).total_seconds()/60 if times else 0,'median_interval_seconds':statistics.median(gaps) if gaps else None,'max_gap_seconds':max(gaps) if gaps else None,'water_ph_min':min(ph) if ph else None,'water_ph_max':max(ph) if ph else None,'missing_temperature':sum(not r['temperature_c'] for r in rows)},indent=2))
