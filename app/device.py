"""ADB-over-network connection to an Android TV / Google TV / Fire TV, using the bundled adb-shell and adbkey."""
import concurrent.futures, hashlib, ipaddress, os, re, socket, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "pylib"))
from adb_shell.adb_device import AdbDeviceTcp  # noqa: E402
from adb_shell.auth.keygen import keygen  # noqa: E402
from adb_shell.auth.sign_pythonrsa import PythonRSASigner  # noqa: E402
from adb_shell.exceptions import DeviceAuthError, TcpTimeoutException  # noqa: E402

KEY = os.path.join(ROOT, "adbkey")


class NotAllowed(Exception):
    """The device answered but nobody pressed 'Allow' on its USB debugging prompt in time."""


def _signer():
    if not os.path.exists(KEY):
        keygen(KEY)
    return PythonRSASigner(open(KEY + ".pub").read(), open(KEY).read())


class Device:
    def __init__(self, host, port=5555):
        self.host, self.port = host, port
        self._adb = None

    @property
    def connected(self):
        return self._adb is not None and self._adb.available

    def connect(self):
        """First connection to a device shows an 'Allow USB debugging?' prompt on the TV; we wait 90 s for it."""
        self.close()
        d = AdbDeviceTcp(self.host, self.port, default_transport_timeout_s=30)
        try:
            d.connect(rsa_keys=[_signer()], transport_timeout_s=10, auth_timeout_s=90)
        except (TcpTimeoutException, DeviceAuthError) as e:
            d.close()
            raise NotAllowed("the device didn't allow this computer") from e
        self._adb = d

    def close(self):
        if self._adb:
            try:
                self._adb.close()
            except Exception:
                pass
        self._adb = None

    def shell(self, cmd, timeout=300):
        # The TV drops idle connections, so reconnect once before giving up.
        for attempt in (1, 2):
            try:
                if not self.connected:
                    self.connect()
                return self._adb.shell(cmd, transport_timeout_s=timeout, read_timeout_s=timeout, timeout_s=timeout) or ""
            except Exception:
                self.close()
                if attempt == 2:
                    raise

    # ---- queries ----
    def info(self):
        out = self.shell("getprop; echo @@NAME; settings get global device_name")
        props_part, _, name = out.partition("@@NAME")
        props = dict(re.findall(r"^\[(.+?)\]: \[(.*?)\]\s*$", props_part, re.M))
        name = name.strip()
        maker = props.get("ro.product.manufacturer", "")
        model = props.get("ro.product.model", "")
        return {
            "name": name if name and name != "null" else f"{maker} {model}".strip(),
            "maker": maker, "model": model,
            "android": props.get("ro.build.version.release", ""),
            "serial": props.get("ro.serialno", ""),
            "fireos": props.get("ro.build.mktg.fireos", ""),
            "props": props_part,
        }

    def packages(self):
        """{package: {"enabled": bool, "system": bool}}"""
        out = self.shell("echo @A; pm list packages; echo @D; pm list packages -d; echo @S; pm list packages -s")
        sections, cur = {"A": set(), "D": set(), "S": set()}, None
        for line in out.splitlines():
            line = line.strip()
            if line in ("@A", "@D", "@S"):
                cur = line[1]
            elif line.startswith("package:") and cur:
                sections[cur].add(line[8:])
        return {p: {"enabled": p not in sections["D"], "system": p in sections["S"]} for p in sections["A"]}

    def home(self):
        out = self.shell("cmd package resolve-activity --brief -a android.intent.action.MAIN "
                         "-c android.intent.category.HOME")
        comps = [l.strip() for l in out.splitlines() if "/" in l]
        return comps[-1] if comps else ""

    def home_component(self, pkg):
        """The HOME activity a launcher package declares, e.g. com.google.android.tvlauncher/.MainActivity."""
        out = self.shell("cmd package query-activities --brief -a android.intent.action.MAIN "
                         "-c android.intent.category.HOME")
        return next((l.strip() for l in out.splitlines() if l.strip().startswith(pkg + "/")), "")

    # ---- changes ----
    def set_enabled(self, changes):
        """changes: {package: enable?} -> {package: (ok, message)}"""
        script = "; ".join(
            f'echo "@@{p}"; ' + (f"pm enable {p} 2>&1" if en else f"pm disable-user --user 0 {p} 2>&1")
            for p, en in changes.items())
        out = self.shell(script)
        results = {}
        for chunk in out.split("@@")[1:]:
            pkg, _, msg = chunk.partition("\n")
            msg = msg.strip()
            results[pkg.strip()] = ("new state" in msg, msg)
        for p in changes:
            results.setdefault(p, (False, "no response from device"))
        return results

    def set_home(self, component):
        return self.shell(f"cmd package set-home-activity {component}; input keyevent KEYCODE_HOME")

    def install_apk(self, local):
        remote = "/data/local/tmp/tvcontrol.apk"
        self._send_file(local, remote)
        return self.shell(f"pm install -r {remote} 2>&1; rm -f {remote}")

    def _send_file(self, local, remote):
        """adb-shell's push stalls on big files, so use a one-shot nc listener on the device, falling back to push."""
        data = open(local, "rb").read()
        md5 = hashlib.md5(data).hexdigest()
        try:
            self.shell(f"rm -f {remote}; (nohup nc -l -p 34567 > {remote} 2>/dev/null &); sleep 1")
            s = socket.create_connection((self.host, 34567), timeout=30)
            s.sendall(data); s.shutdown(socket.SHUT_WR); time.sleep(2); s.close()
            for _ in range(10):
                if self.shell(f"md5sum {remote}").split()[:1] == [md5]:
                    return
                time.sleep(1)
        except OSError:
            pass
        self._adb.push(local, remote, transport_timeout_s=600, read_timeout_s=600)
        if self.shell(f"md5sum {remote}").split()[:1] != [md5]:
            raise RuntimeError("file transfer to the device failed its checksum")


# ---- network scan ----
def local_networks():
    """The laptop's IPv4 networks, each narrowed to at most a /24 around its own address."""
    nets = []
    try:
        out = subprocess.run(["ip", "-o", "-4", "addr", "show", "scope", "global"],
                             capture_output=True, text=True).stdout
    except OSError:
        return nets
    for cidr in re.findall(r"inet (\S+)", out):
        iface = ipaddress.ip_interface(cidr)
        net = iface.network if iface.network.prefixlen >= 24 else ipaddress.ip_interface(f"{iface.ip}/24").network
        nets.append((iface.ip, net))
    return nets


def scan(port=5555, on_found=None):
    """Find hosts on the local network with the ADB port open. Returns [(ip, hostname)]."""
    targets = [str(h) for me, net in local_networks() for h in net.hosts() if h != me]

    def probe(ip):
        try:
            with socket.create_connection((ip, port), timeout=0.6):
                pass
        except OSError:
            return None
        try:
            name = socket.gethostbyaddr(ip)[0]
        except OSError:
            name = ""
        if on_found:
            on_found(ip, name)
        return ip, name

    with concurrent.futures.ThreadPoolExecutor(128) as pool:
        return [r for r in pool.map(probe, targets) if r]
