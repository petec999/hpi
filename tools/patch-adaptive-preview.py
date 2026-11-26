"""Validated source transformation for the experimental integrated preview."""
import ast
from pathlib import Path
import runpy

ROOT=Path(__file__).resolve().parents[1]
MARK="# HOME-IOT ADAPTIVE MODULATION PREVIEW v1"
WEB=runpy.run_path(str(ROOT/"tools/install-web-ui-v2.py"))

UI_HTML="""<article class="card ctlcard"><h3>AntiON-OFF v2</h3>
<div class="ctlrow"><select id="am-control" aria-label="Sterowanie modulacją" disabled>
<option value="legacy">Legacy – oryginalna automatyka</option><option value="manual">Ręczne</option><option value="shadow">Obserwacja</option><option value="auto">Auto – eksperymentalne</option></select>
<button id="am-save" class="primary" disabled>Zastosuj</button></div>
<div class="metric"><span>Tryb / zworka (odczyt)</span><strong id="am-actual">—</strong></div>
<div class="ctlrow"><button id="am-relay-on" disabled>FLimit ON</button><button id="am-relay-off" disabled>FLimit OFF</button></div>
<div class="metric"><span>Propozycja regulatora</span><strong id="am-proposed">—</strong></div>
<div class="metric"><span>Stan / ryzyko</span><strong id="am-risk">—</strong></div>
<div class="metric"><span>Odczytana nastawa CO</span><strong id="am-target">—</strong></div>
<div class="metric"><span>Prognozowana nadwyżka</span><strong id="am-forecast">—</strong></div>
<p id="am-reason" role="status">Oczekiwanie na dane.</p>
<small>Auto jest eksperymentalne. Legacy pozostaje domyślne po restarcie. CWU, odszranianie i wymuszone strefy mają priorytet. Sterowanie ręczne profilem w Auto przełącza na Ręczne.</small></article>"""
UI_JS="""
let amState=null,amBusy=false,amDirty=false;
function amPaint(a){
 amState=a||null;const v=amState||{};
 if(!amDirty)$("am-control").value=v.control||"legacy";
 $("am-control").disabled=!amState||amBusy;
 $("am-save").disabled=!amState||amBusy||!amDirty;
 for(const [id,val] of [["am-relay-on","1"],["am-relay-off","0"]])$(id).disabled=!amState||amBusy||!v.ready||v.pending||v.relay===val||!["manual","auto"].includes(v.control);
 $("am-actual").textContent=v.mode?v.mode+" / FLimit "+(v.relay==="1"?"ON":"OFF"):"—";
 $("am-proposed").textContent=v.proposed||"—";
 $("am-risk").textContent=v.risk||"—";
 $("am-target").textContent=fmt(v.target)+" °C";
 $("am-forecast").textContent=fmt(v.forecast)+" K";
 $("am-reason").textContent=v.fault||v.reason||"Brak odczytu.";
}
$("am-control").addEventListener("change",()=>{amDirty=!!amState&&$("am-control").value!==amState.control;amPaint(amState)});
async function amSend(key,value){
 if(!amState||amBusy)return;
 const expected=key==="adaptive_control"?amState.control:amState.relay;
 if(expected===value||expected===null)return;
 amBusy=true;amPaint(amState);
 const ctrl=new AbortController(),timer=setTimeout(()=>ctrl.abort(),20000);
 try{
  const res=await fetch("./api/control",{method:"POST",credentials:"same-origin",cache:"no-store",headers:{"Content-Type":"application/json","X-HaierPi-CSRF":document.querySelector('meta[name="wv-csrf"]').content},body:JSON.stringify({key,value,expected}),signal:ctrl.signal});
  if(!res.ok||res.redirected||!(await res.json()).accepted)throw Error("rejected");
  amDirty=false;amPaint(null);$("am-reason").textContent="Polecenie przyjęte; czekam na odczyt.";
 }catch(e){amPaint(null);$("am-reason").textContent="Polecenie niepotwierdzone. Sprawdź aktualny stan; brak automatycznej ponawiania."}
 finally{clearTimeout(timer);amBusy=false;}
}
$("am-save").addEventListener("click",()=>amSend("adaptive_control",$("am-control").value));
$("am-relay-on").addEventListener("click",()=>amSend("flimiton","1"));
$("am-relay-off").addEventListener("click",()=>amSend("flimiton","0"));
"""

def once(s,old,new):
    if s.count(old)!=1:
        raise ValueError("Unexpected anchor: "+old[:120])
    return s.replace(old,new,1)

def patch_web(s):
    # Start from exactly the earlier, hardware-tested Stage 2 block.
    s=WEB["patch"](s)
    base=WEB["BLOCK"]
    line=next(x for x in base.splitlines() if x.startswith("_WV_HTML = "))
    html=ast.literal_eval(line.split("=",1)[1].strip())
    html=once(html,'<article class="card ctlcard"><h3>Zaawansowane</h3>',UI_HTML+'<article class="card ctlcard"><h3>Zaawansowane</h3>')
    html=once(html,"function plot(){",UI_JS+"\nfunction plot(){")
    html=once(html,"plot();ctlUpdate(d);","plot();ctlUpdate(d);amPaint(d.adaptive);")
    html=once(html,"available=false;live={};if(pending", "available=false;live={};amPaint(null);if(pending")
    b=once(base,line,"_WV_HTML = "+repr(html))
    b=once(b,'"controls":_wv_controls(g), "control_ready":','"controls":_wv_controls(g), "adaptive":_am.view(), "control_ready":')
    b=once(b,"    return out\n\ndef _wv_ready",'''    am=_am.view()
    out["adaptive_control"]=am["control"]
    out["flimiton"]=am["relay"]
    return out

def _wv_ready''')
    b=once(b,'    if key in ("settemp","dhw"):', '''    if key in ("adaptive_control","flimiton"):
        choices=("legacy","manual","shadow","auto") if key=="adaptive_control" else ("0","1")
        if value not in choices or expected not in choices:
            raise ValueError("invalid adaptive control")
    elif key in ("settemp","dhw"):''')
    b=once(b,'    if key in ("pch","pdhw"):\n        g["statechange"]', '''    if key=="adaptive_control":
        raise RuntimeError("selection requires expected state")
    elif key=="flimiton":
        _,ok=_am.manual("relay",value)
        if ok!="success":
            raise RuntimeError("relay rejected")
    elif key in ("pch","pdhw"):
        g["statechange"]''')
    b=once(b,'_,ok=g["new_presetchange"](value)','_,ok=_am.manual("preset",value)')
    b=once(b,'if not state["control_ready"] or current is None or current!=expected:', 'if (key!="adaptive_control" and not state["control_ready"]) or current is None or current!=expected:')
    b=once(b,'            _wv_execute(g,key,value)', '''            if key=="adaptive_control":
                _am.choose(value,expected)
            elif key=="flimiton":
                with _am.lock:
                    a=_am.view()
                    if a["control"] not in ("manual","auto") or a["relay"]!=expected or not a["ready"] or a["pending"]:
                        raise ValueError("relay control unavailable")
                    _wv_execute(g,key,value)
            else:
                _wv_execute(g,key,value)''')
    return once(s,base,b)

def activation_api(source):
    old='                _am.choose(value,expected)'
    new='''                try:
                    _am.choose(value,expected)
                except _am_sys.modules["_hpi_adaptive_runtime"].SelectionBlocked as exc:
                    return reply({"accepted":False,"reason":str(exc)},409)'''
    if new in source:
        return source
    return once(source,old,new)

def activation_ui(html):
    if 'id="am-owner"' in html:
        return html
    html=once(html,'<div class="metric"><span>Tryb / zworka (odczyt)</span>',
        '<div class="metric"><span>Aktywne sterowanie</span><strong id="am-owner">—</strong></div><p id="am-activation" role="status"></p><div class="metric"><span>Tryb / zworka (odczyt)</span>')
    html=once(html,'let amState=null,amBusy=false,amDirty=false;',
        'let amState=null,amBusy=false,amDirty=false,amError="";')
    html=once(html,' if(!amDirty)$("am-control").value=v.control||"legacy";',
        ''' if(v.control&&(!amDirty||$("am-control").value===v.control)){amDirty=false;$("am-control").value=v.control;}
 $("am-owner").textContent=({legacy:"Legacy",manual:"Ręczne",shadow:"Obserwacja",auto:"Adaptive Auto"})[v.control]||"Brak odczytu";
 $("am-activation").textContent=amError||(v.activation_blocker?"Auto: "+v.activation_blocker:"");''')
    html=once(html,'$("am-control").addEventListener("change",()=>{amDirty=',
        '$("am-control").addEventListener("change",()=>{amError="";amDirty=')
    html=once(html,' amBusy=true;amPaint(amState);',' amError="";amBusy=true;amPaint(amState);')
    html=once(html,'  if(!res.ok||res.redirected||!(await res.json()).accepted)throw Error("rejected");\n  amDirty=false;amPaint(null);$("am-reason").textContent="Polecenie przyjęte; czekam na odczyt.";\n }catch(e){amPaint(null);$("am-reason").textContent="Polecenie niepotwierdzone. Sprawdź aktualny stan; brak automatycznej ponawiania."}\n finally{clearTimeout(timer);amBusy=false;}',
        '''  const body=res.redirected?{}:await res.json();
  if(!res.ok||!body.accepted)throw Error(body.reason||"Polecenie odrzucone (HTTP "+res.status+")");
  amDirty=false;amError="";amPaint(null);
 }catch(e){amDirty=false;amError=e.message||"Brak potwierdzenia polecenia.";amPaint(null);}
 finally{clearTimeout(timer);amBusy=false;amPaint(amState);}''')
    return html

