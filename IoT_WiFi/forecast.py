"""Online 30-minute forecasts and verification against completed sensor minutes."""
from collections import defaultdict
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import math
import sqlite3
import statistics
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ml_review"))
from pipeline import INPUTS
from predict import infer, load_model

MIN = timedelta(minutes=1)
LOCAL = timezone(timedelta(hours=7))
SENSORS = {
    "water_pH": ("ph", "ph_status", 0, 14),
    "water_temp": ("temperature_c", "temperature_status", 0, 100),
    "TDS": ("tds_ppm", "tds_status", 0, math.inf),
}
# SQLite columns for each target, including the legacy pH names.
COLUMNS = {
    "ph": ("predicted", "actual", "baseline"),
    "temperature_c": ("temperature_predicted", "temperature_actual", "temperature_baseline"),
    "tds_ppm": ("tds_predicted", "tds_actual", "tds_baseline"),
}
RULES = {
    "ph": ("ph_low", "ph_high", "current_outside", "forecast_outside"),
    "temperature_c": ("temp_low", "temp_high", "temp_current_outside", "temp_forecast_outside"),
    "tds_ppm": (None, "tds_high", "tds_current_above", "tds_forecast_above"),
}


def stamp(value):
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def iso(t):
    return t.isoformat(timespec="seconds")


@contextmanager
def database(path):
    with closing(sqlite3.connect(path)) as conn, conn:
        yield conn


def finite(value):
    return type(value) in (float, int) and math.isfinite(value)


def config_check(cfg):
    for low, high, floor, ceiling in (("ph_low", "ph_high", 0, 14),
                                      ("temp_low", "temp_high", -55, 125)):
        lo, hi = cfg.get(low), cfg.get(high)
        if lo is None and hi is None:
            continue
        if not finite(lo) or not finite(hi) or not floor <= lo < hi <= ceiling:
            raise ValueError(f"Invalid {low}/{high}")
    high = cfg.get("tds_high")
    if high is not None and (not finite(high) or high <= 0):
        raise ValueError("tds_high must be positive or null")


def valid(row, target):
    name, status, low, high = SENSORS[target]
    v = row.get(name)
    accepted = ("ok", "outside_calibration") if target == "water_pH" else ("ok",)
    return row.get(status) in accepted and finite(v) and low <= v <= high


def minute_series(rows, end, inputs):
    """Index by minute end; demand three valid samples for each joint median."""
    groups = defaultdict(list)
    outside = set()
    for when, row in rows:
        if when >= end or row.get("context") != "water" or not all(valid(row, k) for k in inputs):
            continue
        key = when.replace(second=0, microsecond=0) + MIN
        groups[key].append([row[SENSORS[k][0]] for k in inputs])
        if "water_pH" in inputs and row.get("ph_status") == "outside_calibration":
            outside.add(key)
    return {t: dict(zip(inputs, map(statistics.median, zip(*samples))), ph_outside=t in outside)
            for t, samples in groups.items() if len(samples) >= 3}


def warn(out, name, value, future=False):
    low, high, current_alert, forecast_alert = RULES[name]
    cfg = out["thresholds"]
    if ((low and cfg.get(low) is not None and value < cfg[low])
            or (cfg.get(high) is not None and value > cfg[high])):
        out["warnings"].append(forecast_alert if future else current_alert)


