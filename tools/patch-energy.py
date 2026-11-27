"""Authenticated optional energy configuration and report page."""
import ast

MARK="# HPI ENERGY UI v1"
HTML='''<!doctype html><html lang="pl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>HaierPi – energia</title>
<style>body{font:16px system-ui;margin:0;color-scheme:light dark}main{max-width:1000px;margin:auto;padding:16px}article{border:1px solid #8795a280;border-radius:12px;padding:16px;margin:12px 0}label{display:block;margin:10px 0}input:not([type=checkbox]),select{display:block;box-sizing:border-box;width:100%;padding:8px;font:inherit}button{padding:10px;margin:4px;font:inherit}small{opacity:.8}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:8px;text-align:left;border-bottom:1px solid #8795a250}.scroll{overflow:auto}a{color:inherit}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:10px}</style></head>
<body><main><a href="/v2/">← Pulpit</a> · <a href="/v2/adaptive-report">Raport Adaptive</a><h1>Energia i przepływ</h1>
<article><h2>Konfiguracja</h2><label><input id="enabled" type="checkbox"> Monitoring energii</label>
<label>Źródło elektryczne<select id="source"><option value="ha">Home Assistant</option><option value="mqtt">MQTT (zewnętrzny temat)</option></select></label>
<div class="grid"><label>Licznik narastający (encja lub temat)<input id="energy" maxlength="180" placeholder="sensor.energy_meter"></label><label>Jednostka<select id="energy_unit"><option>kWh</option><option>Wh</option></select></label>
<label>Moc chwilowa (opcjonalna)<input id="power" maxlength="180" placeholder="sensor.power"></label><label>Jednostka<select id="power_unit"><option>W</option><option>kW</option></select></label></div>
<label>Źródło przepływu<select id="flow_source"><option value="none">Brak pomiaru</option><option value="manual">Wartość ręczna</option><option value="ha">Home Assistant</option><option value="mqtt">MQTT</option></select></label>
<div class="grid"><label>Przepływ ręczny [m³/h]<input id="manual_flow" type="number" min="0" max="30" step="0.01"></label><label>Encja lub temat przepływu<input id="flow" maxlength="180" placeholder="sensor.water_flow"></label><label>Jednostka czujnika<select id="flow_unit"><option value="m3/h">m³/h</option><option>l/min</option><option>l/h</option></select></label></div>
<label>Interwał<select id="interval"><option value="30">30 s</option><option value="60">60 s</option></select></label>
<button id="test">Test odczytu</button><button id="save">Zapisz</button><p id="action" role="status"></p>
<small>HA: używa istniejącego adresu i tokenu HaierPi. MQTT: ten sam broker, dokładne tematy pomiarowe poza tematami sterowania HaierPi; wymagane okresowe świeże wiadomości liczbowe, nie tylko retained. Test nowych tematów MQTT po zapisaniu. Zmiana konfiguracji zeruje bieżącą historię energetyczną w RAM.</small></article>
<article><h2>Ostatni odczyt</h2><p id="latest"></p><p id="coverage"></p><button id="refresh">Odśwież</button></article>
<article><h2>Bilans ostatnich 24 h</h2><div class="scroll"><table id="groups"></table></div><h3>Konfiguracje CO</h3><div class="scroll"><table id="modes"></table></div></article>
<article><h2>Test aktywny – bilans konfiguracji</h2><div class="scroll"><table id="experiment"></table></div><small>Bilans przedziałów od włączenia monitoringu, nie pełne cykle. Ciepło szacowane z dodatniego ΔT i przepływu wyłącznie w pracy CO. COP dotyczy tylko przedziałów z obu pomiarami, bez postoju i odszraniania. Historia w RAM, restart ją zeruje. Brak danych nie jest zerem. Nie służy do sterowania.</small></article>
<script>
const $=id=>document.getElementById(id),keys=["enabled","source","energy","energy_unit","power","power_unit","flow_source","flow","flow_unit","manual_flow","interval"];
const fmt=x=>typeof x==="number"&&Number.isFinite(x)?x.toFixed(3):"—";
function form(){let d={};for(const k of keys)d[k]=k==="enabled"?$(k).checked:["interval","manual_flow"].includes(k)?Number($(k).value):$(k).value;return d}
function fill(d){for(const k of keys){if(k==="enabled")$(k).checked=d[k];else $(k).value=d[k]}}
function table(id,rows){const t=$(id);t.replaceChildren();let h=t.insertRow();for(const x of ["Stan / tryb","Czas h","Prąd kWh","Ciepło szac. kWh","COP szac. (praca CO)","Pokrycie COP h"]){let c=document.createElement("th");c.textContent=x;h.append(c)}for(const [k,v] of Object.entries(rows||{})){let r=t.insertRow();for(const x of [k,fmt(v.seconds/3600),fmt(v.kwh),v.paired_seconds?fmt(v.heat_kwh):"—",fmt(v.cop_estimate),fmt(v.paired_seconds/3600)])r.insertCell().textContent=x}}
async function json(url,opts={}){const c=new AbortController(),timer=setTimeout(()=>c.abort(),22000);try{const r=await fetch(url,{credentials:"same-origin",cache:"no-store",signal:c.signal,...opts});if(r.redirected)throw Error("Zaloguj się ponownie");const d=await r.json();if(!r.ok)throw Error(d.reason||"Błąd "+r.status);return d}finally{clearTimeout(timer)}}
async function refresh(loadForm=false){try{const d=await json("/v2/api/energy");if(loadForm)fill(d.settings);const x=d.current||{};$("latest").textContent=(d.settings.enabled?"Monitoring włączony":"Monitoring wyłączony")+" · licznik "+fmt(x.energy)+" kWh · moc "+fmt(x.power)+" kW · przepływ "+fmt(x.flow)+" m³/h"+(d.error?" · "+d.error:"");$("coverage").textContent="Pokrycie: "+fmt(d.coverage_seconds/3600)+" h · "+(d.electricity_estimated?"prąd szacowany z mocy":"prąd z licznika")+" · "+(d.flow_estimated?"przepływ założony":"przepływ z czujnika lub brak");table("groups",d.groups_24h);table("modes",d.modes_24h);table("experiment",d.experiment)}catch(e){$("latest").textContent=e.message}}
async function action(op){$("test").disabled=$("save").disabled=true;$("action").textContent="Odczyt…";try{const d=await json("/v2/api/energy",{method:"POST",headers:{"Content-Type":"application/json","X-HaierPi-CSRF":"__WV_CSRF__"},body:JSON.stringify({action:op,settings:form()})});$("action").textContent=op==="save"?"Zapisano. Odczyt przy następnym cyklu.":"Odczyt: "+JSON.stringify(d.values)+"; brak: "+d.missing.join(", ")+(d.mqtt_requires_saved_settings?" · Zapisz nowe tematy MQTT przed testem.":"");if(op==="save")await refresh()}catch(e){$("action").textContent=e.message}finally{$("test").disabled=$("save").disabled=false}}
$("test").onclick=()=>action("test");$("save").onclick=()=>action("save");$("refresh").onclick=()=>refresh();refresh(true);
</script></main></body></html>'''

