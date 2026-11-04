#!/usr/bin/env python3
import csv
import io
import json
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parent
INDEX = (ROOT / 'index.html').read_text(encoding='utf-8')
PORT = int(os.environ.get('PORT', '8000'))
DATA_DIR = Path(os.environ.get('DATA_DIR', str(ROOT / 'data')))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / 'preference.sqlite3'
ADMIN_TOKEN = os.environ.get('ADMIN_TOKEN', '')
MAX_BODY = 2_000_000


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def db_connect():
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.execute('PRAGMA journal_mode=WAL')
    con.execute('''CREATE TABLE IF NOT EXISTS submissions (
        participant_id TEXT PRIMARY KEY,
        prolific_pid TEXT,
        study_id TEXT,
        session_id TEXT,
        status TEXT NOT NULL,
        started TEXT,
        finished TEXT,
        updated_at TEXT NOT NULL,
        data_json TEXT NOT NULL
    )''')
    return con


def upsert(payload):
    if not isinstance(payload, dict):
        raise ValueError('object required')
    pid = str(payload.get('participant_id') or '').strip()
    if not pid:
        raise ValueError('participant_id is required')
    if not isinstance(payload.get('trials'), list) or not payload.get('consent_given'):
        raise ValueError('consented trial data required')
    status = str(payload.get('status') or 'in_progress')
    if status not in ('in_progress', 'complete', 'screened_out'):
        raise ValueError('invalid status')
    if status == 'complete' and (valid_prediction_count(payload) != 150 or not payload.get('finished')):
        raise ValueError('incomplete experiment')
    row = (
        pid,
        str(payload.get('prolific_pid') or ''),
        str(payload.get('study_id') or ''),
        str(payload.get('session_id') or ''),
        status,
        str(payload.get('started') or ''),
        str(payload.get('finished') or ''),
        now_iso(),
        json.dumps(payload, ensure_ascii=False, separators=(',', ':')),
    )
    with db_connect() as con:
        con.execute('''INSERT INTO submissions
            (participant_id, prolific_pid, study_id, session_id, status, started, finished, updated_at, data_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(participant_id) DO UPDATE SET
              prolific_pid=excluded.prolific_pid,
              study_id=excluded.study_id,
              session_id=excluded.session_id,
              status=excluded.status,
              started=excluded.started,
              finished=excluded.finished,
              updated_at=excluded.updated_at,
              data_json=excluded.data_json
              WHERE submissions.status='in_progress'
                OR excluded.status != 'in_progress'
              ''', row)


def get_payload(participant_id):
    with db_connect() as con:
        row = con.execute("SELECT data_json FROM submissions WHERE participant_id=?", (participant_id,)).fetchone()
    return json.loads(row[0]) if row else None



def valid_prediction_count(data):
    return sum(t.get('block_type') in ('pairwise', 'bdm', 'instructed') and
               isinstance(t.get('response'), (int, float)) and
               (t['response'] in (0, 1) if t['block_type'] != 'bdm' else -5 <= t['response'] <= 5)
               for t in data.get('trials', []) if isinstance(t, dict))


def all_payloads():
    with db_connect() as con:
        rows = con.execute('SELECT data_json FROM submissions ORDER BY updated_at').fetchall()
    return [json.loads(r[0]) for r in rows]


def summary_rows(payloads):
    keys = ['participant_id', 'prolific_pid', 'study_id', 'session_id', 'status',
            'consent_given', 'consent_timestamp', 'started', 'finished', 'first_block',
            'cc1_fails', 'cc2_fails', 'won_bonus', 'bonus_amount', 'endowment', 'total_bonus']
    return [dict({k: p.get(k, '') for k in keys},
                 decisions_completed=valid_prediction_count(p)) for p in payloads]


def submission_list():
    return summary_rows(all_payloads())


def trial_rows(payloads):
    out = []
    for p in payloads:
        for t in p.get('trials', []):
            if t.get('block_type'):
                row = {k: v for k, v in t.items() if k != 'stimulus'}
                row.update(summary_rows([p])[0])
                if t.get('block_type') in ('pairwise', 'instructed'):
                    row['response_label'] = {0: 'Lottery 1', 1: 'Lottery 2'}.get(t.get('response'), '')
                row['rt_sec'] = t['rt'] / 1000 if isinstance(t.get('rt'), (int, float)) else ''
                out.append(row)
    return out


def csv_bytes(rows):
    if not rows: return b''
    fields=[]
    for r in rows:
        for k in r:
            if k not in fields: fields.append(k)
    s=io.StringIO(); w=csv.DictWriter(s, fieldnames=fields); w.writeheader(); w.writerows(rows)
    return s.getvalue().encode('utf-8-sig')


def authorized(query):
    if not ADMIN_TOKEN: return False
    supplied=(query.get('token') or [''])[0]
    return secrets.compare_digest(supplied, ADMIN_TOKEN)


