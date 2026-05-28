import os
import ssl
from datetime import date, datetime
from functools import wraps
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'troque-esta-chave-em-producao')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB

APP_PASSWORD = os.environ.get('APP_PASSWORD', 'paraty2026')

# ── Conexão com banco (totalmente defensiva — nunca trava o app) ──────────────

engine = None

try:
    _raw = os.environ.get('DATABASE_URL', '')
    if _raw:
        # Normaliza esquema para pg8000
        if _raw.startswith('postgres://'):
            _raw = 'postgresql+pg8000://' + _raw[len('postgres://'):]
        elif _raw.startswith('postgresql://'):
            _raw = 'postgresql+pg8000://' + _raw[len('postgresql://'):]

        # Remove sslmode da query string (pg8000 usa ssl_context)
        _parsed = urlparse(_raw)
        _qs = {k: v for k, v in parse_qs(_parsed.query, keep_blank_values=True).items()
               if k != 'sslmode'}
        _clean_url = urlunparse(_parsed._replace(
            query=urlencode({k: v[0] for k, v in _qs.items()})
        ))

        _ssl_ctx = ssl.create_default_context()
        _ssl_ctx.check_hostname = False
        _ssl_ctx.verify_mode = ssl.CERT_NONE

        engine = create_engine(
            _clean_url,
            poolclass=NullPool,
            connect_args={'ssl_context': _ssl_ctx}
        )