def curve_ui(html):
    if 'id="am-curve-recalc"' in html:
        return html
    old='<a href="/">Panel oryginalny</a>'
    html=once(html,old,'<a href="/settings#heatingcurve_section">Edytuj krzywą</a>')
    html=once(html,'<p id="am-reason"', '<div class="ctlrow"><button id="am-curve-recalc" disabled>Przelicz krzywą</button></div><p id="am-curve-result" role="status"></p><p id="am-reason"')
    html=once(html,' $("am-owner").textContent=',' $("am-curve-recalc").disabled=!amState||amBusy||!v.ready||!Number.isFinite(v.curve);\n $("am-owner").textContent=')
    html=once(html,'$("am-save").addEventListener("click",', '''$("am-curve-recalc").addEventListener("click",async()=>{
 if(!amState||amBusy||!amState.ready||!Number.isFinite(amState.curve))return;
 const expected=amState.curve;
 amBusy=true;amPaint(amState);
 const ctrl=new AbortController(),timer=setTimeout(()=>ctrl.abort(),20000);
 try{
  const res=await fetch("./api/control",{method:"POST",credentials:"same-origin",cache:"no-store",headers:{"Content-Type":"application/json","X-HaierPi-CSRF":document.querySelector('meta[name="wv-csrf"]').content},body:JSON.stringify({key:"curve_recalculate",value:"recalculate",expected}),signal:ctrl.signal});
  const body=res.redirected?{}:await res.json();
  if(!res.ok||!body.accepted)throw Error(body.reason||"Odrzucono (HTTP "+res.status+")");
  $("am-curve-result").textContent="Krzywa przeliczona; aktualna nastawa pojawi się po odczycie.";
 }catch(e){$("am-curve-result").textContent=e.message||"Niepotwierdzone przeliczenie.";}
 finally{clearTimeout(timer);amBusy=false;amPaint(amState);}
});
$("am-save").addEventListener("click",''')
    return html

def curve_api(source):
    if '    out["curve_recalculate"]' in source:
        return source
    source=once(source,'    out["adaptive_control"]=am["control"]','    out["curve_recalculate"]=out.get("hcurve")\n    out["adaptive_control"]=am["control"]')
    source=once(source,'    if key in ("adaptive_control","flimiton"):', '''    if key=="curve_recalculate":
        if value!="recalculate" or type(expected) not in (int,float) or not _wv_math.isfinite(expected):
            raise ValueError("invalid curve recalculation")
    elif key in ("adaptive_control","flimiton"):''')
    source=once(source,'            if key=="adaptive_control":\n                try:', '''            if key=="curve_recalculate":
                with _am.lock:
                    a=_am.view()
                    if not a["ready"] or a["pending"] or a["curve"]!=expected:
                        return reply({"accepted":False,"reason":"Krzywa: stan zmienił się lub pompa nie jest gotowa"},409)
                    g["curvecalc"]()
            elif key=="adaptive_control":
                try:''')
    return source

def curve_editor_ui(html):
    old='<a href="/settings#heatingcurve_section">Edytuj krzywą</a>'
    link='<a href="#am-curve-editor">Krzywa grzewcza</a>'
    if old in html:
        html=once(html,old,link)
    if 'id="am-curve-editor"' in html:
        return html
    fields=''.join('<label style="display:grid;gap:4px">'+str(t)+' °C<input id="am-cp-'+str(i)+'" type="number" min="0" max="65" step="0.5" disabled></label>' for i,t in enumerate((-20,-15,-10,-8,-6,-4,-2,0,2,4,6,8,10,15)))
    editor="""<article class="card ctlcard" id="am-curve-editor"><h3>Krzywa grzewcza</h3>
<div class="metric"><span>Aktualna obliczona nastawa</span><strong id="am-c-current">—</strong></div>
<label>Rodzaj krzywej <select id="am-c-mode" disabled><option value="manual">Ręczna</option><option value="static">Statyczna</option><option value="auto">Automatyczna</option><option value="directly" disabled>Bezpośrednio</option></select></label>
<div id="am-c-coeff" style="display:grid;gap:8px;grid-template-columns:repeat(auto-fit,minmax(130px,1fr))">
<label>Nachylenie<input id="am-c-slope" type="number" min="0" max="5" step="0.01" disabled></label>
<label>Przesunięcie<input id="am-c-shift" type="number" min="-30" max="30" step="0.1" disabled></label>
<label>Wzmocnienie<input id="am-c-gain" type="number" min="0" max="20" step="0.1" disabled></label></div>
<div id="am-c-points" style="display:grid;gap:8px;grid-template-columns:repeat(auto-fit,minmax(85px,1fr))">"""+fields+"""</div>
<canvas id="am-c-chart" width="500" height="180" style="width:100%;height:auto" aria-label="Wykres ręcznej krzywej"></canvas>
<div class="ctlrow"><button id="am-c-save" class="primary" disabled>Zapisz krzywą</button><button id="am-c-cancel" disabled>Anuluj zmiany</button></div>
<p id="am-c-msg" role="status">Oczekiwanie na konfigurację.</p><small>Zapis zmienia istniejącą konfigurację HaierPi. Nowa nastawa zostanie zastosowana w zwykłym cyklu obliczeń z zachowaniem zabezpieczeń.</small></article>"""
    html=once(html,'<article class="card ctlcard"><h3>Zaawansowane</h3>',editor+'<article class="card ctlcard"><h3>Zaawansowane</h3>')
    js="""
let curveBase=null,curveDirty=false,curveBusy=false,curveMsg="";
const curveIds=["am-c-mode","am-c-slope","am-c-shift","am-c-gain",...Array.from({length:14},(_,i)=>"am-cp-"+i)];
function curveRead(){
 const num=id=>$(id).value.trim()===""?NaN:Number($(id).value);
 return {mode:$("am-c-mode").value,slope:num("am-c-slope"),shift:num("am-c-shift"),gain:num("am-c-gain"),points:Array.from({length:14},(_,i)=>num("am-cp-"+i))};
}
function curveDraw(){
 const c=$("am-c-chart"),ctx=c.getContext("2d");if(!ctx)return;
 const xs=[-20,-15,-10,-8,-6,-4,-2,0,2,4,6,8,10,15],v=curveRead().points;
 ctx.clearRect(0,0,c.width,c.height);ctx.font="12px sans-serif";ctx.fillStyle="#888";ctx.strokeStyle="#888";
 for(const k of [0,20,40,60]){const y=152-k*2;ctx.fillText(k+"°",4,y);ctx.beginPath();ctx.moveTo(38,y);ctx.lineTo(480,y);ctx.stroke();}
 ctx.fillText("-20°C",38,172);ctx.fillText("15°C",445,172);
 if(v.some(n=>!Number.isFinite(n)))return;
 ctx.strokeStyle="#2794c7";ctx.lineWidth=2;ctx.beginPath();
 v.forEach((n,i)=>{const x=38+(xs[i]+20)*442/35,y=152-n*2;i?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.stroke();ctx.lineWidth=1;
}
function curvePaint(v){
 const cfg=v&&v.curve_settings;
 $("am-c-current").textContent=fmt(v&&v.curve)+" °C";
 if(cfg&&!curveDirty&&!curveBusy){
  curveBase=cfg;
  $("am-c-mode").value=cfg.mode;$("am-c-slope").value=cfg.slope;$("am-c-shift").value=cfg.shift;$("am-c-gain").value=cfg.gain;
  cfg.points.forEach((n,i)=>$("am-cp-"+i).value=n);
 }
 const locked=!cfg||curveBusy||cfg.mode==="directly",mode=$("am-c-mode").value;
 $("am-c-mode").disabled=locked;
 $("am-c-slope").disabled=locked||mode==="manual";
 $("am-c-shift").disabled=locked||mode!=="auto";$("am-c-gain").disabled=locked||mode!=="auto";
 $("am-c-points").hidden=mode!=="manual";$("am-c-chart").hidden=mode!=="manual";
 for(let i=0;i<14;i++)$("am-cp-"+i).disabled=locked||mode!=="manual";
 $("am-c-save").disabled=locked||!curveDirty||v.pending;
 $("am-c-cancel").disabled=curveBusy||!curveDirty;
 const conflict=curveDirty&&cfg&&curveBase&&JSON.stringify(cfg)!==JSON.stringify(curveBase);
 $("am-c-msg").textContent=curveMsg||(conflict?"Konfiguracja zmieniona poza edytorem; anuluj i odczytaj ponownie.":!cfg?"Brak poprawnego odczytu konfiguracji.":cfg.mode==="directly"?"Tryb bezpośredni: edycja krzywej nieaktywna.":curveDirty?"Niezapisane zmiany.":"Konfiguracja odczytana.");
 if(conflict)$("am-c-save").disabled=true;
 curveDraw();
}
for(const id of curveIds)$(id).addEventListener("input",()=>{curveDirty=true;curveMsg="";curvePaint(amState);});
$("am-c-cancel").addEventListener("click",()=>{curveDirty=false;curveMsg="";curvePaint(amState);});
$("am-c-save").addEventListener("click",async()=>{
 if(!curveBase||!amState||!curveDirty||curveBusy||$("am-c-save").disabled)return;
 const value=curveRead(),expected=curveBase;
 if(!curveIds.every(id=>$(id).disabled||$(id).checkValidity())||[value.slope,value.shift,value.gain,...value.points].some(n=>!Number.isFinite(n))){curveMsg="Nieprawidłowe wartości krzywej.";curvePaint(amState);return;}
 curveBusy=true;curveMsg="Zapisywanie…";curvePaint(amState);
 const ctrl=new AbortController(),timer=setTimeout(()=>ctrl.abort(),20000);
 try{
  const res=await fetch("./api/control",{method:"POST",credentials:"same-origin",cache:"no-store",headers:{"Content-Type":"application/json","X-HaierPi-CSRF":document.querySelector('meta[name="wv-csrf"]').content},body:JSON.stringify({key:"curve_settings",value,expected}),signal:ctrl.signal});
  const body=res.redirected?{}:await res.json();
  if(!res.ok||!body.accepted)throw Error(body.reason||"Zapis odrzucony (HTTP "+res.status+")");
  curveDirty=false;curveMsg="Zapisano. Oczekiwanie na kolejny odczyt.";
 }catch(e){curveMsg=e.message||"Niepotwierdzony zapis. Sprawdź odczyt przed ponowieniem.";}
 finally{clearTimeout(timer);curveBusy=false;curvePaint(amState);}
});
"""
    html=once(html,'function amPaint(a){',js+'\nfunction amPaint(a){')
    html=once(html,' amState=a||null;const v=amState||{};',' amState=a||null;const v=amState||{};curvePaint(v);')
    return html

