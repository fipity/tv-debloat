package local.tvhome;

import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.content.pm.ResolveInfo;
import android.graphics.Color;
import android.graphics.Outline;
import android.graphics.drawable.Drawable;
import android.graphics.drawable.GradientDrawable;
import android.text.TextUtils;
import android.view.Gravity;
import android.view.View;
import android.view.ViewOutlineProvider;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;

import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** App discovery, dock persistence and the shared tile view. */
final class Apps {
    static final String[] DEFAULT_DOCK = {
        "com.sony.dtv.tvx",                 // Live TV
        "com.netflix.ninja",
        "com.google.android.youtube.tv",
        "au.com.kayosports.tv",
        "com.spotify.tv.android",
    };

    static final class App {
        final String pkg; final String label; final Drawable banner; final Drawable icon;
        App(String pkg, String label, Drawable banner, Drawable icon) {
            this.pkg = pkg; this.label = label; this.banner = banner; this.icon = icon;
        }
    }

    private static final Map<String, App> cache = new HashMap<>();

    static void invalidate() { cache.clear(); }

    /** All launchable apps (TV launcher entries first, phone launcher entries as fallback), by label. */
    static List<App> all(Context c) {
        PackageManager pm = c.getPackageManager();
        Map<String, App> out = new LinkedHashMap<>();
        for (String cat : new String[] {Intent.CATEGORY_LEANBACK_LAUNCHER, Intent.CATEGORY_LAUNCHER}) {
            Intent q = new Intent(Intent.ACTION_MAIN).addCategory(cat);
            for (ResolveInfo ri : pm.queryIntentActivities(q, 0)) {
                String pkg = ri.activityInfo.packageName;
                if (out.containsKey(pkg) || pkg.equals(c.getPackageName())) continue;
                App a = cache.get(pkg);
                if (a == null) {
                    Drawable banner = ri.activityInfo.loadBanner(pm);
                    if (banner == null) banner = ri.activityInfo.applicationInfo.loadBanner(pm);
                    a = new App(pkg, String.valueOf(ri.loadLabel(pm)), banner, ri.loadIcon(pm));
                    cache.put(pkg, a);
                }
                out.put(pkg, a);
            }
        }
        List<App> list = new ArrayList<>(out.values());
        Collections.sort(list, (x, y) -> x.label.compareToIgnoreCase(y.label));
        return list;
    }

    static Intent launchIntent(Context c, String pkg) {
        PackageManager pm = c.getPackageManager();
        Intent i = pm.getLeanbackLaunchIntentForPackage(pkg);
        if (i == null) i = pm.getLaunchIntentForPackage(pkg);
        if (i != null) i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED);
        return i;
    }

    // ---- dock persistence ----
    private static SharedPreferences prefs(Context c) { return c.getSharedPreferences("dock", 0); }

    static List<String> dock(Context c) {
        String s = prefs(c).getString("apps", null);
        List<String> l = new ArrayList<>();
        if (s == null) Collections.addAll(l, DEFAULT_DOCK);
        else if (!s.isEmpty()) Collections.addAll(l, s.split(","));
        return l;
    }

    static void saveDock(Context c, List<String> l) {
        prefs(c).edit().putString("apps", TextUtils.join(",", l)).apply();
    }

    // ---- tiles ----
    static int dp(Context c, float v) { return Math.round(v * c.getResources().getDisplayMetrics().density); }

    /** A tile: rounded banner that lifts on focus, with its name fading in underneath. */
    static LinearLayout tile(Context c, App a, int wDp, int hDp) {
        LinearLayout cell = new LinearLayout(c);
        cell.setOrientation(LinearLayout.VERTICAL);
        cell.setGravity(Gravity.CENTER_HORIZONTAL);
        cell.setClipChildren(false);
        cell.setClipToPadding(false);

        FrameLayout card = new FrameLayout(c);
        final int radius = dp(c, 14);
        card.setOutlineProvider(new ViewOutlineProvider() {
            @Override public void getOutline(View v, Outline o) { o.setRoundRect(0, 0, v.getWidth(), v.getHeight(), radius); }
        });
        card.setClipToOutline(true);
        card.setElevation(dp(c, 2));

        if (a.banner != null) {
            ImageView iv = new ImageView(c);
            iv.setScaleType(ImageView.ScaleType.CENTER_CROP);
            iv.setImageDrawable(a.banner);
            card.addView(iv, new FrameLayout.LayoutParams(-1, -1));
        } else {
            // No banner: icon + name on a soft glass card.
            GradientDrawable bg = new GradientDrawable();
            bg.setColor(0xCC2A2E35);
            card.setBackground(bg);
            LinearLayout inner = new LinearLayout(c);
            inner.setOrientation(LinearLayout.VERTICAL);
            inner.setGravity(Gravity.CENTER);
            ImageView iv = new ImageView(c);
            iv.setImageDrawable(a.icon);
            inner.addView(iv, new LinearLayout.LayoutParams(dp(c, 44), dp(c, 44)));
            TextView t = new TextView(c);
            t.setText(a.label);
            t.setTextColor(Color.WHITE);
            t.setTextSize(13);
            t.setSingleLine(true);
            t.setEllipsize(TextUtils.TruncateAt.END);
            t.setPadding(dp(c, 8), dp(c, 6), dp(c, 8), 0);
            inner.addView(t);
            card.addView(inner, new FrameLayout.LayoutParams(-1, -1));
        }
        cell.addView(card, new LinearLayout.LayoutParams(dp(c, wDp), dp(c, hDp)));

        final TextView name = new TextView(c);
        name.setText(a.label);
        name.setTextColor(Color.WHITE);
        name.setTextSize(15);
        name.setSingleLine(true);
        name.setEllipsize(TextUtils.TruncateAt.END);
        name.setShadowLayer(8, 0, 2, 0xAA000000);
        name.setGravity(Gravity.CENTER);
        name.setAlpha(0f);
        LinearLayout.LayoutParams np = new LinearLayout.LayoutParams(dp(c, wDp), -2);
        np.topMargin = dp(c, 14);
        cell.addView(name, np);

        cell.setFocusable(true);
        cell.setTag(a.pkg);
        final float lift = dp(c, 18);
        cell.setOnFocusChangeListener((v, has) -> {
            card.animate().scaleX(has ? 1.12f : 1f).scaleY(has ? 1.12f : 1f)
                .translationZ(has ? lift : 0).setDuration(160).start();
            name.animate().alpha(has ? 1f : 0f).translationY(has ? dp(c, 4) : 0).setDuration(160).start();
        });
        return cell;
    }
}
