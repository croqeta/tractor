from flask import Flask, request, jsonify, Response, stream_with_context
import subprocess, os, requests
from urllib.parse import urljoin, quote

app = Flask(__name__)

def get_stream_url(video_url, quality="best"):
    try:
        cmd = [
            'streamlink','--stream-url','--loglevel','error',
            '--http-header','Referer=https://ok.ru/',
            '--http-header','User-Agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36',
            video_url, quality
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return r.stdout.strip() if r.returncode==0 else None
    except Exception as e:
        print(f"Error streamlink: {e}")
        return None

@app.route('/resolve')
def resolve():
    url = request.args.get('url')
    if not url: return jsonify({'error':'Falta ?url='}),400
    stream_url = get_stream_url(url)
    if not stream_url: return jsonify({'error':'No se pudo extraer'}),500
    return jsonify({'url':stream_url,'source':url,'status':'ok'})

@app.route('/proxy')
def proxy():
    target = request.args.get('url')
    if not target: return 'Falta ?url=',400

    headers = {
        'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36',
        'Referer':'https://ok.ru/',
        'Origin':'https://ok.ru'
    }
    range_h = request.headers.get('Range')
    if range_h: headers['Range']=range_h

    try:
        r = requests.get(target, headers=headers, stream=True, timeout=(10,None))
        ctype = r.headers.get('Content-Type','').lower()

        # HLS / DASH -> reescribir manifiesto
        if 'mpegurl' in ctype or target.endswith('.m3u8') or '.m3u8' in target:
            text = r.text
            lines=[]
            for line in text.splitlines():
                if line.startswith('#'):
                    lines.append(line)
                elif line.strip():
                    seg = urljoin(target, line.strip())
                    lines.append(f"/proxy?url={quote(seg,safe='')}")
            body = '\n'.join(lines)
            return Response(body, headers={
                'Content-Type':'application/vnd.apple.mpegurl',
                'Access-Control-Allow-Origin':'*',
                'Cache-Control':'no-store'
            })

        # Binario normal con MIME real y Range
        resp_headers = {
            'Access-Control-Allow-Origin':'*',
            'Access-Control-Expose-Headers':'Content-Length, Content-Range, Accept-Ranges',
            'Accept-Ranges':'bytes'
        }
        for h in ['Content-Type','Content-Length','Content-Range','Accept-Ranges','Last-Modified','ETag']:
            if h in r.headers: resp_headers[h]=r.headers[h]

        if 'Content-Type' not in resp_headers:
            if target.endswith('.m3u8'): resp_headers['Content-Type']='application/vnd.apple.mpegurl'
            elif target.endswith('.mpd'): resp_headers['Content-Type']='application/dash+xml'
            elif target.endswith('.ts'): resp_headers['Content-Type']='video/mp2t'
            else: resp_headers['Content-Type']='video/mp4'

        return Response(
            stream_with_context(r.iter_content(chunk_size=8192)),
            status=r.status_code,
            headers=resp_headers,
            direct_passthrough=True
        )
    except Exception as e:
        print(f"Proxy Error: {e}")
        return "Error proxy",502

@app.route('/health')
def health(): return jsonify({'status':'ok'})