def curve_editor_api(source):
    if '    out["curve_settings"]' in source:
        return source
    source=once(source,'    out["curve_recalculate"]=','    out["curve_settings"]=_am.curve_settings()\n    out["curve_recalculate"]=')
    source=once(source,'    if key=="curve_recalculate":\n        if value', '''    if key=="curve_settings":
        value=_am.validate_curve(value)
        expected=_am.validate_curve(expected)
    elif key=="curve_recalculate":
        if value''')
    source=once(source,'if (key!="adaptive_control" and not state["control_ready"])', 'if (key not in ("adaptive_control","curve_settings") and not state["control_ready"])')
    source=once(source,'            if key=="curve_recalculate":\n                with _am.lock:', '''            if key=="curve_settings":
                try:
                    _am.save_curve(value,expected)
                except _am_sys.modules["_hpi_adaptive_runtime"].SelectionBlocked as exc:
                    return reply({"accepted":False,"reason":str(exc)},409)
            elif key=="curve_recalculate":
                with _am.lock:''')
    return source

def status_ui(html):
    old=' $("am-reason").textContent=v.fault||v.reason||"Brak odczytu.";'
    new=' $("am-reason").textContent=v.fault||v.reason_pl||v.reason||"Brak odczytu.";'
    if new not in html:
        html=once(html,old,new)
    old=' $("am-risk").textContent=v.risk||"—";'
    new=' $("am-risk").textContent=({paused:"Oczekiwanie",balanced:"Stabilizacja / obserwacja",surplus:"Nadwyżka mocy",shortfall:"Niedobór mocy",cycling_risk:"Ryzyko taktowania",cycling_risk_at_minimum:"Ryzyko taktowania przy minimum",surplus_at_minimum:"Nadwyżka przy minimum",efficiency_probe:"Próba redukcji mocy"})[v.risk]||v.risk||"—";'
    if new not in html:
        html=once(html,old,new)
    if 'id="am-return-temp"' not in html:
        html=once(html,'<div class="metric"><span>Prognozowana nadwyżka</span>', '<div class="metric"><span>Twi – powrót</span><strong id="am-return-temp">—</strong></div><div class="metric"><span>Próg STOP (założenie)</span><strong id="am-stop-target">—</strong></div><div class="metric"><span>Do progu STOP</span><strong id="am-stop-margin">—</strong></div><div class="metric"><span>Trend Twi</span><strong id="am-return-trend">—</strong></div><div class="metric"><span>Prognoza Twi względem nastawy</span>')
        html=once(html,' $("am-forecast").textContent=fmt(v.forecast)+" K";', ''' $("am-forecast").textContent=fmt(v.forecast)+" K";
 $("am-return-temp").textContent=fmt(v.return_temp)+" °C";
 $("am-stop-target").textContent=fmt(v.stop_target)+" °C";
 $("am-stop-margin").textContent=fmt(v.stop_margin)+" K";
 $("am-return-trend").textContent=fmt(v.return_trend)+" K/min";''')
    if 'id="am-supply-forecast"' not in html:
        html=once(html,'<span>Próg STOP (założenie)</span>','<span>Próg STOP Two (model +5 K)</span>')
        html=once(html,'<span>Do progu STOP</span>','<span>Do progu STOP Two</span>')
        html=once(html,'<div class="metric"><span>Trend Twi</span>', '<div class="metric"><span>Two – zasilanie</span><strong id="am-supply-temp">—</strong></div><div class="metric"><span>Prognoza Two względem nastawy</span><strong id="am-supply-forecast">—</strong></div><div class="metric"><span>Auto po restarcie</span><strong id="am-resume">—</strong></div><button id="am-cancel-resume" disabled>Anuluj wznowienie Auto</button><div class="metric"><span>Trend Twi</span>')
        html=once(html,' $("am-return-temp").textContent=fmt(v.return_temp)+" °C";', ''' $("am-return-temp").textContent=fmt(v.return_temp)+" °C";
 $("am-supply-temp").textContent=fmt(v.supply_temp)+" °C";
 $("am-supply-forecast").textContent=fmt(v.supply_forecast)+" K";
 $("am-resume").textContent=v.owner_storage_error|| (v.auto_resume_pending?"Oczekuje na dane":v.control==="auto"?"Zapamiętane":"Wyłączone");
 $("am-cancel-resume").disabled=!amState||amBusy||!v.auto_resume_pending;''')
        html=once(html,' if(expected===value||expected===null)return;', ' if(expected===null||(expected===value&&!(key==="adaptive_control"&&value==="manual"&&amState.auto_resume_pending)))return;')
        html=once(html,'$("am-save").addEventListener("click",()=>amSend("adaptive_control",', '$("am-cancel-resume").addEventListener("click",()=>amSend("adaptive_control","manual"));\n$("am-save").addEventListener("click",()=>amSend("adaptive_control",')
    if 'id="am-hysteresis"' not in html:
        html=once(html,'<p id="am-reason"', '<div class="metric"><span>Obserwator histerezy CO (tylko odczyt)</span><strong id="am-hysteresis">—</strong></div><p id="am-hysteresis-time"></p><p id="am-hysteresis-twi"></p><p id="am-hysteresis-two"></p><small>Progi orientacyjne, względem nastawy, z przejść Fset. Oddzielne grupy nastawy, trybu, FLimit i sterowania; bez automatycznej zmiany progów.</small><p id="am-reason"')
        html=once(html,' $("am-reason").textContent=v.fault||v.reason_pl||v.reason||"Brak odczytu.";', ''' const h=v.hysteresis;
 $("am-hysteresis").textContent=h?h.cycles+" / 20 w bieżącym kontekście · "+h.total+" zapisanych łącznie"+(h.storage_error?" · błąd zapisu":""):"—";
 $("am-hysteresis-time").textContent=h?"Od: "+(h.since?new Date(h.since*1000).toLocaleString():"—")+" · zmiana kontekstu: "+(h.changed?new Date(h.changed*1000).toLocaleString():"—"):"—";
 const hs=(x)=>x&&x.start&&x.stop?"START "+fmt(x.start.offset)+" K / STOP "+fmt(x.stop.offset)+" K / pasmo "+fmt(x.width)+" K; MAD STOP "+fmt(x.stop.mad)+" K":"brak pełnych cykli";
 $("am-hysteresis-twi").textContent="Twi: "+hs(h&&h.twi);
 $("am-hysteresis-two").textContent="Two: "+hs(h&&h.two);
 $("am-reason").textContent=v.fault||v.reason_pl||v.reason||"Brak odczytu.";''')
    if 'id="am-hysteresis-mean"' not in html:
        html=once(html,'<p id="am-hysteresis-two"></p>', '<p id="am-hysteresis-two"></p><p id="am-hysteresis-mean"></p><p id="am-hysteresis-extra"></p><p id="am-hysteresis-dwell"></p><small>Czas ponad nastawą / +1 K / +2 K: mediany próbkowanych przedziałów pracy. Średnia Twi/Two jest hipotezą.</small>')
        html=once(html,' $("am-hysteresis-two").textContent="Two: "+hs(h&&h.two);', ''' $("am-hysteresis-two").textContent="Two: "+hs(h&&h.two);
 $("am-hysteresis-mean").textContent="Średnia Twi/Two: "+hs(h&&h.mean);
 const he=h&&h.extended;
 const hv=(x,u)=>x==null?"—":fmt(x)+" "+u;
 $("am-hysteresis-extra").textContent=he?"Rozszerzone cykle: "+he.cycles+" · przed STOP: ΔT "+hv(he.stop_water_delta,"K")+", Fact "+hv(he.stop_fact,"Hz")+", Fset "+hv(he.stop_fset,"Hz")+", na zewnątrz "+hv(he.stop_outdoor,"°C")+" · praca "+hv(he.run_seconds==null?null:he.run_seconds/60,"min"):"—";
 const hd=(k)=>he&&he.above_seconds?[0,1,2].map(b=>hv(he.above_seconds[k][b]==null?null:he.above_seconds[k][b]/60,"min")).join(" / "):"—";
 $("am-hysteresis-dwell").textContent="Ponad progi: Twi "+hd("twi")+" · Two "+hd("two")+" · średnia "+hd("mean");''')
    if 'value="experiment"' not in html:
        html=once(html,'<option value="auto">Auto – eksperymentalne</option>', '<option value="auto">Auto – eksperymentalne</option><option value="experiment">Eksperyment – test konfiguracji</option>')
        html=once(html,'auto:"Adaptive Auto"', 'auto:"Adaptive Auto",experiment:"Eksperyment"')
        html=once(html,'<p id="am-hysteresis-mean"></p>','<p id="am-hysteresis-mean"></p><p id="am-experiment"></p><small>Eksperyment zmienia tryb i FLimit tylko przy potwierdzonym postoju; 3 cykle na konfigurację, bez limitu czasu; zwykła Obserwacja nie zmienia ustawień.</small>')
        html=once(html,' $("am-hysteresis-mean").textContent="Średnia Twi/Two: "+hs(h&&h.mean);',' $("am-hysteresis-mean").textContent="Średnia Twi/Two: "+hs(h&&h.mean);\n const ex=v.experiment;\n $("am-experiment").textContent=ex&&ex.since?"Eksperyment: "+ex.levels.map((x,i)=>x+" "+ex.counts[i]+"/"+ex.per_level).join(" · "):"";'.replace("\n","\n"))
    if 'id="am-start-target"' not in html:
        html=once(html,'<span>Próg STOP Two (model +5 K)</span>','<span>Próg STOP Two (model)</span>')
        html=once(html,'<div class="metric"><span>Do progu STOP Two</span>', '<div class="metric"><span>Próg START (średnia Twi/Two)</span><strong id="am-start-target">—</strong></div><div class="metric"><span>Do START / prognoza</span><strong id="am-start-eta">—</strong></div><p id="am-threshold-model"></p><div class="metric"><span>Do progu STOP Two</span>')
        html=once(html,' $("am-stop-target").textContent=fmt(v.stop_target)+" °C";', ''' const tm=v.threshold_model;
 $("am-start-target").textContent=tm?fmt(tm.start_target)+" °C":"—";
 $("am-start-eta").textContent=tm&&tm.start_margin!=null?fmt(tm.start_margin)+" K"+(tm.start_eta_min==null?"":" / "+fmt(tm.start_eta_min)+" min"):"—";
 $("am-stop-target").textContent=tm?fmt(tm.stop_target)+" °C":"—";
 $("am-threshold-model").textContent=tm?"START "+(tm.start.source==="learned"?"wyuczony":"domyślny")+" ("+tm.start.n+"/8) · STOP "+(tm.stop.source==="learned"?"wyuczony":"domyślny")+" ("+tm.stop.n+"/8)"+(tm.storage_error?" · "+tm.storage_error:""):"";''')
        html=once(html,' $("am-stop-margin").textContent=fmt(v.stop_margin)+" K";',' $("am-stop-margin").textContent=tm&&v.supply_temp!=null?fmt(tm.stop_target-v.supply_temp)+" K":"—";')
    if 'href="/v2/adaptive-report"' not in html:
        html=once(html,'<h3>AntiON-OFF v2</h3>','<h3>AntiON-OFF v2</h3><p><a href="/v2/adaptive-report">Raport Adaptive →</a></p>')
    html=html.replace("Legacy pozostaje domyślne po restarcie.","Zapisany Auto wraca po restarcie po weryfikacji danych.")
    return html

