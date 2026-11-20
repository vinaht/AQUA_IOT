"""pH mean15 forecast. Standard library, no temperature required."""
import json,math,statistics,sqlite3
from datetime import datetime,timezone,timedelta

def stamp(s):return datetime.fromisoformat(s).astimezone(timezone.utc)
def iso(t):return t.isoformat(timespec='seconds')
def config_check(c):
    lo,hi=c.get('ph_low'),c.get('ph_high')
    if lo is None and hi is None:return
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in (lo,hi)) or not 0<=lo<hi<=14:
        raise ValueError('ph_low/ph_high must both be null or 0 <= low < high <= 14')

def minute_values(rows,now):
    groups={}
    for r in rows:
        t=stamp(r['received_at_utc']);end=t.replace(second=0,microsecond=0)+timedelta(minutes=1)
        v=r.get('ph')
        if end>now or r.get('context')!='water' or r.get('ph_status')!='ok':continue
        if type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=14:continue
        groups.setdefault(end,[]).append(v)
    return {t:statistics.median(v) for t,v in groups.items() if len(v)>=3}

def analyze(rows,now,cfg):
    config_check(cfg)
    out={'state':'no_data','forecast':None,'current_ph':None,'warnings':[], 'thresholds':cfg}
    if not rows:return out
    latest=max(rows,key=lambda r:stamp(r['received_at_utc']))
    out['current_ph']=latest.get('ph')
    age=(now-stamp(latest['received_at_utc'])).total_seconds();out['age_seconds']=round(age,1)
    if age<0:out['state']='clock_error';return out
    if age>20:out['state']='stale';return out
    if latest.get('context')!='water':out['state']='calibration';return out
    if latest.get('ph_status')!='ok' or latest.get('ph') is None:out['state']='ph_quality';return out
    # Only same device/session as the latest reading. Never fill across restarts.
    rows=[r for r in rows if (r['device_id'],r['boot_id'])==(latest['device_id'],latest['boot_id'])]
    values=minute_values(rows,now)
    t=now.replace(second=0,microsecond=0)
    times=[t-timedelta(minutes=i) for i in range(15)]
    out['minutes_ready']=sum(k in values for k in times)
    lo,hi=cfg.get('ph_low'),cfg.get('ph_high')
    if lo is not None and not lo<=latest['ph']<=hi:out['warnings'].append('current_outside')
    if not all(k in values for k in times):out['state']='warming_up';return out
    p=statistics.mean(values[k] for k in times)
    out['state']='ready'
    out['forecast']={'issued_at_utc':iso(now),'origin_utc':iso(t),'target_utc':iso(t+timedelta(minutes=30)), 'ph':p,'baseline_ph':values[t], 'method':'mean15','device_id':latest['device_id'],'boot_id':latest['boot_id']}
    if lo is not None and not lo<=p<=hi:out['warnings'].append('forecast_outside')
    return out

class Engine:
    def __init__(self,path,cfg):
        self.path=path;self.cfg=cfg;config_check(cfg)
        with sqlite3.connect(path) as c:
            c.execute('CREATE TABLE IF NOT EXISTS forecasts(device TEXT,boot TEXT,origin TEXT,target TEXT,predicted REAL,baseline REAL,issued TEXT,actual REAL,PRIMARY KEY(device,boot,origin))')
            c.execute('CREATE TABLE IF NOT EXISTS alert_events(id INTEGER PRIMARY KEY,at TEXT,device TEXT,state TEXT,payload TEXT)')
        self.previous={}
    def tick(self,now=None):
        now=now or datetime.now(timezone.utc)
        with sqlite3.connect(self.path) as c:
            devices=c.execute('SELECT DISTINCT device FROM readings').fetchall()
            statuses=[]
            for (device,) in devices:
                raw=c.execute('SELECT payload FROM readings WHERE device=? ORDER BY id DESC LIMIT 20000',(device,)).fetchall()
                rows=[json.loads(p) for (p,) in raw];out=analyze(rows,now,self.cfg);out['device_id']=device
                f=out['forecast']
                if f:
                    c.execute('INSERT OR IGNORE INTO forecasts VALUES(?,?,?,?,?,?,?,NULL)',(device,f['boot_id'],f['origin_utc'],f['target_utc'],f['ph'],f['baseline_ph'],f['issued_at_utc']))
                # Evaluate previously stored forecasts, never rewrite predictions.
                for boot in {r['boot_id'] for r in rows}:
                    vals=minute_values([r for r in rows if r['boot_id']==boot],now)
                    for origin,target in c.execute('SELECT origin,target FROM forecasts WHERE device=? AND boot=? AND actual IS NULL',(device,boot)).fetchall():
                        if stamp(target) in vals:c.execute('UPDATE forecasts SET actual=? WHERE device=? AND boot=? AND origin=?',(vals[stamp(target)],device,boot,origin))
                signature=json.dumps([out['state'],out['warnings']])
                if self.previous.get(device)!=signature:
                    c.execute('INSERT INTO alert_events(at,device,state,payload) VALUES(?,?,?,?)',(iso(now),device,signature,json.dumps(out,allow_nan=False)))
                    self.previous[device]=signature
                statuses.append(out)
            scores=c.execute('SELECT COUNT(*),AVG(ABS(predicted-actual)),AVG(ABS(baseline-actual)) FROM forecasts WHERE actual IS NOT NULL').fetchone()
            events=[json.loads(p) for (p,) in c.execute('SELECT payload FROM alert_events ORDER BY id DESC LIMIT 20')]
        return {'devices':statuses,'evaluation':dict(zip(['matched_count','mae','baseline_mae'],scores)), 'recent_events':events}
