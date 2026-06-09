import os
import ssl
from datetime import date, datetime
from functools import wraps
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

from flask import Flask, jsonify, redirect, render_template_string, request, session, url_for
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'troque-esta-chave-em-producao')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB

APP_PASSWORD = os.environ.get('APP_PASSWORD', 'paraty2026')

# ── Conexão com banco ─────────────────────────────────────────────────────────

engine = None
_engine_error = ''

try:
    # Strip aspas acidentais que podem vir do Vercel
    _raw = os.environ.get('DATABASE_URL', '').strip().strip("'\"")
    if _raw:
        if _raw.startswith('postgres://'):
            _raw = 'postgresql+pg8000://' + _raw[len('postgres://'):]
        elif _raw.startswith('postgresql://'):
            _raw = 'postgresql+pg8000://' + _raw[len('postgresql://'):]

        # Remove parâmetros que pg8000 não entende
        _p = urlparse(_raw)
        _qs = {k: v for k, v in parse_qs(_p.query, keep_blank_values=True).items()
               if k not in ('sslmode', 'channel_binding', 'options')}
        _clean = urlunparse(_p._replace(query=urlencode({k: v[0] for k, v in _qs.items()})))

        _ssl_ctx = ssl.create_default_context()
        _ssl_ctx.check_hostname = False
        _ssl_ctx.verify_mode   = ssl.CERT_NONE

        engine = create_engine(_clean, poolclass=NullPool,
                                connect_args={'ssl_context': _ssl_ctx})
except Exception as _e:
    _engine_error = str(_e)
    print(f'[ENGINE] {_e}')

_db_ready = False


# ── Banco de dados ────────────────────────────────────────────────────────────

def ensure_db():
    global _db_ready
    if _db_ready or not engine:
        return
    try:
        with engine.connect() as conn:
            conn.execute(text('''
                CREATE TABLE IF NOT EXISTS titulos (
                    id         SERIAL PRIMARY KEY,
                    nome       TEXT    NOT NULL,
                    venc       DATE    NOT NULL,
                    nota       TEXT    DEFAULT '',
                    valor      NUMERIC(12,2) NOT NULL,
                    titulo_key TEXT    UNIQUE NOT NULL,
                    filial     TEXT    NOT NULL DEFAULT 'Portal GPN'
                )'''))
            conn.execute(text(
                "ALTER TABLE titulos ADD COLUMN IF NOT EXISTS filial TEXT NOT NULL DEFAULT 'Portal GPN'"
            ))
            conn.execute(text('''
                CREATE TABLE IF NOT EXISTS observacoes (
                    id         SERIAL PRIMARY KEY,
                    titulo_key TEXT    NOT NULL UNIQUE,
                    obs_text   TEXT    NOT NULL,
                    updated_at TIMESTAMP DEFAULT NOW()
                )'''))
            conn.execute(text('''
                CREATE TABLE IF NOT EXISTS meta (
                    key   TEXT PRIMARY KEY,
                    value TEXT
                )'''))
            conn.commit()
        _db_ready = True
    except Exception as e:
        print(f'[DB] {e}')


# ── Autenticação ──────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


# ── Templates embutidos ───────────────────────────────────────────────────────

_LOGIN_TMPL = '''<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Login — Portal GPN</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Inter',sans-serif;background:#0A1E38;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}
.card{background:#fff;border-radius:20px;padding:48px 40px;width:100%;max-width:400px;box-shadow:0 24px 64px rgba(0,0,0,.45)}
.eyebrow{font-family:'DM Mono',monospace;font-size:10px;letter-spacing:.18em;text-transform:uppercase;color:#7A9ABF;margin-bottom:12px}
.title{font-size:30px;font-weight:300;color:#0A1E38;letter-spacing:-.02em;margin-bottom:4px}
.title strong{font-weight:600}
.subtitle{font-size:13px;color:#A0B4C8;margin-bottom:36px}
.label{display:block;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.1em;color:#4A7AAF;margin-bottom:8px}
.input{width:100%;padding:13px 16px;border:1.5px solid #D4E2F0;border-radius:10px;font-family:'Inter',sans-serif;font-size:15px;color:#0A1E38;outline:none;transition:border-color .15s}
.input:focus{border-color:#1A5FAA}
.btn{width:100%;margin-top:20px;padding:14px;background:#1A5FAA;color:#fff;border:none;border-radius:10px;font-family:'Inter',sans-serif;font-size:15px;font-weight:600;cursor:pointer;transition:background .15s}
.btn:hover{background:#1350A0}
.error{margin-top:16px;padding:11px 14px;background:#FDECEA;border-radius:8px;color:#B71C1C;font-size:13px;text-align:center;border:1px solid #FFCDD2}
</style>
</head>
<body>
<div class="card">
  <div class="eyebrow">Portal GPN · R.A.I.S. Náutica</div>
  <h1 class="title"><strong>Inadimplentes</strong></h1>
  <p class="subtitle">Acesso restrito — uso interno</p>
  <form method="POST" autocomplete="on">
    <label class="label" for="pwd">Senha de acesso</label>
    <input class="input" type="password" id="pwd" name="password"
           placeholder="••••••••" autocomplete="current-password" required autofocus>
    <button class="btn" type="submit">Entrar</button>
    {% if error %}<div class="error">{{ error }}</div>{% endif %}
  </form>
</div>
</body>
</html>'''

