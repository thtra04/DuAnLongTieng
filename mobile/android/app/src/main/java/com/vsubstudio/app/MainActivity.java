package com.vsubstudio.app;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.app.DownloadManager;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.text.InputType;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.view.inputmethod.EditorInfo;
import android.view.inputmethod.InputMethodManager;
import android.webkit.CookieManager;
import android.webkit.URLUtil;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import java.net.URI;
import java.util.Locale;

/**
 * Ứng dụng Android của VSub Studio.
 *
 * Phần xử lý nặng (nhận dạng giọng nói, dịch, lồng tiếng) cần GPU nên vẫn chạy trên máy tính;
 * app này là ứng dụng khách: lưu địa chỉ máy tính trong mạng Wi-Fi, mở giao diện điện thoại của
 * VSub Studio trong WebView, cho chọn video từ máy để tải lên và lưu video kết quả vào thư mục Download.
 */
public class MainActivity extends Activity {

    private static final String PREFS = "vsub";
    private static final String KEY_SERVER = "server";
    private static final int REQ_FILE = 1;
    private static final int REQ_STORAGE = 2;
    private static final int DEFAULT_PORT = 8000;

    private static final int BG = 0xFFFAF8F3;
    private static final int BG2 = 0xFFF1ECE0;
    private static final int INK = 0xFF1C1917;
    private static final int MUTED = 0xFF57534E;
    private static final int ACCENT = 0xFFA16207;
    private static final int DANGER = 0xFFB42318;

    private SharedPreferences prefs;
    private WebView web;
    private ProgressBar bar;
    private View setup;
    private EditText address;
    private TextView message;
    private String server;
    private ValueCallback<Uri[]> pendingFiles;
    private String pendingDownload;

    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        prefs = getSharedPreferences(PREFS, MODE_PRIVATE);

        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(BG);
        web = buildWebView();
        root.addView(web, new FrameLayout.LayoutParams(-1, -1));
        bar = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        bar.setMax(100);
        bar.setProgressTintList(android.content.res.ColorStateList.valueOf(ACCENT));
        root.addView(bar, new FrameLayout.LayoutParams(-1, dp(4), Gravity.TOP));
        setup = buildSetup();
        root.addView(setup, new FrameLayout.LayoutParams(-1, -1));
        setContentView(root);

