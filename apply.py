#!/usr/bin/env python3
"""
(Re)apply the debloat + custom launcher, e.g. after a Sony software update re-enabled things.

  python3 apply.py              # disable everything in disabled_by_us.txt, install/refresh TVHome.apk, make it Home
  python3 apply.py --dry-run
"""
import os, sys, tvadb
apk = os.path.join(tvadb.HERE, "TVHome.apk")
cmds = [f"pm disable-user --user 0 {p}" for p in tvadb.packages()]
cmds += ["cmd package set-home-activity local.tvhome/.HomeActivity", "input keyevent KEYCODE_HOME"]
if "--dry-run" in sys.argv: print("install TVHome.apk\n" + "\n".join(cmds)); sys.exit()
print(f"Applying to TV at {tvadb.TV} ...")
if "local.tvhome" not in tvadb.shell("pm list packages local.tvhome"):
    tvadb.send_file(apk, "/data/local/tmp/TVHome.apk")
    print(tvadb.shell("pm install -r /data/local/tmp/TVHome.apk; rm /data/local/tmp/TVHome.apk"))
print(tvadb.shell("; ".join(cmds)))
print("Done.")
