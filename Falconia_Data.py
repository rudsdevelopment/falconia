"""Falconia 2: streaming CSV validation, SQLite archive and local map API.
AI-assisted code; NASA/source observations are not AI-generated.
Python 3.10+, standard library only. Not a trained fire-prediction model.
"""
import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
import sqlite3
import tempfile
import time
from collections import Counter
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

VERSION = 'falconia-2.0.0'
ALIASES = {'A':'Aqua','AQUA':'Aqua','T':'Terra','TERRA':'Terra','N':'S-NPP','SNPP':'S-NPP','S-NPP':'S-NPP','N20':'NOAA-20','NOAA-20':'NOAA-20','N21':'NOAA-21','NOAA-21':'NOAA-21'}
VIIRS = {'S-NPP','NOAA-20','NOAA-21'}
FIELDS = 'latitude longitude observed_at date sensor platform confidence frp_mw type_code daynight brightness_k scan_km track_km version source source_row quality_flags raw'.split()
EPOCH = date(1970, 1, 1)
PLATFORM_CODES = {'Aqua':1, 'Terra':2, 'S-NPP':3, 'NOAA-20':4, 'NOAA-21':5}
PLATFORM_NAMES = {v:k for k, v in PLATFORM_CODES.items()}
COMPACT_FLAGS = ('instrument_platform_alias', 'confidence_series_text', 'confidence_invalid', 'confidence_unknown', 'type_invalid', 'brightness_alias_verify')
COMPACT_FLAG_BITS = {name:1 << i for i, name in enumerate(COMPACT_FLAGS)}

def dump(v):
    return json.dumps(v, ensure_ascii=False, separators=(',', ':'), allow_nan=False)

def num(v, label, low, high, optional=False):
    if v is None or str(v).strip().lower() in ('', 'nan', 'none', 'null'):
        if optional:
            return None
        raise ValueError('Missing ' + label)
    n = float(v)
    if not math.isfinite(n) or not low <= n <= high:
        raise ValueError('Invalid ' + label)
    return n

def normalize(raw, source='input', row_number=2):
    """Keep bad confidence as unknown with an explicit flag; never invent it."""
    row = {str(k).strip().lower():v for k,v in raw.items()}
    flags = []
    latitude = num(row.get('latitude', row.get('lat')), 'latitude', -90, 90)
    longitude = num(row.get('longitude', row.get('lon')), 'longitude', -180, 180)
    platform = ALIASES.get(str(row.get('satellite', row.get('platform', ''))).upper())
    if platform is None:
        raise ValueError('Unknown satellite platform')
    sensor = str(row.get('sensor', row.get('instrument', ''))).upper()
    if sensor in ALIASES and ALIASES[sensor] in VIIRS:
        if ALIASES[sensor] != platform:
            raise ValueError('Instrument alias / platform mismatch')
        sensor = 'VIIRS'
        flags.append('instrument_platform_alias')
    if not sensor:
        sensor = 'VIIRS' if platform in VIIRS else 'MODIS'
    if sensor not in ('MODIS','VIIRS') or (sensor == 'VIIRS') != (platform in VIIRS):
        raise ValueError('Sensor / platform mismatch')
    day = str(row.get('acq_date', row.get('date', '')))
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', day):
        raise ValueError('Invalid ISO date')
    date.fromisoformat(day)
    raw_time = str(row.get('acq_time', '')).strip()
    if not re.fullmatch(r'\d{1,4}(?:\.0+)?', raw_time):
        raise ValueError('Invalid UTC acquisition time')
    clock = str(int(float(raw_time))).zfill(4)
    if int(clock[:2]) > 23 or int(clock[2:]) > 59:
        raise ValueError('Invalid UTC acquisition time')
    observed_at = day+'T'+clock[:2]+':'+clock[2:]+':00.000Z'
    original_confidence = row.get('confidence')
    confidence = None
    try:
        if sensor == 'MODIS':
            confidence = num(original_confidence, 'confidence', 0, 100, True)
        else:
            c = str(original_confidence or '').strip().lower()
            confidence = {'l':'low','n':'nominal','h':'high','low':'low','nominal':'nominal','high':'high','unknown':None,'':None}[c]
    except (ValueError, TypeError, KeyError):
        flags.append('confidence_series_text' if re.search(r'\n|\\n|\.\.\.|dtype|Series', str(original_confidence)) else 'confidence_invalid')
    if confidence is None:
        flags.append('confidence_unknown')
    raw_type = row.get('type', row.get('type_code'))
    try:
        kind = num(raw_type, 'type', 0, 3, True)
        if kind is not None and not kind.is_integer():
            raise ValueError('Invalid type')
        kind = int(kind) if kind is not None else None
    except (ValueError, TypeError):
        kind = None
        flags.append('type_invalid')
    brightness = num(row.get('brightness', row.get('bright_ti4')), 'brightness', 0, 2000, True)
    if sensor == 'VIIRS' and not row.get('bright_ti4') and row.get('brightness'):
        flags.append('brightness_alias_verify')
    daynight = str(row.get('daynight', '')).upper()
    if daynight not in ('D','N',''):
        raise ValueError('Invalid daynight')
    return dict(latitude=latitude, longitude=longitude, observed_at=observed_at, date=day,
                sensor=sensor, platform=platform, confidence=confidence,
                frp_mw=num(row.get('frp', row.get('frp_mw')), 'FRP', 0, 1e7, True),
                type_code=kind, daynight=daynight, brightness_k=brightness,
                scan_km=num(row.get('scan'), 'scan', 0, 100, True),
                track_km=num(row.get('track'), 'track', 0, 100, True),
                version=str(row.get('version', 'unknown')), source=source, source_row=row_number,
                quality_flags=flags, raw=raw)