except Exception as _e:
    print(f'[ENGINE INIT ERROR] {_e}')
    engine = None

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
                    id          SERIAL PRIMARY KEY,
                    nome        TEXT    NOT NULL,
                    venc        DATE    NOT NULL,
                    nota        TEXT    DEFAULT '',
                    valor       NUMERIC(12,2) NOT NULL,
                    titulo_key  TEXT    UNIQUE NOT NULL
                )
            '''))
            conn.execute(text('''
                CREATE TABLE IF NOT EXISTS observacoes (
                    id          SERIAL PRIMARY KEY,
                    titulo_key  TEXT    NOT NULL UNIQUE,
                    obs_text    TEXT    NOT NULL,
                    updated_at  TIMESTAMP DEFAULT NOW()
                )
            '''))
            conn.execute(text('''
                CREATE TABLE IF NOT EXISTS meta (
                    key   TEXT PRIMARY KEY,
                    value TEXT
                )
            '''))
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


# ── Diagnóstico (remover após confirmar funcionamento) ────────────────────────

@app.route('/ping')
def ping():
    import sys
    db_status = 'engine OK' if engine else 'engine None'
    tmpl_folder = app.template_folder
    return (
        f'pong\n'
        f'python={sys.version}\n'
        f'db={db_status}\n'
        f'templates={tmpl_folder}\n'
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
    return render_template('login.html', error=error)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/dashboard')
@login_required
def dashboard():
    ensure_db()
    return render_template('dashboard.html', today=date.today().isoformat())


@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    ensure_db()
    message = error = None

    if request.method == 'POST':
        f = request.files.get('file')
        if not f or not f.filename.lower().endswith('.xls'):
            error = 'Envie um arquivo .XLS válido (exportado do IdealSoft).'
        else:
            try:
                records = parse_xls(f)
                with engine.connect() as conn:
                    conn.execute(text('TRUNCATE TABLE titulos'))
                    for r in records:
                        conn.execute(text('''
                            INSERT INTO titulos (nome, venc, nota, valor, titulo_key)
                            VALUES (:nome, :venc, :nota, :valor, :key)
                            ON CONFLICT (titulo_key) DO UPDATE
                            SET nome = :nome, venc = :venc, nota = :nota, valor = :valor
                        '''), r)
                    now_str = datetime.now().strftime('%d/%m/%Y %H:%M')
                    conn.execute(text('''
                        INSERT INTO meta (key, value) VALUES ('last_updated', :v)
                        ON CONFLICT (key) DO UPDATE SET value = :v
                    '''), {'v': now_str})
                    conn.commit()
                message = f'{len(records)} títulos importados com sucesso.'
            except Exception as e:
                error = f'Erro ao processar o arquivo: {e}'

    return render_template('upload.html', message=message, error=error)


# ── API ───────────────────────────────────────────────────────────────────────

@app.route('/api/data')
@login_required
def api_data():
    ensure_db()
    if not engine:
        return jsonify({'data': [], 'last_updated': None})
    with engine.connect() as conn:
        rows = conn.execute(text('''
            SELECT t.nome, t.venc::text, t.nota, t.valor::float, t.titulo_key,
                   COALESCE(o.obs_text, '') AS obs
            FROM titulos t
            LEFT JOIN observacoes o ON t.titulo_key = o.titulo_key
            ORDER BY t.venc ASC
        ''')).fetchall()
        meta = conn.execute(
            text("SELECT value FROM meta WHERE key = 'last_updated'")
        ).fetchone()

    data = [
        {'nome': r[0], 'venc': r[1], 'nota': r[2] or '',
         'valor': r[3], 'key': r[4], 'obs': r[5]}
        for r in rows
    ]
    return jsonify({'data': data, 'last_updated': meta[0] if meta else None})


@app.route('/api/obs', methods=['POST'])
@login_required
def api_obs():
    ensure_db()
    body    = request.get_json(force=True)
    key     = body.get('key', '').strip()
    obs_val = (body.get('obs') or '').strip()

    if not key:
        return jsonify({'ok': False, 'error': 'key obrigatório'}), 400

    with engine.connect() as conn:
        if obs_val:
            conn.execute(text('''
                INSERT INTO observacoes (titulo_key, obs_text, updated_at)
                VALUES (:key, :obs, NOW())
                ON CONFLICT (titulo_key) DO UPDATE
                SET obs_text = :obs, updated_at = NOW()
            '''), {'key': key, 'obs': obs_val})
        else:
            conn.execute(text('DELETE FROM observacoes WHERE titulo_key = :key'), {'key': key})
        conn.commit()

    return jsonify({'ok': True})


# ── Parser XLS (xlrd puro — sem pandas/numpy) ─────────────────────────────────

def parse_xls(file_obj):
    import xlrd

    wb = xlrd.open_workbook(file_contents=file_obj.read())
    ws = wb.sheet_by_index(0)

    def getv(row_vals, idx):
        if idx >= len(row_vals):
            return None
        v = row_vals[idx]
        if v == '' or v is None:
            return None
        return v

    records = []
    current_venc = None
    all_rows = [ws.row_values(i) for i in range(ws.nrows)]
    i = 0

    while i < len(all_rows):
        vals = all_rows[i]

        v0_raw = getv(vals, 0)
        v0 = str(v0_raw) if v0_raw is not None else 'None'

        if v0 == 'Vencimento:':
            raw = getv(vals, 3)
            if isinstance(raw, float):
                current_venc = xlrd.xldate_as_datetime(raw, wb.datemode)
            else:
                current_venc = raw
            i += 1
            continue

        skip = {'Cliente', 'Empresa:', 'Filial:', 'Vendedor:', 'Data Inicial:',
                'Conta Bancária:', 'Recebíveis em Aberto por Vencimento', 'nan', 'None'}
        if v0 in skip or not v0.strip() or v0.startswith('Tipo:'):
            i += 1
            continue
        if str(getv(vals, 17)) == 'Total:':
            i += 1
            continue

        tipo  = getv(vals, 8)
        valor = getv(vals, 20)
        cod   = getv(vals, 0)
        if cod is None or tipo is None:
            i += 1
            continue

        nome = str(getv(vals, 1)).strip() if getv(vals, 1) else ''
        j = i + 1
        while j < len(all_rows):
            jvals = all_rows[j]
            if str(getv(jvals, 17)) == 'Total:':
                break
            j0 = str(getv(jvals, 0)) if getv(jvals, 0) is not None else ''
            if j0 in ('Vencimento:', 'Cliente'):
                break
            if getv(jvals, 8) is not None:
                break
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
