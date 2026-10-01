from flask import Flask, request, jsonify, Response, stream_with_context
import subprocess
import os
import requests

app = Flask(__name__)

def get_stream_url(video_url, quality="best"):
    try:
        command = [
            'streamlink', '--stream-url', '--loglevel', 'error',
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

# NUEVO: proxy de streaming
@app.route('/proxy')
def proxy():
    """Descarga el video desde Render y lo sirve al cliente."""
    target = request.args.get('url')
    if not target:
        return 'Falta ?url=', 400

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://ok.ru/',
        'Origin': 'https://ok.ru',
        'Range': request.headers.get('Range', 'bytes=0-')
    }

    r = requests.get(target, headers=headers, stream=True)
    return Response(
        stream_with_context(r.iter_content(chunk_size=65536)),
        status=r.status_code,
        headers={
            'Content-Type': 'video/mp4',
            'Accept-Ranges': 'bytes',
            'Access-Control-Allow-Origin': '*',
            'Content-Length': r.headers.get('Content-Length', ''),
            'Content-Range': r.headers.get('Content-Range', '')
        }
    )

@app.route('/health')
def health():
    return jsonify({'status': 'ok'}), 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