_UPLOAD_TMPL = '''<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Atualizar Dados — Portal GPN</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Inter',sans-serif;background:#F4F7FB;color:#0F1E35;min-height:100vh}
.shell{max-width:640px;margin:0 auto;padding:56px 40px 80px}
.back{font-size:13px;color:#7A9ABF;text-decoration:none;display:inline-flex;align-items:center;gap:6px;margin-bottom:32px;transition:color .15s}
.back:hover{color:#1A5FAA}
.header-eyebrow{font-family:'DM Mono',monospace;font-size:10px;letter-spacing:.18em;text-transform:uppercase;color:#4A7AAF;margin-bottom:10px}
.title{font-size:30px;font-weight:300;color:#0A1E38;letter-spacing:-.02em;margin-bottom:28px}
.title strong{font-weight:600}
.card{background:#fff;border:1px solid #D4E2F0;border-radius:16px;padding:32px}
.label{display:block;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.1em;color:#4A7AAF;margin-bottom:12px}
.drop-area{border:2px dashed #C8DAF0;border-radius:12px;padding:44px 24px;text-align:center;cursor:pointer;transition:all .2s;background:#F8FAFD}
.drop-area:hover,.drop-area.dragover{border-color:#1A5FAA;background:#EBF3FB}
.drop-icon{font-size:38px;margin-bottom:12px}
.drop-text{font-size:14px;color:#4A7AAF;font-weight:500;margin-bottom:6px}
.drop-hint{font-size:12px;color:#A0B4C8}
.file-name{margin-top:12px;font-family:'DM Mono',monospace;font-size:12px;color:#1A5FAA;min-height:18px}
input[type="file"]{display:none}
.btn{width:100%;margin-top:20px;padding:14px;background:#1A5FAA;color:#fff;border:none;border-radius:10px;font-family:'Inter',sans-serif;font-size:15px;font-weight:600;cursor:pointer;transition:background .15s}
.btn:hover:not(:disabled){background:#1350A0}
.btn:disabled{background:#C8DAF0;color:#EBF3FB;cursor:not-allowed}
.msg-ok{margin-top:20px;padding:14px 16px;background:#E8F5E9;border:1px solid #A5D6A7;border-radius:10px;color:#1B5E20;font-size:14px;font-weight:500}
.msg-err{margin-top:20px;padding:14px 16px;background:#FDECEA;border:1px solid #FFCDD2;border-radius:10px;color:#B71C1C;font-size:14px}
.rules{margin-top:28px;padding-top:24px;border-top:1px solid #EEF4FB}
.rules-title{font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.12em;color:#7A9ABF;margin-bottom:10px}
.rules ul{list-style:none}
.rules li{font-size:13px;color:#4A7AAF;line-height:1.9;padding-left:14px;position:relative}
.rules li::before{content:'·';position:absolute;left:0;color:#A0B4C8}
@media(max-width:600px){.shell{padding:32px 16px 60px}}
</style>
</head>
<body>
<div class="shell">
  <a class="back" href="/dashboard">← Voltar ao dashboard</a>
  <div class="header-eyebrow">Portal GPN · R.A.I.S. Náutica</div>
  <h1 class="title"><strong>Atualizar</strong> dados</h1>
  <div class="card">
    <label class="label">Planilha de inadimplentes (.XLS)</label>
    <form method="POST" enctype="multipart/form-data" id="form-upload">
      <label class="label">Filial / Portal</label>
      <input class="input" type="text" name="filial" id="filial-input"
             placeholder="Ex: Portal GPN" required autocomplete="off"
             style="margin-bottom:20px" list="filial-list">
      <datalist id="filial-list"><option value="Portal GPN"></datalist>
      <div class="drop-area" id="drop-area">
        <div class="drop-icon">📂</div>
        <div class="drop-text">Clique para selecionar ou arraste o arquivo</div>
        <div class="drop-hint">Apenas arquivos .XLS exportados do IdealSoft · Shop Control 9</div>
        <div class="file-name" id="file-name"></div>
      </div>
      <input type="file" id="file-input" name="file" accept=".xls">
      <button class="btn" type="submit" id="btn-submit" disabled>Importar dados</button>
    </form>
    {% if message %}<div class="msg-ok">✓ {{ message }}</div>{% endif %}
    {% if error %}<div class="msg-err">⚠ {{ error }}</div>{% endif %}
    <div class="rules">
      <div class="rules-title">Lembrete de exportação</div>
      <ul>
        <li>Relatório: <strong>Recebíveis em Aberto por Vencimento</strong></li>
        <li>Formato <strong>.XLS</strong> — nunca converter para .XLSX</li>
        <li>Portal: <strong>Portal GPN</strong></li>
        <li>As observações salvas <strong>não são apagadas</strong> na importação</li>
      </ul>
    </div>
  </div>
</div>
<script>
const fileInput=document.getElementById('file-input');
const fileName=document.getElementById('file-name');
const btnSubmit=document.getElementById('btn-submit');
const dropArea=document.getElementById('drop-area');
dropArea.addEventListener('click',()=>fileInput.click());
fileInput.addEventListener('change',function(){
  if(this.files[0]){fileName.textContent='📄 '+this.files[0].name;btnSubmit.disabled=false;}
});
dropArea.addEventListener('dragover',e=>{e.preventDefault();dropArea.classList.add('dragover');});
dropArea.addEventListener('dragleave',()=>dropArea.classList.remove('dragover'));
dropArea.addEventListener('drop',e=>{
  e.preventDefault();dropArea.classList.remove('dragover');
  const f=e.dataTransfer.files[0];
  if(f){const dt=new DataTransfer();dt.items.add(f);fileInput.files=dt.files;
    fileName.textContent='📄 '+f.name;btnSubmit.disabled=false;}
});
</script>
</body>
</html>'''

