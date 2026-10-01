from flask import Flask, request, jsonify, Response, stream_with_context
import subprocess
import os
import json as jsonlib
import re
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

app = Flask(__name__)

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

# ---------- STREAMLINK: LISTAR CALIDADES ----------
def list_qualities(video_url):
    """Devuelve la lista de nombres de calidad disponibles (ej: ['360p','480p','720p'])"""
    try:
        cmd = [
            'streamlink', '--json', '--loglevel', 'error',
            '--http-header', 'Referer=https://ok.ru/',
            '--http-header', f'User-Agent={UA}',
            video_url
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            print(f"list_qualities stderr: {r.stderr}")
            return []
        data = jsonlib.loads(r.stdout)
        streams = data.get('streams', {})
        return list(streams.keys())
    except Exception as e:
        print(f"list_qualities error: {e}")
        return []

# ---------- STREAMLINK: RESOLVER UNA CALIDAD ----------
def resolve_one(video_url, quality):
    """Devuelve { name, label, height, url, is_audio } para una calidad concreta."""
    try:
        cmd = [
            'streamlink', '--stream-url', '--loglevel', 'error',
            '--http-header', 'Referer=https://ok.ru/',
            '--http-header', f'User-Agent={UA}',
            '--retry-streams', '1',
            '--retry-max', '1',
            '--stream-timeout', '15',
            video_url, quality
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        if r.returncode == 0 and r.stdout.strip():
            url = r.stdout.strip()

            # Etiqueta legible
            h = None
            m = re.match(r'(\d+)p', quality)
            if m:
                h = int(m.group(1))
                label = f'{h}p' + (' HD' if h >= 720 else '')
            else:
                label = quality  # "best", "worst", "audio", etc.

            is_audio = quality.lower() == 'audio'

            return {
                'name': quality,
                'label': label,
                'height': h,
                'width': int(h * 16 / 9) if h else None,
                'url': url,
                'is_audio': is_audio
            }
        return None
    except Exception as e:
        print(f"resolve_one({quality}) error: {e}")
        return None

def quality_sort_key(q):
    """Orden para las calidades. Mayor = mejor."""
    if q == 'best':  return 99999
    if q == 'worst': return -1
    if q == 'audio': return -2
    m = re.match(r'(\d+)p', q)
    if m: return int(m.group(1))
    return 0

# ---------- ENDPOINT: LISTAR TODAS ----------
@app.route('/resolve')
def resolve():
    url = request.args.get('url')
    if not url:
        return jsonify({'error': 'Falta ?url='}), 400

    # 1) Listar calidades disponibles
    qualities = list_qualities(url)
    if not qualities:
        return jsonify({'error': 'No se pudieron listar las calidades del video'}), 500

    # 2) Ordenar por resolución y quedarnos con las 4 mejores (ignorando audio)
    video_q = [q for q in qualities if q.lower() != 'audio']
    video_q.sort(key=quality_sort_key, reverse=True)
    top_qualities = video_q[:4]

    # 3) Resolver SOLO 2 en paralelo (menos carga en Render free)
    results = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {pool.submit(resolve_one, url, q): q for q in top_qualities}
        for f in as_completed(futures):
            try:
                r = f.result()
                if r: results.append(r)
            except Exception as e:
                print(f"future error: {e}")

    if not results:
        return jsonify({'error': 'No se pudo resolver ninguna calidad'}), 500

    # 4) Ordenar de mayor a menor
    results.sort(key=lambda x: quality_sort_key(x['name']), reverse=True)

    # 5) La mejor = la primera
    best = results[0]

    return jsonify({
        'best': best,
        'all': results,
        'source': url,
        'count': len(results),
        'status': 'ok'
    })

# ---------- ENDPOINT: PROXY ----------
@app.route('/proxy')
def proxy():
    target = request.args.get('url')
    if not target:
        return 'Falta ?url=', 400

    headers = {
        'User-Agent': UA,
        'Referer': 'https://ok.ru/',
        'Origin': 'https://ok.ru',
        'Range': request.headers.get('Range', 'bytes=0-')
    }

    try:
        r = requests.get(target, headers=headers, stream=True, timeout=30)
        resp_headers = {
            'Content-Type': r.headers.get('Content-Type', 'video/mp4'),
            'Accept-Ranges': 'bytes',
            'Access-Control-Allow-Origin': '*'
        }
        if 'Content-Length' in r.headers:
            resp_headers['Content-Length'] = r.headers['Content-Length']
        if 'Content-Range' in r.headers:
            resp_headers['Content-Range'] = r.headers['Content-Range']

        return Response(
            stream_with_context(r.iter_content(chunk_size=65536)),
            status=r.status_code,
            headers=resp_headers
        )
    except Exception as e:
        return f'Error en proxy: {e}', 500

# ---------- ENDPOINT: HEALTH ----------
@app.route('/health')
def health():
    return jsonify({'status': 'ok'}), 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