def report_api(source):
    if 'def _wv_adaptive_report_page():' in source:
        return source
    return once(source,"# HOME-IOT WEB UI V2 END","_WV_ADAPTIVE_REPORT_HTML = \"<!doctype html><html lang=\\\"pl\\\"><head><meta charset=\\\"utf-8\\\"><meta name=\\\"viewport\\\" content=\\\"width=device-width,initial-scale=1\\\"><title>Raport Adaptive</title><style>\\n:root{color-scheme:light dark;--line:#8795a24d;--accent:#168b87}body{font:15px system-ui;margin:0}main{max-width:1180px;margin:auto;padding:16px}a{color:inherit}header,.row{display:flex;flex-wrap:wrap;gap:12px;align-items:center}h1{font-size:25px}h2{font-size:18px}article{border:1px solid var(--line);border-radius:12px;padding:14px;margin:12px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}.kpi{padding:10px;border:1px solid var(--line);border-radius:8px}.kpi b{display:block;font-size:26px}small{opacity:.8}.scroll{overflow:auto;max-height:430px}table{border-collapse:collapse;width:100%;font-size:13px}th,td{text-align:left;padding:8px;border-bottom:1px solid var(--line);white-space:nowrap}th{position:sticky;top:0;background:Canvas}button{font:inherit;padding:8px}progress{width:100%;accent-color:var(--accent)}.bar{display:grid;grid-template-columns:115px 1fr 70px;gap:8px;align-items:center;margin:5px 0}</style></head>\\n<body><main><header><a href=\\\"/v2/\\\">← Pulpit</a><h1>Raport Adaptive</h1></header><div class=\\\"row\\\"><button id=\\\"refresh\\\">Odśwież</button><a href=\\\"/v2/api/adaptive-report\\\">JSON</a><a href=\\\"/v2/api/adaptive-report.csv?kind=groups\\\">CSV pomiary</a><a href=\\\"/v2/api/adaptive-report.csv?kind=learning\\\">CSV uczenie</a><a href=\\\"/v2/api/adaptive-report.csv?kind=events\\\">CSV decyzje</a></div><p id=\\\"status\\\" role=\\\"status\\\">Oczekiwanie na dane</p>\\n<article><h2>Uczenie</h2><div class=\\\"grid\\\" id=\\\"kpis\\\"></div><p id=\\\"saved\\\"></p><div id=\\\"scores\\\"></div><small>Oceny nowych obserwacji od włączenia raportu, nie od początku pracy pompy. Dodatnia ocena oznacza nadal obecną nadwyżkę lub ryzyko STOP, nie oszczędność energii.</small></article>\\n<article><h2>Praca CO — Legacy i Auto</h2><div class=\\\"scroll\\\"><table id=\\\"owners\\\"></table></div><small>Obserwowane godziny wyłącznie w normalnym CO z zapotrzebowaniem i świeżymi danymi. Starty według Fset, czas cyklu od Fset START do STOP z potwierdzoną pracą Fact. Zmiany trybu/FLimit nie przerywają cyklu; luki, zmiany właściciela, pasma nastawy i priorytety przerywają. Nie są to pełne dobowe liczniki.</small></article>\\n<article><h2>Porównanie w podobnych warunkach</h2><div class=\\\"scroll\\\"><table id=\\\"compare\\\"></table></div><small>Grupy: temperatura zewnętrzna co 5 K i nastawa co 3 K. Tylko grupy z oboma właścicielami. Porównanie obserwacyjne, nie dowód przyczynowy. Brak danych historycznych sprzed instalacji raportu.</small></article>\\n<article><h2>Starty i pokrycie danych według dni (UTC)</h2><div class=\\\"scroll\\\"><table id=\\\"days\\\"></table></div></article>\\n<article><h2>Wykorzystanie konfiguracji Auto podczas pracy Fact</h2><div id=\\\"levels\\\"></div></article>\\n<article><h2>Wyuczone konteksty</h2><div class=\\\"scroll\\\"><table id=\\\"learning\\\"></table></div><small>Minimum 3 obserwacje przed dostrojeniem; wartości są ograniczone do zakresu regulatora. Ocena jest średnią ważoną wykładniczo.</small></article>\\n<article><h2>Ostatnie decyzje i potwierdzenia</h2><div class=\\\"scroll\\\"><table id=\\\"events\\\"></table></div><small>Rejestrowane polecenia Auto, odczyt zwrotny, błędy, wybór sterowania i oceny uczenia. Polecenie nie oznacza potwierdzenia. Maksymalnie 512 zdarzeń.</small></article>\\n</main><script>\\nconst el=id=>document.getElementById(id), num=(x,d=1)=>Number.isFinite(x)?x.toFixed(d):\\\"—\\\", dt=x=>x==null?\\\"—\\\":new Date(x*1000).toLocaleString(), day=x=>new Date(x*86400000).toISOString().slice(0,10);\\nfunction node(tag,text){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n}\\nfunction table(id,head,rows){const t=el(id);t.replaceChildren();const h=node(\\\"thead\\\"),tr=node(\\\"tr\\\");head.forEach(x=>tr.append(node(\\\"th\\\",x)));h.append(tr);t.append(h);const b=node(\\\"tbody\\\");if(!rows.length){const r=node(\\\"tr\\\"),c=node(\\\"td\\\",\\\"Brak danych\\\");c.colSpan=head.length;r.append(c);b.append(r)}else rows.forEach(v=>{const r=node(\\\"tr\\\");v.forEach(x=>r.append(node(\\\"td\\\",x)));b.append(r)});t.append(b)}\\nconst empty=()=>({coverage_s:0,running_s:0,starts:0,completed:0,run_s:0,levels_s:[0,0,0,0,0,0]});\\nfunction add(a,b){for(const k of [\\\"coverage_s\\\",\\\"running_s\\\",\\\"starts\\\",\\\"completed\\\",\\\"run_s\\\"])a[k]+=b[k];b.levels_s.forEach((v,i)=>a.levels_s[i]+=v);return a}\\nfunction stats(b){return [num(b.coverage_s/3600),b.starts,b.completed,b.completed?num(b.run_s/b.completed/60):\\\"—\\\",b.coverage_s?num(b.starts*3600/b.coverage_s,2):\\\"—\\\"]}\\nfunction bar(parent,label,v,total){const r=node(\\\"div\\\");r.className=\\\"bar\\\";const p=node(\\\"progress\\\");p.max=total||1;p.value=v;r.append(node(\\\"span\\\",label),p,node(\\\"span\\\",total?num(v/total*100)+\\\"%\\\":\\\"—\\\"));parent.append(r)}\\nfunction paint(d){\\nel(\\\"status\\\").textContent=\\\"Dane od \\\"+dt(d.since)+\\\" · ostatni zapis raportu \\\"+dt(d.saved_at)+(d.unsaved?\\\" · nowe dane w RAM\\\":\\\"\\\")+(d.storage_error?\\\" · \\\"+d.storage_error:\\\"\\\")+\\\" · do \\\"+d.retention_days+\\\" dni, maks. 2048 grup\\\";\\nconst l=d.learning,k=el(\\\"kpis\\\");k.replaceChildren();for(const [a,b] of [[\\\"Konteksty\\\",l.contexts+\\\" / \\\"+l.capacity],[\\\"Obserwacje w pamięci\\\",l.observations],[\\\"Dostrojone\\\",l.rows.filter(x=>x.tuned).length]]){const box=node(\\\"div\\\");box.className=\\\"kpi\\\";box.append(node(\\\"small\\\",a),node(\\\"b\\\",b));k.append(box)}\\nel(\\\"saved\\\").textContent=\\\"Ostatni zapis uczenia: \\\"+dt(l.saved_at)+(l.unsaved?\\\" · nowe dane w RAM\\\":\\\"\\\")+(l.storage_error?\\\" · \\\"+l.storage_error:\\\"\\\");\\nconst sc=el(\\\"scores\\\");sc.replaceChildren();const total=Object.values(d.scores).reduce((a,b)=>a+b,0);for(const [key,name] of [[\\\"1\\\",\\\"Nadwyżka\\\"],[\\\"0\\\",\\\"Neutralne\\\"],[\\\"-1\\\",\\\"Niedobór\\\"]])bar(sc,name,d.scores[key],total);\\nconst owners={},groups={},days={};for(const b of d.groups){add(owners[b.owner]??=empty(),b);const g=groups[b.outdoor_band+\\\":\\\"+b.target_band]??={out:b.outdoor_band,target:b.target_band};add(g[b.owner]??=empty(),b);add(days[b.day+\\\":\\\"+b.owner]??=empty(),b)}\\nconst head=[\\\"Godz. obserw.\\\",\\\"Starty\\\",\\\"Pełne cykle\\\",\\\"Śr. cykl min\\\",\\\"Starty / godz.\\\"];\\ntable(\\\"owners\\\",[\\\"Właściciel\\\",...head],Object.entries(owners).map(([k,b])=>[k,...stats(b)]));\\ntable(\\\"compare\\\",[\\\"Zewn. od °C\\\",\\\"Nastawa od °C\\\",\\\"Legacy godz.\\\",\\\"Auto godz.\\\",\\\"Legacy cykle\\\",\\\"Auto cykle\\\",\\\"Legacy min\\\",\\\"Auto min\\\",\\\"Legacy starty/h\\\",\\\"Auto starty/h\\\"],Object.values(groups).filter(g=>g.legacy&&g.auto&&g.legacy.coverage_s>0&&g.auto.coverage_s>0).map(g=>[g.out,g.target,stats(g.legacy)[0],stats(g.auto)[0],g.legacy.completed,g.auto.completed,stats(g.legacy)[3],stats(g.auto)[3],stats(g.legacy)[4],stats(g.auto)[4]]));\\ntable(\\\"days\\\",[\\\"Dzień\\\",\\\"Właściciel\\\",...head],Object.entries(days).sort((a,b)=>b[0].localeCompare(a[0])).map(([k,b])=>{const [n,o]=k.split(\\\":\\\");return [day(+n),o,...stats(b)]}));\\nconst lv=el(\\\"levels\\\");lv.replaceChildren();const auto=owners.auto||empty(),sum=auto.levels_s.reduce((a,b)=>a+b,0);d.levels.forEach((x,i)=>bar(lv,x,auto.levels_s[i],sum));\\ntable(\\\"learning\\\",[\\\"Zewn. od\\\",\\\"Nastawa od\\\",\\\"Zmiana\\\",\\\"n\\\",\\\"Ocena\\\",\\\"Δ Hz\\\",\\\"Potw. s\\\",\\\"Nadwyżka K\\\",\\\"Wczesna K\\\",\\\"Prognoza min\\\",\\\"Aktualizacja\\\"],l.rows.map(x=>[x.outdoor_band,x.target_band,x.transition,x.n,num(x.score,2),num(x.delta_hz),num(x.down_confirm),num(x.surplus_band,2),num(x.early_surplus,2),num(x.forecast_min,2),dt(x.last)]));\\ntable(\\\"events\\\",[\\\"Czas\\\",\\\"Typ\\\",\\\"Właściciel\\\",\\\"Szczegóły\\\"],d.events.slice().reverse().map(x=>[dt(x.at),x.kind,x.owner,x.detail]));\\n}\\nasync function refresh(){const b=el(\\\"refresh\\\");b.disabled=true;try{const r=await fetch(\\\"/v2/api/adaptive-report\\\",{cache:\\\"no-store\\\",credentials:\\\"same-origin\\\"});if(!r.ok||r.redirected)throw Error(\\\"Brak dostępu lub sesja wygasła\\\");paint(await r.json())}catch(e){el(\\\"status\\\").textContent=\\\"Nie udało się odczytać raportu: \\\"+e.message}finally{b.disabled=false}}\\nel(\\\"refresh\\\").addEventListener(\\\"click\\\",refresh);refresh();\\n</script></body></html>\"\n\n@app.route(\"/v2/adaptive-report\", methods=[\"GET\"])\n@login_required\ndef _wv_adaptive_report_page():\n    return _wv_headers(_wv_Response(_WV_ADAPTIVE_REPORT_HTML,mimetype=\"text/html\"))\n\n@app.route(\"/v2/api/adaptive-report\", methods=[\"GET\"])\n@login_required\ndef _wv_adaptive_report_json():\n    return _wv_headers(_wv_jsonify(_am.report_view()))\n\n@app.route(\"/v2/api/adaptive-report.csv\", methods=[\"GET\"])\n@login_required\ndef _wv_adaptive_report_csv():\n    import csv,io\n    kind=_wv_request.args.get(\"kind\",\"groups\")\n    data=_am.report_view()\n    if kind==\"groups\":\n        rows=[dict({k:v for k,v in b.items() if k!=\"levels_s\"},**{\"level_\"+str(i)+\"_s\":v for i,v in enumerate(b[\"levels_s\"])}) for b in data[\"groups\"]]\n        fields=[\"day\",\"owner\",\"outdoor_band\",\"target_band\",\"coverage_s\",\"running_s\",\"starts\",\"completed\",\"run_s\"]+[\"level_\"+str(i)+\"_s\" for i in range(6)]\n    elif kind==\"learning\":\n        rows=data[\"learning\"][\"rows\"]\n        fields=[\"context\",\"outdoor_band\",\"target_band\",\"transition\",\"n\",\"score\",\"delta_hz\",\"delta_error\",\"return_trend\",\"last\",\"tuned\",\"down_confirm\",\"surplus_band\",\"early_surplus\",\"forecast_min\"]\n    elif kind==\"events\":\n        rows=data[\"events\"]\n        fields=[\"at\",\"kind\",\"owner\",\"detail\"]\n    else:\n        return _wv_headers(_wv_Response(\"Unknown report kind\",status=400))\n    out=io.StringIO()\n    writer=csv.DictWriter(out,fieldnames=fields,extrasaction=\"ignore\")\n    writer.writeheader()\n    writer.writerows(rows)\n    response=_wv_Response(out.getvalue(),mimetype=\"text/csv\")\n    response.headers[\"Content-Disposition\"]='attachment; filename=\"adaptive-'+kind+'.csv\"'\n    return _wv_headers(response)\n\n# HOME-IOT WEB UI V2 END")