_DASHBOARD_TMPL = '''<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Inadimplentes — Portal GPN</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Inter',sans-serif;background:#F4F7FB;color:#0F1E35;min-height:100vh}
.shell{max-width:1360px;margin:0 auto;padding:44px 40px 80px}
.header{margin-bottom:32px;border-bottom:1px solid #D4E2F0;padding-bottom:22px;display:flex;align-items:flex-end;justify-content:space-between;gap:16px}
.header-eyebrow{font-family:'DM Mono',monospace;font-size:10px;letter-spacing:.18em;text-transform:uppercase;color:#4A7AAF;margin-bottom:10px}
.header-title{font-size:34px;font-weight:300;color:#0A1E38;letter-spacing:-.02em;line-height:1.1;margin-bottom:5px}
.header-title strong{font-weight:600}
.header-meta{font-size:12px;color:#7A9ABF}
.header-nav{display:flex;align-items:center;gap:8px;flex-shrink:0}
.nav-btn{font-family:'Inter',sans-serif;font-size:12px;padding:7px 16px;border-radius:8px;text-decoration:none;cursor:pointer;transition:all .15s;white-space:nowrap;border:1px solid}
.nav-update{background:#1A5FAA;color:#fff;border-color:#1A5FAA}
.nav-update:hover{background:#1350A0;border-color:#1350A0}
.nav-logout{background:transparent;color:#7A9ABF;border-color:#D4E2F0}
.nav-logout:hover{color:#0A1E38;border-color:#7A9ABF}
.ano-row{display:flex;align-items:center;gap:8px;margin-bottom:32px;flex-wrap:wrap}
.ano-label{font-family:'DM Mono',monospace;font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:#7A9ABF;margin-right:4px}
.ano-btn{font-family:'Inter',sans-serif;font-size:12px;padding:5px 16px;border-radius:99px;border:1px solid #C8DAF0;background:transparent;color:#4A7AAF;cursor:pointer;transition:all .15s}
.ano-btn:hover{border-color:#1A5FAA;color:#1A5FAA;background:#EBF3FB}
.ano-btn.active{background:#1A5FAA;border-color:#1A5FAA;color:#fff;font-weight:500}
.kpi-row{display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px;margin-bottom:36px}
.kpi{background:#fff;border:1px solid #D4E2F0;border-radius:14px;padding:24px 28px;position:relative;overflow:hidden;transition:box-shadow .2s}
.kpi:hover{box-shadow:0 2px 12px rgba(26,95,170,.08)}
.kpi::after{content:'';position:absolute;bottom:0;left:0;right:0;height:3px;background:linear-gradient(90deg,#1A5FAA,#2E8BC0)}
.kpi-label{font-size:10px;font-weight:500;text-transform:uppercase;letter-spacing:.1em;color:#7A9ABF;margin-bottom:10px}
.kpi-value{font-family:'DM Mono',monospace;font-size:28px;font-weight:400;color:#1A5FAA;line-height:1;margin-bottom:6px}
.kpi-hint{font-size:12px;color:#7A9ABF}
.table-meta{display:flex;align-items:center;margin-bottom:10px;gap:10px;flex-wrap:wrap}
.table-meta-title{font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.12em;color:#4A7AAF;white-space:nowrap}
.table-meta-count{font-family:'DM Mono',monospace;font-size:11px;color:#7A9ABF;white-space:nowrap;margin-left:auto}
.search-wrap{flex:1;min-width:140px;max-width:260px}
.search-input{width:100%;padding:7px 12px;border:1.5px solid #D4E2F0;border-radius:8px;font-family:'Inter',sans-serif;font-size:13px;color:#0F1E35;outline:none;transition:border-color .15s;background:#fff}
.search-input:focus{border-color:#1A5FAA}
.search-input::placeholder{color:#B0C4D8}
.table-wrap{background:#fff;border:1px solid #D4E2F0;border-radius:14px;overflow-x:auto;-webkit-overflow-scrolling:touch}
table{width:100%;border-collapse:collapse;min-width:640px}
thead tr{background:#EBF3FB;border-bottom:1px solid #D4E2F0}
thead th{padding:11px 12px;font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.1em;color:#4A7AAF;text-align:left;white-space:nowrap}
thead th.right{text-align:right}
thead th.cb-col{width:44px;text-align:center}
tbody tr{border-bottom:1px solid #EEF4FB;transition:background .1s}
tbody tr:last-child{border-bottom:none}
tbody tr:hover{background:#F4F9FF}
tbody tr.row-selected{background:#EBF3FB !important}
tbody td{padding:11px 12px;font-size:13px;color:#3A5A7A;vertical-align:middle;white-space:nowrap}
tbody td.right{text-align:right}
tbody td.cb-col{text-align:center}
tbody td.obs-col{white-space:normal}
.td-nome{color:#0A1E38;font-weight:500;white-space:normal}
.td-date{font-family:'DM Mono',monospace;font-size:12px;color:#4A7AAF}
.td-nota{font-family:'DM Mono',monospace;font-size:12px;color:#4A7AAF}
.td-nota-none{color:#C8DAF0}
.td-val{font-family:'DM Mono',monospace;font-size:13px;color:#1A5FAA;font-weight:500}
.badge{display:inline-block;font-family:'DM Mono',monospace;font-size:11px;font-weight:500;padding:3px 10px;border-radius:99px;white-space:nowrap}
.b-crit{background:#FDECEA;color:#B71C1C}
.b-high{background:#FFF3E0;color:#BF5B00}
.b-mid{background:#FFFDE7;color:#8A6500}
.b-low{background:#E8F5E9;color:#1B5E20}
.b-zero{background:#F1F8E9;color:#33691E}
.c-urgente{display:inline-block;font-family:'DM Mono',monospace;font-size:11px;font-weight:600;padding:3px 10px;border-radius:99px;white-space:nowrap;background:#FDECEA;color:#B71C1C;border:1px solid #FFCDD2}
.c-protestar{display:inline-block;font-family:'DM Mono',monospace;font-size:11px;font-weight:600;padding:3px 10px;border-radius:99px;white-space:nowrap;background:#FFF3E0;color:#BF5B00;border:1px solid #FFE0B2}
.c-cartorio{display:inline-block;font-family:'DM Mono',monospace;font-size:11px;font-weight:600;padding:3px 10px;border-radius:99px;white-space:nowrap;background:#E3F2FD;color:#1565C0;border:1px solid #90CAF9}
.cb-input{width:16px;height:16px;cursor:pointer;accent-color:#1A5FAA}
.obs-trigger{display:inline-flex;align-items:center;gap:5px;font-size:12px;border-radius:6px;padding:4px 9px;cursor:pointer;transition:all .15s;max-width:200px;white-space:normal;line-height:1.3;border:1px solid transparent}
.obs-empty{color:#B0C4D8;border:1px dashed #D4E2F0;background:transparent;font-style:italic}
.obs-empty:hover{color:#4A7AAF;border-color:#7A9ABF;background:#F4F9FF}
.obs-auth{background:#E8F5E9;color:#1B5E20;border-color:#A5D6A7}
.obs-hold{background:#FFF3E0;color:#BF5B00;border-color:#FFCC80}
.obs-sent{background:#E3F2FD;color:#1565C0;border-color:#90CAF9}
.obs-note{background:#F3E8FF;color:#5B21B6;border-color:#C4B5FD}
.obs-auth:hover,.obs-hold:hover,.obs-sent:hover,.obs-note:hover{filter:brightness(.95)}
.obs-text{overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;word-break:break-word}
.obs-editor{position:fixed;width:310px;max-width:calc(100vw - 24px);background:#fff;border:1px solid #D4E2F0;border-radius:14px;box-shadow:0 8px 40px rgba(10,30,56,.18);padding:16px;z-index:999;display:none}
.obs-editor-title{font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.12em;color:#7A9ABF;margin-bottom:12px}
.obs-chips{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px}
.obs-chip{font-size:11px;padding:4px 10px;border-radius:99px;cursor:pointer;font-family:'Inter',sans-serif;transition:all .12s;border:1px solid;background:transparent}
.obs-chip-auth{border-color:#A5D6A7;color:#1B5E20}.obs-chip-auth:hover{background:#E8F5E9}
.obs-chip-hold{border-color:#FFCC80;color:#BF5B00}.obs-chip-hold:hover{background:#FFF3E0}
.obs-chip-sent{border-color:#90CAF9;color:#1565C0}.obs-chip-sent:hover{background:#E3F2FD}
.obs-ta{width:100%;min-height:82px;padding:9px 11px;border:1px solid #D4E2F0;border-radius:8px;font-family:'Inter',sans-serif;font-size:13px;color:#0F1E35;resize:vertical;outline:none;margin-bottom:10px;transition:border-color .15s;line-height:1.5}
.obs-ta:focus{border-color:#1A5FAA}
.obs-footer{display:flex;align-items:center;gap:7px}
.obs-btn{font-family:'Inter',sans-serif;font-size:12px;padding:7px 16px;border-radius:7px;cursor:pointer;border:none;transition:all .15s;font-weight:500}
.obs-save{background:#1A5FAA;color:#fff}.obs-save:hover{background:#1350A0}
.obs-cancel{background:#F4F7FB;color:#7A9ABF;border:1px solid #D4E2F0}.obs-cancel:hover{background:#EBF3FB}
.obs-clear{margin-left:auto;background:transparent;color:#E84C4C;font-size:11px;padding:5px 8px;text-decoration:underline}.obs-clear:hover{color:#B71C1C}
.empty{text-align:center;padding:52px;color:#C8DAF0;font-size:13px}
.loading{text-align:center;padding:52px;color:#A0B4C8;font-size:13px}
.footer{margin-top:36px;text-align:center;font-family:'DM Mono',monospace;font-size:10px;color:#C8DAF0;letter-spacing:.1em}
.sel-bar{position:fixed;bottom:0;left:0;right:0;background:#0A1E38;padding:16px 40px;display:flex;align-items:center;justify-content:space-between;transform:translateY(100%);transition:transform .3s cubic-bezier(.4,0,.2,1);z-index:200;box-shadow:0 -4px 32px rgba(0,0,0,.3);border-top:1px solid #162A45}
.sel-bar.visible{transform:translateY(0)}
.sel-info-top{display:flex;align-items:baseline;gap:8px}
.sel-count{font-family:'DM Mono',monospace;font-size:24px;font-weight:500;color:#4DC3F7}
.sel-count-label{font-size:13px;color:#7ABFEF}
.sel-total{font-family:'DM Mono',monospace;font-size:13px;color:#4A7AAF;margin-top:4px}
.sel-actions{display:flex;align-items:center;gap:10px}
.btn-clear{background:transparent;color:#7A9ABF;border:1px solid #2A4A6A;padding:10px 20px;border-radius:8px;font-family:'Inter',sans-serif;font-size:13px;cursor:pointer;transition:all .15s}
.btn-clear:hover{border-color:#7A9ABF;color:#fff}
.btn-wpp{background:#25D366;color:#fff;border:none;padding:12px 24px;border-radius:8px;font-family:'Inter',sans-serif;font-size:14px;font-weight:600;cursor:pointer;display:flex;align-items:center;gap:8px;transition:background .15s;white-space:nowrap}
.btn-wpp:hover{background:#1DAF56}
@media(max-width:768px){
  .shell{padding:20px 14px 80px}
  .header{flex-direction:column;align-items:flex-start;gap:10px;padding-bottom:16px;margin-bottom:20px}
  .header-title{font-size:26px}
  .header-nav{width:100%;flex-wrap:wrap;gap:6px}
  .nav-btn{font-size:12px;padding:8px 14px}
  .kpi-row{grid-template-columns:1fr 1fr;gap:10px;margin-bottom:20px}
  .kpi{padding:16px 18px}
  .kpi-value{font-size:22px}
  .ano-row{margin-bottom:20px;gap:6px}
  .cb-input{width:18px;height:18px}
  .obs-trigger{min-height:30px}
  .sel-bar{padding:12px 14px;flex-direction:column;gap:10px;align-items:stretch}
  .sel-actions{justify-content:flex-end}
  .btn-wpp{font-size:13px;padding:10px 16px}
  .btn-clear{padding:8px 16px;font-size:12px}
  .sel-count{font-size:20px}
}
@media(max-width:480px){
  .kpi-row{grid-template-columns:1fr}
  .header-title{font-size:22px}
  .kpi-value{font-size:24px}
  thead th,tbody td{padding:9px 8px;font-size:11px}
  .td-nome{font-size:12px}
  .td-val{font-size:12px}
  .badge,.c-urgente,.c-protestar,.c-cartorio{font-size:10px;padding:2px 8px}
  .obs-editor{left:12px !important;width:calc(100vw - 24px)}
}
</style>
</head>
<body>
<div class="shell">
  <div class="header">
    <div class="header-left">
      <div class="header-eyebrow">Relatório Financeiro · Portal GPN</div>
      <h1 class="header-title"><strong>Inadimplentes</strong></h1>
      <div class="header-meta">R.A.I.S. Com. de Produtos Náuticos Ltda ME &nbsp;·&nbsp; <span id="last-updated">carregando...</span></div>
    </div>
    <div class="header-nav">
      <a class="nav-btn nav-update" href="/upload">↑ Atualizar dados</a>
      <a class="nav-btn nav-logout" href="/logout">Sair</a>
    </div>
  </div>
  <div class="ano-row">
    <span class="ano-label">ANO</span>
    <button class="ano-btn active" data-a="Todos">Todos</button>
    <button class="ano-btn" data-a="2023">2023</button>
    <button class="ano-btn" data-a="2024">2024</button>
    <button class="ano-btn" data-a="2025">2025</button>
    <button class="ano-btn" data-a="2026">2026</button>
  </div>
  <div class="ano-row" id="filial-row" style="display:none"></div>
  <div class="kpi-row">
    <div class="kpi">
      <div class="kpi-label">Total em aberto</div>
      <div class="kpi-value" id="kpi-total">—</div>
      <div class="kpi-hint"  id="kpi-hint">—</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Clientes</div>
      <div class="kpi-value" id="kpi-clientes">—</div>
      <div class="kpi-hint">com pendências</div>
    </div>
    <div class="kpi" style="border-color:#FFCDD2;">
      <div class="kpi-label" style="color:#BF5B00;">Títulos p/ Cartório</div>
      <div class="kpi-value" id="kpi-cartorio" style="color:#B71C1C;">—</div>
      <div class="kpi-hint"  id="kpi-cartorio-hint">entre 30 e 59 dias</div>
    </div>
  </div>
  <div class="table-meta">
    <span class="table-meta-title">Títulos em aberto</span>
    <div class="search-wrap">
      <input class="search-input" id="search-input" type="search" placeholder="🔍  Buscar cliente..." autocomplete="off">
    </div>
    <span class="table-meta-count" id="table-count">—</span>
  </div>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th class="cb-col"><input type="checkbox" class="cb-input" id="cb-all" title="Selecionar todos visíveis"></th>
          <th style="width:22%">Razão Social</th>
          <th style="width:9%">Vencimento</th>
          <th style="width:7%">Nota</th>
          <th style="width:13%">Status</th>
          <th style="width:11%">Cartório</th>
          <th class="right" style="width:10%">Valor</th>
          <th style="width:16%">Observação</th>
        </tr>
      </thead>
      <tbody id="tbody">
        <tr><td colspan="8" class="loading">Carregando dados...</td></tr>
      </tbody>
    </table>
  </div>
  <div class="footer" id="footer">Portal GPN &nbsp;·&nbsp; Uso interno</div>
</div>

<div class="obs-editor" id="obs-editor">
  <div class="obs-editor-title">Observação do título</div>
  <div class="obs-chips">
    <button class="obs-chip obs-chip-auth" data-text="✅ Autorizado p/ cartório">✅ Autorizado</button>
    <button class="obs-chip obs-chip-hold" data-text="⛔ Segurar — não enviar">⛔ Segurar</button>
    <button class="obs-chip obs-chip-sent" id="chip-sent">📬 Enviado hoje</button>
  </div>
  <textarea class="obs-ta" id="obs-ta" placeholder="Anotação livre..."></textarea>
  <div class="obs-footer">
    <button class="obs-btn obs-save"   id="obs-save-btn">Salvar</button>
    <button class="obs-btn obs-cancel" id="obs-cancel-btn">Cancelar</button>
    <button class="obs-btn obs-clear"  id="obs-clear-btn">Limpar nota</button>
  </div>
</div>

<div class="sel-bar" id="sel-bar">
  <div>
    <div class="sel-info-top">
      <span class="sel-count" id="sel-count">0</span>
      <span class="sel-count-label">título(s) selecionado(s)</span>
    </div>
    <div class="sel-total" id="sel-total">R$ 0,00 selecionados</div>
  </div>
  <div class="sel-actions">
    <button class="btn-clear" onclick="clearSelection()">Limpar seleção</button>
    <button class="btn-wpp" onclick="sendWhatsApp()">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z"/></svg>
      Enviar ao Cartório via WhatsApp
    </button>
  </div>
</div>

<script>
let DATA=[];
let fAno='Todos';
let fFilial='Todas';
let fBusca='';
const TODAY=new Date('{{ today }}');
TODAY.setHours(12,0,0,0);
const brl=v=>'R$ '+v.toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2});
const dtBR=s=>{const[y,m,d]=s.split('-');return d+'/'+m+'/'+y;};
const todayBR=()=>dtBR(TODAY.toISOString().slice(0,10));

function obsRaw(d){return(d.obs||'').trim();}
function obsClass(val){
  if(!val)return'';
  const lv=val.toLowerCase();
  if(lv.includes('segurar'))return'obs-hold';
  if(lv.includes('autorizado'))return'obs-auth';
  if(lv.includes('enviado'))return'obs-sent';
  return'obs-note';
}

let activeObsKey=null;
function openObs(d,anchorEl){
  activeObsKey=d.key;
  const ed=document.getElementById('obs-editor');
  const ta=document.getElementById('obs-ta');
  const clr=document.getElementById('obs-clear-btn');
  ta.value=obsRaw(d);
  clr.style.display=obsRaw(d)?'':'none';
  document.getElementById('chip-sent').dataset.text='📬 Enviado ao cartório em '+todayBR();
  const rect=anchorEl.getBoundingClientRect();
  const W=Math.min(310,window.innerWidth-24),H=260;
  let left=rect.left,top=rect.bottom+6;
  if(left+W>window.innerWidth-12)left=window.innerWidth-W-12;
  if(left<8)left=8;
  if(top+H>window.innerHeight-8)top=Math.max(8,rect.top-H-6);
  ed.style.left=left+'px';ed.style.top=top+'px';
  ed.style.display='block';ta.focus();
}
function closeObs(){document.getElementById('obs-editor').style.display='none';activeObsKey=null;}

async function saveObs(){
  if(!activeObsKey)return;
  const key=activeObsKey;
  const val=document.getElementById('obs-ta').value.trim();
  const btn=document.getElementById('obs-save-btn');
  btn.disabled=true;
  try{
    const resp=await fetch('/api/obs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({key,obs:val})});
    if(!resp.ok){const t=await resp.text();throw new Error('Servidor retornou '+resp.status+': '+t.slice(0,120));}
    const item=DATA.find(x=>x.key===key);
    if(item)item.obs=val;
  }catch(e){alert('Erro ao salvar: '+e.message);btn.disabled=false;return;}
  btn.disabled=false;
  closeObs();render();
}
async function clearObsEntry(){
  if(!activeObsKey)return;
  const key=activeObsKey;
  try{
    const resp=await fetch('/api/obs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({key,obs:''})});
    if(!resp.ok){const t=await resp.text();throw new Error('Servidor retornou '+resp.status+': '+t.slice(0,120));}
    const item=DATA.find(x=>x.key===key);
    if(item)item.obs='';
  }catch(e){alert('Erro ao limpar: '+e.message);return;}
  closeObs();render();
}

document.querySelectorAll('.obs-chip').forEach(chip=>chip.addEventListener('click',function(){
  document.getElementById('obs-ta').value=this.dataset.text;
  document.getElementById('obs-ta').focus();
}));
document.getElementById('obs-save-btn').addEventListener('click',saveObs);
document.getElementById('obs-cancel-btn').addEventListener('click',closeObs);
document.getElementById('obs-clear-btn').addEventListener('click',clearObsEntry);
document.getElementById('obs-ta').addEventListener('keydown',function(e){
  if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)){e.preventDefault();saveObs();}
  if(e.key==='Escape')closeObs();
});
document.addEventListener('click',function(e){
  const ed=document.getElementById('obs-editor');
  if(ed.style.display==='none')return;
  if(ed.contains(e.target)||e.target.closest('.obs-trigger'))return;
  closeObs();
});

const selIds=new Set();
function updateSelBar(){
  const n=selIds.size;
  const bar=document.getElementById('sel-bar');
  if(n>0){
    bar.classList.add('visible');document.body.style.paddingBottom='80px';
    const tot=DATA.filter(d=>selIds.has(d._id)).reduce((s,d)=>s+d.valor,0);
    document.getElementById('sel-count').textContent=n;
    document.getElementById('sel-total').textContent=brl(tot)+' selecionados';
  }else{bar.classList.remove('visible');document.body.style.paddingBottom='';}
  const cbs=[...document.querySelectorAll('.row-cb')];
  const cbAll=document.getElementById('cb-all');
  if(!cbs.length){cbAll.checked=false;cbAll.indeterminate=false;}
  else if(cbs.every(c=>c.checked)){cbAll.checked=true;cbAll.indeterminate=false;}
  else if(cbs.some(c=>c.checked)){cbAll.checked=false;cbAll.indeterminate=true;}
  else{cbAll.checked=false;cbAll.indeterminate=false;}
}
function clearSelection(){
  selIds.clear();
  document.querySelectorAll('.row-cb').forEach(c=>c.checked=false);
  document.querySelectorAll('tbody tr').forEach(tr=>tr.classList.remove('row-selected'));
  updateSelBar();
}
function sendWhatsApp(){
  const items=DATA.filter(d=>selIds.has(d._id));
  if(!items.length)return;
  const total=items.reduce((s,d)=>s+d.valor,0);
  let msg='📋 *Títulos para Envio ao Cartório*\\nR.A.I.S. Com. de Produtos Náuticos · Portal GPN\\nGerado em '+todayBR()+'\\n━━━━━━━━━━━━━━━━━━━━━━\\n\\n';
  items.forEach((d,i)=>{
    const dias=Math.floor((TODAY-new Date(d.venc))/86400000);
    const diasStr=dias===1?'1 dia em atraso':dias+' dias em atraso';
    const notaStr=d.nota?'NF '+d.nota+'  ·  ':'';
    const obs=obsRaw(d);
    msg+='*'+(i+1)+'. '+d.nome+'*\\n   '+notaStr+'Venc: '+dtBR(d.venc)+'\\n   '+diasStr+'  ·  '+brl(d.valor)+'\\n';
    if(obs)msg+='   _'+obs+'_\\n';
    msg+='\\n';
  });
  msg+='━━━━━━━━━━━━━━━━━━━━━━\\n*Total: '+brl(total)+'  ·  '+items.length+' título(s)*';
  window.open('https://wa.me/5524981882196?text='+encodeURIComponent(msg),'_blank');
}

function badge(venc){
  const d=Math.floor((TODAY-new Date(venc))/86400000);
  const lbl=d<=0?'0d em atraso':d===1?'1d em atraso':d+'d em atraso';
  if(d>365)return['b-crit',lbl];
  if(d>60)return['b-high',lbl];
  if(d>10)return['b-mid',lbl];
  if(d>0)return['b-low',lbl];
  return['b-zero',lbl];
}
function cartorio(d){
  if(obsRaw(d).toLowerCase().includes('enviado'))return'<span class="c-cartorio">Em cartório</span>';
  const dias=Math.floor((TODAY-new Date(d.venc))/86400000);
  if(dias>=60)return'<span class="c-urgente">⚠ Prazo perdido</span>';
  if(dias>=45)return'<span class="c-urgente">⚠ Urgente</span>';
  if(dias>=30)return'<span class="c-protestar">Protestar</span>';
  return'<span style="color:#C8DAF0">—</span>';
}

function buildFilialBtns(){
  const filiais=[...new Set(DATA.map(d=>d.filial||'Portal GPN'))].sort();
  const row=document.getElementById('filial-row');
  if(filiais.length<=1){row.style.display='none';return;}
  row.innerHTML='<span class="ano-label">FILIAL</span>';
  ['Todas',...filiais].forEach(f=>{
    const btn=document.createElement('button');
    btn.className='ano-btn'+(fFilial===f?' active':'');
    btn.dataset.f=f;btn.textContent=f;
    btn.addEventListener('click',()=>{
      row.querySelectorAll('.ano-btn').forEach(x=>x.classList.remove('active'));
      btn.classList.add('active');fFilial=f;render();
    });
    row.appendChild(btn);
  });
  row.style.display='flex';
}

function render(){
  closeObs();
  let rows=DATA.filter(d=>fAno==='Todos'||d.venc.slice(0,4)===fAno);
  if(fFilial!=='Todas')rows=rows.filter(d=>(d.filial||'Portal GPN')===fFilial);
  const q=fBusca.trim().toLowerCase();
  if(q)rows=rows.filter(d=>d.nome.toLowerCase().includes(q));
  const total=rows.reduce((s,d)=>s+d.valor,0);
  const clienteSet=new Set(rows.map(d=>d.nome));
  document.getElementById('kpi-total').textContent=brl(total);
  document.getElementById('kpi-hint').textContent=rows.length+' título'+(rows.length!==1?'s':'');
  document.getElementById('kpi-clientes').textContent=clienteSet.size;
  let countTxt=rows.length+' registro'+(rows.length!==1?'s':'');
  if(q&&clienteSet.size===1)countTxt=rows.length+' parcela'+(rows.length!==1?'s':'')+' · '+[...clienteSet][0];
  else if(q&&clienteSet.size>1)countTxt=rows.length+' registro'+(rows.length!==1?'s':'')+' · '+clienteSet.size+' clientes';
  document.getElementById('table-count').textContent=countTxt;
  const jaEnviado=d=>obsRaw(d).toLowerCase().includes('enviado');
  const nProtestar=rows.filter(d=>{const x=Math.floor((TODAY-new Date(d.venc))/86400000);return!jaEnviado(d)&&x>=30&&x<45;}).length;
  const nUrgente=rows.filter(d=>{const x=Math.floor((TODAY-new Date(d.venc))/86400000);return!jaEnviado(d)&&x>=45&&x<60;}).length;
  const nPerdido=rows.filter(d=>{const x=Math.floor((TODAY-new Date(d.venc))/86400000);return!jaEnviado(d)&&x>=60;}).length;
  document.getElementById('kpi-cartorio').textContent=nProtestar+nUrgente;
  document.getElementById('kpi-cartorio').style.color=nUrgente>0?'#B71C1C':'#BF5B00';
  const hints=[];
  if(nUrgente>0)hints.push(nUrgente+' urgente'+(nUrgente>1?'s':''));
  if(nPerdido>0)hints.push(nPerdido+' prazo perdido');
  document.getElementById('kpi-cartorio-hint').textContent=hints.length?hints.join(' · '):'entre 30 e 59 dias';
  const tbody=document.getElementById('tbody');
  tbody.innerHTML='';
  if(!rows.length){tbody.innerHTML='<tr><td colspan="8" class="empty">Nenhum título encontrado.</td></tr>';updateSelBar();return;}
  rows.forEach(d=>{
    const[cls,lbl]=badge(d.venc);
    const notaHtml=d.nota?'<span class="td-nota">'+d.nota+'</span>':'<span class="td-nota-none">—</span>';
    const checked=selIds.has(d._id);
    const obsVal=obsRaw(d);
    const obsCls=obsClass(obsVal);
    const obsHtml=obsVal?'<span class="obs-trigger '+obsCls+'" title="'+obsVal.replace(/"/g,"&quot;")+'"><span class="obs-text">'+obsVal+'</span></span>':'<span class="obs-trigger obs-empty">+ nota</span>';
    const tr=document.createElement('tr');
    if(checked)tr.classList.add('row-selected');
    tr.innerHTML='<td class="cb-col"><input type="checkbox" class="cb-input row-cb"'+(checked?' checked':'')+'></td><td class="td-nome">'+d.nome+'</td><td><span class="td-date">'+dtBR(d.venc)+'</span></td><td>'+notaHtml+'</td><td><span class="badge '+cls+'">'+lbl+'</span></td><td>'+cartorio(d)+'</td><td class="right td-val">'+brl(d.valor)+'</td><td class="obs-col">'+obsHtml+'</td>';
    tr.querySelector('.row-cb').addEventListener('change',function(){
      if(this.checked){selIds.add(d._id);tr.classList.add('row-selected');}
      else{selIds.delete(d._id);tr.classList.remove('row-selected');}
      updateSelBar();
    });
    tr.querySelector('.obs-trigger').addEventListener('click',function(e){e.stopPropagation();openObs(d,this);});
    tbody.appendChild(tr);
  });
  updateSelBar();
}

document.getElementById('cb-all').addEventListener('change',function(){
  const vis=DATA.filter(d=>fAno==='Todos'||d.venc.slice(0,4)===fAno);
  document.querySelectorAll('.row-cb').forEach((cb,i)=>{
    cb.checked=this.checked;
    const tr=cb.closest('tr');
    if(this.checked){selIds.add(vis[i]._id);tr.classList.add('row-selected');}
    else{selIds.delete(vis[i]._id);tr.classList.remove('row-selected');}
  });
  this.indeterminate=false;updateSelBar();
});

document.querySelectorAll('.ano-btn').forEach(b=>b.addEventListener('click',()=>{
  document.querySelectorAll('.ano-btn').forEach(x=>x.classList.remove('active'));
  b.classList.add('active');fAno=b.dataset.a;render();
}));

document.getElementById('search-input').addEventListener('input',function(){
  fBusca=this.value;render();
});

async function loadData(){
  try{
    const resp=await fetch('/api/data');
    if(resp.status===401){window.location.href='/login';return;}
    const json=await resp.json();
    DATA=json.data;DATA.forEach((d,i)=>d._id=i);
    buildFilialBtns();
    const lu=document.getElementById('last-updated');
    lu.textContent=json.last_updated?'Atualizado em '+json.last_updated:'dados não importados ainda';
    if(!DATA.length){
      document.getElementById('tbody').innerHTML='<tr><td colspan="8" class="empty">Nenhum dado importado. Use <a href="/upload">Atualizar dados</a> para importar a planilha.</td></tr>';
      document.getElementById('kpi-total').textContent='R$ 0,00';
      document.getElementById('kpi-hint').textContent='0 títulos';
      document.getElementById('kpi-clientes').textContent='0';
      document.getElementById('kpi-cartorio').textContent='0';
      return;
    }
    render();
  }catch(e){
    document.getElementById('tbody').innerHTML='<tr><td colspan="8" class="empty">Erro ao carregar dados. Recarregue a página.</td></tr>';
  }
}
loadData();
</script>
</body>
</html>'''


