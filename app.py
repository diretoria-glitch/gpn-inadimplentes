import os
import numpy as np
from datetime import date, datetime
from functools import wraps

import pandas as pd
from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'troque-esta-chave-em-producao')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB

APP_PASSWORD = os.environ.get('APP_PASSWORD', 'paraty2026')

DATABASE_URL = os.environ.get('DATABASE_URL', '')
if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

engine = create_engine(DATABASE_URL, poolclass=NullPool) if DATABASE_URL else None


# ── Banco de dados ────────────────────────────────────────────────────────────

def init_db():
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


try:
    if engine:
        with app.app_context():
            init_db()
except Exception as e:
    print(f'[AVISO] Inicialização do banco: {e}')


# ── Autenticação ──────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


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


# ── Páginas ───────────────────────────────────────────────────────────────────

@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html', today=date.today().isoformat())


@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
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


# ── Parser XLS ────────────────────────────────────────────────────────────────

def parse_xls(file_obj):
    df = pd.read_excel(file_obj, engine='xlrd', header=None)

    def getv(vals, idx):
        v = vals[idx] if idx < len(vals) else None
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return None
        if str(v) in ('nan', 'NaT'):
            return None
        return v

    records = []
    current_venc = None
    all_rows = list(df.iterrows())
    i = 0

    while i < len(all_rows):
        _, row = all_rows[i]
        vals = row.tolist()

        if str(getv(vals, 0)) == 'Vencimento:':
            current_venc = vals[3]
            i += 1
            continue

        skip = {'Cliente', 'Empresa:', 'Filial:', 'Vendedor:', 'Data Inicial:',
                'Conta Bancária:', 'Recebíveis em Aberto por Vencimento', 'nan', 'None'}
        v0 = str(getv(vals, 0)) if getv(vals, 0) is not None else 'None'
        if v0 in skip or v0.startswith('Tipo:'):
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
            _, jrow = all_rows[j]
            jvals = jrow.tolist()
            if str(getv(jvals, 17)) == 'Total:': break
            if str(getv(jvals, 0)) in ('Vencimento:', 'Cliente'): break
            if getv(jvals, 8) is not None: break
            cont = getv(jvals, 1)
            if cont is not None:
                nome = (nome + ' ' + str(cont).strip()).strip()
            j += 1
        nome = ' '.join(nome.split())

        nota_raw = str(getv(vals, 10)).strip() if getv(vals, 10) else ''
        nota = '' if nota_raw == '0' else nota_raw

        if hasattr(current_venc, 'strftime'):
            venc_str = current_venc.strftime('%Y-%m-%d')
        else:
            venc_str = str(current_venc)[:10]

        valor_f   = float(valor) if valor is not None else 0.0
        titulo_key = f'{nome}|{venc_str}|{valor_f}'

        records.append({'nome': nome, 'venc': venc_str, 'nota': nota,
                        'valor': valor_f, 'key': titulo_key})
        i += 1

    return records


if __name__ == '__main__':
    app.run(debug=True)
