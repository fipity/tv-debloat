package local.tvhome;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.provider.Settings;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.view.ViewGroup;
import android.widget.FrameLayout;
import android.widget.HorizontalScrollView;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextClock;
import android.widget.TextView;
import android.widget.Toast;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

public class HomeActivity extends Activity {
    private static final long ROTATE_MS = 45_000;
    private static final long FADE_MS = 2_000;

    private final Handler ui = new Handler(Looper.getMainLooper());
    private ImageView[] walls;
    private int front = 0;
    private List<String> wallFiles = new ArrayList<>();
    private final Map<String, String> credits = new HashMap<>();
    private int wallIndex = -1;
    private TextView credit;
    private LinearLayout dockRow;
    private HorizontalScrollView dockScroll;

    private final Runnable rotate = new Runnable() {
        @Override public void run() { nextWallpaper(); ui.postDelayed(this, ROTATE_MS); }
    };

    // ---- start on Live TV ----
    // Turning the TV on wakes it from standby (Sony sends its own SCREEN_ON as well as Android's) and brings
    // Home to the front. Open Live TV instead; pressing Home afterwards still shows this screen as normal.
    static final String LIVE_TV = "com.sony.dtv.tvx";
    private static final String SONY_SCREEN_ON = "com.sony.dtv.intent.action.SCREEN_ON";
    private static final long WAKE_WINDOW_MS = 8_000;
    private long wokeAt = -1;          // elapsedRealtime of the last power-on; -1 when there's nothing left to do
    private long liveTvOpenedAt = -WAKE_WINDOW_MS;
    private int opensThisWake = 0;     // at most twice: the first open, plus once more if the system re-shows Home

    private final BroadcastReceiver screenOn = new BroadcastReceiver() {
        @Override public void onReceive(Context c, Intent i) {
            wokeAt = SystemClock.elapsedRealtime();
            opensThisWake = 0;
            ui.removeCallbacks(openLiveTvAfterWake);
            ui.postDelayed(openLiveTvAfterWake, 700);   // let the system's own wake-up Home launch land first
        }
    };

    private final Runnable openLiveTvAfterWake = () -> {
        long now = SystemClock.elapsedRealtime();
        if (wokeAt < 0 || now - wokeAt > WAKE_WINDOW_MS || now - liveTvOpenedAt < 2_000) return;
        liveTvOpenedAt = now;
        if (++opensThisWake >= 2) wokeAt = -1;
        launch(LIVE_TV);
    };

    private final BroadcastReceiver pkgChanged = new BroadcastReceiver() {
        @Override public void onReceive(Context c, Intent i) { Apps.invalidate(); buildDock(false); }
    };

    @Override protected void onCreate(Bundle b) {
        super.onCreate(b);
        getWindow().getDecorView().setSystemUiVisibility(
            View.SYSTEM_UI_FLAG_FULLSCREEN | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY);

        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.BLACK);
        root.setClipChildren(false);

        walls = new ImageView[] {new ImageView(this), new ImageView(this)};
        for (ImageView w : walls) {
            w.setScaleType(ImageView.ScaleType.CENTER_CROP);
            w.setAlpha(0f);
            root.addView(w, new FrameLayout.LayoutParams(-1, -1));
        }

        // Scrims keep text legible on bright photos.
        View top = new View(this);
        top.setBackground(new GradientDrawable(GradientDrawable.Orientation.TOP_BOTTOM, new int[] {0x88000000, 0x00000000}));
        root.addView(top, new FrameLayout.LayoutParams(-1, Apps.dp(this, 160), Gravity.TOP));
        View bottom = new View(this);
        bottom.setBackground(new GradientDrawable(GradientDrawable.Orientation.BOTTOM_TOP, new int[] {0xAA000000, 0x00000000}));
        root.addView(bottom, new FrameLayout.LayoutParams(-1, Apps.dp(this, 300), Gravity.BOTTOM));

        root.addView(buildTopBar(), new FrameLayout.LayoutParams(-1, -2, Gravity.TOP));