ROUTES='''
@app.route("/v2/energy",methods=["GET"])
@login_required
def _wv_energy_page():
    token=_wv_session.get("_wv_csrf")
    if not isinstance(token,str) or len(token)!=64:
        token=_wv_secrets.token_hex(32)
        _wv_session["_wv_csrf"]=token
    return _wv_headers(_wv_Response(_WV_ENERGY_HTML.replace("__WV_CSRF__",token),mimetype="text/html"))

@app.route("/v2/api/energy",methods=["GET","POST"])
@login_required
def _wv_energy_api():
    def reply(body,code=200):
        response=_wv_jsonify(body)
        response.status_code=code
        return _wv_headers(response)
    if _wv_request.method=="GET":
        return reply(_am.energy.summary())
    token=_wv_session.get("_wv_csrf")
    sent=_wv_request.headers.get("X-HaierPi-CSRF","")
    if not isinstance(token,str) or len(token)!=64 or not _wv_secrets.compare_digest(token,sent) or _wv_request.headers.get("Origin")!=_wv_request.host_url.rstrip("/"):
        return reply({"reason":"Brak autoryzacji żądania"},403)
    if not _wv_request.is_json or _wv_request.content_length is None or _wv_request.content_length>4096:
        return reply({"reason":"Niepoprawne żądanie"},400)
    try:
        d=_wv_request.get_json(silent=True)
        if not isinstance(d,dict) or set(d)!={"action","settings"}:
            raise ValueError("Invalid request")
        if d["action"]=="save":
            _am.energy.save(d["settings"])
            return reply({"saved":True})
        if d["action"]=="test":
            return reply(_am.energy.probe(d["settings"]))
        raise ValueError("Invalid action")
    except (ValueError,TypeError):
        return reply({"reason":"Nieprawidłowa konfiguracja lub odczyt zajęty"},400)
    except OSError:
        return reply({"reason":"Nie można zapisać ustawień"},409)
'''

def patch(source):
    if MARK in source:
        if source.count(MARK)!=1 or "def _wv_energy_api():" not in source:
            raise ValueError("Incomplete energy patch")
        return source
    lines=source.splitlines(keepends=True)
    tree=ast.parse(source)
    for n in reversed(tree.body):
        if not isinstance(n,ast.Assign) or len(n.targets)!=1 or not isinstance(n.targets[0],ast.Name):
            continue
        name=n.targets[0].id
        if name not in ("_WV_HTML","_WV_ADAPTIVE_REPORT_HTML"):
            continue
        html=ast.literal_eval(n.value)
        anchor="</nav>" if name=="_WV_HTML" else "</header>"
        if html.count(anchor)!=1:
            raise ValueError("Unexpected energy navigation")
        html=html.replace(anchor,'<a href="/v2/energy">Energia</a>'+anchor,1)
        lines[n.lineno-1:n.end_lineno]=[name+" = "+repr(html)+"\n"]
    source="".join(lines)
    def once(old,new):
        nonlocal source
        if source.count(old)!=1:
            raise ValueError("Unexpected energy anchor: "+old[:100])
        source=source.replace(old,new,1)
    once("# HOME-IOT WEB UI V2 END",MARK+"\n_WV_ENERGY_HTML = "+repr(HTML)+"\n"+ROUTES+"\n# HOME-IOT WEB UI V2 END")
    # Callbacks run after initialization; no separate MQTT client.
    once("def on_connect(client, userdata, flags, rc):\n","def on_connect(client, userdata, flags, rc):\n    if rc==0:\n        _am.energy.mqtt_connect(client)\n")
    once("def on_disconnect(client, userdata, rc):  # The callback for when\n","def on_disconnect(client, userdata, rc):  # The callback for when\n    _am.energy.mqtt_disconnect(client)\n")
    # Use the exact existing watchdog statement as anchor, before command parsing.
    once('    if msg.topic == str(mqtt_topic) + "/haierpi/watchdog_heartbeat":\n','    if _am.energy.mqtt_message(client,msg):\n        return\n    if msg.topic == str(mqtt_topic) + "/haierpi/watchdog_heartbeat":\n')
    compile(source,"main.py","exec")
    return source