class Handler(BaseHTTPRequestHandler):
    server_version='PreferencePilot/1.0'

    def log_message(self, fmt, *args):
        pass  # Avoid logging participant IDs or admin tokens in URL query strings.

    def send_bytes(self, body, content_type='text/plain; charset=utf-8', status=200, extra=None):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Referrer-Policy','no-referrer')
        if extra:
            for k,v in extra.items(): self.send_header(k,v)
        self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        u=urlparse(self.path); q=parse_qs(u.query)
        if u.path in ('/','/index.html'):
            body=INDEX.encode('utf-8')
            return self.send_bytes(body,'text/html; charset=utf-8')
        if u.path=='/researcher':
            if not authorized(q): return self.send_bytes(b'Forbidden',status=403)
            token=(q.get('token') or [''])[0]
            rows=submission_list()
            esc=lambda x: str(x).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('\"','&quot;')
            trs=''.join(
                '<tr>'+''.join(f'<td>{esc(r.get(k,""))}</td>' for k in ['participant_id','prolific_pid','study_id','session_id','status','consent_given','decisions_completed','cc1_fails','cc2_fails','total_bonus','won_bonus','updated_at'])+'</tr>'
                for r in rows
            ) or '<tr><td colspan=11>No submissions saved yet.</td></tr>'
            html=f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Preference Elicitation Researcher Dashboard</title>
            <style>body{{font-family:system-ui,-apple-system,sans-serif;margin:30px;color:#1f2937}}a{{color:#1455c0}}table{{border-collapse:collapse;width:100%;font-size:12px;margin-top:20px}}th,td{{border:1px solid #d1d5db;padding:6px;vertical-align:top}}th{{background:#f3f4f6;position:sticky;top:0}}.links a{{margin-right:18px}}code{{background:#f3f4f6;padding:2px 4px}}</style></head><body>
            <h1>Preference Elicitation researcher dashboard</h1><p>This page reads the <strong>server database</strong>. Opening it does not create a participant record.</p>
            <div class="links"><a href="/admin/export/summary.csv?token={token}">Download summary CSV</a><a href="/admin/export/trials.csv?token={token}">Download trials CSV</a><a href="/admin/export/raw.json?token={token}">Download raw JSON</a></div>
            <p>Saved submissions: <strong>{len(rows)}</strong></p>
            <table><thead><tr>{''.join(f'<th>{h}</th>' for h in ['participant_id','prolific_pid','study_id','session_id','status','consent','decisions','check 1 failures','check 2 failures','total bonus','bonus won','updated'])}</tr></thead><tbody>{trs}</tbody></table>
            </body></html>'''
            return self.send_bytes(html.encode('utf-8'),'text/html; charset=utf-8')
        if u.path=='/api/verify':
            pid=(q.get('participant_id') or [''])[0]
            p=get_payload(pid) if pid else None
            if not p: return self.send_bytes(b'{"ok":false,"error":"not_found"}','application/json; charset=utf-8',status=404)
            body=json.dumps({'ok':True,'participant_id':pid,'prolific_pid':p.get('prolific_pid',''),'study_id':p.get('study_id',''),'session_id':p.get('session_id',''),'status':p.get('status',''),'decisions_completed':valid_prediction_count(p),'finished':p.get('finished') or ''},separators=(',',':')).encode('utf-8')
            return self.send_bytes(body,'application/json; charset=utf-8')
        if u.path == '/config.js':
            config = {k: os.environ.get(k, '') for k in ('SUCCESS_CODE', 'SCREENOUT_CODE')}
            return self.send_bytes(('window.PILOT_CONFIG=' + json.dumps(config) + ';').encode(), 'application/javascript')
        if u.path=='/healthz':
            return self.send_bytes(b'ok')
        if u.path.startswith('/admin/export/'):
            if not authorized(q): return self.send_bytes(b'Forbidden',status=403)
            ps=all_payloads()
            if u.path.endswith('/summary.csv'):
                body=csv_bytes(summary_rows(ps)); name='preference_summary.csv'
            elif u.path.endswith('/trials.csv'):
                body=csv_bytes(trial_rows(ps)); name='preference_trials.csv'
            elif u.path.endswith('/raw.json'):
                body=json.dumps(ps,ensure_ascii=False,indent=2).encode('utf-8'); name='preference_raw.json'
                return self.send_bytes(body,'application/json; charset=utf-8',extra={'Content-Disposition':f'attachment; filename="{name}"'})
            else: return self.send_bytes(b'Not found',status=404)
            return self.send_bytes(body,'text/csv; charset=utf-8',extra={'Content-Disposition':f'attachment; filename="{name}"'})
        return self.send_bytes(b'Not found',status=404)

    def do_POST(self):
        u=urlparse(self.path)
        if u.path!='/api/save': return self.send_bytes(b'Not found',status=404)
        try:
            n=int(self.headers.get('Content-Length','0'))
            if n<=0 or n>MAX_BODY: raise ValueError('invalid body size')
            payload=json.loads(self.rfile.read(n).decode('utf-8'))
            upsert(payload)
            reply={'ok':True,'participant_id':payload.get('participant_id',''),'prolific_pid':payload.get('prolific_pid',''),'study_id':payload.get('study_id',''),'session_id':payload.get('session_id',''),'status':payload.get('status',''),'decisions_completed':valid_prediction_count(payload)}
            return self.send_bytes(json.dumps(reply,separators=(',',':')).encode('utf-8'),'application/json; charset=utf-8')
        except Exception as e:
            print('SAVE ERROR:',repr(e),flush=True)
            return self.send_bytes(b'{"ok":false}','application/json; charset=utf-8',status=400)


if __name__=='__main__':
    db_connect().close()
    print(f'Data: {DB_PATH}', flush=True)
    ThreadingHTTPServer(('0.0.0.0', PORT), Handler).serve_forever()