def file_hash(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()

def ingest(files, db_path):
    db_path = Path(db_path).resolve()
    if db_path.exists():
        raise ValueError('Database exists. Use a new --db filename; the original is not overwritten.')
    db_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='falconia-build-', suffix='.sqlite', dir=db_path.parent)
    os.close(fd)
    conn = sqlite3.connect(tmp)
    conn.execute('PRAGMA journal_mode=DELETE')
    conn.executescript('''
      CREATE TABLE observations (
       id INTEGER PRIMARY KEY, fingerprint TEXT UNIQUE, latitude REAL, longitude REAL,
       observed_at TEXT, date TEXT, sensor TEXT, platform TEXT, confidence TEXT,
       frp_mw REAL, type_code INTEGER, daynight TEXT, brightness_k REAL, scan_km REAL,
       track_km REAL, version TEXT, source TEXT, source_row INTEGER, quality_flags TEXT,
       raw TEXT, occurrences INTEGER NOT NULL DEFAULT 1);
      CREATE TABLE duplicate_lineage(fingerprint TEXT, source TEXT, source_row INTEGER);
      CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT);
    ''')
    counts = Counter(); flags = Counter(); rejected_examples = []; sources = []
    try:
        for filename in files:
            path = Path(filename).resolve()
            sha = file_hash(path)
            source = path.name+'#'+sha[:12]
            sources.append(dict(file_name=path.name, sha256=sha, size_bytes=path.stat().st_size))
            with path.open('r', encoding='utf-8-sig', newline='') as f:
                sample_header = f.readline(); f.seek(0)
                delimiter = ';' if sample_header.count(';') > sample_header.count(',') else ','
                reader = csv.DictReader(f, delimiter=delimiter)
                if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
                    raise ValueError('Missing or duplicate CSV headers')
                for row_number, raw in enumerate(reader, 2):
                    counts['input_rows'] += 1
                    try:
                        if None in raw or any(v is None for v in raw.values()):
                            raise ValueError('CSV column count mismatch')
                        p = normalize(raw, source, row_number)
                        # Ignore only pandas export-index artifacts in exact-source deduplication.
                        canonical = {k:v for k,v in raw.items() if not str(k).lower().startswith('unnamed:')}
                        fingerprint = hashlib.sha256(json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                        values = [dump(p[k]) if k in ('quality_flags','raw') else p[k] for k in FIELDS]
                        changed = conn.execute('INSERT OR IGNORE INTO observations(fingerprint,'+','.join(FIELDS)+') VALUES ('+','.join('?' for _ in range(len(FIELDS)+1))+')', [fingerprint]+values).rowcount
                        if changed:
                            counts['accepted_rows'] += 1
                            flags.update(p['quality_flags'])
                        else:
                            counts['exact_duplicates'] += 1
                            conn.execute('UPDATE observations SET occurrences=occurrences+1 WHERE fingerprint=?', (fingerprint,))
                            conn.execute('INSERT INTO duplicate_lineage VALUES (?,?,?)', (fingerprint, source, row_number))
                    except (ValueError, TypeError, KeyError, OverflowError) as exc:
                        counts['rejected_rows'] += 1
                        if len(rejected_examples) < 100:
                            rejected_examples.append(dict(source=source,row=row_number,error=str(exc)))
                    if counts['input_rows'] % 10000 == 0:
                        conn.commit()
                    if counts['input_rows'] % 100000 == 0:
                        print(dump(dict(progress=dict(counts))), flush=True)
        if not counts['accepted_rows']:
            raise ValueError('No valid coordinate/time/sensor records. Check the source CSV.')
        conn.executescript('CREATE INDEX obs_date ON observations(date); CREATE INDEX obs_location ON observations(longitude,latitude); CREATE INDEX obs_sensor ON observations(sensor,date);')
        audit = dict(software=VERSION,created_at=datetime.now(timezone.utc).isoformat(),counts=dict(counts),quality_flags=dict(flags),sources=sources,rejected_examples=rejected_examples,
                     coverage='unknown',mode='source_observations_only',ai_disclosure='AI-assisted pipeline; original source values retained. No predictive model trained.')
        conn.execute('INSERT INTO metadata VALUES (?,?)', ('audit',dump(audit)))
        conn.commit(); conn.close(); os.replace(tmp, db_path)
        print(dump(dict(database=str(db_path),audit=audit)), flush=True)
        return audit
    except BaseException:
        conn.close()
        Path(tmp).unlink(missing_ok=True)
        raise

def ingest_compact(files, db_path):
    """Build a compact archive: scaled integers, coded enums, no per-row raw blob.

    Provenance stays available through source SHA-256 and source_row. Exact
    duplicates are counted but their per-row lineage table is not kept, which is
    the main size trade-off against ``ingest``. Raw source text is not stored.
    """
    db_path = Path(db_path).resolve()
    if db_path.exists():
        raise ValueError('Database exists. Use a new --db filename; the original is not overwritten.')
    db_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='falconia-compact-', suffix='.sqlite', dir=db_path.parent)
    os.close(fd)
    conn = sqlite3.connect(tmp)
    conn.execute('PRAGMA page_size=16384')
    conn.execute('PRAGMA journal_mode=OFF')
    conn.execute('PRAGMA synchronous=OFF')
    conn.execute('PRAGMA cache_size=-200000')
    conn.executescript('''
      CREATE TABLE observations (
       lat INTEGER NOT NULL, lon INTEGER NOT NULL, day INTEGER NOT NULL, sec INTEGER NOT NULL,
       sensor INTEGER NOT NULL, platform INTEGER NOT NULL, confidence INTEGER,
       frp INTEGER, type_code INTEGER, daynight INTEGER NOT NULL, brightness INTEGER,
       scan INTEGER, track INTEGER, version INTEGER NOT NULL, source INTEGER NOT NULL,
       source_row INTEGER NOT NULL, flags INTEGER NOT NULL DEFAULT 0);
      CREATE TABLE dictionary (kind TEXT NOT NULL, code INTEGER NOT NULL, value TEXT NOT NULL,
       PRIMARY KEY(kind, code)) WITHOUT ROWID;
      CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT) WITHOUT ROWID;
    ''')
    counts = Counter(); flags = Counter(); rejected_examples = []; sources = []
    seen = set(); versions = {}; source_codes = {}

    def scaled(value):
        return None if value is None else int(round(value * 10))

    try:
        for filename in files:
            path = Path(filename).resolve()
            sha = file_hash(path)
            source = path.name + '#' + sha[:12]
            source_code = source_codes.setdefault(source, len(source_codes) + 1)
            sources.append(dict(file_name=path.name, sha256=sha, size_bytes=path.stat().st_size))
            with path.open('r', encoding='utf-8-sig', newline='') as f:
                sample_header = f.readline(); f.seek(0)
                delimiter = ';' if sample_header.count(';') > sample_header.count(',') else ','
                reader = csv.DictReader(f, delimiter=delimiter)
                if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
                    raise ValueError('Missing or duplicate CSV headers')
                batch = []
                for row_number, raw in enumerate(reader, 2):
                    counts['input_rows'] += 1
                    try:
                        if None in raw or any(v is None for v in raw.values()):
                            raise ValueError('CSV column count mismatch')
                        p = normalize(raw, source, row_number)
                        canonical = {k:v for k, v in raw.items() if str(k).strip() and not str(k).lower().startswith('unnamed:')}
                        digest = hashlib.blake2b(json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode(), digest_size=8).digest()
                        key = int.from_bytes(digest, 'big')
                        if key in seen:
                            counts['exact_duplicates'] += 1
                            continue
                        seen.add(key)
                        parsed = datetime.strptime(p['observed_at'], '%Y-%m-%dT%H:%M:%S.000Z')
                        day = (date.fromisoformat(p['date']) - EPOCH).days
                        sec = parsed.hour * 3600 + parsed.minute * 60 + parsed.second
                        sensor = 1 if p['sensor'] == 'MODIS' else 2
                        if p['confidence'] is None:
                            confidence = -1
                        elif sensor == 1:
                            confidence = int(round(float(p['confidence'])))
                        else:
                            confidence = {'low':1, 'nominal':2, 'high':3}.get(p['confidence'], -1)
                        version = versions.setdefault(p['version'], len(versions) + 1)
                        bitmask = 0
                        for name in p['quality_flags']:
                            bitmask |= COMPACT_FLAG_BITS.get(name, 0)
                        flags.update(p['quality_flags'])
                        batch.append((int(round(p['latitude'] * 1e6)), int(round(p['longitude'] * 1e6)),
                                      day, sec, sensor, PLATFORM_CODES[p['platform']], confidence,
                                      scaled(p['frp_mw']), p['type_code'],
                                      {'D':1, 'N':2}.get(p['daynight'], 0), scaled(p['brightness_k']),
                                      scaled(p['scan_km']), scaled(p['track_km']), version, source_code,
                                      p['source_row'], bitmask))
                        counts['accepted_rows'] += 1
                    except (ValueError, TypeError, KeyError, OverflowError) as exc:
                        counts['rejected_rows'] += 1
                        if len(rejected_examples) < 100:
                            rejected_examples.append(dict(source=source, row=row_number, error=str(exc)))
                    if len(batch) >= 50000:
                        conn.executemany('INSERT INTO observations VALUES (' + ','.join('?' for _ in range(17)) + ')', batch)
                        conn.commit(); batch.clear()
                    if counts['input_rows'] % 100000 == 0:
                        print(dump(dict(progress=dict(counts))), flush=True)
                if batch:
                    conn.executemany('INSERT INTO observations VALUES (' + ','.join('?' for _ in range(17)) + ')', batch)
                    conn.commit()
        if not counts['accepted_rows']:
            raise ValueError('No valid coordinate/time/sensor records. Check the source CSV.')
        conn.execute('CREATE INDEX obs_day ON observations(day)')
        conn.executemany('INSERT INTO dictionary VALUES (?,?,?)', [('version', code, text) for text, code in versions.items()] + [('source', code, text) for text, code in source_codes.items()])
        audit = dict(software=VERSION, created_at=datetime.now(timezone.utc).isoformat(), format='compact-v1',
                     counts=dict(counts), quality_flags=dict(flags), sources=sources, rejected_examples=rejected_examples,
                     coverage='unknown', mode='source_observations_only', raw_retained=False,
                     storage='scaled integers, coded enums, exact duplicates removed; raw text not stored',
                     ai_disclosure='AI-assisted pipeline; original source values retained. No predictive model trained.')
        conn.execute('INSERT INTO metadata VALUES (?,?)', ('format', 'compact-v1'))
        conn.execute('INSERT INTO metadata VALUES (?,?)', ('audit', dump(audit)))
        conn.execute('INSERT INTO metadata VALUES (?,?)', ('epoch', '1970-01-01'))
        conn.commit(); conn.close()
        conn = sqlite3.connect(tmp)
        conn.execute('VACUUM'); conn.commit(); conn.close()
        os.replace(tmp, db_path)
        print(dump(dict(database=str(db_path), audit=audit)), flush=True)
        return audit
    except BaseException:
        conn.close()
        Path(tmp).unlink(missing_ok=True)
        raise

