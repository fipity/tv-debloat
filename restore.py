#!/usr/bin/env python3
"""
Undo the debloat and bring back the stock Sony/Google home screen.

  python3 restore.py                    # re-enable everything we disabled, stock home screen back
  python3 restore.py --remove-launcher  # ...and uninstall the custom "Home" launcher (local.tvhome)
  python3 restore.py --dry-run          # just print the commands
  TV=192.168.0.50 python3 restore.py    # if the TV's IP address has changed

Only touches packages listed in disabled_by_us.txt; apps that were already disabled before
(backup/packages_disabled.txt) stay as they were. Re-apply later with apply.py.
"""
import sys, tvadb
cmds = [f"pm enable {p}" for p in tvadb.packages()]
cmds.append("cmd package set-home-activity com.google.android.tvlauncher/.MainActivity")
if "--remove-launcher" in sys.argv: cmds.append("pm uninstall local.tvhome")
cmds.append("input keyevent KEYCODE_HOME")
if "--dry-run" in sys.argv: print("\n".join(cmds)); sys.exit()
print(f"Restoring TV at {tvadb.TV} ...")
print(tvadb.shell("; ".join(cmds)))
print("Done. The stock home screen is back.")