def analyze(rows, now, cfg):
    config_check(cfg)
    out = dict(state="no_data", current_ph=None, current_temperature_c=None, tds_ppm=None,
               forecast=None, warnings=[], thresholds=cfg, channels={})
    if not rows:
        return out
    latest = max(rows, key=lambda r: r["received_at_utc"])
    device, boot = latest["device_id"], latest["boot_id"]
    out.update(current_ph=latest.get("ph"), current_temperature_c=latest.get("temperature_c"),
               tds_ppm=latest.get("tds_ppm"))
    age = (now - stamp(latest["received_at_utc"])).total_seconds()
    out["age_seconds"] = round(age, 1)
    if age < 0 or age > 20 or latest.get("context") != "water":
        out["state"] = "clock_error" if age < 0 else "stale" if age > 20 else "calibration"
        return out

    end = now.replace(second=0, microsecond=0)
    start = end - 31 * MIN
    history = []
    for r in rows:
        if (r["device_id"], r["boot_id"]) == (device, boot):
            t = stamp(r["received_at_utc"])
            if start <= t < end:
                history.append((t, r))
    recent = [end - i*MIN for i in range(15)]
    forecast = dict(issued_at_utc=iso(now), origin_utc=iso(end), target_utc=iso(end + 30*MIN),
                    device_id=device, boot_id=boot, ph=None, temperature_c=None, tds_ppm=None,
                    baselines={}, methods={}, outside_inputs={})
    if latest.get("ph_status") == "outside_calibration":
        out["warnings"].append("pH hiện tại nằm ngoài dải hiệu chuẩn. Số đo chỉ mang tính tham khảo.")
    for target, (name, status, low, high) in SENSORS.items():
        channel = out["channels"][name] = {"state": "sensor", "minutes": 0}
        if not valid(latest, target):
            continue
        warn(out, name, latest[name])
        try:
            bundle = load_model(target)
        except (OSError, RuntimeError, KeyError, ValueError) as err:
            channel.update(state="model", detail=str(err))
            continue
        method = bundle["candidate"]
        inputs = [target] if method in ("persistence", "mean15") else INPUTS[target]
        if not all(valid(latest, k) for k in inputs):
            channel["state"] = "inputs"
            continue
        minutes = minute_series(history, end, inputs)
        count = sum(t in minutes for t in recent)
        channel.update(state="history", minutes=count)
        if count < 15:
            continue
        if method == "persistence":
            value = minutes[end][target]
        elif method == "mean15":
            value = statistics.mean(minutes[t][target] for t in recent)
        else:
            frame = pd.DataFrame.from_dict(minutes, orient="index").sort_index()
            # The dataset labels the start of a minute in local time.
            frame.index = (frame.index - pd.Timedelta(minutes=1)).tz_convert(LOCAL).tz_localize(None)
            value = infer(target, frame[inputs])
        forecast[name] = value
        forecast["outside_inputs"][name] = any(minutes[t]["ph_outside"] for t in recent)
        forecast["baselines"][name] = minutes[end][target]
        forecast["methods"][name] = method
        channel["state"] = "ready"
        warn(out, name, value, future=True)

    out["minutes_ready"] = out["channels"]["ph"]["minutes"]
    if forecast["methods"]:
        forecast["baseline_ph"] = forecast["baselines"].get("ph")
        forecast["method"] = forecast["methods"].get("ph")
        out.update(state="ready", forecast=forecast)
    elif not valid(latest, "water_pH"):
        out["state"] = "ph_quality"
    else:
        out["state"] = "warming_up"
    return out