def threshold_report_api(source):
    source=report_api(source)
    line=next(l for l in source.splitlines() if l.startswith("_WV_ADAPTIVE_REPORT_HTML = "))
    html=ast.literal_eval(line.split("=",1)[1].strip())
    if 'id="thresholds"' in html:
        return source
    html=once(html,'<article><h2>Wyuczone konteksty</h2>','<article><h2>Model START / STOP</h2><p id="threshold-status"></p><div class="scroll"><table id="thresholds"></table></div><small>Minimum 8 zgodnych przejść na konfigurację i pasmo nastawy. START: średnia tylko przy zgodnych Twi/Two; STOP: Two. Brak zgodności oznacza powrót do modelu domyślnego. Nie jest to fabryczna histereza.</small></article><article><h2>Wyuczone konteksty</h2>')
    html=once(html,'const l=d.learning,k=el("kpis");','const th=d.thresholds;el("threshold-status").textContent=th?"Ostatni zapis "+dt(th.saved_at)+(th.unsaved?" · RAM":"")+(th.storage_error?" · "+th.storage_error:""):"—";table("thresholds",["Przejście","Tryb","FLimit","Nastawa od","n","Twi K","Two K","MAD K","Model K","Źródło"],(th?th.groups:[]).map(x=>[x.edge,x.preset,x.flimit?"ON":"OFF",x.target_band,x.n,num(x.twi_median,2),num(x.two_median,2),num(x.mad,2),num(x.offset,2),x.source==="learned"?"Wyuczony":"Domyślny"]));const l=d.learning,k=el("kpis");')
    return once(source,line,"_WV_ADAPTIVE_REPORT_HTML = "+repr(html))

