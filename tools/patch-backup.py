"""Add a login-protected backup page to WWW v2."""
import ast
MARK="# HPI BACKUP UI v1"
HTML='''<!doctype html><html lang="pl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>HaierPi – kopie zapasowe</title><style>body{font:16px system-ui;margin:0;color-scheme:light dark}main{max-width:900px;margin:auto;padding:16px}article{border:1px solid #8795a280;border-radius:12px;padding:16px;margin:12px 0}button{font:inherit;padding:9px;margin:4px}table{border-collapse:collapse;width:100%}td,th{padding:8px;text-align:left;border-bottom:1px solid #8795a250}.scroll{overflow:auto}a{color:inherit}</style></head>
<body><main><a href="/v2/">← Pulpit</a><h1>Kopie zapasowe HaierPi</h1>
<article><h2>Automatyczne kopie</h2><p id="timer">Odczyt…</p><p>Codziennie o 03:15 czasu Nano. Ostatnie 7 kopii, kontrola sum SHA-256 każdego pliku. Zawierają konfigurację, kod, zapisane dane uczenia, eksperyment, energię i powiadomienia. Nie są obrazem systemu; dane tylko w RAM nie są zachowane.</p><button id="create">Utwórz kopię teraz</button><button id="refresh">Odśwież</button><p id="status" role="status"></p><p id="last-operation"></p></article>
<article><h2>Dostępne kopie</h2><p>Pobierz kopię na komputer. Archiwa zawierają poufne dane dostępowe. Korzystaj z zaufanej sieci lokalnej lub VPN; nie udostępniaj ich publicznie.</p><div class="scroll"><table id="copies"></table></div></article>
<article><h2>Przywracanie</h2><p>Przywracaj wyłącznie własne archiwa. Weryfikacja sum nie potwierdza pochodzenia. Przywracanie nadpisuje pliki znajdujące się w kopii i zachowuje inne pliki. Wymaga działającej instalacji, restartuje usługę HaierPi i tworzy kopię przed zmianą. Po restarcie sprawdź tryb sterowania. Zewnętrzną kopię przywracaj z terminala po skopiowaniu do prywatnego katalogu kopii.</p><p>W przypadku awarii systemu najpierw odtwórz bazową instalację HaierPi i ten moduł backupu.</p></article>
<script>
const $=id=>document.getElementById(id);
async function request(action,name){const options={cache:"no-store",credentials:"same-origin"};if(action){options.method="POST";options.headers={"Content-Type":"application/json","X-HaierPi-CSRF":"__WV_CSRF__"};options.body=JSON.stringify({action,name:name||null})}const r=await fetch("/v2/api/backup",options);if(r.redirected)throw Error("Zaloguj się ponownie");const d=await r.json();if(!r.ok)throw Error(d.reason||"Błąd "+r.status);return d}
async function refresh(){try{const d=await request();$("timer").textContent=d.timer?"Automatyczny backup: aktywny":"Automatyczny backup: nieaktywny";const o=d.operation;$("last-operation").textContent=o?new Date(o.at*1000).toLocaleString()+" — "+o.message:"";const t=$("copies");t.replaceChildren();const h=t.insertRow();for(const x of ["Utworzono","Rozmiar","Operacje"]){const c=document.createElement("th");c.textContent=x;h.append(c)}for(const b of d.copies){const r=t.insertRow();r.insertCell().textContent=new Date(b.created*1000).toLocaleString();r.insertCell().textContent=(b.size/1024).toFixed(0)+" KiB";const cell=r.insertCell(),link=document.createElement("a");link.href="/v2/backup/download/"+encodeURIComponent(b.name);link.textContent="Pobierz";cell.append(link);const verify=document.createElement("button");verify.textContent="Sprawdź";verify.onclick=()=>operate("verify",b.name);cell.append(verify);const restore=document.createElement("button");restore.textContent="Przywróć";restore.onclick=()=>{if(confirm("Przywrócić "+b.name+"? HaierPi zostanie zrestartowany. Ustawienia i wyniki z kopii zastąpią obecne."))operate("restore",b.name)};cell.append(restore)}if(!d.copies.length)t.insertRow().insertCell().textContent="Brak kopii."}catch(e){$("status").textContent=e.message}}
async function operate(action,name){$("create").disabled=true;$("status").textContent="Wykonywanie…";try{const d=await request(action,name);$("status").textContent=d.message;if(action==="create"){setTimeout(refresh,4000)}else if(action==="restore"){setTimeout(refresh,15000)}else await refresh()}catch(e){$("status").textContent=e.message}finally{$("create").disabled=false}}
$("create").onclick=()=>operate("create");$("refresh").onclick=refresh;refresh();setInterval(refresh,15000);
</script></main></body></html>'''
ROUTES='''
@app.route("/v2/backup",methods=["GET"])
@login_required
def _wv_backup_page():
    token=_wv_session.get("_wv_csrf")
    if not isinstance(token,str) or len(token)!=64:
        token=_wv_secrets.token_hex(32)
        _wv_session["_wv_csrf"]=token
    return _wv_headers(_wv_Response(_WV_BACKUP_HTML.replace("__WV_CSRF__",token),mimetype="text/html"))

@app.route("/v2/backup/download/<name>",methods=["GET"])
@login_required
def _wv_backup_download(name):
    import runpy
    try:
        b=runpy.run_path("/opt/haier/haierpi-backup.py")
        path=b["archive_path"](name)
        response=send_file(str(path),as_attachment=True)
        return _wv_headers(response)
    except (ValueError,OSError):
        return _wv_headers(_wv_Response("Backup unavailable",status=404))

@app.route("/v2/api/backup",methods=["GET","POST"])
@login_required
def _wv_backup_api():
    import runpy
    import subprocess
    def reply(body,code=200):
        response=_wv_jsonify(body)
        response.status_code=code
        return _wv_headers(response)
    if _wv_request.method=="POST":
        token=_wv_session.get("_wv_csrf")
        sent=_wv_request.headers.get("X-HaierPi-CSRF","")
        if not isinstance(token,str) or len(token)!=64 or not _wv_secrets.compare_digest(token,sent) or _wv_request.headers.get("Origin")!=_wv_request.host_url.rstrip("/"):
            return reply({"reason":"Unauthorized request"},403)
        if not _wv_request.is_json or _wv_request.content_length is None or _wv_request.content_length>1024:
            return reply({"reason":"Invalid request"},400)
    try:
        b=runpy.run_path("/opt/haier/haierpi-backup.py")
        if _wv_request.method=="GET":
            return reply({"copies":b["archives"](),"timer":b["active"]("haierpi-backup.timer"),"operation":b["last_operation"]()})
        d=_wv_request.get_json(silent=True)
        if not isinstance(d,dict) or set(d)!={"action","name"}:
            raise ValueError("Invalid request")
        if d["action"]=="create" and d["name"] is None:
            subprocess.run(["systemctl","start","--no-block","haierpi-backup.service"],check=True,timeout=10)
            return reply({"message":"Zlecono wykonanie kopii. Lista odświeży się automatycznie."},202)
        if d["action"]=="verify":
            b["validate"](b["archive_path"](d["name"]))
            return reply({"message":"Sprawdzono strukturę archiwum i sumy SHA-256."})
        if d["action"]=="restore":
            b["archive_path"](d["name"])
            # Fixed transient unit name prevents concurrent restore launches.
            subprocess.run(["systemd-run","--unit=haierpi-backup-restore","--collect",
                "--property=TimeoutStartSec=600","/opt/haier/env/bin/python",
                "/opt/haier/haierpi-backup.py","--restore",d["name"]],check=True,timeout=15)
            return reply({"message":"Rozpoczęto przywracanie. Po restarcie sprawdź stan operacji i tryb sterowania."},202)
        raise ValueError("Invalid action")
    except (ValueError,TypeError):
        return reply({"reason":"Invalid backup or request"},400)
    except (OSError,subprocess.SubprocessError,RuntimeError):
        return reply({"reason":"Backup operation unavailable; check system journal"},409)
'''
def patch(source):
    if MARK in source:
        if source.count(MARK)!=1 or "def _wv_backup_api():" not in source:
            raise ValueError("Incomplete backup patch")
        return source
    tree=ast.parse(source)
    lines=source.splitlines(keepends=True)
    nodes=[n for n in tree.body if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name) and n.targets[0].id=="_WV_HTML"]
    if len(nodes)!=1:
        raise ValueError("Missing WWW v2")
    n=nodes[0]
    html=ast.literal_eval(n.value)
    if html.count("</nav>")!=1:
        raise ValueError("Missing navigation")
    html=html.replace("</nav>",'<a href="/v2/backup">Backup</a></nav>')
    lines[n.lineno-1:n.end_lineno]=["_WV_HTML = "+ascii(html)+"\n"]
    source="".join(lines)
    anchor="# HOME-IOT WEB UI V2 END"
    if source.count(anchor)!=1:
        raise ValueError("Missing WWW marker")
    source=source.replace(anchor,MARK+"\n_WV_BACKUP_HTML = "+ascii(HTML)+"\n"+ROUTES+"\n"+anchor)
    compile(source,"main.py","exec")
    return source
