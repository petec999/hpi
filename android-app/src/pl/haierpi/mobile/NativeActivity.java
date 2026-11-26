package pl.haierpi.mobile;

import android.app.*;
import android.content.*;
import android.graphics.*;
import android.graphics.drawable.GradientDrawable;
import android.os.*;
import android.view.*;
import android.webkit.CookieManager;
import android.widget.*;
import java.net.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;
import java.util.regex.*;
import org.json.*;

public final class NativeActivity extends Activity {
    private static final int BG=0xff101b26,CARD=0xff203141,FG=0xffedf5fa,MUTED=0xffb3c5d1,ACCENT=0xff5edbc9,HOT=0xffffa074,COOL=0xff82bdff;
    private static final long FRESH_MS=15000;
    private static final String[] TABS={"Pulpit","Adaptive","Trendy","Sterowanie"};
    private final Handler ui=new Handler(Looper.getMainLooper());
    private final ExecutorService io=Executors.newSingleThreadExecutor();
    private final ArrayList<float[]> history=new ArrayList<>();
    private SharedPreferences prefs;
    private LinearLayout body,nav;
    private TextView status,heading;
    private ScrollView scroll;
    private JSONObject data;
    private String origin,problem="",message="";
    private boolean demo,active,busy,writing,confirming;
    private int tab,epoch,demoStep;
    private long observed,lastHistory;
    private final Runnable ticker=new Runnable(){public void run(){if(active){refresh();ui.postDelayed(this,5000);}}};
    @Override public void onCreate(Bundle b){
        super.onCreate(b);
        prefs=getSharedPreferences("haierpi",Context.MODE_PRIVATE);
        origin=prefs.getString("origin",null);
        demo=prefs.getBoolean("demo",origin==null);
        getWindow().setStatusBarColor(BG);getWindow().setNavigationBarColor(BG);
        LinearLayout root=column();root.setBackgroundColor(BG);
        LinearLayout header=row();header.setPadding(dp(16),dp(10),dp(8),dp(5));
        heading=txt("HaierPi",25,FG,true);header.addView(heading,new LinearLayout.LayoutParams(0,-2,1));
        Button setup=button("Połączenie");setup.setOnClickListener(v->settings());header.addView(setup);root.addView(header);
        status=txt("",13,MUTED,false);status.setPadding(dp(16),0,dp(16),dp(10));root.addView(status);
        scroll=new ScrollView(this);scroll.setFillViewport(true);
        body=column();body.setPadding(dp(12),0,dp(12),dp(12));scroll.addView(body);root.addView(scroll,new LinearLayout.LayoutParams(-1,0,1));
        nav=row();nav.setPadding(dp(4),dp(4),dp(4),dp(6));root.addView(nav);
        for(int i=0;i<TABS.length;i++){final int k=i;Button btt=button(TABS[i]);btt.setTextSize(11);btt.setPadding(0,0,0,0);
            btt.setOnClickListener(v->{tab=k;scroll.scrollTo(0,0);render();});nav.addView(btt,new LinearLayout.LayoutParams(0,dp(50),1));}
        setContentView(root);render();
    }
    @Override protected void onResume(){super.onResume();active=true;ui.removeCallbacks(ticker);ticker.run();}
    @Override protected void onPause(){active=false;ui.removeCallbacks(ticker);super.onPause();}
    @Override protected void onDestroy(){ui.removeCallbacksAndMessages(null);io.shutdownNow();super.onDestroy();}
    private int dp(float x){return Math.round(x*getResources().getDisplayMetrics().density);}
    private LinearLayout column(){LinearLayout l=new LinearLayout(this);l.setOrientation(LinearLayout.VERTICAL);return l;}
    private LinearLayout row(){LinearLayout l=new LinearLayout(this);l.setOrientation(LinearLayout.HORIZONTAL);l.setGravity(Gravity.CENTER_VERTICAL);return l;}
    private TextView txt(String s,int size,int color,boolean bold){TextView t=new TextView(this);t.setText(s);t.setTextSize(size);t.setTextColor(color);if(bold)t.setTypeface(null,Typeface.BOLD);return t;}
    private GradientDrawable bg(int color,int radius){GradientDrawable d=new GradientDrawable();d.setColor(color);d.setCornerRadius(dp(radius));return d;}
    private Button button(String s){Button b=new Button(this);b.setText(s);b.setAllCaps(false);b.setTextColor(ACCENT);return b;}
    private LinearLayout panel(){LinearLayout l=column();l.setBackground(bg(CARD,14));l.setPadding(dp(15),dp(13),dp(15),dp(13));LinearLayout.LayoutParams lp=new LinearLayout.LayoutParams(-1,-2);lp.setMargins(dp(4),dp(4),dp(4),dp(8));l.setLayoutParams(lp);return l;}
    private void section(String s){TextView t=txt(s,17,FG,true);t.setPadding(dp(5),dp(12),0,dp(6));body.addView(t);}
    private void line(LinearLayout p,String label,String val){LinearLayout r=row();TextView a=txt(label,14,MUTED,false),b=txt(val,15,FG,true);b.setGravity(Gravity.END);a.setPadding(0,dp(7),dp(8),dp(7));r.addView(a,new LinearLayout.LayoutParams(0,-2,1));r.addView(b,new LinearLayout.LayoutParams(0,-2,1));p.addView(r);}
    private void note(String s){TextView t=txt(s,13,MUTED,false);t.setPadding(dp(7),dp(5),dp(7),dp(9));body.addView(t);}
    private void action(String label,boolean enabled,Runnable run){Button b=button(label);b.setEnabled(enabled);b.setOnClickListener(v->run.run());body.addView(b);}
    private JSONObject obj(JSONObject o,String k){JSONObject n=o==null?null:o.optJSONObject(k);return n==null?new JSONObject():n;}
    private String val(JSONObject o,String k){return o==null||o.isNull(k)?"—":o.optString(k,"—");}
    private String fmt(JSONObject o,String k,String unit){double n=o==null?Double.NaN:o.optDouble(k,Double.NaN);return Double.isFinite(n)?String.format(Locale.forLanguageTag("pl-PL"),"%.1f",n)+unit:"—";}
    private boolean fresh(){return data!=null&&SystemClock.elapsedRealtime()-observed<=FRESH_MS;}
    private JSONObject current(){return fresh()?data:new JSONObject();}
    private void reset(){epoch++;data=null;observed=0;history.clear();lastHistory=0;problem="";message="";demoStep=0;}
    private void setDemo(boolean value){demo=value;prefs.edit().putBoolean("demo",demo).apply();reset();render();refresh();}
    private void settings(){
        if(writing||confirming)return;
        LinearLayout p=column();p.setPadding(dp(20),dp(10),dp(20),dp(10));
        TextView hint=txt("Adres istniejącego panelu HaierPi, razem z portem. HTTP tylko przez zaufane Wi-Fi lub VPN.",14,FG,false);p.addView(hint);
        EditText e=new EditText(this);e.setSingleLine(true);e.setInputType(17);e.setHint("http://haierpi.local:5000");if(origin!=null)e.setText(origin);p.addView(e);
        AlertDialog d=new AlertDialog.Builder(this).setTitle("Połączenie z HaierPi").setView(p)
            .setPositiveButton("Połącz",null).setNeutralButton("Demo",(a,b)->setDemo(true)).setNegativeButton("Anuluj",null).create();
        d.setOnShowListener(x->d.getButton(-1).setOnClickListener(v->{
            try{String next=normalize(e.getText().toString());d.dismiss();Runnable apply=()->{
                if(!Objects.equals(origin,next)){
                    reset();origin=next;
                    CookieManager.getInstance().removeAllCookies(ignored->{prefs.edit().putString("origin",next).apply();setDemo(false);});
                }else{prefs.edit().putString("origin",next).apply();setDemo(false);}
            };if(next.startsWith("http://")&&!next.equals(origin))new AlertDialog.Builder(this).setTitle("Nieszyfrowane HTTP")
                .setMessage("Hasło i dane mogą być przechwycone w niezaufanej sieci. Użyj HTTPS lub VPN, jeśli dostępne.")
                .setPositiveButton("Rozumiem",(a,b)->apply.run()).setNegativeButton("Anuluj",null).show();else apply.run();
            }catch(Exception ex){e.setError("Nieprawidłowy adres lub port.");}
        }));d.show();
    }
    private static String normalize(String s) throws Exception {
        s=s.trim();if(!s.contains("://"))s="http://"+s;
        URI u=new URI(s);String protocol=u.getScheme().toLowerCase(Locale.ROOT);
        String path=u.getPath();
        if(!Arrays.asList("http","https").contains(protocol)||u.getHost()==null||u.getUserInfo()!=null||u.getPort()==0||u.getPort()>65535||u.getQuery()!=null||u.getFragment()!=null||
            (path!=null&&!Arrays.asList("","/","/v2","/v2/").contains(path)))throw new IllegalArgumentException();
        int port=u.getPort();if((protocol.equals("http")&&port==80)||(protocol.equals("https")&&port==443))port=-1;
        return new URI(protocol,null,u.getHost().toLowerCase(Locale.ROOT),port,null,null,null).toASCIIString();
    }
    private void web(){if(!demo&&origin!=null)startActivity(new Intent(this,MainActivity.class));}
    private static String read(InputStream is,int max) throws IOException {
        try(InputStream input=is;ByteArrayOutputStream out=new ByteArrayOutputStream()){
            byte[] buf=new byte[4096];int n;while((n=input.read(buf))!=-1){if(out.size()+n>max)throw new IOException("Odpowiedź za duża");out.write(buf,0,n);}return out.toString("UTF-8");
        }
    }
    private static final class Reply{final int code;final String body;Reply(int c,String b){code=c;body=b;}}
    private Reply request(String base,String path,JSONObject post,String csrf) throws Exception {
        URL url=new URL(base+path);
        HttpURLConnection c=(HttpURLConnection)url.openConnection(Proxy.NO_PROXY);
        c.setInstanceFollowRedirects(false);c.setConnectTimeout(6000);c.setReadTimeout(6000);c.setUseCaches(false);
        c.setRequestProperty("Accept",post!=null||path.contains("/api/")?"application/json":"text/html");
        String cookie=CookieManager.getInstance().getCookie(url.toString());if(cookie!=null&&!cookie.isEmpty())c.setRequestProperty("Cookie",cookie);
        try{
            if(post!=null){c.setRequestMethod("POST");c.setDoOutput(true);c.setRequestProperty("Content-Type","application/json");
                c.setRequestProperty("X-HaierPi-CSRF",csrf);c.setRequestProperty("Origin",base);
                byte[] bytes=post.toString().getBytes(StandardCharsets.UTF_8);c.setFixedLengthStreamingMode(bytes.length);
                try(OutputStream out=c.getOutputStream()){out.write(bytes);}
            }
            int code=c.getResponseCode();
            for(Map.Entry<String,List<String>> h:c.getHeaderFields().entrySet())if("set-cookie".equalsIgnoreCase(h.getKey()))for(String x:h.getValue())CookieManager.getInstance().setCookie(url.toString(),x);
            InputStream stream=code>=400?c.getErrorStream():c.getInputStream();
            return new Reply(code,stream==null?"":read(stream,1024*1024));
        }finally{c.disconnect();}
    }
    private JSONObject fetchState(String base) throws Exception{
        Reply reply=request(base,"/v2/api/state",null,null);
        if(reply.code==401||reply.code==403||reply.code/100==3)throw new IOException("Zaloguj się do HaierPi w panelu WWW.");
        if(reply.code==404)throw new IOException("Brak API v2 – sprawdź adres i wersję serwera.");
        if(reply.code!=200)throw new IOException("HTTP "+reply.code);
        JSONObject j;try{j=new JSONObject(reply.body);}catch(JSONException e){throw new IOException("Serwer nie zwrócił API v2. Sprawdź logowanie.");}
        if(j.optInt("schema",-1)!=1||j.optJSONObject("values")==null)throw new IOException("Niezgodna wersja API.");
        return j;
    }
    private void refresh(){
        if(!active||busy||writing||confirming)return;
        if(demo){try{data=demoData();observed=SystemClock.elapsedRealtime();problem="";record();}catch(Exception ignored){}render();return;}
        if(origin==null){render();return;}
        final String base=origin;final int gen=epoch;busy=true;
        io.execute(()->{JSONObject result=null;String error="";
            try{result=fetchState(base);}catch(Exception e){error=e.getMessage()==null?"Brak połączenia":e.getMessage();}
            final JSONObject r=result;final String err=error;
            ui.post(()->{busy=false;if(isFinishing()||isDestroyed())return;if(gen==epoch){data=r;observed=r==null?0:SystemClock.elapsedRealtime();problem=err;record();}if(active)render();});
        });
    }
    private void record(){
        long now=SystemClock.elapsedRealtime();if(now-lastHistory<4000)return;lastHistory=now;
        JSONObject v=obj(data,"values");float a=(float)v.optDouble("twi",Double.NaN),b=(float)v.optDouble("two",Double.NaN),f=(float)v.optDouble("fact",Double.NaN);
        history.add(new float[]{a,b,f});if(history.size()>120)history.remove(0);
    }
    private JSONObject demoData() throws Exception{
        double phase=(demoStep++%90)/90.0, twi=29.2+3.0*phase,two=twi+3.1,hz=34+7*Math.sin(phase*6.28);
        JSONObject j=new JSONObject(),v=new JSONObject(),a=new JSONObject(),c=new JSONObject(),h=new JSONObject();
        v.put("twi",twi).put("two",two).put("delta",3.1).put("tao",1.4).put("fact",hz).put("fset",hz).put("current",3.2).put("voltage",320).put("comp_temp",42).put("defrost",false);
        c.put("pch","on").put("pdhw","off").put("hcurve",32).put("settemp",30).put("dhw",50).put("mode","eco").put("heatcontrol","curve");
        h.put("cycles",3).put("total",7).put("twi",new JSONObject("{\"start\":{\"offset\":-2.2},\"stop\":{\"offset\":0.7},\"width\":2.9}"))
         .put("two",new JSONObject("{\"start\":{\"offset\":-2.2},\"stop\":{\"offset\":3.8},\"width\":6}"));
        a.put("control","experiment").put("mode","eco").put("relay","0").put("curve",32).put("reason_pl","Przykładowe dane – eksperyment").put("proposed","quiet / OFF").put("hysteresis",h);
        a.put("experiment",new JSONObject("{\"levels\":[\"eco / OFF\",\"quiet / OFF\",\"quiet+FLimit\",\"eco+FLimit\",\"turbo+FLimit\",\"turbo / OFF\"],\"counts\":[3,2,1,0,0,0],\"per_level\":3}"));
        return j.put("schema",1).put("values",v).put("controls",c).put("adaptive",a).put("control_ready",false).put("mqtt",true);
    }
    private String controlName(String s){switch(s){case "legacy":return "Legacy";case "manual":return "Ręczne";case "shadow":return "Obserwacja";case "auto":return "Adaptive Auto";case "experiment":return "Eksperyment";default:return s;}}
    private void tile(LinearLayout row,String label,String value,int color){
        LinearLayout p=panel();LinearLayout.LayoutParams lp=new LinearLayout.LayoutParams(0,-2,1);lp.setMargins(dp(4),dp(4),dp(4),dp(4));p.setLayoutParams(lp);
        p.addView(txt(label,13,MUTED,false));TextView t=txt(value,27,color,true);t.setPadding(0,dp(5),0,0);p.addView(t);row.addView(p);
    }
    private void render(){
        if(isFinishing()||isDestroyed())return;
        int old=scroll.getScrollY();body.removeAllViews();
        for(int i=0;i<nav.getChildCount();i++){Button b=(Button)nav.getChildAt(i);b.setTextColor(i==tab?FG:ACCENT);b.setBackground(bg(i==tab?0xff365565:BG,8));}
        heading.setText(demo?"HaierPi · DEMO":"HaierPi");
        status.setText(demo?"Dane symulowane • sterowanie wyłączone":writing?"Wysyłanie polecenia…":fresh()?"Połączono · "+origin:origin==null?"Brak adresu – wybierz Połączenie":problem.isEmpty()?"Oczekiwanie na odczyt…":problem);
        status.setTextColor(demo||fresh()?ACCENT:HOT);
        JSONObject j=current(),v=obj(j,"values"),c=obj(j,"controls"),a=obj(j,"adaptive");
        if(!demo&&!fresh()){note("Brak aktualnych danych. Polecenia są zablokowane.");action("Logowanie / panel WWW",origin!=null,()->web());}
        if(!message.isEmpty())note(message);
        if(tab==0){
            section("Obieg grzewczy");LinearLayout r=row();tile(r,"Zasilanie · Two",fmt(v,"two","°"),HOT);tile(r,"Powrót · Twi",fmt(v,"twi","°"),COOL);body.addView(r);
            r=row();tile(r,"Sprężarka · Fact",fmt(v,"fact"," Hz"),ACCENT);tile(r,"Na zewnątrz",fmt(v,"tao","°"),FG);body.addView(r);
            LinearLayout p=panel();line(p,"ΔT wody",fmt(v,"delta"," K"));line(p,"Nastawa z krzywej",fmt(c,"hcurve"," °C"));line(p,"Zadana częstotliwość",fmt(v,"fset"," Hz"));
            line(p,"CO",val(c,"pch"));line(p,"Tryb",val(c,"mode"));line(p,"Odszranianie",val(v,"defrost"));body.addView(p);
            section("Sprężarka");p=panel();line(p,"Prąd",fmt(v,"current"," A"));line(p,"Napięcie",fmt(v,"voltage"," V"));line(p,"Temperatura",fmt(v,"comp_temp"," °C"));line(p,"MQTT",val(j,"mqtt"));body.addView(p);
            section("Komunikacja");p=panel();JSONObject frames=obj(j,"frames");for(String key:new String[]{"r141","r241"})line(p,key.toUpperCase(Locale.ROOT),fmt(obj(frames,key),"age_s"," s"));
            line(p,"Watchdog",val(obj(j,"watchdog"),"status"));body.addView(p);
        }else if(tab==1){
            section("Adaptive / obserwator");LinearLayout p=panel();line(p,"Sterowanie",controlName(val(a,"control")));line(p,"Odczyt trybu",val(a,"mode"));line(p,"FLimit","1".equals(val(a,"relay"))?"ON":"0".equals(val(a,"relay"))?"OFF":"—");
            line(p,"Propozycja",val(a,"proposed"));line(p,"Próg STOP (model)",fmt(a,"stop_target"," °C"));line(p,"Do STOP (model)",fmt(a,"stop_margin"," K"));
            p.addView(txt(val(a,"reason_pl"),14,FG,false));body.addView(p);
            JSONObject h=obj(a,"hysteresis");section("Histereza – pomiary");p=panel();line(p,"Cykle w kontekście",val(h,"cycles"));line(p,"Łącznie",val(h,"total"));
            for(String key:new String[]{"twi","two","mean"}){JSONObject s=obj(h,key);p.addView(txt(key.equals("mean")?"Średnia Twi/Two":key.equals("twi")?"Twi – powrót":"Two – zasilanie",14,ACCENT,true));line(p,"START / STOP",fmt(obj(s,"start"),"offset"," K")+" / "+fmt(obj(s,"stop"),"offset"," K"));line(p,"Pasmo",fmt(s,"width"," K"));}
            JSONObject ext=obj(h,"extended");line(p,"Fact przed STOP",fmt(ext,"stop_fact"," Hz"));line(p,"ΔT przed STOP",fmt(ext,"stop_water_delta"," K"));line(p,"Na zewnątrz przed STOP",fmt(ext,"stop_outdoor"," °C"));body.addView(p);
            JSONObject exp=obj(a,"experiment");JSONArray levels=exp.optJSONArray("levels"),counts=exp.optJSONArray("counts");
            if(levels!=null&&counts!=null){section("Eksperyment");p=panel();for(int i=0;i<Math.min(levels.length(),counts.length());i++)line(p,levels.optString(i),counts.optInt(i)+" / "+exp.optInt("per_level",3));body.addView(p);}
            note("Progi obserwowane, nie potwierdzone parametry firmware. Zmiany tylko w sterowaniu lub panelu WWW.");
        }else if(tab==2){
            section("Trendy od otwarcia aplikacji");LinearLayout p=panel();p.addView(txt("Temperatury  ·  Two (pomarańczowy) / Twi (niebieski)",15,FG,true));p.addView(new Plot(false),new LinearLayout.LayoutParams(-1,dp(200)));p.addView(txt("Sprężarka · Fact",15,FG,true));p.addView(new Plot(true),new LinearLayout.LayoutParams(-1,dp(160)));body.addView(p);
            note("Ostatnie 120 próbek, co około 5 sekund podczas pracy aplikacji. Brak trwałej historii. Braki danych przerywają wykres.");
        }else{
            section("Sterowanie");boolean ok=!demo&&fresh()&&!busy&&!writing&&j.optBoolean("control_ready")&&!a.optBoolean("pending");
            LinearLayout p=panel();line(p,"CO",val(c,"pch"));line(p,"CWU",val(c,"pdhw"));line(p,"Tryb",val(c,"mode"));line(p,"Adaptive",controlName(val(a,"control")));body.addView(p);
            for(String key:new String[]{"pch","pdhw"}){String x=val(c,key),next="on".equals(x)?"off":"on";action((key.equals("pch")?"CO":"CWU")+" – "+("on".equals(x)?"wyłącz":"włącz"),ok&&Arrays.asList("on","off").contains(x),()->confirm(key,next,x));}
            String owner=val(a,"control");boolean manual=owner.equals("manual")||owner.equals("legacy")||a.length()==0;
            action("Zmień tryb Quiet / Eco / Turbo",ok&&manual,()->select("mode",val(c,"mode"),new String[]{"quiet","eco","turbo"},new String[]{"Quiet","Eco","Turbo"}));
            action("Zmień sterowanie Adaptive",!demo&&fresh()&&!busy&&!writing&&a.has("control")&&!a.optBoolean("pending"),()->select("adaptive_control",owner,new String[]{"legacy","manual","shadow","auto","experiment"},new String[]{"Legacy","Ręczne","Obserwacja","Adaptive Auto","Eksperyment"}));
            note("Każde polecenie wymaga potwierdzenia, aktualnego odczytu i akceptacji przez serwer. Brak automatycznego ponawiania. Krzywa grzewcza i pozostałe ustawienia są w panelu WWW.");
            action("Zaawansowane ustawienia / WWW V2",!demo&&origin!=null,()->web());
        }
        scroll.post(()->scroll.scrollTo(0,old));
    }
    private void select(String key,String expected,String[] values,String[] labels){
        if(!fresh()||demo||busy||writing||confirming)return;
        confirming=true;
        AlertDialog d=new AlertDialog.Builder(this).setTitle("Wybierz ustawienie").setItems(labels,(a,i)->{confirming=false;if(!values[i].equals(expected))confirm(key,values[i],expected);}).setNegativeButton("Anuluj",null).create();
        d.setOnDismissListener(x->{if(!writing){confirming=false;}});d.show();
    }
    private void confirm(String key,String value,String expected){
        if(!fresh()||demo||busy||writing)return;
        confirming=true;
        String label=key.equals("adaptive_control")?"Sterowanie Adaptive":key.equals("mode")?"Tryb pracy":key.equals("pch")?"CO":"CWU";
        AlertDialog d=new AlertDialog.Builder(this).setTitle("Potwierdź zmianę").setMessage(label+": "+expected+" → "+value+"\nPolecenie dotyczy rzeczywistej pompy.")
            .setPositiveButton("Zastosuj",(a,b)->{confirming=false;send(key,value,expected);}).setNegativeButton("Anuluj",null).create();
        d.setOnDismissListener(x->confirming=false);d.show();
    }
    private void send(String key,String value,String expected){
        if(demo||origin==null||!fresh()||busy||writing)return;
        JSONObject j=current(),a=obj(j,"adaptive"),c=obj(j,"controls");
        if(a.optBoolean("pending")||!expected.equals(key.equals("adaptive_control")?val(a,"control"):val(c,key))||
           (!key.equals("adaptive_control")&&!j.optBoolean("control_ready")))return;
        final String base=origin;final int gen=epoch;writing=true;message="";render();
        io.execute(()->{
            String result;
            try{
                Reply page=request(base,"/v2/",null,null);
                if(page.code!=200)throw new IOException("Brak zalogowanej sesji v2");
                Matcher m=Pattern.compile("name=\"wv-csrf\"\\s+content=\"([a-f0-9]{64})\"").matcher(page.body);
                if(!m.find())throw new IOException("Brak tokenu CSRF");
                JSONObject post=new JSONObject().put("key",key).put("value",value).put("expected",expected);
                Reply r=request(base,"/v2/api/control",post,m.group(1));
                if(r.code/100!=2||!new JSONObject(r.body).optBoolean("accepted"))throw new IOException("Serwer nie zaakceptował polecenia (HTTP "+r.code+")");
                result="Polecenie zaakceptowane. Sprawdź nowy stan w odczycie.";
            }catch(Exception e){result="Brak potwierdzenia. "+(e.getMessage()==null?"":e.getMessage())+" Sprawdź odczyt przed ponowieniem.";}
            final String feedback=result;
            ui.post(()->{writing=false;if(isFinishing()||isDestroyed())return;if(gen==epoch){data=null;observed=0;message=feedback;}render();refresh();});
        });
    }
    private final class Plot extends View {
        private final boolean frequency;private final Paint paint=new Paint(Paint.ANTI_ALIAS_FLAG);
        Plot(boolean f){super(NativeActivity.this);frequency=f;setContentDescription(f?"Wykres częstotliwości sprężarki":"Wykres temperatur wody");}
        @Override protected void onDraw(Canvas c){
            super.onDraw(c);float left=dp(38),right=getWidth()-dp(8),top=dp(16),bottom=getHeight()-dp(24);
            float lo=frequency?0:Float.POSITIVE_INFINITY,hi=frequency?60:Float.NEGATIVE_INFINITY;
            for(float[] s:history){for(int k:frequency?new int[]{2}:new int[]{0,1})if(Float.isFinite(s[k])){lo=Math.min(lo,s[k]);hi=Math.max(hi,s[k]);}}
            if(!Float.isFinite(lo)||!Float.isFinite(hi)){lo=0;hi=10;}if(!frequency){lo=(float)Math.floor(lo-1);hi=(float)Math.ceil(hi+1);}if(hi<=lo)hi=lo+1;
            paint.setTextSize(dp(11));paint.setStrokeWidth(dp(1));paint.setStyle(Paint.Style.FILL);
            for(int i=0;i<4;i++){float y=top+(bottom-top)*i/3;paint.setColor(0xff486172);c.drawLine(left,y,right,y,paint);paint.setColor(MUTED);c.drawText(String.format(Locale.ROOT,"%.0f",hi-(hi-lo)*i/3),0,y+dp(3),paint);}
            paint.setColor(MUTED);c.drawText("starsze",left,getHeight()-dp(5),paint);c.drawText("teraz",right-dp(33),getHeight()-dp(5),paint);
            for(int k:frequency?new int[]{2}:new int[]{0,1}){
                paint.setColor(k==2?ACCENT:k==0?COOL:HOT);paint.setStrokeWidth(dp(2));boolean have=false;float px=0,py=0;
                for(int i=0;i<history.size();i++){float value=history.get(i)[k];if(!Float.isFinite(value)){have=false;continue;}
                    float x=right-(right-left)*(history.size()-1-i)/119f,y=bottom-(bottom-top)*(value-lo)/(hi-lo);
                    if(have)c.drawLine(px,py,x,y,paint);else c.drawCircle(x,y,dp(2),paint);px=x;py=y;have=true;
                }
            }
        }
    }
}