def performance_report_api(source):
    source=threshold_report_api(source)
    line=next(l for l in source.splitlines() if l.startswith("_WV_ADAPTIVE_REPORT_HTML = "))
    html=ast.literal_eval(line.split("=",1)[1].strip())
    if 'id="run-kpis"' not in html:
        html=once(html,'<article><h2>Praca CO — Legacy i Auto</h2>','<article><h2>Cel: ciągła praca bez STOP</h2><div class="grid" id="run-kpis"></div><small>Ciągłość potwierdzana przez dodatnie Fset i Fact w kolejnych próbkach. Zmiany trybu i nastawy nie zerują pomiaru; przerwy w danych, priorytet i zmiana właściciela zerują. Rekord to dolna granica czasu, nie pełny cykl. Godziny ponad pierwszą godzinę oznaczają czas od 61. minuty każdego obserwowanego odcinka. Brak danych sprzed włączenia tego pomiaru.</small></article><article><h2>Praca CO — Legacy i Auto</h2>')
        html=once(html,'<h2>Wykorzystanie konfiguracji Auto podczas pracy Fact</h2><div id="levels"></div>','<h2>Wykorzystanie konfiguracji Auto podczas pracy Fact</h2><div id="levels"></div><div class="scroll"><table id="level-details"></table></div><small>Procent liczony względem sumy zarejestrowanego czasu pracy Fact w sześciu konfiguracjach, nie względem całej doby.</small>')
        html=once(html,'<div class="scroll"><table id="thresholds"></table></div>','<div class="scroll"><table id="thresholds"></table></div><details><summary>Zapisane pomiary użyte do obliczeń</summary><p><a href="/v2/api/adaptive-report.csv?kind=thresholds">CSV progi</a> · <a href="/v2/api/adaptive-report.csv?kind=threshold_samples">CSV pomiary progów</a></p><div class="scroll"><table id="threshold-samples"></table></div></details>')
        html=once(html,'const empty=()=>({coverage_s:0,running_s:0,starts:0,completed:0,run_s:0,levels_s:[0,0,0,0,0,0]});','const empty=()=>({coverage_s:0,running_s:0,starts:0,completed:0,run_s:0,levels_s:[0,0,0,0,0,0],max_continuous_s:0,beyond_hour_s:0});')
        html=once(html,'b.levels_s.forEach((v,i)=>a.levels_s[i]+=v);return a','b.levels_s.forEach((v,i)=>a.levels_s[i]+=v);a.max_continuous_s=Math.max(a.max_continuous_s,b.max_continuous_s||0);a.beyond_hour_s+=b.beyond_hour_s||0;return a')
        html=once(html,'d.levels.forEach((x,i)=>bar(lv,x,auto.levels_s[i],sum));','''d.levels.forEach((x,i)=>bar(lv,x,auto.levels_s[i],sum));
table("level-details",["Tryb / FLimit","Godziny","Udział"],d.levels.map((x,i)=>[x,num(auto.levels_s[i]/3600,2),sum?num(auto.levels_s[i]*100/sum,2)+"%":"—"]));
const run=el("run-kpis");run.replaceChildren();const st=d.current_streak;
for(const [a,b] of [["Bieżąca ciągła praca Auto",st&&st.owner==="auto"?num(st.seconds/3600,2)+" h":"—"],["Rekord Auto",auto.max_continuous_s?num(auto.max_continuous_s/3600,2)+" h":"—"],["Rekord Legacy",owners.legacy&&owners.legacy.max_continuous_s?num(owners.legacy.max_continuous_s/3600,2)+" h":"—"],["Auto – godziny ponad 1 h ciągłości",num(auto.beyond_hour_s/3600,2)+" h"],["Auto – czas pracy Fact",num(auto.running_s/3600,2)+" h"]]){const k=node("div");k.className="kpi";k.append(node("small",a),node("b",b));run.append(k)}
const ts=(d.thresholds?d.thresholds.groups:[]).flatMap(g=>(g.samples||[]).map(x=>[x.at,g.edge,g.preset,g.flimit?"ON":"OFF",g.target_band,x.twi_offset,x.two_offset]));ts.sort((a,b)=>b[0]-a[0]);table("threshold-samples",["Czas","Przejście","Tryb","FLimit","Nastawa od °C","Twi K","Two K"],ts.map(x=>[dt(x[0]),...x.slice(1,5),num(x[5],3),num(x[6],3)]));''')
        source=once(source,line,"_WV_ADAPTIVE_REPORT_HTML = "+repr(html))
    if 'elif kind=="threshold_samples":' not in source:
        source=once(source,'    elif kind=="events":','''    elif kind=="thresholds":
        rows=data["thresholds"]["groups"]
        fields=["edge","preset","flimit","target_band","n","sensor","twi_median","two_median","median","mad","offset","source"]
    elif kind=="threshold_samples":
        rows=[dict(sample,edge=g["edge"],preset=g["preset"],flimit=g["flimit"],target_band=g["target_band"]) for g in data["thresholds"]["groups"] for sample in g["samples"]]
        fields=["at","edge","preset","flimit","target_band","twi_offset","two_offset"]
    elif kind=="events":''')
        source=once(source,'"completed","run_s"]+["level_"','"completed","run_s","max_continuous_s","beyond_hour_s"]+["level_"')
    return source