# ── Diagnóstico ───────────────────────────────────────────────────────────────

@app.route('/ping')
def ping():
    import sys
    has_db = bool(os.environ.get('DATABASE_URL', ''))
    db_st  = 'OK' if engine else f'None | url_set={has_db} | err={_engine_error[:80]}'
    count, qerr, join_err, sample = 0, '', '', []
    if engine:
        try:
            with engine.connect() as conn:
                r = conn.execute(text('SELECT COUNT(*) FROM titulos')).fetchone()
                count = int(r[0])
        except Exception as e:
            qerr = str(e)[:120]
        try:
            with engine.connect() as conn:
                rows = conn.execute(text('''
                    SELECT t.nome, t.venc::text, t.valor::float
                    FROM titulos t
                    LEFT JOIN observacoes o ON t.titulo_key = o.titulo_key
                    ORDER BY t.venc ASC LIMIT 3
                ''')).fetchall()
                sample = [(r[0][:25], r[1], r[2]) for r in rows]
        except Exception as e:
            join_err = str(e)[:150]
    return (
        f'pong\npython={sys.version}\n'
        f'db={db_st}\n'
        f'titulos_no_banco={count}\n'
        f'count_err={qerr}\n'
        f'join_query_err={join_err}\n'
        f'sample_3_rows={sample}\n'
    ), 200, {'Content-Type': 'text/plain'}