class Archive:
    def __init__(self, path):
        self.path = Path(path).resolve()
        if not self.path.is_file():
            raise ValueError('Database not found; run ingest first.')

    def connect(self):
        c = sqlite3.connect(self.path.as_uri()+'?mode=ro', uri=True)
        c.row_factory = sqlite3.Row
        deadline = time.monotonic()+25
        c.set_progress_handler(lambda:int(time.monotonic()>deadline), 20000)
        return c

    @lru_cache(maxsize=1)
    def status(self):
        with closing(self.connect()) as c:
            audit = json.loads(c.execute("SELECT value FROM metadata WHERE key='audit'").fetchone()[0])
            extent = dict(c.execute('SELECT count(*) AS count,min(date) AS start,max(date) AS end,min(longitude) AS west,min(latitude) AS south,max(longitude) AS east,max(latitude) AS north FROM observations').fetchone())
        return dict(software=VERSION,audit=audit,extent=extent)

    def where(self, p):
        b = [float(x) for x in p.get('bbox','-180,-90,180,90').split(',')]
        if len(b)!=4 or not all(math.isfinite(x) for x in b) or not(-180<=b[0]<b[2]<=180 and -90<=b[1]<b[3]<=90):
            raise ValueError('Invalid bounding box; split areas crossing the date line.')
        clauses=['longitude>=?','latitude>=?','longitude<=?','latitude<=?']; args=list(b)
        for key,op in [('start','>='),('end','<=')]:
            if p.get(key):
                date.fromisoformat(p[key]);clauses.append('date'+op+'?');args.append(p[key])
        if p.get('start') and p.get('end') and p['start']>p['end']:
            raise ValueError('Start must precede end')
        for key,allowed in [('sensor',('ALL','MODIS','VIIRS')),('quality',('all','standard','high')),('type',('ALL','0','1','2','3','unknown'))]:
            if p.get(key,allowed[0]) not in allowed:
                raise ValueError('Invalid '+key)
        if p.get('sensor','ALL')!='ALL':clauses.append('sensor=?');args.append(p['sensor'])
        if p.get('type','ALL')!='ALL':
            if p['type']=='unknown':clauses.append('type_code IS NULL')
            else:clauses.append('type_code=?');args.append(int(p['type']))
        quality=p.get('quality','all')
        if quality!='all':
            threshold=80 if quality=='high' else 30
            levels="('high')" if quality=='high' else "('nominal','high')"
            clauses.append("((sensor='MODIS' AND confidence IS NOT NULL AND CAST(confidence AS REAL)>="+str(threshold)+") OR (sensor='VIIRS' AND confidence IN "+levels+"))")
        if p.get('until'):
            stamp=p['until'];datetime.strptime(stamp,'%Y-%m-%dT%H:%M:%S.000Z')
            clauses.append('observed_at<=?');args.append(stamp)
        return ' AND '.join(clauses),args,b

    @lru_cache(maxsize=24)
    def view_cached(self, key):
        p=json.loads(key);where,args,b=self.where(p)
        grid=max(.02,min(5,max((b[2]-b[0])/72,(b[3]-b[1])/36)))
        with closing(self.connect()) as c:
            # All matching observations contribute. Point display is aggregated, not sampled.
            points=[dict(r) for r in c.execute('SELECT avg(longitude) AS longitude,avg(latitude) AS latitude,count(*) AS count,sum(sensor=\'MODIS\') AS MODIS,sum(sensor=\'VIIRS\') AS VIIRS,sum(confidence IS NULL) AS unknown,MAX(date) AS latest FROM observations WHERE '+where+' GROUP BY CAST((longitude+180)/? AS INTEGER),CAST((latitude+90)/? AS INTEGER)',args+[grid,grid])]
            daily=[dict(r) for r in c.execute("SELECT date,count(*) AS count,sum(sensor='MODIS') AS MODIS,sum(sensor='VIIRS') AS VIIRS,sum(confidence IS NULL) AS unknown FROM observations WHERE "+where+' GROUP BY date ORDER BY date',args)]
        return dict(points=points,daily=daily,count=sum(x['count'] for x in daily),grid_degrees=grid,bbox=b,aggregation='geographic display cells; not equal-area harmonization',coverage='unknown',all_matching_rows=True)

    def view(self,p):return self.view_cached(dump(dict(sorted(p.items()))))

    def subset(self,p):
        where,args,b=self.where(p)
        with closing(self.connect()) as c:
            n=c.execute('SELECT count(*) FROM observations WHERE '+where,args).fetchone()[0]
            if n>100000:raise ValueError(str(n)+' matching rows; narrow the area or date range to at most 100,000 before detailed analysis.')
            out=[]
            for r in c.execute('SELECT * FROM observations WHERE '+where+' ORDER BY observed_at,id',args):
                d=dict(r);d['id']='db:'+str(d['id']);d['raw']=json.loads(d['raw']);d['quality_flags']=json.loads(d['quality_flags'])
                if d['sensor']=='MODIS':d['confidence']=float(d['confidence']) if d['confidence'] is not None else None
                elif d['confidence'] is None:d['confidence']='unknown'
                d['lineage']=[dict(source=d['source'],source_row=d['source_row'],occurrences=d['occurrences'])]
                d.pop('fingerprint');out.append(d)
        return dict(schema_version='falconia-2.0',manifest=dict(name='Local archive selection',bbox=b,coverage='unknown',selection=p,total_records=n,source_audit=self.status()['audit']),observations=out)