def register_watch_api(source):
    source=performance_report_api(source)
    line=next(l for l in source.splitlines() if l.startswith("_WV_ADAPTIVE_REPORT_HTML = "))
    html=ast.literal_eval(line.split("=",1)[1].strip())
    if 'id="register-events"' not in html:
        html=once(html,'<article><h2>Ostatnie decyzje i potwierdzenia</h2>','<article><h2>Diagnostyka grzałek / CWU (pasywna)</h2><p id="register-status"></p><div class="scroll"><table id="register-flags"></table></div><details><summary>Przejścia i zmienione bity</summary><p><a href="/v2/api/adaptive-report.csv?kind=register_changes">CSV zmiany bitów</a> · pełne próbki w JSON raportu.</p><div class="scroll"><table id="register-events"></table></div></details><small>Znane sygnały Heater/CWU, zmiany kandydatów R144/R150/R151/R155/R156 oraz próbki co 2 min przy wybranym trybie TANK. Bit TANK oznacza tryb, nie stan grzałki. Zmienione bity są kandydatami, nie identyfikacją wyjścia zasobnika. Bez dodatkowych zapytań RS485 i bez sterowania. Zmiany między próbkami mogą zostać pominięte.</small></article><article><h2>Ostatnie decyzje i potwierdzenia</h2>')
        html=once(html,'table("events",["Czas","Typ","Właściciel","Szczegóły"]', '''const rw=d.register_watch;
el("register-status").textContent=rw?(rw.fresh?"Świeże dane":"Brak świeżych danych")+" · "+rw.events.length+"/"+rw.limit+" zdarzeń · zapis "+dt(rw.saved_at)+(rw.unsaved?" · RAM":"")+(rw.storage_error?" · "+rw.storage_error:""):"Brak danych";
const names={heater_command:"Polecenie Heater A04",heater_readback:"Odczyt Heater A4A",valve_dhw:"Zawór CWU",valve_ch:"Zawór CO",pdhw:"PDHW",dhw_enabled:"Wybrany tryb TANK (CWU)",dhw_heating:"Grzanie CWU",dhw_heater_assist_active:"Wspomaganie CWU",anti_legionella_active:"Antylegionella"};
table("register-flags",["Sygnał","Stan"],Object.entries(names).map(([k,v])=>[v,rw&&rw.flags&&rw.flags[k]!=null?(rw.flags[k]?"ON":"OFF"):"—"]));
table("register-events",["Czas","Zdarzenie","Rejestr","Przed","Po","XOR","Bity ON","Bity OFF"],(rw?rw.events:[]).slice().reverse().flatMap(e=>e.changes.length?e.changes.map(c=>[dt(e.at),e.kind+" "+e.flags.join(", "),"R"+c.register,c.before,c.after,"0x"+c.xor.toString(16),c.set_bits.join(","),c.cleared_bits.join(",")]):[[dt(e.at),e.kind,"—","—","—","—","—","—"]]));
table("events",["Czas","Typ","Właściciel","Szczegóły"]''')
        source=once(source,line,"_WV_ADAPTIVE_REPORT_HTML = "+repr(html))
    if 'elif kind=="register_changes":' not in source:
        source=once(source,'    elif kind=="events":','''    elif kind=="register_changes":
        rows=[dict(c,at=e["at"],kind=e["kind"],flags=";".join(e["flags"]),set_bits=";".join(map(str,c["set_bits"])),cleared_bits=";".join(map(str,c["cleared_bits"]))) for e in data["register_watch"]["events"] for c in e["changes"]]
        fields=["at","kind","flags","register","before","after","xor","set_bits","cleared_bits"]
    elif kind=="events":''')
    return source

def heater_counter_api(source):
    source=register_watch_api(source)
    line=next(l for l in source.splitlines() if l.startswith("_WV_ADAPTIVE_REPORT_HTML = "))
    html=ast.literal_eval(line.split("=",1)[1].strip())
    if 'id="heater-kpis"' not in html:
        html=once(html,'<article><h2>Diagnostyka grzałek / CWU (pasywna)</h2>','<article><h2>Heater — odczyt A4A</h2><p id="heater-kpis"></p><div class="scroll"><table id="heater-events"></table></div><small>Załączenia OFF→ON z kolejnych świeżych próbek. Czas ON to dolna granica (bez przerw i nieznanych odcinków przejściowych). Odczyt sterownika, nie pomiar poboru prądu. Dane od instalacji licznika.</small></article><article><h2>Diagnostyka grzałek / CWU (pasywna)</h2>')
        html=once(html,'const rw=d.register_watch;', '''const hc=d.heater_counter;
el("heater-kpis").textContent=hc?("Stan: "+(hc.state===null?"—":hc.state?"ON":"OFF")+" · Załączenia: "+hc.starts+" · Czas: "+num(hc.seconds/3600,3)+" h"+(hc.storage_error?" · "+hc.storage_error:hc.unsaved?" · RAM":"")):"Brak danych";
table("heater-events",["Czas","Stan A4A"],(hc?hc.events:[]).slice().reverse().map(e=>[dt(e[0]),e[1]?"ON":"OFF"]));
const rw=d.register_watch;''')
        source=once(source,line,"_WV_ADAPTIVE_REPORT_HTML = "+repr(html))
    # Reuse the native discovery function and device identity. Non-retained
    # periodic samples expire when the frame or service is unavailable.
    if '"HaierPi_HeaterStartsObserved"' not in source:
        anchor='    configure_binary_sensor("Heater", st(\'heater\'), "HaierPi_Heater")'
        source=once(source,anchor,anchor+'''
    for _suffix,_uid,_name,_unit in (
        ("starts","HaierPi_HeaterStartsObserved","Heater observed starts",None),
        ("seconds","HaierPi_HeaterSecondsObserved","Heater observed run time","s"),
    ):
        _hc_cfg={"name":_name,"stat_t":mqtt_topic+"/diagnostics/heater/"+_suffix,
                 "uniq_id":_uid,"exp_aft":90,"stat_cla":"total_increasing"}
        if _unit:
            _hc_cfg["unit_of_meas"]=_unit
            _hc_cfg["dev_cla"]="duration"
        _pub("sensor",_uid,_hc_cfg)
''')
    return source

def heater_control_api(source):
    source=heater_counter_api(source)
    if 'out["heater_mode"]' not in source:
        source=once(source,'    out["adaptive_control"]=am["control"]','    out["heater_mode"]=am["heater"]["mode"]\n    out["adaptive_control"]=am["control"]')
        source=once(source,'    if key=="curve_settings":\n        value=_am.validate_curve(value)', '''    if key=="heater_mode":
        if value not in ("off","on","auto") or expected not in ("off","on","auto"):
            raise ValueError("invalid heater mode")
    elif key=="curve_settings":
        value=_am.validate_curve(value)''')
        source=once(source,'if (key not in ("adaptive_control","curve_settings") and not state["control_ready"])','if (key not in ("adaptive_control","curve_settings","heater_mode") and not state["control_ready"])')
        source=once(source,'            if key=="curve_settings":\n                try:', '''            if key=="heater_mode":
                _am.heater_request(value,expected)
            elif key=="curve_settings":
                try:''')
        source=once(source,'    if msg.topic == topic + "/power/set":','''    if msg.topic == topic + "/ch/heater/mode/set":
        if not msg.retain:
            try:
                _am.heater_request(payload_raw.strip().lower())
            except ValueError:
                logging.warning("Rejected Heater CO request")
        return
    if msg.topic == topic + "/power/set":''')
        source=once(source,'    configure_switch("Service test: Heater (A04)",','''    configure_select("Heater CO request (preview)", mqtt_topic + "/ch/heater/mode/set",
                     mqtt_topic + "/ch/heater/mode/state", "HaierPi_HeaterCORequest", ["off","on","auto"])
    configure_sensor("Heater CO reason", mqtt_topic + "/ch/heater/reason/state", "HaierPi_HeaterCOReason")
    configure_switch("Service test: Heater (A04)",''')
    line=next(l for l in source.splitlines() if l.startswith("_WV_HTML = "))
    html=ast.literal_eval(line.split("=",1)[1].strip())
    if 'id="heater-request"' not in html:
        html=once(html,'<p id="am-reason"', '<div class="metric"><span>Heater CO — żądanie (preview)</span><strong id="heater-request">—</strong></div><div class="ctlrow"><button id="heater-on" disabled>ON</button><button id="heater-off" disabled>OFF</button><button id="heater-auto" disabled>AUTO</button></div><p id="heater-reason"></p><small>ON: ręczne żądanie bez limitu czasu, dopóki warunki CO są bezpieczne. OFF kończy własne wspomaganie. AUTO pozostawia sterowanie fabryczne. OFF nie blokuje ochrony fabrycznej. Nie dotyczy osobnej grzałki zasobnika.</small><p id="am-reason"')
        html=once(html,' const expected=key==="adaptive_control"?amState.control:amState.relay;', ' const expected=key==="heater_mode"?amState.heater.mode:key==="adaptive_control"?amState.control:amState.relay;')
        html=once(html,' $("am-owner").textContent=', ''' const ht=v.heater;
 $("heater-request").textContent=ht?ht.mode+" · A4A "+(ht.state===null?"—":ht.state?"ON":"OFF"):"—";
 $("heater-reason").textContent=ht?ht.reason+(ht.uncertain?" · Niepotwierdzony stan":""):"";
 for(const k of ["on","off","auto"])$("heater-"+k).disabled=!amState||amBusy||!ht||(k!=="off"&&ht.uncertain);
 $("am-owner").textContent=''')
        html=once(html,'$("am-save").addEventListener("click",', '''for(const k of ["on","off","auto"])$("heater-"+k).addEventListener("click",()=>{if(k!=="on"||window.confirm("Włączyć ręczne wspomaganie CO?"))amSend("heater_mode",k)});
$("am-save").addEventListener("click",''')
        source=once(source,line,"_WV_HTML = "+repr(html))
    # Upgrade installed previews without leaving old labels.
    old_html=html
    html=html.replace('>ON (15 min)</button>','>ON</button>').replace(
        'OFF anuluje nasze wspomaganie, nie wyłącza ochrony fabrycznej. AUTO: 60 min CO, niedobór &gt;3 K i wolny wzrost; próba maks. 10 min. Nie dotyczy osobnej grzałki zasobnika.',
        'ON: ręczne żądanie bez limitu czasu, dopóki warunki CO są bezpieczne. OFF kończy własne wspomaganie. AUTO pozostawia sterowanie fabryczne. OFF nie blokuje ochrony fabrycznej. Nie dotyczy osobnej grzałki zasobnika.')
    if html!=old_html:
        source=once(source,"_WV_HTML = "+repr(old_html),"_WV_HTML = "+repr(html))
    return source

