"""Shared TV connection for restore.py / apply.py: uses `adb` if installed, else bundled adb-shell + adbkey."""
import os, shutil, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
TV = os.environ.get("TV", "192.168.0.108")

def packages():
    return [l.strip() for l in open(os.path.join(HERE, "disabled_by_us.txt")) if l.strip() and not l.startswith("#")]

def shell(script):
    if shutil.which("adb"):
        subprocess.run(["adb", "connect", f"{TV}:5555"], check=False, stdout=subprocess.DEVNULL)
        return subprocess.run(["adb", "-s", f"{TV}:5555", "shell", script], capture_output=True, text=True).stdout
    sys.path.insert(0, os.path.join(HERE, "pylib"))
    from adb_shell.adb_device import AdbDeviceTcp
    from adb_shell.auth.sign_pythonrsa import PythonRSASigner
    key = os.path.join(HERE, "adbkey")
    d = AdbDeviceTcp(TV, 5555, default_transport_timeout_s=300)
    d.connect(rsa_keys=[PythonRSASigner(open(key + ".pub").read(), open(key).read())], auth_timeout_s=60)
    try: return d.shell(script, transport_timeout_s=300, read_timeout_s=300, timeout_s=600)
    finally: d.close()

def send_file(local, remote):
    """Copy a file to the TV (adb push, or a one-shot nc listener: adb-shell's push stalls on big files)."""
    if shutil.which("adb"):
        subprocess.run(["adb", "-s", f"{TV}:5555", "push", local, remote], check=True); return
    import socket, time, hashlib
    shell(f"rm -f {remote}; (nohup nc -l -p 34567 > {remote} 2>/dev/null &); sleep 1")
    data = open(local, "rb").read()
    s = socket.create_connection((TV, 34567), timeout=30); s.sendall(data); s.shutdown(socket.SHUT_WR); time.sleep(2); s.close()
    for _ in range(10):
        if shell(f"md5sum {remote}").split()[:1] == [hashlib.md5(data).hexdigest()]: return
        time.sleep(1)
    raise RuntimeError("file transfer to TV failed checksum")