        server = prefs.getString(KEY_SERVER, null);
        if (server == null) {
            showSetup(null);
        } else if (saved != null && web.restoreState(saved) != null) {
            showWeb();
        } else {
            open(server);
        }
    }

    // ------------------------------------------------------------------ WebView

    private WebView buildWebView() {
        WebView w = new WebView(this);
        WebSettings s = w.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);           // giao diện lưu tông màu, tuỳ chọn, phiên làm dở
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setAllowFileAccess(false);
        s.setLoadWithOverviewMode(true);
        s.setUseWideViewPort(true);
        s.setUserAgentString(s.getUserAgentString() + " VSubStudioAndroid/1.1");
        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(w, false);

        w.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) {
                Uri u = req.getUrl();
                if (isStudioUrl(u)) return false;
                if (!"https".equals(u.getScheme()) || !req.isForMainFrame()) return true;
                // Liên kết ra ngoài (GitHub, trang tài liệu…) mở bằng trình duyệt của máy
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, u));
                } catch (Exception ignored) {
                }
                return true;
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest req, WebResourceError err) {
                if (req.isForMainFrame()) {
                    showSetup("Không kết nối được tới " + server + "\n(" + err.getDescription() + ")");
                }
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                bar.setVisibility(View.GONE);
            }
        });

        w.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onProgressChanged(WebView view, int p) {
                bar.setVisibility(p < 100 ? View.VISIBLE : View.GONE);
                bar.setProgress(p);
            }

            @Override
            public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> cb, FileChooserParams params) {
                if (pendingFiles != null) pendingFiles.onReceiveValue(null);
                pendingFiles = cb;
                try {
                    startActivityForResult(params.createIntent(), REQ_FILE);
                } catch (Exception e) {
                    pendingFiles = null;
                    toast("Máy không có ứng dụng chọn tệp");
                    return false;
                }
                return true;
            }
        });

        w.setDownloadListener((url, ua, disposition, mime, length) -> download(url, disposition, mime));
        return w;
    }

    private void open(String url) {
        String valid = normalize(url);
        if (valid == null) {
            showSetup("Địa chỉ cũ dùng HTTP qua Wi-Fi. Hãy đổi sang HTTPS hoặc kết nối USB.");
            return;
        }
        server = valid;
        showWeb();
        bar.setVisibility(View.VISIBLE);
        web.loadUrl(valid + "/");
    }

    private boolean isStudioUrl(Uri u) {
        if (server == null || u.getUserInfo() != null) return false;
        Uri base = Uri.parse(server);
        return base.getScheme().equals(u.getScheme()) && base.getHost() != null
                && base.getHost().equalsIgnoreCase(u.getHost()) && base.getPort() == u.getPort();
    }

    private void showWeb() {
        setup.setVisibility(View.GONE);
        web.setVisibility(View.VISIBLE);
    }

    // ------------------------------------------------------------------ Tải video kết quả

    private void download(String url, String disposition, String mime) {
        if (!isStudioUrl(Uri.parse(url))) {
            toast("Chỉ tải tệp từ studio đang kết nối");
            return;
        }
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q
                && checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE) != PackageManager.PERMISSION_GRANTED) {
            pendingDownload = url + "\n" + (disposition == null ? "" : disposition) + "\n" + (mime == null ? "" : mime);
            requestPermissions(new String[]{Manifest.permission.WRITE_EXTERNAL_STORAGE}, REQ_STORAGE);
            return;
        }
        String name = URLUtil.guessFileName(url, disposition, mime);
        DownloadManager.Request r = new DownloadManager.Request(Uri.parse(url));
        r.setTitle(name);
        r.setMimeType(mime);
        r.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
        r.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, name);
        String cookie = CookieManager.getInstance().getCookie(url);
        if (cookie != null) r.addRequestHeader("Cookie", cookie);
        ((DownloadManager) getSystemService(Context.DOWNLOAD_SERVICE)).enqueue(r);
        toast("Đang tải " + name + " về thư mục Download");
    }

    @Override
    public void onRequestPermissionsResult(int code, String[] perms, int[] results) {
        if (code == REQ_STORAGE && pendingDownload != null) {
            String[] p = pendingDownload.split("\n", -1);
            pendingDownload = null;
            if (results.length > 0 && results[0] == PackageManager.PERMISSION_GRANTED) {
                download(p[0], p[1].isEmpty() ? null : p[1], p[2].isEmpty() ? null : p[2]);
            } else {
                toast("Cần quyền lưu trữ để tải video về máy");
            }
        }
    }

    @Override
    protected void onActivityResult(int code, int result, Intent data) {
        if (code == REQ_FILE && pendingFiles != null) {
            pendingFiles.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(result, data));
            pendingFiles = null;
            return;
        }
        super.onActivityResult(code, result, data);
    }

    // ------------------------------------------------------------------ Màn hình kết nối

    private View buildSetup() {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(dp(24), dp(32), dp(24), dp(28));

        LinearLayout poster = new LinearLayout(this);
        poster.setOrientation(LinearLayout.VERTICAL);
        poster.setPadding(dp(22), dp(20), dp(22), dp(24));
        GradientDrawable cover = new GradientDrawable(GradientDrawable.Orientation.TL_BR,
                new int[]{0xFF423B2C, 0xFF232821});
        cover.setCornerRadius(dp(18));
        poster.setBackground(cover);
        TextView folio = text("VS  /  PHÒNG HẬU KỲ", 12, 0xFFEDC78E, true);
        folio.setLetterSpacing(.12f);
        poster.addView(folio);
        TextView logo = text("VSub Studio.", 40, BG, false);
        logo.setTypeface(Typeface.SERIF, Typeface.ITALIC);
        logo.setPadding(0, dp(12), 0, dp(5));
        poster.addView(logo);
        poster.addView(text("Biên tập phụ đề và lời thoại ngay trên điện thoại.", 15, BG2, false));
        box.addView(poster);
        TextView step = text("01   /   KẾT NỐI MÁY CHỦ", 12, ACCENT, true);
        step.setLetterSpacing(.10f);
        step.setPadding(0, dp(28), 0, dp(12));
        box.addView(step);

        box.addView(text("Địa chỉ máy tính đang chạy VSub Studio", 14, INK, true));
        address = new EditText(this);
        address.setHint("https://studio.example:8000");
        address.setSingleLine(true);
        address.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        address.setImeOptions(EditorInfo.IME_ACTION_GO);
        address.setTextSize(TypedValue.COMPLEX_UNIT_SP, 17);
        address.setTextColor(INK);
        address.setContentDescription("Địa chỉ máy chủ VSub Studio");
        address.setPadding(dp(14), dp(12), dp(14), dp(12));
        address.setBackground(round(Color.WHITE, 0x4D574623));
        address.setOnEditorActionListener((v, id, ev) -> {
            if (id == EditorInfo.IME_ACTION_GO
                    || (ev != null && ev.getKeyCode() == KeyEvent.KEYCODE_ENTER && ev.getAction() == KeyEvent.ACTION_DOWN)) {
                connect();
                return true;
            }
            return false;
        });
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.topMargin = dp(8);
        box.addView(address, lp);

        message = text("", 14, DANGER, false);
        message.setPadding(0, dp(10), 0, 0);
        box.addView(message);

        Button go = new Button(this);
        go.setText("Tiếp tục đến đăng nhập");
        go.setAllCaps(false);
        go.setTextSize(TypedValue.COMPLEX_UNIT_SP, 17);
        go.setTextColor(BG);
        go.setTypeface(Typeface.DEFAULT_BOLD);
        go.setBackground(round(INK, INK));
        go.setOnClickListener(v -> connect());
        LinearLayout.LayoutParams gp = new LinearLayout.LayoutParams(-1, dp(52));
        gp.topMargin = dp(16);
        box.addView(go, gp);

        TextView help = text(
                "Chọn cách kết nối\n\n"
                        + "Wi-Fi  ·  Nhập địa chỉ HTTPS của studio. Chứng thư phải được điện thoại tin cậy.\n\n"
                        + "USB  ·  Trên máy tính chạy VSub Studio, bật gỡ lỗi USB rồi chạy:\n"
                        + "adb reverse tcp:8000 tcp:8000\nNhập localhost:8000 trên điện thoại.\n\n"
                        + "Lần đầu? Xin mã mời từ chủ máy để tạo tài khoản. Video vẫn được xử lý trên máy tính.",
                14, MUTED, false);
        help.setLineSpacing(0, 1.25f);
        help.setPadding(dp(16), dp(14), dp(16), dp(14));
        help.setBackground(round(BG2, BG2));
        LinearLayout.LayoutParams hp = new LinearLayout.LayoutParams(-1, -2);
        hp.topMargin = dp(28);
        box.addView(help, hp);

        ScrollView scroll = new ScrollView(this);
        scroll.setBackgroundColor(BG);
        scroll.setFillViewport(true);
        scroll.addView(box);
        return scroll;
    }

    private void showSetup(String error) {
        web.setVisibility(View.GONE);
        bar.setVisibility(View.GONE);
        setup.setVisibility(View.VISIBLE);
        String s = server != null ? server : prefs.getString(KEY_SERVER, "");
        address.setText(s == null ? "" : s);
        address.setSelection(address.getText().length());
        message.setText(error == null ? "" : error);
        message.setVisibility(error == null ? View.GONE : View.VISIBLE);
    }

    private void connect() {
        String url = normalize(address.getText().toString());
        if (url == null) {
            message.setText("Wi-Fi cần địa chỉ HTTPS. Qua USB, dùng localhost:8000.");
            message.setVisibility(View.VISIBLE);
            return;
        }
        prefs.edit().putString(KEY_SERVER, url).apply();
        ((InputMethodManager) getSystemService(Context.INPUT_METHOD_SERVICE))
                .hideSoftInputFromWindow(address.getWindowToken(), 0);
        address.clearFocus();
        web.clearHistory();
        open(url);
    }

    /** Never submit studio credentials over cleartext Wi-Fi. */
    static String normalize(String raw) {
        String s = raw == null ? "" : raw.trim();
        if (!s.contains("://")) s = (s.matches("(?i)(localhost|127\\.0\\.0\\.1)([:/].*)?") ? "http://" : "https://") + s;
        try {
            URI u = new URI(s);
            String h = u.getHost(), scheme = u.getScheme().toLowerCase(Locale.ROOT);
            if (h == null || u.getUserInfo() != null || u.getQuery() != null || u.getFragment() != null
                    || !(u.getPath().isEmpty() || u.getPath().equals("/"))) return null;
            boolean loopback = h.equalsIgnoreCase("localhost") || h.equals("127.0.0.1") || h.equals("[::1]");
            if (!scheme.equals("https") && !(loopback && scheme.equals("http"))) return null;
            int port = u.getPort();
            if (port == 0 || port > 65535) return null;
            if (port == -1 && scheme.equals("http")) port = DEFAULT_PORT;
            return scheme + "://" + h + (port == -1 || (port == 443 && scheme.equals("https")) ? "" : ":" + port);
        } catch (Exception invalid) {
            return null;
        }
    }

    // ------------------------------------------------------------------ Nút quay lại

    @Override
    public void onBackPressed() {
        if (setup.getVisibility() == View.VISIBLE) {
            if (server != null && prefs.getString(KEY_SERVER, null) != null && web.getUrl() != null) {
                showWeb();
            } else {
                super.onBackPressed();
            }
            return;
        }
        if (web.canGoBack()) {
            web.goBack();
            return;
        }
        new AlertDialog.Builder(this)
                .setTitle("VSub Studio")
                .setMessage("Đang kết nối tới " + server)
                .setPositiveButton("Thoát", (d, w) -> finish())
                .setNeutralButton("Đổi máy tính", (d, w) -> showSetup(null))
                .setNegativeButton("Tải lại", (d, w) -> web.reload())
                .show();
    }

    @Override
    protected void onSaveInstanceState(Bundle out) {
        super.onSaveInstanceState(out);
        web.saveState(out);
    }

    @Override
    protected void onDestroy() {
        web.destroy();
        super.onDestroy();
    }

    // ------------------------------------------------------------------ Tiện ích

    private TextView text(String s, int sp, int color, boolean bold) {
        TextView t = new TextView(this);
        t.setText(s);
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp);
        t.setTextColor(color);
        if (bold) t.setTypeface(Typeface.DEFAULT_BOLD);
        return t;
    }

    private GradientDrawable round(int fill, int stroke) {
        GradientDrawable g = new GradientDrawable();
        g.setColor(fill);
        g.setCornerRadius(dp(14));
        g.setStroke(dp(1), stroke);
        return g;
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }

    private void toast(String s) {
        Toast.makeText(this, s, Toast.LENGTH_LONG).show();
    }
}
