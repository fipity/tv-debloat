"""
What the Features tab offers. A feature is only shown when at least one of its packages is on the connected
device, so the lists for other brands are harmless. ON = the apps are enabled (stock behaviour); OFF = disabled
with `pm disable-user` (reversible any time, nothing is uninstalled).
"""
from dataclasses import dataclass


@dataclass
class Feature:
    id: str
    name: str
    desc: str
    category: str
    packages: tuple
    warn: str = ""
    recommend_off: bool = False


CATEGORIES = [
    "Tracking & telemetry",
    "Ads & recommendations",
    "Voice assistants",
    "Casting & screen sharing",
    "Preinstalled apps",
    "TV extras",
    "System updates",
    "Home screen",
]

FEATURES = [
    # ---- tracking & telemetry ----
    Feature("samba", "Samba TV viewing tracker",
            "Recognises what is on screen and reports it to advertisers.",
            "Tracking & telemetry", ("tv.samba.ssm",), recommend_off=True),
    Feature("sony_idd", "Sony usage analytics",
            "Sony's IDD agent and device-analytics services that upload usage data.",
            "Tracking & telemetry",
            ("com.sonyericsson.idd.agent", "com.sony.dtv.da.service", "com.qterics.da.product"), recommend_off=True),
    Feature("bugreports", "Bug-report & feedback senders",
            "Background services that upload crash reports and feedback to Google and the manufacturer.",
            "Tracking & telemetry",
            ("com.sony.dtv.sonybugreportsys", "com.google.android.tv.bugreportsender", "com.google.android.feedback"),
            recommend_off=True),
    Feature("amazon_metrics", "Amazon crash & usage metrics",
            "Fire OS metrics and crash-report uploaders.",
            "Tracking & telemetry",
            ("com.amazon.device.crashmanager", "com.amazon.client.metrics", "com.amazon.client.metrics.api"),
            recommend_off=True),

    # ---- ads & recommendations ----
    Feature("sony_promos", "Sony promotions",
            "Promotional banners and pop-ups from Sony.",
            "Ads & recommendations", ("com.sony.dtv.promos",), recommend_off=True),
    Feature("tv_recs", "Google recommendations feed",
            "Feeds sponsored and recommended content rows into the home screen.",
            "Ads & recommendations",
            ("com.google.android.tvrecommendations", "com.google.android.leanbacklauncher.recommendations"),
            recommend_off=True),
    Feature("amazon_precog", "Amazon recommendation engine",
            "Builds the 'recommended for you' rows on the Fire TV home screen.",
            "Ads & recommendations", ("com.amazon.precog",),
            warn="Some Fire TV home rows may show as empty."),

    # ---- voice ----
    Feature("assistant", "Google Assistant & voice search",
            "The microphone button on the remote and 'Hey Google'.",
            "Voice assistants",
            ("com.google.android.katniss", "com.google.android.tv.assistant", "com.sony.dtv.assistantadapter"),
            warn="The remote's microphone button stops working."),
    Feature("alexa", "Alexa voice",
            "Alexa on the Fire TV remote.",
            "Voice assistants", ("com.amazon.vizzini",),
            warn="The remote's Alexa button stops working."),

    # ---- casting ----
    Feature("chromecast", "Chromecast built-in",
            "Cast from phone apps (YouTube, Netflix, Spotify...) to the TV.",
            "Casting & screen sharing", ("com.google.android.apps.mediashell",),
            warn="You won't be able to cast to this device any more."),
    Feature("airplay", "AirPlay & HomeKit",
            "Apple AirPlay casting and HomeKit control.",
            "Casting & screen sharing", ("com.sony.dtv.airplayapp", "com.sony.dtv.homekit"),
            warn="Sony keeps these running even when disabled (they are 'persistent' system apps)."),
    Feature("miracast", "Screen mirroring (Miracast / Wi-Fi Direct)",
            "Mirror an Android phone or Windows laptop screen over Wi-Fi Direct.",
            "Casting & screen sharing", ("com.mediatek.wfd", "com.sony.dtv.networkapp.wifidirect")),

    # ---- preinstalled apps ----
    Feature("play_movies", "Google Play Movies & TV", "Google's movie store app.",
            "Preinstalled apps", ("com.google.android.videos",)),
    Feature("play_games", "Google Play Games", "Google's games hub.",
            "Preinstalled apps", ("com.google.android.play.games",)),
    Feature("yt_music", "YouTube Music", "The YouTube Music TV app.",
            "Preinstalled apps", ("com.google.android.youtube.tvmusic",)),
    Feature("prime_video", "Prime Video", "Amazon's video app.",
            "Preinstalled apps", ("com.amazon.avod.thirdpartyclient",)),
    Feature("amazon_photos", "Amazon Photos", "Amazon Photos app and its screensaver.",
            "Preinstalled apps", ("com.amazon.bueller.photos",),
            warn="The Amazon Photos screensaver goes away."),
    Feature("gamecircle", "Amazon GameCircle", "Old Amazon game services.",
            "Preinstalled apps", ("com.amazon.ags.app",)),

    # ---- TV extras ----
    Feature("ambient", "Ambient mode screensaver",
            "Google TV's photo/info screensaver.",
            "TV extras", ("com.google.android.apps.tv.dreamx",),
            warn="The TV falls back to a plain screensaver."),
    Feature("usb_rec", "USB recording", "Record live TV to a USB drive.",
            "TV extras", ("com.sony.dtv.recapp",)),
    Feature("timers", "Timers & reminders", "Programme reminders and recording timers.",
            "TV extras", ("com.sony.dtv.timers", "com.sony.dtv.reminderservice")),

    # ---- updates ----
    Feature("amazon_ota", "Fire OS automatic updates",
            "Downloads and installs Fire OS updates.",
            "System updates",
            ("com.amazon.device.software.ota", "com.amazon.device.software.ota.override",
             "com.amazon.tv.forcedotaupdater.v2"),
            warn="You stop getting security fixes. Updates also tend to re-enable things you turned off."),

    # ---- home screen (special-cased: needs a replacement home screen before it can be turned off) ----
    Feature("stock_launcher", "Stock home screen",
            "The manufacturer's home screen, with its ad and recommendation rows. To turn it off, install the "
            "TVHome launcher first (Home screen tab).",
            "Home screen",
            ("com.google.android.tvlauncher", "com.google.android.apps.tv.launcherx",
             "com.google.android.leanbacklauncher"),
            warn="Only do this with TVHome installed, otherwise the TV has no home screen."),
]

