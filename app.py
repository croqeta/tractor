@app.route('/proxy')
def proxy():
    target = request.args.get('url')
    if not target:
        return 'Falta ?url=', 400

    # Reenviar el Range EXACTO que pide el cliente
    client_range = request.headers.get('Range')

    headers = {
        'User-Agent': UA,
        'Referer': 'https://ok.ru/',
        'Origin': 'https://ok.ru',
        'Accept': '*/*',
    }
    # Solo pedir rango si el cliente lo pide
    if client_range:
        headers['Range'] = client_range
    # Si no hay Range, pedimos todo (OK.ru devolverá 200 con todo)

    try:
        r = requests.get(target, headers=headers, stream=True, timeout=60, allow_redirects=True)

        # Construir headers de respuesta
        resp_headers = {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, HEAD, OPTIONS',
            'Access-Control-Allow-Headers': 'Range, Content-Type, Accept, Origin, Referer',
            'Access-Control-Expose-Headers': 'Content-Length, Content-Range, Accept-Ranges',
            'Accept-Ranges': 'bytes',
        }

        # Copiar headers críticos del upstream
        for h in ['Content-Type', 'Content-Length', 'Content-Range', 'Last-Modified', 'ETag']:
            if h in r.headers:
                resp_headers[h] = r.headers[h]

        # Forzar Content-Type de video si viene raro
        ct = resp_headers.get('Content-Type', '')
        if not ct.startswith('video/') and not ct.startswith('application/octet'):
            resp_headers['Content-Type'] = 'video/mp4'
        elif ct.startswith('application/octet'):
            resp_headers['Content-Type'] = 'video/mp4'

        # Si no hay Content-Range, es una respuesta 200 completa
        if r.status_code == 200 and 'Content-Range' not in resp_headers:
            # OK, respuesta completa
            pass

        return Response(
            stream_with_context(r.iter_content(chunk_size=128 * 1024)),
            status=r.status_code,
            headers=resp_headers
        )

    except requests.exceptions.Timeout:
        return 'Timeout al pedir el video a OK.ru', 504
    except Exception as e:
        return f'Error en proxy: {e}', 500