# ── Rotas ─────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return redirect(url_for('dashboard') if session.get('logged_in') else url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        if request.form.get('password') == APP_PASSWORD:
            session.permanent = True
            session['logged_in'] = True
            return redirect(url_for('dashboard'))
        error = 'Senha incorreta.'
    return render_template_string(_LOGIN_TMPL, error=error)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/dashboard')
@login_required
def dashboard():
    ensure_db()
    return render_template_string(_DASHBOARD_TMPL, today=date.today().isoformat())


@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    ensure_db()
    message = error = None

    if request.method == 'POST':
        f = request.files.get('file')
        filial = request.form.get('filial', '').strip() or 'Portal GPN'
        if not f or not f.filename.lower().endswith('.xls'):
            error = 'Envie um arquivo .XLS válido (exportado do IdealSoft).'
        else:
            try:
                records = parse_xls(f)
                with engine.connect() as conn:
                    conn.execute(text('DELETE FROM titulos WHERE filial=:f'), {'f': filial})
                    for r in records:
                        r['filial'] = filial
                        conn.execute(text('''
                            INSERT INTO titulos (nome, venc, nota, valor, titulo_key, filial)
                            VALUES (:nome, :venc, :nota, :valor, :key, :filial)
                            ON CONFLICT (titulo_key) DO UPDATE
                            SET nome=:nome, venc=:venc, nota=:nota, valor=:valor, filial=:filial
                        '''), r)
                    now_str = datetime.now().strftime('%d/%m/%Y %H:%M')
                    conn.execute(text('''
                        INSERT INTO meta (key, value) VALUES ('last_updated', :v)
                        ON CONFLICT (key) DO UPDATE SET value=:v
                    '''), {'v': now_str})
                    conn.commit()
                message = f'{len(records)} títulos importados com sucesso.'
            except Exception as e:
                error = f'Erro ao processar o arquivo: {e}'

    return render_template_string(_UPLOAD_TMPL, message=message, error=error)