def experiment_api(source):
    old='choices=("legacy","manual","shadow","auto") if key=="adaptive_control"'
    new='choices=("legacy","manual","shadow","auto","experiment") if key=="adaptive_control"'
    source=source if new in source else once(source,old,new)
    old='if current==value:'
    new='if current==value and not (key=="adaptive_control" and value=="manual" and _am.view()["auto_resume_pending"]):'
    return heater_control_api(source if new in source else once(source,old,new))

def learning_block():
    policy=(ROOT/"adaptive/regulator.py").read_text(encoding="utf-8")
    runtime=(ROOT/"adaptive/live_runtime.py").read_text(encoding="utf-8").replace("from adaptive.regulator import","from _hpi_adaptive_policy import")
    block=MARK+"\nimport sys as _am_sys, types as _am_types\n"
    for name,code in (("_hpi_adaptive_policy",policy),("_hpi_adaptive_runtime",runtime)):
        block+=f'_am_module = _am_types.ModuleType({name!r})\n_am_sys.modules[{name!r}] = _am_module\nexec(compile({code!r}, {name!r}, "exec"), _am_module.__dict__)\n'
    block+='_am = _am_module.Runtime(globals(), learning_path="/opt/haier/.adaptive-learning-two-v3.json")\n# HOME-IOT ADAPTIVE MODULATION END'
    return block

def learning_ui(source):
    line=next(l for l in source.splitlines() if l.startswith("_WV_HTML = "))
    html=ast.literal_eval(line.split("=",1)[1].strip())
    # /curvecalc returns JSON, not an HTML configuration page.
    # The legacy root and other links below are actual template routes.
    old='<a href="/curvecalc">Krzywa grzewcza</a>'
    if old in html:
        html=once(html,old,'<a href="#am-curve-editor">Krzywa grzewcza</a>' if 'id="am-curve-editor"' in html else '<a href="/settings#heatingcurve_section">Edytuj krzywą</a>' if 'id="am-curve-recalc"' in html else '<a href="/">Panel oryginalny</a>')
    html=curve_editor_ui(curve_ui(activation_ui(html)))
    if 'id="am-learning"' in html:
        html=status_ui(html)
        return experiment_api(curve_editor_api(curve_api(activation_api(source if html==ast.literal_eval(line.split("=",1)[1].strip()) else once(source,line,"_WV_HTML = "+repr(html))))))
    html=once(html,'<p id="am-reason"', '<div class="metric"><span>Uczenie (obserwacje / konteksty)</span><strong id="am-learning">—</strong></div><div class="metric"><span>Pamięć / dostrojenie</span><strong id="am-learning-detail">—</strong></div><p id="am-reason"')
    html=once(html,' $("am-reason").textContent=v.fault||v.reason||"Brak odczytu.";',
    ''' const l=v.learning;
 $("am-learning").textContent=l?l.observations+" / "+l.contexts:"—";
 $("am-learning-detail").textContent=l?(l.storage_error?"RAM (błąd zapisu)":l.unsaved?"RAM (oczekuje na zapis)":"Zapis / brak nowych danych")+" · "+fmt(v.down_confirm)+" s / "+fmt(v.surplus_band)+" K":"—";
 $("am-reason").textContent=v.fault||v.reason||"Brak odczytu.";''')
    html=status_ui(html)
    return experiment_api(curve_editor_api(curve_api(activation_api(once(source,line,"_WV_HTML = "+repr(html))))))

def patch(source):
    if MARK in source:
        if source.count(MARK)!=1 or "_am.tick()" not in source or 'id="am-control"' not in ast.literal_eval(next(l for l in source.splitlines() if l.startswith("_WV_HTML = ")).split("=",1)[1].strip()):
            raise ValueError("Incomplete adaptive patch")
        end="# HOME-IOT ADAPTIVE MODULATION END"
        if source.count(end)!=1:
            raise ValueError("Incomplete adaptive module")
        start=source.index(MARK)
        stop=source.index(end,start)+len(end)
        updated=learning_ui(source[:start]+learning_block()+source[stop:])
        compile(updated,"main.py","exec")
        return updated
    # Match known call sites by AST and reject new writers. Do not edit arbitrary strings.
    tree=ast.parse(source)
    functions={n.name:n for n in tree.body if isinstance(n,ast.FunctionDef)}
    expected={
        "on_message":(1,1),
        "GetParameters":(2,2),
        "_tempzone_flimit_restore_guard":(0,2),
        "curvecalc":(10,4),
        "flimitreset":(0,1),
        "deltacheck":(3,2),
        "change_mode_route":(1,0),
        "change_flimitrelay_route":(0,1),
    }
    lines=source.splitlines(keepends=True)
    changes=[]
    for name,n in functions.items():
        calls=[x for x in ast.walk(n) if isinstance(x,ast.Call) and isinstance(x.func,ast.Name) and x.func.id in ("new_presetchange","flimitchange")]
        if not calls:
            continue
        counts=tuple(sum(x.func.id==k for x in calls) for k in ("new_presetchange","flimitchange"))
        if counts!=expected.pop(name,None):
            raise ValueError("Unrecognized output writer: "+name+" "+str(counts))
        for x in calls:
            kind="preset" if x.func.id=="new_presetchange" else "relay"
            if len(x.args)!=1 or x.keywords or x.lineno!=x.end_lineno:
                raise ValueError("Unexpected call format")
            arg=ast.get_source_segment(source,x.args[0])
            if name=="curvecalc":
                repl='_am.legacy('+repr(kind)+','+arg+',zone)'
            elif name in ("GetParameters","_tempzone_flimit_restore_guard"):
                repl='_am.priority_write('+repr(kind)+','+arg+')'
            elif name in ("on_message","change_mode_route","change_flimitrelay_route"):
                repl='_am.manual('+repr(kind)+','+arg+')'
            else:
                # Existing legacy checks run only when allowed by legacy_tick.
                continue
            # AST columns are UTF-8 offsets; replacements operate on encoded lines.
            changes.append((x.lineno-1,x.col_offset,x.end_col_offset,repl))
    if expected:
        raise ValueError("Missing expected output writers: "+repr(expected))
    for i,a,b,repl in sorted(changes,reverse=True):
        raw=lines[i].encode("utf-8")
        lines[i]=(raw[:a]+repl.encode("utf-8")+raw[b:]).decode("utf-8")
    s="".join(lines)
    s=once(s,"    deltacheck(twitwo)\n    flimitreset()", '    _am.legacy_tick("deltacheck",twitwo)\n    _am.legacy_tick("flimitreset")')
    s=once(s,"    log_status_snapshot(30)","    _am.tick()\n    log_status_snapshot(30)")
    for key in ("101","141","201","241"):
        old="                    R"+key+"=T"+key+"\n"
        s=once(s,old,old+'                    _am.note("R'+key+'",T'+key+')\n')
    # Serialize the existing single-slot write mailbox across all callers.
    n=next(n for n in ast.parse(s).body if isinstance(n,ast.FunctionDef) and n.name=="set_newframe")
    ls=s.splitlines(keepends=True)
    start=n.body[0].lineno-1
    ls[start:n.end_lineno]=["    with _am.serial_lock:\n"]+["    "+l if l.strip() else l for l in ls[start:n.end_lineno]]
    s="".join(ls)
    block="\n"+learning_block()+"\n\n"
    # Defined before MQTT callback, reader and any core output call.
    n=next(n for n in ast.parse(s).body if isinstance(n,ast.FunctionDef) and n.name=="on_message")
    ls=s.splitlines(keepends=True)
    ls.insert(min([n.lineno]+[d.lineno for d in n.decorator_list])-1,block)
    s="".join(ls)
    s=learning_ui(patch_web(s))
    compile(s,"main.py","exec")
    return s
