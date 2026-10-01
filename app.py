from flask import Flask, request, jsonify, Response, stream_with_context
import subprocess
import os
import json as jsonlib
import re
import requests

app = Flask(__name__)

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'


# ---------- UNA SOLA LLAMADA A STREAMLINK ----------
def get_all_qualities(video_url):
    """
    Llama a streamlink UNA VEZ y devuelve todas las calidades con sus URLs.
    Es mucho más rápido y ligero que lanzar un proceso por calidad.
    """
    try:
        cmd = [
            'streamlink', '--json', '--loglevel', 'error',
            '--http-header', 'Referer=https://ok.ru/',
            '--http-header', f'User-Agent={UA}',
            '--retry-streams', '1',
            '--retry-max', '1',
            '--stream-timeout', '15',
            video_url
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=40)
        if r.returncode != 0:
            print(f"streamlink stderr: {r.stderr}")
            return None
        data = jsonlib.loads(r.stdout)
        return data.get('streams', {})
    except subprocess.TimeoutExpired:
        print("streamlink timeout")
        return None
    except Exception as e:
        print(f"get_all_qualities error: {e}")
        return None


def quality_sort_key(name):
    if name == 'best':  return 99999
    if name == 'worst': return -1
    if name == 'audio': return -2
    m = re.match(r'(\d+)p', name)
    if m: return int(m.group(1))
    return 0


# ---------- ENDPOINT: LISTAR TODAS LAS CALIDADES ----------
@app.route('/resolve')
def resolve():
    url = request.args.get('url')
    if not url:
        return jsonify({'error': 'Falta ?url='}), 400

    streams = get_all_qualities(url)
    if not streams:
        return jsonify({'error': 'No se pudieron obtener las calidades del video'}), 500

    results = []
    for name, info in streams.items():
        stream_url = info.get('url')
        if not stream_url:
            continue

        # Etiqueta legible
        h = None
        m = re.match(r'(\d+)p', name)
        if m:
            h = int(m.group(1))
            label = f'{h}p' + (' HD' if h >= 720 else '')
        else:
            label = name

        # Resolución desde streamlink si la trae
        res = info.get('resolution', '')
        if res and 'x' in res:
            try:
                w, hh = res.split('x')
                h = int(hh)
            except Exception:
                pass

        is_audio = (name.lower() == 'audio' or info.get('type') == 'audio')

        results.append({
            'name': name,
            'label': label,
            'height': h,
            'width': int(h * 16 / 9) if h else None,
            'url': stream_url,
            'is_audio': is_audio
        })

    if not results:
        return jsonify({'error': 'No se pudo resolver ninguna calidad'}), 500

    # Ordenar de mayor a menor, audio al final
    results.sort(key=lambda x: quality_sort_key(x['name']), reverse=True)
    results = [q for q in results if not q['is_audio']] + [q for q in results if q['is_audio']]

    # Mejor = primera no-audio
    best = next((q for q in results if not q['is_audio']), results[0])

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

    client_range = request.headers.get('Range')

    headers = {
        'User-Agent': UA,
        'Referer': 'https://ok.ru/',
        'Origin': 'https://ok.ru',
        'Accept': '*/*',
    }
    if client_range:
        headers['Range'] = client_range

    try:
        r = requests.get(
            target,
            headers=headers,
            stream=True,
            timeout=60,
            allow_redirects=True
        )

        resp_headers = {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, HEAD, OPTIONS',
            'Access-Control-Allow-Headers': 'Range, Content-Type, Accept, Origin, Referer',
            'Access-Control-Expose-Headers': 'Content-Length, Content-Range, Accept-Ranges',
            'Accept-Ranges': 'bytes',
        }

        for h in ['Content-Type', 'Content-Length', 'Content-Range', 'Last-Modified', 'ETag']:
            if h in r.headers:
                resp_headers[h] = r.headers[h]

        ct = resp_headers.get('Content-Type', '')
        if not ct.startswith('video/') and not ct.startswith('application/octet'):
            resp_headers['Content-Type'] = 'video/mp4'
        elif ct.startswith('application/octet'):
            resp_headers['Content-Type'] = 'video/mp4'

        return Response(
            stream_with_context(r.iter_content(chunk_size=128 * 1024)),
            status=r.status_code,
            headers=resp_headers
        )

    except requests.exceptions.Timeout:
        return 'Timeout al pedir el video a OK.ru', 504
    except Exception as e:
        return f'Error en proxy: {e}', 500


# ---------- ENDPOINT: HEALTH ----------
@app.route('/health')
def health():
    return jsonify({'status': 'ok'}), 200


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