class CompactArchive(Archive):
    """Read-only view of the compact-v1 schema. API responses match Archive."""
    def __init__(self, path):
        self.path = Path(path).resolve()
        if not self.path.is_file():
            raise ValueError('Database not found; run ingest first.')
        with closing(self.connect()) as c:
            rows = c.execute("SELECT kind, code, value FROM dictionary").fetchall()
        self.versions = {r['code']: r['value'] for r in rows if r['kind'] == 'version'}
        self.sources = {r['code']: r['value'] for r in rows if r['kind'] == 'source'}

    @staticmethod
    def day_to_date(day):
        return (EPOCH + timedelta(days=day)).isoformat()

    @staticmethod
    def decode_time(day, sec):
        d = EPOCH + timedelta(days=day)
        return '%sT%02d:%02d:%02d.000Z' % (d.isoformat(), sec // 3600, sec % 3600 // 60, sec % 60)

    @lru_cache(maxsize=1)
    def status(self):
        with closing(self.connect()) as c:
            audit = json.loads(c.execute("SELECT value FROM metadata WHERE key='audit'").fetchone()[0])
            extent = dict(c.execute('SELECT count(*) AS count,min(day) AS start_day,max(day) AS end_day,min(lon) AS west,min(lat) AS south,max(lon) AS east,max(lat) AS north FROM observations').fetchone())
        extent['start'] = self.day_to_date(extent.pop('start_day'))
        extent['end'] = self.day_to_date(extent.pop('end_day'))
        for key in ('west', 'east'):
            extent[key] = extent[key] / 1e6
        for key in ('south', 'north'):
            extent[key] = extent[key] / 1e6
        return dict(software=VERSION, audit=audit, extent=extent)

    def where(self, p):
        b = [float(x) for x in p.get('bbox', '-180,-90,180,90').split(',')]
        if len(b) != 4 or not all(math.isfinite(x) for x in b) or not (-180 <= b[0] < b[2] <= 180 and -90 <= b[1] < b[3] <= 90):
            raise ValueError('Invalid bounding box; split areas crossing the date line.')
        clauses = ['lon>=?', 'lat>=?', 'lon<=?', 'lat<=?']
        args = [int(round(b[0] * 1e6)), int(round(b[1] * 1e6)), int(round(b[2] * 1e6)), int(round(b[3] * 1e6))]
        for key, op in [('start', '>='), ('end', '<=')]:
            if p.get(key):
                clauses.append('day' + op + '?')
                args.append((date.fromisoformat(p[key]) - EPOCH).days)
        if p.get('start') and p.get('end') and p['start'] > p['end']:
            raise ValueError('Start must precede end')
        for key, allowed in [('sensor', ('ALL', 'MODIS', 'VIIRS')), ('quality', ('all', 'standard', 'high')), ('type', ('ALL', '0', '1', '2', '3', 'unknown'))]:
            if p.get(key, allowed[0]) not in allowed:
                raise ValueError('Invalid ' + key)
        if p.get('sensor', 'ALL') != 'ALL':
            clauses.append('sensor=?'); args.append(1 if p['sensor'] == 'MODIS' else 2)
        if p.get('type', 'ALL') != 'ALL':
            if p['type'] == 'unknown':
                clauses.append('type_code IS NULL')
            else:
                clauses.append('type_code=?'); args.append(int(p['type']))
        quality = p.get('quality', 'all')
        if quality != 'all':
            threshold = 80 if quality == 'high' else 30
            levels = '(3)' if quality == 'high' else '(2,3)'
            clauses.append("((sensor=1 AND confidence IS NOT NULL AND confidence>=" + str(threshold) + ") OR (sensor=2 AND confidence IN " + levels + "))")
        if p.get('until'):
            stamp = p['until']
            dt = datetime.strptime(stamp, '%Y-%m-%dT%H:%M:%S.000Z')
            clauses.append('day*86400+sec<=?')
            args.append(int((dt - datetime(1970, 1, 1)).total_seconds()))
        return ' AND '.join(clauses), args, b

    @lru_cache(maxsize=24)
    def view_cached(self, key):
        p = json.loads(key); where, args, b = self.where(p)
        grid = max(.02, min(5, max((b[2] - b[0]) / 72, (b[3] - b[1]) / 36)))
        micro = int(round(grid * 1e6))
        with closing(self.connect()) as c:
            raw_points = c.execute('SELECT avg(lon)/1000000.0 AS longitude,avg(lat)/1000000.0 AS latitude,count(*) AS count,sum(sensor=1) AS MODIS,sum(sensor=2) AS VIIRS,sum(confidence=-1) AS unknown,MAX(day) AS latest_day FROM observations WHERE ' + where + ' GROUP BY CAST((lon+180000000)/? AS INTEGER),CAST((lat+90000000)/? AS INTEGER)', args + [micro, micro]).fetchall()
            points = []
            for r in raw_points:
                d = dict(r); d['latest'] = self.day_to_date(d.pop('latest_day')); points.append(d)
            raw_daily = c.execute("SELECT day,count(*) AS count,sum(sensor=1) AS MODIS,sum(sensor=2) AS VIIRS,sum(confidence=-1) AS unknown FROM observations WHERE " + where + ' GROUP BY day ORDER BY day', args).fetchall()
            daily = []
            for r in raw_daily:
                d = dict(r); d['date'] = self.day_to_date(d.pop('day')); daily.append(d)
        return dict(points=points, daily=daily, count=sum(x['count'] for x in daily), grid_degrees=grid, bbox=b, aggregation='geographic display cells; not equal-area harmonization', coverage='unknown', all_matching_rows=True)

    def view(self, p):
        return self.view_cached(dump(dict(sorted(p.items()))))

    def subset(self, p):
        where, args, b = self.where(p)
        with closing(self.connect()) as c:
            n = c.execute('SELECT count(*) FROM observations WHERE ' + where, args).fetchone()[0]
            if n > 100000:
                raise ValueError(str(n) + ' matching rows; narrow the area or date range to at most 100,000 before detailed analysis.')
            out = []
            for r in c.execute('SELECT rowid AS rid,* FROM observations WHERE ' + where + ' ORDER BY day*86400+sec,rowid', args):
                d = dict(r); rid = d.pop('rid')
                sensor = 'MODIS' if d['sensor'] == 1 else 'VIIRS'
                if sensor == 'MODIS':
                    confidence = None if d['confidence'] in (None, -1) else float(d['confidence'])
                else:
                    confidence = {1:'low', 2:'nominal', 3:'high'}.get(d['confidence'], 'unknown')
                day = self.day_to_date(d['day'])
                observed_at = self.decode_time(d['day'], d['sec'])
                version = self.versions[d['version']]
                source = self.sources[d['source']]
                quality_flags = [name for name in COMPACT_FLAGS if d['flags'] & COMPACT_FLAG_BITS[name]]
                frp = None if d['frp'] is None else d['frp'] / 10
                bright = None if d['brightness'] is None else d['brightness'] / 10
                scan = None if d['scan'] is None else d['scan'] / 10
                track = None if d['track'] is None else d['track'] / 10
                daynight = {1:'D', 2:'N'}.get(d['daynight'], '')
                platform = PLATFORM_NAMES[d['platform']]
                raw = dict(latitude=d['lat'] / 1e6, longitude=d['lon'] / 1e6, acq_date=day,
                           acq_time=int(d['sec'] // 3600) * 100 + int(d['sec'] % 3600 // 60),
                           satellite=platform, instrument=sensor,
                           confidence=confidence, version=version, frp=frp, brightness=bright,
                           scan=scan, track=track, daynight=daynight, type=d['type_code'])
                out.append(dict(id='db:' + str(rid), latitude=d['lat'] / 1e6, longitude=d['lon'] / 1e6,
                                observed_at=observed_at, date=day, sensor=sensor, platform=PLATFORM_NAMES[d['platform']],
                                confidence=confidence, frp_mw=frp, type_code=d['type_code'], daynight=daynight,
                                brightness_k=bright, scan_km=scan, track_km=track, version=version, source=source,
                                source_row=d['source_row'], quality_flags=quality_flags, raw=raw,
                                occurrences=1, lineage=[dict(source=source, source_row=d['source_row'], occurrences=1)]))
        return dict(schema_version='falconia-2.0', manifest=dict(name='Local archive selection', bbox=b, coverage='unknown', selection=p, total_records=n, source_audit=self.status()['audit']), observations=out)

def open_archive(db_path):
    path = Path(db_path).resolve()
    if not path.is_file():
        raise ValueError('Database not found; run ingest first.')
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as c:
        row = c.execute("SELECT value FROM metadata WHERE key='format'").fetchone()
    fmt = row[0] if row else 'raw-v1'
    return CompactArchive(path) if fmt == 'compact-v1' else Archive(path)

def serve(db_path, port, root):
    archive=open_archive(db_path);archive.status();root=Path(root).resolve()
    class Handler(BaseHTTPRequestHandler):
        def reply(self,status,payload,content_type='application/json; charset=utf-8'):
            data=payload if isinstance(payload,bytes) else dump(payload).encode('utf-8')
            self.send_response(status);self.send_header('Content-Type',content_type)
            origin=self.headers.get('Origin','')
            if origin=='null' or re.fullmatch(r'http://(?:localhost|127\.0\.0\.1)(?::\d+)?',origin):self.send_header('Access-Control-Allow-Origin',origin)
            self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        def do_GET(self):
            try:
                u=urlparse(self.path);p={k:v[-1] for k,v in parse_qs(u.query).items()}
                if u.path=='/api/status':self.reply(200,archive.status())
                elif u.path=='/api/view':self.reply(200,archive.view(p))
                elif u.path=='/api/observations':self.reply(200,archive.subset(p))
                elif u.path in ('/','/Falconia_Template.html'):
                    self.reply(200,(root/'Falconia_Template.html').read_bytes(),'text/html; charset=utf-8')
                else:self.reply(404,dict(error='Not found'))
            except (ValueError,KeyError) as exc:self.reply(400,dict(error=str(exc)))
            except sqlite3.OperationalError:self.reply(503,dict(error='Query could not finish within the local resource/time limit. Narrow the area or period.'))
            except (BrokenPipeError,ConnectionResetError):pass
            except FileNotFoundError:self.reply(404,dict(error='Keep Falconia_Template.html next to this script.'))
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    print('Falconia local preview: http://127.0.0.1:'+str(port),flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()

def main():
    csv.field_size_limit(20*1024*1024)
    parser=argparse.ArgumentParser(description=__doc__)
    subs=parser.add_subparsers(dest='command',required=True)
    imp=subs.add_parser('ingest');imp.add_argument('csv',nargs='+');imp.add_argument('--db',default='falconia.sqlite');imp.add_argument('--compact',action='store_true',help='Store scaled integers and coded enums instead of per-row raw JSON')
    web=subs.add_parser('serve');web.add_argument('--db',default='falconia.sqlite');web.add_argument('--port',type=int,default=8765);web.add_argument('--root',default=str(Path(__file__).parent))
    args=parser.parse_args()
    try:
        if args.command=='ingest':ingest_compact(args.csv,args.db) if args.compact else ingest(args.csv,args.db)
        else:serve(args.db,args.port,args.root)
    except (ValueError,OSError,sqlite3.Error) as exc:parser.exit(1,str(exc)+'\n')

if __name__=='__main__':main()