        // Dock: a single row of large tiles on a glass shelf.
        FrameLayout shelf = new FrameLayout(this);
        GradientDrawable glass = new GradientDrawable();
        glass.setColor(0x33FFFFFF);
        glass.setCornerRadius(Apps.dp(this, 28));
        glass.setStroke(1, 0x22FFFFFF);
        shelf.setBackground(glass);
        shelf.setClipToOutline(true);   // scrolled tiles stay inside the glass
        dockScroll = new HorizontalScrollView(this);
        dockScroll.setHorizontalScrollBarEnabled(false);
        // The fading edge doubles as a scroll margin, so a lifted end tile is never cut off.
        dockScroll.setHorizontalFadingEdgeEnabled(true);
        dockScroll.setFadingEdgeLength(Apps.dp(this, 48));
        dockScroll.setFillViewport(false);
        dockRow = new LinearLayout(this);
        dockRow.setClipChildren(false);
        dockRow.setClipToPadding(false);
        int p = Apps.dp(this, 22);
        dockRow.setPadding(p, Apps.dp(this, 20), p, Apps.dp(this, 4));
        dockScroll.addView(dockRow);
        shelf.addView(dockScroll, new FrameLayout.LayoutParams(-2, -2, Gravity.CENTER));
        FrameLayout.LayoutParams sp = new FrameLayout.LayoutParams(-2, -2, Gravity.BOTTOM | Gravity.CENTER_HORIZONTAL);
        sp.bottomMargin = Apps.dp(this, 40);
        sp.leftMargin = sp.rightMargin = Apps.dp(this, 40);
        root.addView(shelf, sp);

        credit = new TextView(this);
        credit.setTextColor(0x99FFFFFF);
        credit.setTextSize(10);
        credit.setShadowLayer(4, 0, 1, 0xAA000000);
        FrameLayout.LayoutParams cp = new FrameLayout.LayoutParams(-2, -2, Gravity.BOTTOM | Gravity.START);
        cp.leftMargin = Apps.dp(this, 24);
        cp.bottomMargin = Apps.dp(this, 10);
        root.addView(credit, cp);

        setContentView(root);
        loadWallpaperList();
        buildDock(true);

        IntentFilter f = new IntentFilter();
        f.addAction(Intent.ACTION_PACKAGE_ADDED);
        f.addAction(Intent.ACTION_PACKAGE_REMOVED);
        f.addAction(Intent.ACTION_PACKAGE_CHANGED);
        f.addDataScheme("package");
        registerReceiver(pkgChanged, f);

