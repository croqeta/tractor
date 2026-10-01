# app.py
from flask import Flask, request, jsonify
import subprocess
import os

app = Flask(__name__)

def get_stream_url(video_url, quality="best"):
    try:
        # Comando que ejecuta streamlink para extraer la URL directa
        command = [
            'streamlink',
            '--stream-url',
            '--loglevel', 'error',
            '--http-header', 'Referer=https://ok.ru/',
            '--http-header', 'User-Agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            video_url,
            quality
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        else:
            print(f"Error: {result.stderr.strip()}")
            return None
    except subprocess.TimeoutExpired:
        print("Timeout")
        return None
    except Exception as e:
        print(f"Error inesperado: {e}")
        return None

@app.route('/resolve')
def resolve():
    url = request.args.get('url')
    quality = request.args.get('quality', 'best')
    if not url:
        return jsonify({'error': 'Falta el parámetro ?url='}), 400
    stream_url = get_stream_url(url, quality)
    if not stream_url:
        return jsonify({'error': 'No se pudo extraer el enlace'}), 500
    return jsonify({
        'url': stream_url,
        'quality': quality,
        'source': url,
        'status': 'ok'
    })

@app.route('/health')
def health():
    return jsonify({'status': 'ok'}), 200

if __name__ == '__main__':
    # Render usa la variable de entorno PORT, con 10000 por defecto
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)