# ── API ───────────────────────────────────────────────────────────────────────

@app.route('/api/data')
@login_required
def api_data():
    ensure_db()
    if not engine:
        return jsonify({'data': [], 'last_updated': None})
    try:
        with engine.connect() as conn:
            rows = conn.execute(text('''
                SELECT t.nome, t.venc::text, t.nota, t.valor::float, t.titulo_key,
                       COALESCE(o.obs_text,'') AS obs, t.filial
                FROM titulos t
                LEFT JOIN observacoes o ON t.titulo_key = o.titulo_key
                ORDER BY t.venc ASC
            ''')).fetchall()
            meta = conn.execute(
                text("SELECT value FROM meta WHERE key='last_updated'")
            ).fetchone()
        data = [{'nome':r[0],'venc':r[1],'nota':r[2] or '','valor':r[3],'key':r[4],'obs':r[5],'filial':r[6] or 'Portal GPN'}
                for r in rows]
        return jsonify({'data': data, 'last_updated': meta[0] if meta else None})
    except Exception as e:
        print(f'[API/DATA] {e}')
        return jsonify({'data': [], 'last_updated': None, 'error': str(e)})


@app.route('/api/obs', methods=['POST'])
@login_required
def api_obs():
    ensure_db()
    if not engine:
        return jsonify({'ok': False, 'error': 'banco indisponível'}), 503
    body = request.get_json(force=True)
    if not body:
        return jsonify({'ok': False, 'error': 'corpo JSON inválido'}), 400
    key     = body.get('key', '').strip()
    obs_val = (body.get('obs') or '').strip()
    if not key:
        return jsonify({'ok': False, 'error': 'key obrigatório'}), 400
    try:
        with engine.connect() as conn:
            if obs_val:
                conn.execute(text('''
                    INSERT INTO observacoes (titulo_key, obs_text, updated_at)
                    VALUES (:key, :obs, NOW())
                    ON CONFLICT (titulo_key) DO UPDATE
                    SET obs_text=:obs, updated_at=NOW()
                '''), {'key': key, 'obs': obs_val})
            else:
                conn.execute(text('DELETE FROM observacoes WHERE titulo_key=:key'), {'key': key})
            conn.commit()
        return jsonify({'ok': True})
    except Exception as e:
        print(f'[API/OBS] {e}')
        return jsonify({'ok': False, 'error': str(e)}), 500


