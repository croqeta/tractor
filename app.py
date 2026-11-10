from flask import Flask, request, jsonify, Response, stream_with_context
import subprocess
import os
import json as jsonlib
import re
import requests
from urllib.parse import urljoin, quote

app = Flask(__name__)

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

# ---------- EXTRAER TODAS LAS CALIDADES DESDE data-options ----------
def get_all_qualities_okru(video_url):
    """
    Extrae todas las calidades disponibles parseando el JSON 'data-options'
    del iframe de videoembed de OK.ru.
    """
    try:
        # Extraer el ID del video
        m = re.search(r'/video/(\d+)', video_url)
        if not m:
            print("No se pudo extraer el ID del video")
            return None
        video_id = m.group(1)

        # Petición al iframe de videoembed
        embed_url = f"https://ok.ru/videoembed/{video_id}"
        headers = {
            'User-Agent': UA,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
            'Referer': 'https://ok.ru/'
        }
        r = requests.get(embed_url, headers=headers, timeout=30)
        if r.status_code != 200:
            print(f"HTTP {r.status_code} al pedir videoembed")
            return None

        html = r.text

        # Buscar el atributo data-options
        match = re.search(r'data-options\s*=\s*"((?:[^"\\]|\\.)*)"', html)
        if not match:
            match = re.search(r"data-options\s*=\s*'([^']*)'", html)
        if not match:
            print("No se encontró data-options en el HTML")
            return None

        # Decodificar entidades HTML
        raw = match.group(1)
        raw = (raw.replace('&quot;', '"')
                    .replace('&#34;', '"')
                    .replace('&apos;', "'")
                    .replace('&#39;', "'")
                    .replace('&amp;', '&')
                    .replace('&lt;', '<')
                    .replace('&gt;', '>')
                    .replace('&#x2F;', '/'))

        try:
            data = jsonlib.loads(raw)
        except Exception as e:
            print(f"Error parseando JSON: {e}")
            return None

        # Navegar hasta la lista de videos
        videos = None
        flashvars = data.get('flashvars') or data
        metadata = flashvars.get('metadata')
        if isinstance(metadata, str):
            try:
                metadata = jsonlib.loads(metadata)
            except Exception:
                metadata = None
        if metadata and isinstance(metadata.get('videos'), list):
            videos = metadata['videos']
        if not videos and isinstance(data.get('videos'), list):
            videos = data['videos']

        if not videos:
            print("No se encontró la lista de videos en el JSON")
            return None

        # Mapeo de nombres internos a resolución visible
        NAME_TO_RES = {
            'mobile':  {'label': '144p', 'height': 144},
            'lowest':  {'label': '240p', 'height': 240},
            'low':     {'label': '360p', 'height': 360},
            'sd':      {'label': '480p', 'height': 480},
            'hd':      {'label': '720p HD', 'height': 720},
            'full':    {'label': '1080p Full HD', 'height': 1080},
            'quad':    {'label': '1440p Quad HD', 'height': 1440},
            'ultra':   {'label': '2160p 4K', 'height': 2160},
        }

        results = []
        for v in videos:
            if not v or not v.get('url'):
                continue
            name = (v.get('name') or '').lower()
            info = NAME_TO_RES.get(name)
            h = v.get('height') or (info['height'] if info else None)
            w = v.get('width') or (int(h * 16 / 9) if h else None)
            label = info['label'] if info else (f'{h}p' if h else name)

            results.append({
                'name': name,
                'label': label,
                'height': h,
                'width': w,
                'url': v['url'],
                'is_audio': False
            })

        return results

    except Exception as e:
        print(f"Error en get_all_qualities_okru: {e}")
        return None

# ---------- EXTRAER CALIDADES PARA VK ----------
# Nuevo plan: yt-dlp primero (mantiene VK al día), streamlink como fallback.
def _vk_ytdlp(video_url):
    """Intento principal: yt-dlp (soporte activo y actualizado para VK)."""
    try:
        cmd = [
            'yt-dlp',
            '--no-warnings',
            '--no-playlist',
            '--no-check-certificate',
            '--geo-bypass',
            '--user-agent', UA,
            '--referer', 'https://vk.com/',
            '--add-header', 'Accept-Language:es-ES,es;q=0.9,en;q=0.8',
            '-J',  # volcar toda la info del video como JSON
            video_url
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=55)
        if r.returncode != 0:
            print(f"[VK/yt-dlp] rc={r.returncode}")
            print(f"[VK/yt-dlp] stderr:\n{r.stderr[:1500]}")
            return None

        data = jsonlib.loads(r.stdout)
        formats = data.get('formats') or []
        if not formats:
            print("[VK/yt-dlp] Sin formats en la respuesta")
            return None

        results = []
        seen = set()
        for f in formats:
            u = f.get('url')
            if not u:
                continue
            vcodec = (f.get('vcodec') or '').lower()
            acodec = (f.get('acodec') or '').lower()
            is_audio = (vcodec == 'none' and acodec != 'none')
            h = f.get('height') or 0
            w = f.get('width')
            fid = f.get('format_id') or ''
            fnote = f.get('format_note') or ''

            if is_audio:
                label = 'Audio'
            elif h:
                label = f'{h}p' + (' HD' if h >= 720 else '') + (' 4K' if h >= 2000 else '')
            else:
                label = fnote or fid or 'Video'

            # Evitar duplicados de misma altura (audio se mantiene)
            key = ('a' if is_audio else 'v', h)
            if key in seen:
                continue
            seen.add(key)

            results.append({
                'name': fid or fnote or label,
                'label': label,
                'height': h,
                'width': w or (int(h * 16 / 9) if h else None),
                'url': u,
                'is_audio': is_audio
            })

        if not results:
            print("[VK/yt-dlp] Formats vacíos tras filtrado")
            return None
        return results

    except Exception as e:
        print(f"[VK/yt-dlp] excepción: {type(e).__name__}: {e}")
        return None


