package pl.haierpi.mobile;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.net.Uri;
import android.net.http.SslError;
import android.os.Bundle;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.CookieManager;
import android.webkit.HttpAuthHandler;
import android.webkit.SslErrorHandler;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;
import java.net.URI;
import java.util.Locale;

public final class MainActivity extends Activity {
    private WebView web;
    private SharedPreferences prefs;
    private ProgressBar progress;
    private TextView status;
    private String origin;
    private boolean prompting;
    private static final String DEFAULT_PATH="/v2/";

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        prefs=getSharedPreferences("haierpi", Context.MODE_PRIVATE);
        LinearLayout root=new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.rgb(21,52,68));
        LinearLayout bar=new LinearLayout(this);
        bar.setOrientation(LinearLayout.HORIZONTAL);
        bar.setPadding(dp(8),dp(4),dp(8),dp(4));
        TextView title=new TextView(this);
        title.setText("HaierPi");
        title.setTextColor(Color.WHITE);
        title.setTextSize(20);
        title.setGravity(android.view.Gravity.CENTER_VERTICAL);
        bar.addView(title,new LinearLayout.LayoutParams(0,dp(48),1));
        Button reload=new Button(this);
        reload.setText("V2");
        reload.setOnClickListener(v->{if(origin!=null)web.loadUrl(origin+DEFAULT_PATH);});
        bar.addView(reload);
        Button address=new Button(this);
        address.setText("Pulpit");
        address.setOnClickListener(v->finish());
        bar.addView(address);
        root.addView(bar);
        status=new TextView(this);
        status.setTextColor(Color.WHITE);
        status.setTextSize(13);
        status.setPadding(dp(12),dp(4),dp(12),dp(4));
        root.addView(status);
        progress=new ProgressBar(this,null,android.R.attr.progressBarStyleHorizontal);
        root.addView(progress,new LinearLayout.LayoutParams(-1,dp(3)));
        web=new WebView(this);
        root.addView(web,new LinearLayout.LayoutParams(-1,0,1));
        setContentView(root);

        WebSettings settings=web.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setJavaScriptCanOpenWindowsAutomatically(false);
        settings.setSupportMultipleWindows(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        CookieManager.getInstance().setAcceptThirdPartyCookies(web,false);
        web.setWebChromeClient(new WebChromeClient(){
            @Override public void onProgressChanged(WebView view,int n){
                progress.setProgress(n);
                progress.setVisibility(n<100?View.VISIBLE:View.GONE);
            }
        });
        web.setWebViewClient(new WebViewClient(){
            @Override public boolean shouldOverrideUrlLoading(WebView v,WebResourceRequest req){
                if(!req.isForMainFrame())return false;
                if(sameOrigin(req.getUrl().toString()))return false;
                Toast.makeText(MainActivity.this,"Zablokowano przejście poza adres HaierPi",Toast.LENGTH_SHORT).show();
                return true;
            }
            @Override public void onPageFinished(WebView v,String url){
                if(sameOrigin(url))status.setText(url);
            }
            @Override public void onReceivedError(WebView v,WebResourceRequest req,WebResourceError error){
                if(req.isForMainFrame())status.setText("Brak połączenia. Sprawdź Wi-Fi, VPN i adres.");
            }
            @Override public void onReceivedSslError(WebView v,SslErrorHandler handler,SslError error){
                handler.cancel();
                status.setText("Błąd certyfikatu HTTPS. Połączenie przerwane.");
            }
            @Override public void onReceivedHttpAuthRequest(WebView v,HttpAuthHandler handler,String host,String realm){
                if(origin==null||!Uri.parse(origin).getHost().equalsIgnoreCase(host)||prompting){
                    handler.cancel();return;
                }
                prompting=true;
                LinearLayout form=new LinearLayout(MainActivity.this);
                form.setOrientation(LinearLayout.VERTICAL);
                form.setPadding(dp(20),dp(8),dp(20),dp(8));
                EditText user=new EditText(MainActivity.this);user.setHint("Użytkownik");
                user.setSingleLine(true);form.addView(user);
                EditText pass=new EditText(MainActivity.this);pass.setHint("Hasło");
                pass.setInputType(129);pass.setSingleLine(true);form.addView(pass);
                AlertDialog dialog=new AlertDialog.Builder(MainActivity.this)
                    .setTitle("Logowanie HaierPi").setView(form)
                    .setPositiveButton("Zaloguj",(a,b)->handler.proceed(user.getText().toString(),pass.getText().toString()))
                    .setNegativeButton("Anuluj",(a,b)->handler.cancel())
                    .setOnCancelListener(a->handler.cancel()).create();
                dialog.setOnDismissListener(a->prompting=false);
                dialog.show();
            }
        });
        String saved=prefs.getString("origin",null);
        if(saved==null){status.setText("Podaj adres lokalnego HaierPi.");chooseAddress();}
        else open(saved);
    }

    private int dp(int n){return Math.round(n*getResources().getDisplayMetrics().density);}
    private static String normalize(String value) throws Exception {
        String s=value.trim();
        if(!s.contains("://"))s="http://"+s;
        URI u=new URI(s);
        String scheme=u.getScheme().toLowerCase(Locale.ROOT);
        if((!scheme.equals("http")&&!scheme.equals("https"))||u.getHost()==null||
           u.getUserInfo()!=null||u.getQuery()!=null||u.getFragment()!=null||
           u.getPort()==0||u.getPort()>65535)throw new IllegalArgumentException();
        String path=u.getPath();
        if(path!=null&&!path.isEmpty()&&!path.equals("/")&&!path.equals("/v2")&&!path.equals("/v2/"))
            throw new IllegalArgumentException();
        return new URI(scheme,null,u.getHost().toLowerCase(Locale.ROOT),u.getPort(),null,null,null).toASCIIString();
    }
    private boolean sameOrigin(String url){
        try {
            URI a=new URI(origin),b=new URI(url);
            int ap=a.getPort()<0?(a.getScheme().equals("https")?443:80):a.getPort();
            int bp=b.getPort()<0?("https".equalsIgnoreCase(b.getScheme())?443:80):b.getPort();
            return a.getScheme().equalsIgnoreCase(b.getScheme())&&a.getHost().equalsIgnoreCase(b.getHost())
                &&ap==bp&&b.getUserInfo()==null;
        }catch(Exception e){return false;}
    }
    private void open(String address){
        origin=address;
        status.setText("Łączenie: "+origin);
        web.loadUrl(origin+DEFAULT_PATH);
    }
    private void confirm(String address){
        Runnable apply=()->{
            if(origin!=null&&!origin.equals(address)){
                web.stopLoading();web.clearHistory();web.clearFormData();
                CookieManager.getInstance().removeAllCookies(null);
            }
            prefs.edit().putString("origin",address).apply();
            open(address);
        };
        if(address.startsWith("http://")&&!address.equals(origin)){
            new AlertDialog.Builder(this).setTitle("Połączenie HTTP")
                .setMessage("HTTP nie szyfruje danych ani hasła. Korzystaj tylko z zaufanej sieci domowej lub bezpiecznego VPN. Jeśli masz HTTPS, wybierz ten protokół.")
                .setPositiveButton("Kontynuuj",(d,w)->apply.run())
                .setNegativeButton("Anuluj",null).show();
        }else apply.run();
    }
    private void chooseAddress(){
        EditText input=new EditText(this);
        input.setSingleLine(true);
        input.setInputType(17);
        input.setHint("http://haierpi.local:PORT");
        if(origin!=null)input.setText(origin);
        LinearLayout form=new LinearLayout(this);
        form.setOrientation(LinearLayout.VERTICAL);
        form.setPadding(dp(20),dp(8),dp(20),dp(8));
        TextView note=new TextView(this);
        note.setText("Wpisz adres IP lub nazwę i port działającego panelu HaierPi. Aplikacja sama otworzy /v2/.");
        form.addView(note);form.addView(input,new LinearLayout.LayoutParams(-1,-2));
        AlertDialog dialog=new AlertDialog.Builder(this).setTitle("Adres HaierPi")
            .setView(form).setPositiveButton("Połącz",null).setNegativeButton("Anuluj",null).create();
        dialog.setOnShowListener(d->dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v->{
            try{String address=normalize(input.getText().toString());dialog.dismiss();confirm(address);}
            catch(Exception e){input.setError("Podaj poprawny adres HTTP lub HTTPS.");}
        }));
        dialog.show();
    }
    @Override public void onBackPressed(){if(web.canGoBack())web.goBack();else super.onBackPressed();}
    @Override protected void onDestroy(){
        if(web!=null){web.stopLoading();((ViewGroup)web.getParent()).removeView(web);web.destroy();}
        super.onDestroy();
    }
}