# ── Parser XLS ────────────────────────────────────────────────────────────────

def parse_xls(file_obj):
    import xlrd
    wb = xlrd.open_workbook(file_contents=file_obj.read())
    ws = wb.sheet_by_index(0)

    def getv(row_vals, idx):
        if idx >= len(row_vals): return None
        v = row_vals[idx]
        if v == '' or v is None: return None
        return v

    records, current_venc = [], None
    all_rows = [ws.row_values(i) for i in range(ws.nrows)]
    i = 0
    while i < len(all_rows):
        vals = all_rows[i]
        v0_raw = getv(vals, 0)
        v0 = str(v0_raw) if v0_raw is not None else 'None'

        if v0 == 'Vencimento:':
            raw = getv(vals, 3)
            current_venc = xlrd.xldate_as_datetime(raw, wb.datemode) if isinstance(raw, float) else raw
            i += 1; continue

        skip = {'Cliente','Empresa:','Filial:','Vendedor:','Data Inicial:',
                'Conta Bancária:','Recebíveis em Aberto por Vencimento','nan','None'}
        if v0 in skip or not v0.strip() or v0.startswith('Tipo:'):
            i += 1; continue
        if str(getv(vals, 17)) == 'Total:':
            i += 1; continue

        tipo  = getv(vals, 8)
        valor = getv(vals, 20)
        cod   = getv(vals, 0)
        if cod is None or tipo is None:
            i += 1; continue

        nome = str(getv(vals, 1)).strip() if getv(vals, 1) else ''
        j = i + 1
        while j < len(all_rows):
            jvals = all_rows[j]
            if str(getv(jvals, 17)) == 'Total:': break
            j0 = str(getv(jvals, 0)) if getv(jvals, 0) is not None else ''
            if j0 in ('Vencimento:', 'Cliente'): break
            if getv(jvals, 8) is not None: break
            cont = getv(jvals, 1)
            if cont is not None:
                nome = (nome + ' ' + str(cont).strip()).strip()
            j += 1
        nome = ' '.join(nome.split())

        nota_raw = str(getv(vals, 10)).strip() if getv(vals, 10) else ''
        nota = '' if nota_raw in ('0', '0.0') else nota_raw

        if hasattr(current_venc, 'strftime'):
            venc_str = current_venc.strftime('%Y-%m-%d')
        else:
            venc_str = str(current_venc)[:10] if current_venc else '2000-01-01'

        valor_f    = float(valor) if valor is not None else 0.0
        titulo_key = f'{nome}|{venc_str}|{valor_f}'
        records.append({'nome': nome, 'venc': venc_str, 'nota': nota,
                        'valor': valor_f, 'key': titulo_key})
        i += 1
    return records


if __name__ == '__main__':
    app.run(debug=True)