def _vk_streamlink(video_url):
    """Fallback: streamlink (el que ya tenías)."""
    try:
        cmd = [
            'streamlink', '--json', '--loglevel', 'error',
            '--http-header', 'Referer=https://vk.com/',
            '--http-header', f'User-Agent={UA}',
            video_url
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=40)
        if r.returncode != 0:
            print(f"[VK/streamlink] stderr: {r.stderr[:800]}")
            return None
        data = jsonlib.loads(r.stdout)
        streams = data.get('streams', {})
        if not streams:
            return None

        results = []
        for name, info in streams.items():
            u = info.get('url')
            if not u:
                continue
            h = None
            m = re.match(r'(\d+)p', name)
            if m:
                h = int(m.group(1))
            label = f'{h}p' + (' HD' if h and h >= 720 else '') if h else name
            results.append({
                'name': name,
                'label': label,
                'height': h,
                'width': int(h * 16 / 9) if h else None,
                'url': u,
                'is_audio': name.lower() == 'audio'
            })
        return results or None
    except Exception as e:
        print(f"[VK/streamlink] excepción: {type(e).__name__}: {e}")
        return None


def get_all_qualities_vk(video_url):
    """yt-dlp primero; si falla, streamlink como respaldo."""
    print(f"[VK] intentando yt-dlp con {video_url}")
    r = _vk_ytdlp(video_url)
    if r:
        print(f"[VK] yt-dlp OK, {len(r)} formatos")
        return r
    print("[VK] yt-dlp falló, probando streamlink")
    r = _vk_streamlink(video_url)
    if r:
        print(f"[VK] streamlink OK, {len(r)} formatos")
    else:
        print("[VK] ambos extractores fallaron")
    return r

# ---------- ENDPOINT: LISTAR TODAS LAS CALIDADES ----------
@app.route('/resolve')
def resolve():
    url = request.args.get('url')
    if not url:
        return jsonify({'error': 'Falta ?url='}), 400

    is_vk = bool(re.search(r'vk\.com|vkvideo\.ru|vk\.ru', url, re.I))
    is_ok = bool(re.search(r'ok\.ru', url, re.I))

    if is_ok:
        results = get_all_qualities_okru(url)
    elif is_vk:
        results = get_all_qualities_vk(url)
    else:
        return jsonify({'error': 'URL no soportada'}), 400

    if not results:
        return jsonify({'error': 'No se pudieron obtener las calidades del video'}), 500

    # Ordenar de mayor a menor, audio al final
    video_results = [q for q in results if not q['is_audio']]
    audio_results = [q for q in results if q['is_audio']]
    video_results.sort(key=lambda x: (x.get('height') or 0), reverse=True)
    results = video_results + audio_results

    if not results:
        return jsonify({'error': 'No hay calidades de video disponibles'}), 500

    best = results[0]

    return jsonify({
        'best': best,
        'all': results,
        'source': url,
        'count': len(results),
        'status': 'ok'
    })

# ---------- ENDPOINT: PROXY (MP4 + HLS) ----------
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

        content_type = r.headers.get('Content-Type', '').lower()
        is_m3u8 = (
            'mpegurl' in content_type
            or target.endswith('.m3u8')
            or '/m3u8' in target
        )

        # ---------- CASO 1: MANIFIESTO HLS ----------
        if is_m3u8:
            content = r.text
            base_proxy = request.host_url.rstrip('/')
            new_lines = []

            for line in content.split('\n'):
                stripped = line.strip()
                if not stripped:
                    new_lines.append(line)
                    continue

                if stripped.startswith('#'):
                    if 'URI="' in stripped:
                        def replace_uri(m):
                            uri = m.group(1)
                            absolute = uri if uri.startswith('http') else urljoin(target, uri)
                            proxied = f"{base_proxy}/proxy?url={quote(absolute, safe='')}"
                            return f'URI="{proxied}"'
                        stripped = re.sub(r'URI="([^"]+)"', replace_uri, stripped)
                    new_lines.append(stripped)
                else:
                    absolute = stripped if stripped.startswith('http') else urljoin(target, stripped)
                    proxied = f"{base_proxy}/proxy?url={quote(absolute, safe='')}"
                    new_lines.append(proxied)

            new_content = '\n'.join(new_lines)

            return Response(
                new_content,
                status=200,
                headers={
                    'Content-Type': 'application/vnd.apple.mpegurl',
                    'Access-Control-Allow-Origin': '*',
                    'Access-Control-Allow-Methods': 'GET, HEAD, OPTIONS',
                    'Access-Control-Allow-Headers': 'Range, Content-Type, Accept, Origin, Referer',
                    'Access-Control-Expose-Headers': 'Content-Length, Content-Range, Accept-Ranges',
                    'Cache-Control': 'no-store',
                }
            )

        # ---------- CASO 2: SEGMENTO O VIDEO MP4 ----------
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

        ct = resp_headers.get('Content-Type', '').lower()
        if target.endswith('.ts') or 'mp2t' in ct:
            resp_headers['Content-Type'] = 'video/mp2t'
        elif not ct.startswith('video/') and not ct.startswith('application/octet'):
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

@app.route('/health')
def health():
    return jsonify({'status': 'ok'}), 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
