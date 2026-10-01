from flask import Flask, request, jsonify, Response
import subprocess
import requests
from urllib.parse import urljoin

app = Flask(__name__)

def get_stream_url(video_url, quality="best"):
    try:
        command = [
            'streamlink',
            '--stream-url',
            '--loglevel', 'error',
            '--http-header', 'Referer=https://ok.ru/',
            '--http-header', 'User-Agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            video_url, quality
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        return None
    except Exception as e:
        print(f"Error: {e}")
        return None

@app.route('/resolve')
def resolve():
    url = request.args.get('url')
    if not url:
        return jsonify({'error': 'Falta ?url='}), 400
    stream_url = get_stream_url(url)
    if not stream_url:
        return jsonify({'error': 'No se pudo extraer'}), 500
    return jsonify({'url': stream_url, 'source': url, 'status': 'ok'})

@app.route('/health')
def health():
    return jsonify({'status': 'ok'}), 200

@app.route('/proxy-manifest')
def proxy_manifest():
    """Solo reenvía el manifiesto HLS con Referer correcto.
    Los segmentos quedan con su URL original, por lo que no pasan por Render."""
    target = request.args.get('url')
    if not target:
        return 'Falta ?url=', 400

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://ok.ru/',
        'Origin': 'https://ok.ru'
    }
    try:
        r = requests.get(target, headers=headers, timeout=15)
        ctype = r.headers.get('Content-Type','').lower()

        is_hls = 'mpegurl' in ctype or target.endswith('.m3u8') or '.m3u8' in target
        if not is_hls:
            return 'No es manifiesto HLS', 400

        text = r.text
        # Hacer URLs absolutas por si el manifiesto usa rutas relativas
        lines = []
        for line in text.splitlines():
            if line.startswith('#'):
                lines.append(line)
            elif line.strip():
                abs_url = urljoin(target, line.strip())
                lines.append(abs_url)
        body = '\n'.join(lines)

        return Response(body, headers={
            'Content-Type': 'application/vnd.apple.mpegurl',
            'Access-Control-Allow-Origin': '*',
            'Cache-Control': 'no-store'
        })
    except Exception as e:
        print(f"Proxy manifest error: {e}")
        return 'Error proxy manifest', 502

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