STOCK_LAUNCHERS = set(next(f for f in FEATURES if f.id == "stock_launcher").packages)
CUSTOM_HOME = "local.tvhome/.HomeActivity"
CUSTOM_HOME_PKG = "local.tvhome"

# Never offered: disabling these can leave a device unusable (no settings, no keyboard, boot loop...).
PROTECTED = {
    "android": "Core Android",
    "com.android.systemui": "System UI",
    "com.android.settings": "Settings", "com.android.tv.settings": "Settings",
    "com.amazon.tv.settings": "Settings", "com.amazon.tv.settings.v2": "Settings",
    "com.android.shell": "Needed for this app to talk to the device",
    "com.android.packageinstaller": "App installer", "com.google.android.packageinstaller": "App installer",
    "com.android.permissioncontroller": "Permissions", "com.google.android.permissioncontroller": "Permissions",
    "com.google.android.gms": "Google Play Services", "com.google.android.gsf": "Google Services Framework",
    "com.google.android.webview": "WebView (many apps need it)", "com.android.webview": "WebView (many apps need it)",
    "com.google.android.leanback.ime": "On-screen keyboard", "com.amazon.tv.ime": "On-screen keyboard",
    "com.google.android.tvkeyboard": "On-screen keyboard",
    "com.amazon.tv.launcher": "Fire TV home screen (can't be replaced on Fire OS)",
    "com.amazon.firehomestarter": "Fire TV home screen",
    "com.google.android.tungsten.setupwraith": "Setup", "com.google.android.apps.tv.launcherx.setup": "Setup",
    "com.android.bluetooth": "Bluetooth (remote control)", "com.android.keychain": "Certificates",
    "com.android.externalstorage": "Storage", "com.android.server.telecom": "System service",
    "com.google.android.ext.services": "System service", "com.android.phone": "System service",
    "com.vewd.core.service": "Sony needs it: disabling caused a crash loop",
    "com.vewd.core.integration.dia": "Sony needs it: disabling caused a crash loop",
    "com.sony.dtv.hbbtvplayer": "Sony needs it: disabling caused a crash loop",
    CUSTOM_HOME_PKG: "Your custom home screen (manage it on the Home screen tab)",
}
PROTECTED_PREFIXES = ("com.android.providers.", "com.android.networkstack", "com.android.wifi",
                      "com.android.inputmethod", "com.android.bluetooth", "com.android.se",
                      "com.google.android.inputmethod")


def protected_reason(pkg):
    if pkg in PROTECTED:
        return PROTECTED[pkg]
    if pkg.startswith(PROTECTED_PREFIXES):
        return "Core system component"
    return None


def feature_for(pkg):
    return next((f for f in FEATURES if pkg in f.packages), None)


SETUP_HELP = {
    "Android / Google TV": "Settings → System → About → select “Android TV OS build” 7 times. Then Settings → System → "
                           "Developer options → turn on “USB debugging” (Sony: also “Network debugging”).",
    "Fire TV": "Settings → My Fire TV → About → select the device name 7 times. Then My Fire TV → "
               "Developer options → turn on “ADB debugging”.",
}