        IntentFilter on = new IntentFilter(Intent.ACTION_SCREEN_ON);
        on.addAction(SONY_SCREEN_ON);
        registerReceiver(screenOn, on);
        // Cold boot (e.g. after a power cut): Home starts during boot, so treat that as a power-on too.
        if (SystemClock.elapsedRealtime() < 5 * 60_000) { wokeAt = SystemClock.elapsedRealtime(); ui.postDelayed(openLiveTvAfterWake, 1_500); }
    }

    private View buildTopBar() {
        LinearLayout bar = new LinearLayout(this);
        bar.setGravity(Gravity.CENTER_VERTICAL | Gravity.END);
        int p = Apps.dp(this, 36);
        bar.setPadding(p, Apps.dp(this, 26), p, 0);

        bar.addView(pill("All Apps", v -> startActivity(new Intent(this, AppsActivity.class))));
        bar.addView(pill("Settings", v -> {
            try { startActivity(new Intent(Settings.ACTION_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)); }
            catch (Exception e) { Toast.makeText(this, "Settings unavailable", Toast.LENGTH_SHORT).show(); }
        }));

        LinearLayout clockBox = new LinearLayout(this);
        clockBox.setOrientation(LinearLayout.VERTICAL);
        clockBox.setGravity(Gravity.END);
        clockBox.setPadding(Apps.dp(this, 22), 0, 0, 0);
        TextClock time = new TextClock(this);
        time.setFormat12Hour("h:mm");
        time.setFormat24Hour("H:mm");
        time.setTextSize(40);
        time.setTextColor(Color.WHITE);
        time.setTypeface(Typeface.create("sans-serif-light", Typeface.NORMAL));
        time.setShadowLayer(10, 0, 2, 0x99000000);
        TextClock date = new TextClock(this);
        date.setFormat12Hour("EEEE d MMMM");
        date.setFormat24Hour("EEEE d MMMM");
        date.setTextSize(14);
        date.setTextColor(0xDDFFFFFF);
        date.setShadowLayer(8, 0, 1, 0x99000000);
        clockBox.addView(time);
        clockBox.addView(date);
        bar.addView(clockBox);
        return bar;
    }

    private TextView pill(String text, View.OnClickListener l) {
        TextView t = new TextView(this);
        t.setText(text);
        t.setTextColor(Color.WHITE);
        t.setTextSize(15);
        int h = Apps.dp(this, 18), v = Apps.dp(this, 8);
        t.setPadding(h, v, h, v);
        GradientDrawable bg = new GradientDrawable();
        bg.setCornerRadius(Apps.dp(this, 20));
        bg.setColor(0x33FFFFFF);
        t.setBackground(bg);
        t.setFocusable(true);
        t.setOnClickListener(l);
        t.setOnFocusChangeListener((view, has) -> {
            bg.setColor(has ? 0xF2FFFFFF : 0x33FFFFFF);
            t.setTextColor(has ? Color.BLACK : Color.WHITE);
            view.animate().scaleX(has ? 1.08f : 1f).scaleY(has ? 1.08f : 1f).setDuration(120).start();
        });
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-2, -2);
        lp.leftMargin = Apps.dp(this, 12);
        t.setLayoutParams(lp);
        return t;
    }

    // ---- dock ----
    private void buildDock(boolean focusFirst) {
        View focused = getCurrentFocus();
        Object keep = focused != null ? focused.getTag() : null;
        dockRow.removeAllViews();
        Map<String, Apps.App> byPkg = new HashMap<>();
        for (Apps.App a : Apps.all(this)) byPkg.put(a.pkg, a);
        List<String> dock = Apps.dock(this);
        View refocus = null;
        for (String pkg : dock) {
            Apps.App a = byPkg.get(pkg);
            if (a == null) continue;   // disabled or uninstalled: hide, but keep its slot saved
            LinearLayout t = Apps.tile(this, a, 150, 84);
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-2, -2);
            lp.rightMargin = Apps.dp(this, 22);
            t.setOnClickListener(v -> launch(pkg));
            t.setOnLongClickListener(v -> { editDock(pkg); return true; });
            dockRow.addView(t, lp);
            if (pkg.equals(keep)) refocus = t;
        }
        if (dockRow.getChildCount() > 0) {
            View last = dockRow.getChildAt(dockRow.getChildCount() - 1);
            ((LinearLayout.LayoutParams) last.getLayoutParams()).rightMargin = 0;
        }
        if (refocus == null && focusFirst && dockRow.getChildCount() > 0) refocus = dockRow.getChildAt(0);
        if (refocus != null) refocus.requestFocus();
    }

    private void launch(String pkg) {
        Intent i = Apps.launchIntent(this, pkg);
        if (i == null) { Toast.makeText(this, "Can't open this app", Toast.LENGTH_SHORT).show(); return; }
        try { startActivity(i); } catch (Exception e) { Toast.makeText(this, "Can't open this app", Toast.LENGTH_SHORT).show(); }
    }

    private void editDock(String pkg) {
        List<String> dock = Apps.dock(this);
        int i = dock.indexOf(pkg);
        new AlertDialog.Builder(this, android.R.style.Theme_Material_Dialog_Alert)
            .setItems(new String[] {"Move left", "Move right", "Remove from dock"}, (d, which) -> {
                if (which == 0 && i > 0) Collections.swap(dock, i, i - 1);
                else if (which == 1 && i < dock.size() - 1) Collections.swap(dock, i, i + 1);
                else if (which == 2) dock.remove(i);
                Apps.saveDock(this, dock);
                buildDock(true);
            }).show();
    }

    @Override public boolean onKeyDown(int code, KeyEvent e) {
        View f = getCurrentFocus();
        if (code == KeyEvent.KEYCODE_MENU && f != null && f.getTag() instanceof String) { editDock((String) f.getTag()); return true; }
        if (code == KeyEvent.KEYCODE_BACK) return true;   // home is the bottom of the stack
        return super.onKeyDown(code, e);
    }

    @Override protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        // Home pressed while already home: jump back to the start of the dock.
        dockScroll.smoothScrollTo(0, 0);
        if (dockRow.getChildCount() > 0) dockRow.getChildAt(0).requestFocus();
    }

    // ---- wallpapers ----
    private void loadWallpaperList() {
        try {
            for (String s : getAssets().list("walls")) if (s.endsWith(".jpg")) wallFiles.add(s);
            InputStream in = getAssets().open("walls/CREDITS.txt");
            BufferedReader r = new BufferedReader(new InputStreamReader(in, "UTF-8"));
            for (String line; (line = r.readLine()) != null; ) {
                String[] parts = line.split(" — ");
                int colon = line.indexOf(": ");
                if (colon < 0 || parts.length < 3) continue;
                String title = parts[0].substring(colon + 2).replaceAll("\\.(jpe?g|JPG)$", "");
                credits.put(line.substring(0, colon), title + " · " + parts[1].split("\\s{2,}")[0] + " · " + parts[2]);
            }
            r.close();
        } catch (Exception ignored) { }
        Collections.shuffle(wallFiles);
    }

    private void nextWallpaper() {
        if (wallFiles.isEmpty()) return;
        wallIndex = (wallIndex + 1) % wallFiles.size();
        final String name = wallFiles.get(wallIndex);
        new Thread(() -> {
            Bitmap bmp = null;
            try (InputStream in = getAssets().open("walls/" + name)) { bmp = BitmapFactory.decodeStream(in); }
            catch (Exception ignored) { }
            final Bitmap b = bmp;
            if (b == null) return;
            ui.post(() -> {
                if (isDestroyed()) { b.recycle(); return; }
                ImageView next = walls[1 - front], cur = walls[front];
                next.setImageBitmap(b);
                next.setScaleX(1f); next.setScaleY(1f);
                next.animate().alpha(1f).setDuration(cur.getDrawable() == null ? 400 : FADE_MS).withLayer().start();
                // Slow drift for a living-photo feel; stops at ~8% zoom.
                next.animate().scaleX(1.08f).scaleY(1.08f).setDuration(ROTATE_MS + FADE_MS).start();
                cur.animate().alpha(0f).setDuration(FADE_MS).withEndAction(() -> {
                    cur.animate().cancel();
                    cur.setImageDrawable(null);   // free the old bitmap
                }).start();
                front = 1 - front;
                String c = credits.get(name);
                credit.setText(c != null ? c : "");
            });
        }, "wallpaper").start();
    }

    @Override protected void onResume() {
        super.onResume();
        ui.removeCallbacks(rotate);
        // Show a photo immediately on first start; afterwards keep the current one until the next tick.
        if (wallIndex < 0 || walls[front].getDrawable() == null) rotate.run(); else ui.postDelayed(rotate, ROTATE_MS);
        Apps.invalidate();
        buildDock(getCurrentFocus() == null);
        if (wokeAt >= 0 && SystemClock.elapsedRealtime() - wokeAt < WAKE_WINDOW_MS) ui.postDelayed(openLiveTvAfterWake, 300);
    }

    @Override protected void onPause() {
        super.onPause();
        ui.removeCallbacks(rotate);   // no work while an app is in front
    }

    @Override protected void onDestroy() {
        super.onDestroy();
        unregisterReceiver(pkgChanged);
        unregisterReceiver(screenOn);
    }

    @Override public void onTrimMemory(int level) {
        super.onTrimMemory(level);
        if (level >= TRIM_MEMORY_UI_HIDDEN) {
            // An app is in front: give it our photos and banner cache; both reload on return.
            for (ImageView w : walls) { w.animate().cancel(); w.setImageDrawable(null); w.setAlpha(0f); }
            Apps.invalidate();
        }
    }
}
