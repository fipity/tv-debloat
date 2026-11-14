package local.tvhome;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.os.Bundle;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import java.util.List;

/** Every installed app in a grid. Hold OK (or press Menu) to add/remove from the dock. */
public class AppsActivity extends Activity {
    private static final int COLS = 5;
    private LinearLayout grid;

    @Override protected void onCreate(Bundle b) {
        super.onCreate(b);
        ScrollView scroll = new ScrollView(this);
        scroll.setBackground(new GradientDrawable(GradientDrawable.Orientation.TL_BR, new int[] {0xFF1B2733, 0xFF0B0F14}));
        scroll.setClipChildren(false);
        scroll.setVerticalScrollBarEnabled(false);
        grid = new LinearLayout(this);
        grid.setOrientation(LinearLayout.VERTICAL);
        grid.setGravity(Gravity.CENTER_HORIZONTAL);
        grid.setClipChildren(false);
        grid.setClipToPadding(false);
        int p = Apps.dp(this, 48);
        grid.setPadding(p, Apps.dp(this, 32), p, p);
        scroll.addView(grid, new ScrollView.LayoutParams(-1, -2));
        setContentView(scroll);
    }

    @Override protected void onResume() {
        super.onResume();
        build();
    }

    private void build() {
        View f = getCurrentFocus();
        Object keep = f != null ? f.getTag() : null;
        grid.removeAllViews();
        TextView title = new TextView(this);
        title.setText("All Apps");
        title.setTextColor(Color.WHITE);
        title.setTextSize(26);
        title.setPadding(0, 0, 0, Apps.dp(this, 18));
        grid.addView(title, new LinearLayout.LayoutParams(-1, -2));

        List<Apps.App> apps = Apps.all(this);
        List<String> dock = Apps.dock(this);
        LinearLayout row = null;
        View refocus = null;
        for (int i = 0; i < apps.size(); i++) {
            if (i % COLS == 0) {
                row = new LinearLayout(this);
                row.setClipChildren(false);
                row.setClipToPadding(false);
                LinearLayout.LayoutParams rp = new LinearLayout.LayoutParams(-2, -2);
                rp.bottomMargin = Apps.dp(this, 4);
                grid.addView(row, rp);
            }
            Apps.App a = apps.get(i);
            LinearLayout t = Apps.tile(this, a, 150, 84);
            if (dock.contains(a.pkg)) {
                // Small dot marks apps already in the dock.
                View dot = new View(this);
                GradientDrawable d = new GradientDrawable();
                d.setShape(GradientDrawable.OVAL);
                d.setColor(0xFFFFFFFF);
                dot.setBackground(d);
                LinearLayout.LayoutParams dp = new LinearLayout.LayoutParams(Apps.dp(this, 6), Apps.dp(this, 6));
                dp.topMargin = Apps.dp(this, 2);
                dp.gravity = Gravity.CENTER_HORIZONTAL;
                t.addView(dot, 1, dp);
            }
            t.setOnClickListener(v -> {
                Intent li = Apps.launchIntent(this, a.pkg);
                try { startActivity(li); } catch (Exception e) { Toast.makeText(this, "Can't open this app", Toast.LENGTH_SHORT).show(); }
            });
            t.setOnLongClickListener(v -> { toggleDock(a); return true; });
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-2, -2);
            lp.rightMargin = Apps.dp(this, 24);
            row.addView(t, lp);
            if (a.pkg.equals(keep)) refocus = t;
        }
        if (refocus == null && grid.getChildCount() > 1) refocus = ((LinearLayout) grid.getChildAt(1)).getChildAt(0);
        if (refocus != null) refocus.requestFocus();
    }

    private void toggleDock(Apps.App a) {
        List<String> dock = Apps.dock(this);
        boolean in = dock.contains(a.pkg);
        new AlertDialog.Builder(this, android.R.style.Theme_Material_Dialog_Alert)
            .setTitle(a.label)
            .setItems(new String[] {in ? "Remove from dock" : "Add to dock"}, (d, w) -> {
                if (in) dock.remove(a.pkg); else dock.add(a.pkg);
                Apps.saveDock(this, dock);
                build();
            }).show();
    }

    @Override public boolean onKeyDown(int code, KeyEvent e) {
        View f = getCurrentFocus();
        if (code == KeyEvent.KEYCODE_MENU && f != null && f.getTag() instanceof String) {
            for (Apps.App a : Apps.all(this)) if (a.pkg.equals(f.getTag())) { toggleDock(a); return true; }
        }
        return super.onKeyDown(code, e);
    }
}