class Engine:
    def __init__(self, path, cfg):
        config_check(cfg)
        self.path, self.cfg, self.previous = path, cfg, {}
        with database(path) as c:
            c.execute("""CREATE TABLE IF NOT EXISTS forecasts(device TEXT, boot TEXT,
                origin TEXT, target TEXT, predicted REAL, baseline REAL, issued TEXT, actual REAL,
                PRIMARY KEY(device,boot,origin))""")
            c.execute("""CREATE TABLE IF NOT EXISTS alert_events(id INTEGER PRIMARY KEY,
                at TEXT, device TEXT, state TEXT, payload TEXT)""")
            existing = {r[1] for r in c.execute("PRAGMA table_xinfo(forecasts)")}
            for triple in COLUMNS.values():
                for col in triple:
                    if col not in existing:
                        c.execute(f"ALTER TABLE forecasts ADD COLUMN {col} REAL")
            for name, (pred, actual, _) in COLUMNS.items():
                quality = name + "_used_outside_ph"
                error = name + "_abs_error"
                if quality not in existing:
                    c.execute(f"ALTER TABLE forecasts ADD COLUMN {quality} INTEGER")
                if error not in existing:
                    c.execute(f"ALTER TABLE forecasts ADD COLUMN {error} REAL "
                              f"GENERATED ALWAYS AS (abs({pred} - {actual})) VIRTUAL")
            if "ph_actual_outside" not in existing:
                c.execute("ALTER TABLE forecasts ADD COLUMN ph_actual_outside INTEGER")

    def save(self, c, f):
        identity = (f["device_id"], f["boot_id"], f["origin_utc"])
        c.execute("""INSERT OR IGNORE INTO forecasts (device,boot,origin,target,issued)
                  VALUES (?,?,?,?,?)""", (*identity, f["target_utc"], f["issued_at_utc"]))
        for name, (pred, actual, baseline) in COLUMNS.items():
            if f[name] is not None:
                c.execute(f"""UPDATE forecasts SET {pred}=?, {baseline}=?, {name}_used_outside_ph=?
                    WHERE device=? AND boot=? AND origin=? AND {pred} IS NULL""",
                    (f[name], f["baselines"][name], f["outside_inputs"][name], *identity))

    def match(self, c, device, rows, now):
        sessions = defaultdict(list)
        for row in rows:
            sessions[row["boot_id"]].append((stamp(row["received_at_utc"]), row))
        for boot, session in sessions.items():
            for target, (name, *_) in SENSORS.items():
                pred, actual, baseline = COLUMNS[name]
                pending = c.execute(f"""SELECT origin,target FROM forecasts WHERE device=? AND boot=?
                    AND {pred} IS NOT NULL AND {actual} IS NULL AND target<=? AND target>=?""",
                    (device, boot, iso(now), iso(min(t for t, _ in session)))).fetchall()
                if not pending:
                    continue
                minutes = minute_series(session, now.replace(second=0, microsecond=0), [target])
                for origin, target_time in pending:
                    obs = minutes.get(stamp(target_time))
                    if obs:
                        if name == "ph":
                            c.execute("UPDATE forecasts SET ph_actual_outside=? WHERE device=? AND boot=? AND origin=?",
                                      (obs["ph_outside"], device, boot, origin))
                        c.execute(f"UPDATE forecasts SET {actual}=? WHERE device=? AND boot=? AND origin=?",
                                  (obs[target], device, boot, origin))

    def tick(self, now=None):
        now = now or datetime.now(timezone.utc)
        statuses, evaluation = [], {}
        with database(self.path) as c:
            for device, in c.execute("SELECT DISTINCT device FROM readings").fetchall():
                raw = c.execute("SELECT payload FROM readings WHERE device=? ORDER BY id DESC LIMIT 20000",
                                (device,)).fetchall()
                rows = [json.loads(row[0]) for row in raw]
                out = analyze(rows, now, self.cfg)
                out["device_id"] = device
                if out["forecast"]:
                    self.save(c, out["forecast"])
                self.match(c, device, rows, now)
                signature = json.dumps([out["state"], out["warnings"],
                                        {n: v["state"] for n, v in out["channels"].items()}])
                if self.previous.get(device) != signature:
                    c.execute("INSERT INTO alert_events(at,device,state,payload) VALUES(?,?,?,?)",
                              (iso(now), device, signature, json.dumps(out, allow_nan=False)))
                    self.previous[device] = signature
                statuses.append(out)
            for name, (pred, actual, baseline) in COLUMNS.items():
                result = c.execute(f"""SELECT COUNT(*), AVG(ABS({pred}-{actual})), AVG(ABS({baseline}-{actual}))
                                     FROM forecasts WHERE {pred} IS NOT NULL AND {actual} IS NOT NULL""").fetchone()
                evaluation[name] = dict(zip(("matched_count", "mae", "baseline_mae"), result))
            saved = c.execute("SELECT payload FROM alert_events ORDER BY id DESC LIMIT 20").fetchall()
        return dict(devices=statuses, evaluation={**evaluation["ph"], "channels": evaluation},
                    recent_events=[json.loads(r[0]) for r in saved])

