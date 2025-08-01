#!/usr/bin/python3

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import urllib.request
import webbrowser
import gi
import psutil
import requests
import vdf
import tarfile
import gettext
import locale
import signal
from pathlib import Path

gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('AyatanaAppIndicator3', '0.1')

from gi.repository import Gtk, Gdk, GdkPixbuf, GLib, AyatanaAppIndicator3, Gio, Pango
from PIL import Image
from filelock import FileLock, Timeout

class PathManager:
    @staticmethod
    def system_data(*relative_paths):
        xdg_data_dirs = os.getenv('XDG_DATA_DIRS', '/usr/local/share:/usr/share').split(':')
        for data_dir in xdg_data_dirs:
            path = Path(data_dir).joinpath(*relative_paths)
            if path.exists():
                return str(path)
        return str(Path(xdg_data_dirs[0]).joinpath(*relative_paths))

    @staticmethod
    def user_data(*relative_paths):
        xdg_data_home = Path(os.getenv('XDG_DATA_HOME', Path.home() / '.local/share'))
        return str(xdg_data_home.joinpath(*relative_paths))

    @staticmethod
    def user_config(*relative_paths):
        xdg_config_home = Path(os.getenv('XDG_CONFIG_HOME', Path.home() / '.config'))
        return str(xdg_config_home.joinpath(*relative_paths))

    @staticmethod
    def find_binary(binary_name):
        paths = os.getenv('PATH', '').split(':')
        for path in paths:
            binary_path = Path(path) / binary_name
            if binary_path.exists():
                return str(binary_path)
        return f'/usr/bin/{binary_name}'  # Fallback

    @staticmethod
    def get_icon(icon_name):
        icon_paths = [
            PathManager.user_data('icons', icon_name),
            PathManager.system_data('icons/hicolor/256x256/apps', icon_name),
            PathManager.system_data('icons', icon_name)
        ]
        for path in icon_paths:
            if Path(path).exists():
                return path
        return icon_paths[-1]  # Fallback

IS_FLATPAK = 'FLATPAK_ID' in os.environ or os.path.exists('/.flatpak-info')

faugus_banner = PathManager.system_data('faugus-launcher/faugus-banner.png')
faugus_notification = PathManager.system_data('faugus-launcher/faugus-notification.ogg')
faugus_launcher_dir = PathManager.user_config('faugus-launcher')
prefixes_dir = str(Path.home() / 'Faugus')
logs_dir = PathManager.user_config('faugus-launcher/logs')
icons_dir = PathManager.user_config('faugus-launcher/icons')
banners_dir = PathManager.user_config('faugus-launcher/banners')
config_file_dir = PathManager.user_config('faugus-launcher/config.ini')
envar_dir = PathManager.user_config('faugus-launcher/envar.txt')
shorcuts_dir = PathManager.user_config('faugus-launcher/shortcuts.json')
share_dir = PathManager.user_data()
faugus_mono_icon = PathManager.get_icon('faugus-mono.svg')

if IS_FLATPAK:
    app_dir = str(Path.home() / '.local/share/applications')
    faugus_png = PathManager.get_icon('io.github.Faugus.faugus-launcher.png')
    tray_icon = 'io.github.Faugus.faugus-launcher'

    mono_dest = Path(os.path.expanduser('~/.local/share/faugus-launcher/faugus-mono.svg'))
    mono_dest.parent.mkdir(parents=True, exist_ok=True)
    if not mono_dest.exists():
        shutil.copy(faugus_mono_icon, mono_dest)
    faugus_mono_icon = os.path.expanduser('~/.local/share/faugus-launcher/faugus-mono.svg')

    lsfgvk_path = Path("/usr/lib/extensions/vulkan/lsfgvk/lib/liblsfg-vk.so")
    lsfgvk_path = lsfgvk_path if lsfgvk_path.exists() else Path(os.path.expanduser('~/.local/lib/liblsfg-vk.so'))
else:
    app_dir = PathManager.user_data('applications')
    faugus_png = PathManager.get_icon('faugus-launcher.png')
    tray_icon = PathManager.get_icon('faugus-launcher.png')
    lsfgvk_possible_paths = [
        Path("/usr/lib/liblsfg-vk.so"),
        Path(os.path.expanduser('~/.local/lib/liblsfg-vk.so'))
    ]
    lsfgvk_path = next((p for p in lsfgvk_possible_paths if p.exists()), lsfgvk_possible_paths[-1])

epic_icon = PathManager.get_icon('faugus-epic-games.png')
battle_icon = PathManager.get_icon('faugus-battlenet.png')
ubisoft_icon = PathManager.get_icon('faugus-ubisoft-connect.png')
ea_icon = PathManager.get_icon('faugus-ea.png')

faugus_run = PathManager.find_binary('faugus-run')
faugus_proton_manager = PathManager.find_binary('faugus-proton-manager')
umu_run = PathManager.find_binary('umu-run')
mangohud_dir = PathManager.find_binary('mangohud')
gamemoderun = PathManager.find_binary('gamemoderun')

games_json = PathManager.user_config('faugus-launcher/games.json')
latest_games = PathManager.user_config('faugus-launcher/latest-games.txt')
faugus_launcher_share_dir = PathManager.user_data('faugus-launcher')
faugus_temp = str(Path.home() / 'faugus_temp')
running_games = PathManager.user_data('faugus-launcher/running_games.json')

lock_file_path = PathManager.user_data('faugus-launcher/faugus-launcher.lock')
lock = FileLock(lock_file_path, timeout=0)

faugus_backup = False

os.makedirs(faugus_launcher_share_dir, exist_ok=True)
os.makedirs(faugus_launcher_dir, exist_ok=True)

possible_steam_locations = [
    Path.home() / '.local' / 'share' / 'Steam' / 'userdata',
    Path.home() / '.steam' / 'steam' / 'userdata',
    Path.home() / '.steam' / 'root' / 'userdata',
    os.path.expanduser('~/.var/app/com.valvesoftware.Steam/.steam/steam/userdata/')
]

steam_userdata_path = None
IS_STEAM_FLATPAK = False

for location in possible_steam_locations:
    if Path(location).exists():
        steam_userdata_path = location
        if str(location).startswith(str(Path.home() / '.var' / 'app' / 'com.valvesoftware.Steam')):
            IS_STEAM_FLATPAK = True
        break

def detect_steam_id():
    if steam_userdata_path:
        try:
            steam_ids = [f for f in os.listdir(steam_userdata_path)
                         if os.path.isdir(os.path.join(steam_userdata_path, f)) and f.isdigit()]
            return steam_ids[0] if steam_ids else None
        except (FileNotFoundError, PermissionError):
            return None
    return None

steam_id = detect_steam_id()

steam_shortcuts_path = f'{steam_userdata_path}/{steam_id}/config/shortcuts.vdf' if steam_id else ""

def find_lossless_dll():
    possible_common_locations = [
        Path.home() / '.local' / 'share' / 'Steam' / 'steamapps' / 'common',
        Path.home() / '.steam' / 'steam' / 'steamapps' / 'common',
        Path.home() / '.steam' / 'root' / 'steamapps' / 'common',
        Path.home() / 'SteamLibrary' / 'steamapps' / 'common',
        Path(os.path.expanduser('~/.var/app/com.valvesoftware.Steam/.steam/steamapps/common/'))
    ]

    for location in possible_common_locations:
        dll_candidate = location / 'Lossless Scaling' / 'Lossless.dll'
        if dll_candidate.exists():
            return str(dll_candidate)

    return ""

def get_desktop_dir():
    try:
        desktop_dir = subprocess.check_output(['xdg-user-dir', 'DESKTOP'], text=True).strip()
        return desktop_dir
    except (FileNotFoundError, subprocess.CalledProcessError):
        print("xdg-user-dir not found or failed; falling back to ~/Desktop")
        return str(Path.home() / 'Desktop')

desktop_dir = get_desktop_dir()

def get_system_locale():
    lang = os.environ.get('LANG') or os.environ.get('LC_MESSAGES')
    if lang:
        return lang.split('.')[0]

    try:
        loc = locale.getdefaultlocale()[0]
        if loc:
            return loc
    except Exception:
        pass

    return 'en_US'

def get_language_from_config():
    if os.path.exists(config_file_dir):
        with open(config_file_dir, 'r') as f:
            for line in f:
                line = line.strip()
                if line.startswith('language='):
                    return line.split('=', 1)[1].strip()
    return None

lang = get_language_from_config()
if not lang:
    lang = get_system_locale()

LOCALE_DIR = (
    PathManager.system_data('locale')
    if os.path.isdir(PathManager.system_data('locale'))
    else os.path.join(os.path.dirname(__file__), 'locale')
)

try:
    translation = gettext.translation(
        'faugus-launcher',
        localedir=LOCALE_DIR,
        languages=[lang] if lang else ['en_US']
    )
    translation.install()
    globals()['_'] = translation.gettext
except FileNotFoundError:
    gettext.install('faugus-launcher', localedir=LOCALE_DIR)
    globals()['_'] = gettext.gettext

def format_title(title):
    title_formatted = re.sub(r'[^a-zA-Z0-9\s]', '', title)
    title_formatted = title_formatted.replace(' ', '-')
    title_formatted = '-'.join(title_formatted.lower().split())
    return title_formatted

class ConfigManager:
    def __init__(self):
        self.default_config = {
            'close-onlaunch': 'False',
            'default-prefix': prefixes_dir,
            'mangohud': 'False',
            'gamemode': 'False',
            'disable-hidraw': 'False',
            'default-runner': 'GE-Proton',
            'lossless-location': '',
            'discrete-gpu': 'False',
            'splash-disable': 'False',
            'system-tray': 'False',
            'start-boot': 'False',
            'mono-icon': 'False',
            'interface-mode': 'List',
            'start-maximized': 'False',
            'start-fullscreen': 'False',
            'show-labels': 'False',
            'smaller-banners': 'False',
            'enable-logging': 'False',
            'wayland-driver': 'False',
            'enable-hdr': 'False',
            'enable-ntsync': 'False',
            'enable-wow64': 'False',
            'language': lang,
        }

        self.config = {}
        self.load_config()

    def load_config(self):
        if os.path.isfile(config_file_dir):
            with open(config_file_dir, 'r') as f:
                for line in f.read().splitlines():
                    if '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip().strip('"')
                        self.config[key] = value

        updated = False
        for key, default_value in self.default_config.items():
            if key not in self.config:
                self.config[key] = default_value
                updated = True

        if updated or not os.path.isfile(config_file_dir):
            self.save_config()

    def save_config(self):
        if not os.path.exists(faugus_launcher_dir):
            os.makedirs(faugus_launcher_dir)

        with open(config_file_dir, 'w') as f:
            for key, value in self.config.items():
                if key in ['default-prefix', 'default-runner']:
                    f.write(f'{key}="{value}"\n')
                else:
                    f.write(f'{key}={value}\n')

    def save_with_values(self, *args):
        keys = list(self.default_config.keys())
        for key, value in zip(keys, args):
            self.config[key] = str(value)
        self.save_config()

class Main(Gtk.Window):
    def __init__(self):
        # Initialize the main window with title and default size
        Gtk.Window.__init__(self, title="Faugus Launcher")
        self.set_icon_from_file(faugus_png)

        self.start_maximized = False
        self.start_fullscreen = False
        self.fullscreen_activated = False
        self.system_tray = False
        self.start_boot = False
        self.mono_icon = False
        self.theme = None

        self.current_prefix = None
        self.games = []
        self.flowbox_child = None
        self.updated_steam_id = None
        self.game_running = False

        self.last_click_time = 0
        self.last_clicked_item = None
        self.double_click_time_threshold = 500

        self.processos = {}
        self.button_locked = {}

        self.working_directory = faugus_launcher_dir
        os.chdir(self.working_directory)

        self.provider = Gtk.CssProvider()
        self.provider.load_from_data(b"""
            .hbox-dark-background {
                background-color: rgba(25, 25, 25, 0.5);
            }
            .hbox-light-background {
                background-color: rgba(25, 25, 25, 0.1);
            }
            .hbox-red-background {
                background-color: rgba(255, 0, 0, 0.5);
            }
        """)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), self.provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self.check_theme()
        self.load_config()

        self.context_menu = Gtk.Menu()

        self.menu_item_play = Gtk.MenuItem(label=_("Play"))
        self.menu_item_play.connect("activate", self.on_context_menu_play)
        self.context_menu.append(self.menu_item_play)

        self.menu_item_edit = Gtk.MenuItem(label=_("Edit"))
        self.menu_item_edit.connect("activate", self.on_context_menu_edit)
        self.context_menu.append(self.menu_item_edit)

        self.menu_item_delete = Gtk.MenuItem(label=_("Delete"))
        self.menu_item_delete.connect("activate", self.on_context_menu_delete)
        self.context_menu.append(self.menu_item_delete)

        menu_item_duplicate = Gtk.MenuItem(label=_("Duplicate"))
        menu_item_duplicate.connect("activate", self.on_context_menu_duplicate)
        self.context_menu.append(menu_item_duplicate)

        self.menu_item_prefix = Gtk.MenuItem(label=_("Open prefix location"))
        self.menu_item_prefix.connect("activate", self.on_context_menu_prefix)
        self.context_menu.append(self.menu_item_prefix)

        self.menu_show_logs = Gtk.MenuItem(label=_("Show logs"))
        self.menu_show_logs.connect("activate", self.on_context_show_logs)
        self.context_menu.append(self.menu_show_logs)

        self.context_menu.show_all()

        if self.interface_mode == "List":
            self.small_interface()
        if self.interface_mode == "Blocks":
            if self.start_maximized:
                self.maximize()
            if self.start_fullscreen:
                self.fullscreen()
                self.fullscreen_activated = True
            self.big_interface()
        if self.interface_mode == "Banners":
            if self.start_maximized:
                self.maximize()
            if self.start_fullscreen:
                self.fullscreen()
                self.fullscreen_activated = True
            self.big_interface()
        if not self.interface_mode:
            self.interface_mode = "List"
            self.small_interface()

        self.flowbox.connect("button-press-event", self.on_item_right_click)

        # Create the tray indicator
        if self.mono_icon:
            self.indicator = AyatanaAppIndicator3.Indicator.new("Faugus Launcher",
                faugus_mono_icon,
                AyatanaAppIndicator3.IndicatorCategory.APPLICATION_STATUS)
        else:
            self.indicator = AyatanaAppIndicator3.Indicator.new("Faugus Launcher",
                tray_icon,  # Path to the icon
                AyatanaAppIndicator3.IndicatorCategory.APPLICATION_STATUS)
        self.indicator.set_menu(self.create_tray_menu())
        self.indicator.set_title("Faugus Launcher")

        if self.system_tray:
            self.indicator.set_status(AyatanaAppIndicator3.IndicatorStatus.ACTIVE)
            self.connect("delete-event", self.on_window_delete_event)

        if IS_FLATPAK:
            signal.signal(signal.SIGCHLD, self.on_child_process_closed)
        else:
            GLib.timeout_add_seconds(1, self.check_running_processes)

    def on_child_process_closed(self, signum, frame):
        for title, processo in list(self.processos.items()):
            retcode = processo.poll()
            if retcode is not None:
                del self.processos[title]

                selected_child = None

                for child in self.flowbox.get_children():
                    if child.get_state_flags() & Gtk.StateFlags.SELECTED:
                        selected_child = child
                        break

                if selected_child:
                    hbox = selected_child.get_children()[0]
                    game_label = hbox.get_children()[1]
                    selected_title = game_label.get_text()

                    if selected_title not in self.processos:
                        self.menu_item_play.set_sensitive(True)
                        self.button_play.set_sensitive(True)
                        self.button_play.set_image(
                            Gtk.Image.new_from_icon_name("faugus-play-symbolic", Gtk.IconSize.BUTTON))
                    else:
                        self.menu_item_play.set_sensitive(False)
                        self.button_play.set_sensitive(False)
                        self.button_play.set_image(
                            Gtk.Image.new_from_icon_name("faugus-stop-symbolic", Gtk.IconSize.BUTTON))

    def check_running_processes(self):
        processos = self.load_processes_from_file()

        updated = False
        to_remove = []

        for title, data in processos.items():
            pid_main = data.get("main")

            try:
                proc = psutil.Process(pid_main)
                if proc.status() == psutil.STATUS_ZOMBIE:
                    to_remove.append(title)
            except psutil.NoSuchProcess:
                to_remove.append(title)
            except Exception as e:
                to_remove.append(title)

        for title in to_remove:
            del processos[title]
            updated = True
            if title in self.button_locked:
                del self.button_locked[title]

        if updated:
            with open(running_games, "w") as f:
                json.dump(processos, f, indent=2)

        selected_child = None
        for child in self.flowbox.get_children():
            if child.get_state_flags() & Gtk.StateFlags.SELECTED:
                selected_child = child
                break

        if selected_child:
            hbox = selected_child.get_children()[0]
            game_label = hbox.get_children()[1]
            selected_title = game_label.get_text()

            self.on_item_selected(self.flowbox, selected_child)

        return True

    def load_processes_from_file(self):
        if os.path.exists(running_games):
            try:
                with open(running_games, "r") as f:
                    return json.load(f)
            except json.JSONDecodeError:
                return {}
        return {}

    def check_theme(self):
        settings = Gtk.Settings.get_default()
        prefer_dark = settings.get_property('gtk-application-prefer-dark-theme')
        output = subprocess.check_output(['gsettings', 'get', 'org.gnome.desktop.interface', 'gtk-theme']).decode(
            'utf-8')
        theme = output.strip().strip("'")
        if prefer_dark or 'dark' in theme:
            self.theme = "hbox-dark-background"
        else:
            self.theme = "hbox-light-background"

    def small_interface(self):
        self.set_default_size(-1, 610)
        self.set_resizable(False)
        self.big_interface_active = False

        # Create main box and its components
        self.box_main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.box_top = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.box_bottom = Gtk.Box()

        # Create buttons for adding, editing, and deleting games
        self.button_add = Gtk.Button()
        self.button_add.connect("clicked", self.on_button_add_clicked)
        self.button_add.set_can_focus(False)
        self.button_add.set_size_request(50, 50)
        self.button_add.set_image(Gtk.Image.new_from_icon_name("faugus-add-symbolic", Gtk.IconSize.BUTTON))
        self.button_add.set_margin_top(10)
        self.button_add.set_margin_start(10)
        self.button_add.set_margin_bottom(10)

        # Create button for killing processes
        button_kill = Gtk.Button()
        button_kill.connect("clicked", self.on_button_kill_clicked)
        button_kill.set_can_focus(False)
        button_kill.set_tooltip_text(_("Force close all running games"))
        button_kill.set_size_request(50, 50)
        button_kill.set_image(Gtk.Image.new_from_icon_name("faugus-kill-symbolic", Gtk.IconSize.BUTTON))
        button_kill.set_margin_top(10)
        button_kill.set_margin_end(10)
        button_kill.set_margin_bottom(10)

        # Create button for settings
        button_settings = Gtk.Button()
        button_settings.connect("clicked", self.on_button_settings_clicked)
        button_settings.set_can_focus(False)
        button_settings.set_size_request(50, 50)
        button_settings.set_image(Gtk.Image.new_from_icon_name("faugus-settings-symbolic", Gtk.IconSize.BUTTON))
        button_settings.set_margin_top(10)
        button_settings.set_margin_start(10)
        button_settings.set_margin_bottom(10)

        # Create button for launching games
        self.button_play = Gtk.Button()
        self.button_play.connect("clicked", self.on_button_play_clicked)
        self.button_play.set_can_focus(False)
        self.button_play.set_size_request(50, 50)
        self.button_play.set_image(Gtk.Image.new_from_icon_name("faugus-play-symbolic", Gtk.IconSize.BUTTON))
        self.button_play.set_margin_top(10)
        self.button_play.set_margin_end(10)
        self.button_play.set_margin_bottom(10)

        self.entry_search = Gtk.Entry()
        self.entry_search.set_placeholder_text(_("Search..."))
        self.entry_search.connect("changed", self.on_search_changed)

        self.entry_search.set_size_request(170, 50)
        self.entry_search.set_margin_top(10)
        self.entry_search.set_margin_start(10)
        self.entry_search.set_margin_bottom(10)
        self.entry_search.set_margin_end(10)

        # Create scrolled window for game list
        scroll_box = Gtk.ScrolledWindow()
        scroll_box.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll_box.set_margin_start(10)
        scroll_box.set_margin_top(10)
        scroll_box.set_margin_end(10)

        self.flowbox = Gtk.FlowBox()
        self.flowbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.flowbox.set_halign(Gtk.Align.START)
        self.flowbox.set_valign(Gtk.Align.START)
        self.flowbox.connect('child-activated', self.on_item_selected)
        self.flowbox.connect('button-release-event', self.on_item_release_event)
        self.flowbox.set_halign(Gtk.Align.FILL)

        scroll_box.add(self.flowbox)
        self.load_games()

        # Pack left and scrolled box into the top box
        self.box_top.pack_start(scroll_box, True, True, 0)

        # Pack buttons and other components into the bottom box
        self.box_bottom.pack_start(self.button_add, False, False, 0)
        self.box_bottom.pack_start(button_settings, False, False, 0)
        self.box_bottom.pack_start(self.entry_search, True, True, 0)
        self.box_bottom.pack_end(self.button_play, False, False, 0)
        self.box_bottom.pack_end(button_kill, False, False, 0)

        # Pack top and bottom boxes into the main box
        self.box_main.pack_start(self.box_top, True, True, 0)
        self.box_main.pack_end(self.box_bottom, False, True, 0)
        self.add(self.box_main)

        self.menu_item_edit.set_sensitive(False)
        self.menu_item_delete.set_sensitive(False)
        self.menu_item_play.set_sensitive(False)
        self.button_play.set_sensitive(False)

        if self.flowbox.get_children():
            self.flowbox.select_child(self.flowbox.get_children()[0])
            self.on_item_selected(self.flowbox, self.flowbox.get_children()[0])

        self.connect("key-press-event", self.on_key_press_event)
        self.show_all()

    def big_interface(self):
        self.set_default_size(1280, 720)
        self.set_resizable(True)
        self.big_interface_active = True

        # Create main box and its components
        self.box_main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.box_top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.box_bottom = Gtk.Box()

        # Create buttons for adding, editing, and deleting games
        self.button_add = Gtk.Button()
        self.button_add.connect("clicked", self.on_button_add_clicked)
        self.button_add.set_can_focus(False)
        self.button_add.set_size_request(50, 50)
        self.button_add.set_image(Gtk.Image.new_from_icon_name("faugus-add-symbolic", Gtk.IconSize.BUTTON))
        self.button_add.set_margin_top(10)
        self.button_add.set_margin_start(10)
        self.button_add.set_margin_bottom(10)

        # Create button for killing processes
        button_kill = Gtk.Button()
        button_kill.connect("clicked", self.on_button_kill_clicked)
        button_kill.set_can_focus(False)
        button_kill.set_tooltip_text(_("Force close all running games"))
        button_kill.set_size_request(50, 50)
        button_kill.set_image(Gtk.Image.new_from_icon_name("faugus-kill-symbolic", Gtk.IconSize.BUTTON))
        button_kill.set_margin_top(10)
        button_kill.set_margin_bottom(10)

        # Create button for exiting
        button_bye = Gtk.Button()
        button_bye.connect("clicked", self.on_button_bye_clicked)
        button_bye.set_can_focus(False)
        button_bye.set_size_request(50, 50)
        button_bye.set_image(Gtk.Image.new_from_icon_name("faugus-exit-symbolic", Gtk.IconSize.BUTTON))
        button_bye.set_margin_start(10)
        button_bye.set_margin_top(10)
        button_bye.set_margin_bottom(10)
        button_bye.set_margin_end(10)

        # Create button for settings
        button_settings = Gtk.Button()
        button_settings.connect("clicked", self.on_button_settings_clicked)
        button_settings.set_can_focus(False)
        button_settings.set_size_request(50, 50)
        button_settings.set_image(Gtk.Image.new_from_icon_name("faugus-settings-symbolic", Gtk.IconSize.BUTTON))
        button_settings.set_margin_top(10)
        button_settings.set_margin_start(10)
        button_settings.set_margin_bottom(10)

        # Create button for launching games
        self.button_play = Gtk.Button()
        self.button_play.connect("clicked", self.on_button_play_clicked)
        self.button_play.set_can_focus(False)
        self.button_play.set_size_request(50, 50)
        self.button_play.set_image(Gtk.Image.new_from_icon_name("faugus-play-symbolic", Gtk.IconSize.BUTTON))
        self.button_play.set_margin_top(10)
        self.button_play.set_margin_start(10)
        self.button_play.set_margin_end(10)
        self.button_play.set_margin_bottom(10)

        self.entry_search = Gtk.Entry()
        self.entry_search.set_placeholder_text(_("Search..."))
        self.entry_search.connect("changed", self.on_search_changed)

        self.entry_search.set_size_request(170, 50)
        self.entry_search.set_margin_top(10)
        self.entry_search.set_margin_start(10)
        self.entry_search.set_margin_bottom(10)
        self.entry_search.set_margin_end(10)

        self.grid_left = Gtk.Grid()
        self.grid_left.get_style_context().add_class(self.theme)
        self.grid_left.set_hexpand(True)
        self.grid_left.set_halign(Gtk.Align.END)

        self.grid_left.add(self.button_add)
        self.grid_left.add(button_settings)

        grid_middle = Gtk.Grid()
        grid_middle.get_style_context().add_class(self.theme)

        grid_middle.add(self.entry_search)

        grid_right = Gtk.Grid()
        grid_right.get_style_context().add_class(self.theme)
        grid_right.set_hexpand(True)
        grid_right.set_halign(Gtk.Align.START)

        grid_right.add(button_kill)
        grid_right.add(self.button_play)

        self.grid_corner = Gtk.Grid()
        self.grid_corner.get_style_context().add_class(self.theme)
        self.grid_corner.add(button_bye)

        # Create scrolled window for game list
        scroll_box = Gtk.ScrolledWindow()
        scroll_box.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll_box.set_margin_top(10)
        scroll_box.set_margin_end(10)
        scroll_box.set_margin_start(10)
        scroll_box.set_margin_bottom(10)

        self.flowbox = Gtk.FlowBox()
        self.flowbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.flowbox.set_halign(Gtk.Align.CENTER)
        self.flowbox.set_valign(Gtk.Align.CENTER)
        self.flowbox.set_min_children_per_line(2)
        self.flowbox.set_max_children_per_line(20)
        self.flowbox.connect('child-activated', self.on_item_selected)
        self.flowbox.connect('button-release-event', self.on_item_release_event)

        scroll_box.add(self.flowbox)
        self.load_games()

        self.box_top.pack_start(scroll_box, True, True, 0)

        self.box_bottom.pack_start(self.grid_left, True, True, 0)
        self.box_bottom.pack_start(grid_middle, False, False, 0)
        self.box_bottom.pack_start(grid_right, True, True, 0)
        self.box_bottom.pack_end(self.grid_corner, False, False, 0)

        self.box_main.pack_start(self.box_top, True, True, 0)
        self.box_main.pack_end(self.box_bottom, False, True, 0)
        self.add(self.box_main)

        self.menu_item_edit.set_sensitive(False)
        self.menu_item_delete.set_sensitive(False)
        self.menu_item_play.set_sensitive(False)
        self.button_play.set_sensitive(False)

        if self.flowbox.get_children():
            self.flowbox.select_child(self.flowbox.get_children()[0])
            self.on_item_selected(self.flowbox, self.flowbox.get_children()[0])

        self.connect("key-press-event", self.on_key_press_event)
        self.show_all()
        if self.start_fullscreen:
            self.fullscreen_activated = True
            self.grid_corner.set_visible(True)
            self.grid_left.set_margin_start(70)
        else:
            self.fullscreen_activated = False
            self.grid_corner.set_visible(False)
            self.grid_left.set_margin_start(0)

    def on_destroy(self, *args):
        if lock.is_locked:
            lock.release()
        Gtk.main_quit()

    def on_button_bye_clicked(self, widget):
        menu = Gtk.Menu()

        shutdown_item = Gtk.MenuItem(label=_("Shut down"))
        reboot_item = Gtk.MenuItem(label=_("Reboot"))
        close_item = Gtk.MenuItem(label=_("Close"))

        shutdown_item.connect("activate", self.on_shutdown)
        reboot_item.connect("activate", self.on_reboot)
        close_item.connect("activate", self.on_close)

        menu.append(shutdown_item)
        menu.append(reboot_item)
        menu.append(close_item)

        menu.show_all()
        menu.popup(None, None, None, None, 0, Gtk.get_current_event_time())

    def on_shutdown(self, widget):
        subprocess.run(["pkexec", "shutdown", "-h", "now"])

    def on_reboot(self, widget):
        subprocess.run(["pkexec", "reboot"])

    def on_close(self, widget):
        if lock.is_locked:
            lock.release()
        Gtk.main_quit()

    def on_item_right_click(self, widget, event):
        if event.button == Gdk.BUTTON_SECONDARY:
            item = self.get_item_at_event(event)
            if item:
                self.flowbox.emit('child-activated', item)
                self.flowbox.select_child(item)

                selected_children = self.flowbox.get_selected_children()
                selected_child = selected_children[0]
                hbox = selected_child.get_child()
                game_label = hbox.get_children()[1]
                title = game_label.get_text()
                game = next((j for j in self.games if j.title == title), None)

                if game.protonfix:
                    match = re.search(r"umu-(\d+)", game.protonfix)
                    if match:
                        log_id = match.group(1)
                    else:
                        log_id = "0"
                    self.log_file_path = f"{logs_dir}/{game.gameid}/steam-{log_id}.log"
                else:
                    self.log_file_path = f"{logs_dir}/{game.gameid}/steam-0.log"
                self.umu_log_file_path = f"{logs_dir}/{game.gameid}/umu.log"

                if self.enable_logging:
                    self.menu_show_logs.set_visible(True)
                    if os.path.exists(self.log_file_path):
                        self.menu_show_logs.set_sensitive(True)
                        self.current_title = title
                    else:
                        self.menu_show_logs.set_sensitive(False)
                else:
                    self.menu_show_logs.set_visible(False)

                processos = self.load_processes_from_file()
                if title in processos:
                    self.menu_item_play.get_child().set_text(_("Stop"))
                else:
                    self.menu_item_play.get_child().set_text(_("Play"))

                if os.path.isdir(game.prefix):
                    self.menu_item_prefix.set_sensitive(True)
                    self.current_prefix = game.prefix
                else:
                    self.menu_item_prefix.set_sensitive(False)
                    self.current_prefix = None

                self.context_menu.popup_at_pointer(event)

    def on_context_menu_play(self, menu_item):
        selected_item = self.flowbox.get_selected_children()[0]
        self.on_button_play_clicked(selected_item)

    def on_context_menu_edit(self, menu_item):
        selected_item = self.flowbox.get_selected_children()[0]
        self.on_button_edit_clicked(selected_item)

    def on_context_menu_delete(self, menu_item):
        selected_item = self.flowbox.get_selected_children()[0]
        self.on_button_delete_clicked(selected_item)

    def on_context_menu_duplicate(self, menu_item):
        selected_item = self.flowbox.get_selected_children()[0]
        self.on_duplicate_clicked(selected_item)

    def on_context_menu_prefix(self, menu_item):
        subprocess.run(["xdg-open", self.current_prefix], check=True)

    def on_context_show_logs(self, menu_item):
        selected_item = self.flowbox.get_selected_children()[0]
        self.on_show_logs_clicked(selected_item)

    def on_show_logs_clicked(self, widget):
        dialog = Gtk.Dialog(title=_("%s Logs") % self.current_title, parent=self, modal=True)
        dialog.set_icon_from_file(faugus_png)
        dialog.set_default_size(1280, 720)

        scrolled_window1 = Gtk.ScrolledWindow()
        scrolled_window1.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        text_view1 = Gtk.TextView()
        text_view1.set_editable(False)
        text_buffer1 = text_view1.get_buffer()
        with open(self.log_file_path, "r") as log_file:
            text_buffer1.set_text(log_file.read())
        scrolled_window1.add(text_view1)

        scrolled_window2 = Gtk.ScrolledWindow()
        scrolled_window2.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        text_view2 = Gtk.TextView()
        text_view2.set_editable(False)
        text_buffer2 = text_view2.get_buffer()
        with open(self.umu_log_file_path, "r") as log_file:
            text_buffer2.set_text(log_file.read())
        scrolled_window2.add(text_view2)

        def copy_to_clipboard(button):
            current_page = notebook.get_current_page()
            if current_page == 0:  # Tab 1: Proton
                start_iter, end_iter = text_buffer1.get_bounds()
                text_to_copy = text_buffer1.get_text(start_iter, end_iter, False)
            elif current_page == 1:  # Tab 2: UMU-Launcher
                start_iter, end_iter = text_buffer2.get_bounds()
                text_to_copy = text_buffer2.get_text(start_iter, end_iter, False)
            else:
                text_to_copy = ""

            clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
            clipboard.set_text(text_to_copy, -1)
            clipboard.store()

        def open_location(button):
            subprocess.run(["xdg-open", os.path.dirname(self.log_file_path)], check=True)

        button_copy_clipboard = Gtk.Button(label=_("Copy to clipboard"))
        button_copy_clipboard.set_size_request(150, -1)
        button_copy_clipboard.connect("clicked", copy_to_clipboard)

        button_open_location = Gtk.Button(label=_("Open file location"))
        button_open_location.set_size_request(150, -1)
        button_open_location.connect("clicked", open_location)

        notebook = Gtk.Notebook()
        notebook.set_margin_start(10)
        notebook.set_margin_end(10)
        notebook.set_margin_top(10)
        notebook.set_margin_bottom(10)
        notebook.set_halign(Gtk.Align.FILL)
        notebook.set_valign(Gtk.Align.FILL)
        notebook.set_vexpand(True)
        notebook.set_hexpand(True)

        tab_box1 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        tab_label1 = Gtk.Label(label="Proton")
        tab_label1.set_width_chars(15)
        tab_label1.set_xalign(0.5)
        tab_box1.pack_start(tab_label1, True, True, 0)
        tab_box1.set_hexpand(True)

        tab_box2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        tab_label2 = Gtk.Label(label="UMU-Launcher")
        tab_label2.set_width_chars(15)
        tab_label2.set_xalign(0.5)
        tab_box2.pack_start(tab_label2, True, True, 0)
        tab_box2.set_hexpand(True)

        notebook.append_page(scrolled_window1, tab_box1)
        notebook.append_page(scrolled_window2, tab_box2)

        content_area = dialog.get_content_area()
        box_bottom = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box_bottom.set_margin_start(10)
        box_bottom.set_margin_end(10)
        box_bottom.set_margin_bottom(10)
        box_bottom.pack_start(button_copy_clipboard, True, True, 0)
        box_bottom.pack_start(button_open_location, True, True, 0)

        content_area.add(notebook)
        content_area.add(box_bottom)

        tab_box1.show_all()
        tab_box2.show_all()
        dialog.show_all()
        dialog.run()
        dialog.destroy()

    def on_duplicate_clicked(self, widget):
        selected_children = self.flowbox.get_selected_children()
        selected_child = selected_children[0]
        hbox = selected_child.get_child()
        game_label = hbox.get_children()[1]
        title = game_label.get_text()

        # Display duplicate dialog
        duplicate_dialog = DuplicateDialog(self, title)

        game = next((g for g in self.games if g.title == title), None)

        while True:
            response = duplicate_dialog.run()

            if response == Gtk.ResponseType.OK:
                new_title = duplicate_dialog.entry_title.get_text()

                if any(new_title == game.title for game in self.games):
                    duplicate_dialog.show_warning_dialog(duplicate_dialog, _("%s already exists.") % title)
                else:
                    title_formatted_old = format_title(game.title)

                    icon = f"{icons_dir}/{title_formatted_old}.ico"
                    banner = game.banner

                    game.title = new_title
                    title_formatted = format_title(game.title)

                    new_icon = f"{icons_dir}/{title_formatted}.ico"
                    new_banner = f"{banners_dir}/{title_formatted}.png"

                    if os.path.exists(icon):
                        shutil.copyfile(icon, new_icon)

                    if os.path.exists(banner):
                        shutil.copyfile(banner, new_banner)

                    game.banner = new_banner

                    game_info = {"gameid": game.gameid, "title": game.title, "path": game.path, "prefix": game.prefix,
                        "launch_arguments": game.launch_arguments, "game_arguments": game.game_arguments,
                        "mangohud": game.mangohud, "gamemode": game.gamemode, "disable_hidraw": game.disable_hidraw,
                        "protonfix": game.protonfix, "runner": game.runner, "addapp_checkbox": game.addapp_checkbox,
                        "addapp": game.addapp, "addapp_bat": game.addapp_bat, "banner": game.banner, }

                    games = []
                    if os.path.exists("games.json"):
                        try:
                            with open("games.json", "r", encoding="utf-8") as file:
                                games = json.load(file)
                        except json.JSONDecodeError as e:
                            print(f"Error reading the JSON file: {e}")

                    games.append(game_info)

                    with open("games.json", "w", encoding="utf-8") as file:
                        json.dump(games, file, ensure_ascii=False, indent=4)

                    self.games.append(game)
                    self.add_item_list(game)
                    self.update_list()

                    # Select the added game
                    self.select_game_by_title(new_title)

                    break

            else:
                break

        duplicate_dialog.destroy()

    def on_item_release_event(self, widget, event):
        if event.button == Gdk.BUTTON_PRIMARY:
            current_time = event.time
            current_item = self.get_item_at_event(event)

            if current_item:
                self.flowbox.select_child(current_item)
                if current_item == self.last_clicked_item and current_time - self.last_click_time < self.double_click_time_threshold:
                    self.on_item_double_click(current_item)

            self.last_clicked_item = current_item
            self.last_click_time = current_time

    def get_item_at_event(self, event):
        x, y = event.x, event.y
        return self.flowbox.get_child_at_pos(x, y)

    def on_item_double_click(self, item):
        selected_children = self.flowbox.get_selected_children()

        if not selected_children:
            return

        selected_child = selected_children[0]
        hbox = selected_child.get_child()
        game_label = hbox.get_children()[1]
        title = game_label.get_text()

        current_focus = self.get_focus()

        if IS_FLATPAK:
            if title not in self.processos:
                self.on_button_play_clicked(item)
            else:
                self.running_dialog(title)
        else:
            processos = self.load_processes_from_file()
            if title not in processos:
                self.on_button_play_clicked(selected_child)
            else:
                self.running_dialog(title)

    def on_key_press_event(self, widget, event):
        selected_children = self.flowbox.get_selected_children()

        if not selected_children:
            return

        selected_child = selected_children[0]
        hbox = selected_child.get_child()
        game_label = hbox.get_children()[1]
        title = game_label.get_text()

        current_focus = self.get_focus()

        if event.keyval in (Gdk.KEY_Up, Gdk.KEY_Down, Gdk.KEY_Left, Gdk.KEY_Right):
            if current_focus not in self.flowbox.get_children():
                selected_child.grab_focus()

        if self.interface_mode != "List":
            if event.keyval == Gdk.KEY_Return and event.state & Gdk.ModifierType.MOD1_MASK:
                if self.get_window().get_state() & Gdk.WindowState.FULLSCREEN:
                    self.fullscreen_activated = False
                    self.unfullscreen()
                    self.grid_corner.set_visible(False)
                    self.grid_left.set_margin_start(0)
                else:
                    self.fullscreen_activated = True
                    self.fullscreen()
                    self.grid_corner.set_visible(True)
                    self.grid_left.set_margin_start(70)
                return True

        if IS_FLATPAK:
            if event.keyval == Gdk.KEY_Return:
                if title not in self.processos:
                    widget = self.button_play
                    self.on_button_play_clicked(selected_child)
                else:
                    self.running_dialog(title)
            elif event.keyval == Gdk.KEY_Delete:
                self.on_button_delete_clicked(selected_child)
        else:
            if event.keyval == Gdk.KEY_Return:
                processos = self.load_processes_from_file()
                if title not in processos:
                    self.on_button_play_clicked(selected_child)
                else:
                    self.running_dialog(title)
            elif event.keyval == Gdk.KEY_Delete:
                self.on_button_delete_clicked(selected_child)

        if event.string:
            if event.string.isprintable():
                self.entry_search.grab_focus()
                current_text = self.entry_search.get_text()
                new_text = current_text + event.string
                self.entry_search.set_text(new_text)
                self.entry_search.set_position(len(new_text))
            elif event.keyval == Gdk.KEY_BackSpace:
                self.entry_search.grab_focus()
                current_text = self.entry_search.get_text()
                new_text = current_text[:-1]
                self.entry_search.set_text(new_text)
                self.entry_search.set_position(len(new_text))

            return True

        return False

    def running_dialog(self, title):
        dialog = Gtk.Dialog(title="Faugus Launcher", parent=self, modal=True)
        dialog.set_resizable(False)
        dialog.set_icon_from_file(faugus_png)
        subprocess.Popen(["canberra-gtk-play", "-f", faugus_notification])

        label = Gtk.Label()
        label.set_label(_("%s is already running.") % title)
        label.set_halign(Gtk.Align.CENTER)

        button_yes = Gtk.Button(label=_("Ok"))
        button_yes.set_size_request(150, -1)
        button_yes.connect("clicked", lambda x: dialog.response(Gtk.ResponseType.YES))

        content_area = dialog.get_content_area()
        content_area.set_border_width(0)
        content_area.set_halign(Gtk.Align.CENTER)
        content_area.set_valign(Gtk.Align.CENTER)
        content_area.set_vexpand(True)
        content_area.set_hexpand(True)

        box_top = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box_top.set_margin_start(20)
        box_top.set_margin_end(20)
        box_top.set_margin_top(20)
        box_top.set_margin_bottom(20)

        box_bottom = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box_bottom.set_margin_start(10)
        box_bottom.set_margin_end(10)
        box_bottom.set_margin_bottom(10)

        box_top.pack_start(label, True, True, 0)
        box_bottom.pack_start(button_yes, True, True, 0)

        content_area.add(box_top)
        content_area.add(box_bottom)

        dialog.show_all()
        dialog.run()
        dialog.destroy()

    def load_config(self):
        cfg = ConfigManager()

        self.system_tray = cfg.config.get('system-tray', 'False') == 'True'
        self.start_boot = cfg.config.get('start-boot', 'False') == 'True'
        self.mono_icon = cfg.config.get('mono-icon', 'False') == 'True'
        self.close_on_launch = cfg.config.get('close-onlaunch', 'False') == 'True'
        self.start_maximized = cfg.config.get('start-maximized', 'False') == 'True'
        self.interface_mode = cfg.config.get('interface-mode', '').strip('"')
        self.start_fullscreen = cfg.config.get('start-fullscreen', 'False') == 'True'
        self.show_labels = cfg.config.get('show-labels', 'False') == 'True'
        self.smaller_banners = cfg.config.get('smaller-banners', 'False') == 'True'
        self.enable_logging = cfg.config.get('enable-logging', 'False') == 'True'
        self.wayland_driver = cfg.config.get('wayland-driver', 'False') == 'True'
        self.enable_hdr = cfg.config.get('enable-hdr', 'False') == 'True'
        self.enable_ntsync = cfg.config.get('enable-ntsync', 'False') == 'True'
        self.enable_wow64 = cfg.config.get('enable-wow64', 'False') == 'True'
        self.language = cfg.config.get('language', '')

    def create_tray_menu(self):
        # Create the tray menu
        menu = Gtk.Menu()

        # Add game items from latest-games.txt
        games_file_path = latest_games
        if os.path.exists(games_file_path):
            with open(games_file_path, "r") as games_file:
                for line in games_file:
                    game_name = line.strip()
                    if game_name:
                        game_item = Gtk.MenuItem(label=game_name)
                        game_item.connect("activate", self.on_game_selected, game_name)
                        menu.append(game_item)

        # Add a separator between game items and the other menu items
        separator = Gtk.SeparatorMenuItem()
        menu.append(separator)

        # Item to restore the window
        restore_item = Gtk.MenuItem(label=_("Open Faugus Launcher"))
        restore_item.connect("activate", self.restore_window)
        menu.append(restore_item)

        # Item to quit the application
        quit_item = Gtk.MenuItem(label=_("Quit"))
        quit_item.connect("activate", self.on_quit_activate)
        menu.append(quit_item)

        menu.show_all()
        return menu

    def on_game_selected(self, widget, game_name):
        # Find the game in the FlowBox by name and select it
        self.flowbox.unselect_all()
        for child in self.flowbox.get_children():
            hbox = child.get_children()[0]  # Assuming HBox structure
            game_label = hbox.get_children()[1]  # The label should be the second item in HBox
            title = game_label.get_text()
            if game_label.get_text() == game_name:
                # Select this item in FlowBox
                self.flowbox.select_child(child)
                break

        # Call the function to run the selected game
        processos = self.load_processes_from_file()
        if title not in processos:
            self.on_button_play_clicked(widget)
        else:
            self.running_dialog(title)

    def on_window_delete_event(self, widget, event):
        # Only prevent closing when system tray is active
        self.load_config()
        if self.system_tray:
            self.hide()  # Minimize the window instead of closing
            return True  # Stop the event to keep the app running
        return False  # Allow the window to close

    def restore_window(self, widget):
        # Restore the window when clicking the tray icon
        self.show_all()
        if self.interface_mode != "List":
            if self.fullscreen_activated:
                self.fullscreen_activated = True
                self.grid_corner.set_visible(True)
                self.grid_left.set_margin_start(70)
            else:
                self.fullscreen_activated = False
                self.grid_corner.set_visible(False)
                self.grid_left.set_margin_start(0)
        self.present()

    def on_quit_activate(self, widget):
        if lock.is_locked:
            lock.release()
        Gtk.main_quit()

    def load_games(self):
        # Load games from JSON file
        try:
            with open("games.json", "r", encoding="utf-8") as file:
                games_data = json.load(file)

                for game_data in games_data:
                    gameid = game_data.get("gameid", "")
                    title = game_data.get("title", "")
                    path = game_data.get("path", "")
                    prefix = game_data.get("prefix", "")
                    launch_arguments = game_data.get("launch_arguments", "")
                    game_arguments = game_data.get("game_arguments", "")
                    mangohud = game_data.get("mangohud", "")
                    gamemode = game_data.get("gamemode", "")
                    disable_hidraw = game_data.get("disable_hidraw", "")
                    protonfix = game_data.get("protonfix", "")
                    runner = game_data.get("runner", "")
                    addapp_checkbox = game_data.get("addapp_checkbox", "")
                    addapp = game_data.get("addapp", "")
                    addapp_bat = game_data.get("addapp_bat", "")
                    banner = game_data.get("banner", "")
                    lossless = game_data.get("lossless", "")

                    game = Game(gameid, title, path, prefix, launch_arguments, game_arguments, mangohud, gamemode, disable_hidraw,
                                protonfix, runner, addapp_checkbox, addapp, addapp_bat, banner, lossless)
                    self.games.append(game)

                self.games = sorted(self.games, key=lambda x: x.title.lower())
                self.filtered_games = self.games[:]
                self.flowbox.foreach(Gtk.Widget.destroy)
                for game in self.filtered_games:
                    self.add_item_list(game)
        except FileNotFoundError:
            pass
        except json.JSONDecodeError as e:
            print(f"Error reading the JSON file: {e}")

    def add_item_list(self, game):
        # Add a game item to the list
        if self.interface_mode == "List":
            hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        if self.interface_mode == "Blocks":
            hbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            hbox.set_size_request(200, -1)
        if self.interface_mode == "Banners":
            hbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        hbox.get_style_context().add_class(self.theme)

        game_icon = f'{icons_dir}/{game.gameid}.ico'
        game_label = Gtk.Label.new(game.title)

        if self.interface_mode == "Blocks" or self.interface_mode == "Banners":
            game_label.set_line_wrap(True)
            game_label.set_max_width_chars(1)
            game_label.set_justify(Gtk.Justification.CENTER)

        if os.path.isfile(game_icon):
            pass
        else:
            game_icon = faugus_png

        self.flowbox_child = Gtk.FlowBoxChild()

        pixbuf = GdkPixbuf.Pixbuf.new_from_file(game_icon)
        if self.interface_mode == "List":
            scaled_pixbuf = pixbuf.scale_simple(40, 40, GdkPixbuf.InterpType.BILINEAR)
            image = Gtk.Image.new_from_file(game_icon)
            image.set_from_pixbuf(scaled_pixbuf)
            image.set_margin_start(10)
            image.set_margin_end(10)
            image.set_margin_top(10)
            image.set_margin_bottom(10)
            game_label.set_margin_start(10)
            game_label.set_margin_end(10)
            game_label.set_margin_top(10)
            game_label.set_margin_bottom(10)
            hbox.pack_start(image, False, False, 0)
            hbox.pack_start(game_label, False, False, 0)
            self.flowbox_child.set_size_request(300, -1)
            self.flowbox.set_homogeneous(True)
            self.flowbox_child.set_valign(Gtk.Align.START)
            self.flowbox_child.set_halign(Gtk.Align.FILL)
        if self.interface_mode == "Blocks":
            self.flowbox_child.set_hexpand(True)
            self.flowbox_child.set_vexpand(True)
            scaled_pixbuf = pixbuf.scale_simple(100, 100, GdkPixbuf.InterpType.BILINEAR)
            image = Gtk.Image.new_from_file(game_icon)
            image.set_from_pixbuf(scaled_pixbuf)
            hbox.pack_start(image, False, False, 0)
            hbox.pack_start(game_label, True, False, 0)
            image.set_margin_top(10)
            game_label.set_margin_top(10)
            game_label.set_margin_end(10)
            game_label.set_margin_start(10)
            game_label.set_margin_bottom(10)
            self.flowbox_child.set_valign(Gtk.Align.FILL)
            self.flowbox_child.set_halign(Gtk.Align.FILL)
        if self.interface_mode == "Banners":
            self.flowbox_child.set_hexpand(True)
            self.flowbox_child.set_vexpand(True)
            image2 = Gtk.Image()
            game_label.set_size_request(-1, 50)
            game_label.set_margin_end(10)
            game_label.set_margin_start(10)
            self.flowbox_child.set_margin_start(10)
            self.flowbox_child.set_margin_end(10)
            self.flowbox_child.set_margin_top(10)
            self.flowbox_child.set_margin_bottom(10)
            self.flowbox_child.set_valign(Gtk.Align.FILL)
            self.flowbox_child.set_halign(Gtk.Align.FILL)
            if game.banner == "" or not os.path.isfile(game.banner):
                if self.smaller_banners:
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(faugus_banner, 180, 270, False)
                else:
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(faugus_banner, 230, 345, False)
            else:
                if self.smaller_banners:
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(game.banner, 180, 270, False)
                else:
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(game.banner, 230, 345, False)
            image2.set_from_pixbuf(pixbuf)
            hbox.pack_start(image2, False, False, 0)
            hbox.pack_start(game_label, True, False, 0)
            if not self.show_labels:
                game_label.set_no_show_all(True)

        self.flowbox_child.add(hbox)
        self.flowbox.add(self.flowbox_child)

    def on_search_changed(self, entry):
        search_text = entry.get_text().lower()
        self.filtered_games = [game for game in self.games if search_text in game.title.lower()]

        for child in self.flowbox.get_children():
            self.flowbox.remove(child)

        if self.filtered_games:
            for game in self.filtered_games:
                self.add_item_list(game)

            first_child = self.flowbox.get_children()[0]
            self.flowbox.select_child(first_child)
            self.on_item_selected(self.flowbox, first_child)

        else:
            pass

        self.flowbox.show_all()

    def on_item_selected(self, flowbox, child):
        if child is not None:
            children = child.get_children()
            hbox = children[0]
            label_children = hbox.get_children()
            game_label = label_children[1]
            title = game_label.get_text()

            self.menu_item_edit.set_sensitive(True)
            self.menu_item_delete.set_sensitive(True)

            if IS_FLATPAK:
                if title in self.processos:
                    self.menu_item_play.set_sensitive(False)
                    self.button_play.set_sensitive(False)
                    self.button_play.set_image(
                        Gtk.Image.new_from_icon_name("faugus-stop-symbolic", Gtk.IconSize.BUTTON))
                else:
                    self.menu_item_play.set_sensitive(True)
                    self.button_play.set_sensitive(True)
                    self.button_play.set_image(
                        Gtk.Image.new_from_icon_name("faugus-play-symbolic", Gtk.IconSize.BUTTON))
            else:
                processos = self.load_processes_from_file()
                if title in self.button_locked:
                    self.menu_item_play.set_sensitive(False)
                    self.button_play.set_sensitive(False)
                    self.button_play.set_image(Gtk.Image.new_from_icon_name("faugus-stop-symbolic", Gtk.IconSize.BUTTON))
                elif title in processos:
                    self.menu_item_play.set_sensitive(True)
                    self.button_play.set_sensitive(True)
                    self.button_play.set_image(Gtk.Image.new_from_icon_name("faugus-stop-symbolic", Gtk.IconSize.BUTTON))
                else:
                    self.menu_item_play.set_sensitive(True)
                    self.button_play.set_sensitive(True)
                    self.button_play.set_image(
                        Gtk.Image.new_from_icon_name("faugus-play-symbolic", Gtk.IconSize.BUTTON))

        else:
            self.menu_item_edit.set_sensitive(False)
            self.menu_item_delete.set_sensitive(False)
            self.menu_item_play.set_sensitive(False)
            self.button_play.set_sensitive(False)

    def on_button_settings_clicked(self, widget):
        # Handle add button click event
        settings_dialog = Settings(self)
        settings_dialog.connect("response", self.on_settings_dialog_response, settings_dialog)

        settings_dialog.show()

    def on_settings_dialog_response(self, dialog, response_id, settings_dialog):
        if faugus_backup:
            subprocess.Popen([sys.executable, __file__])
            self.destroy()
            self.load_config()
            self.manage_autostart_file(self.start_boot)
            settings_dialog.destroy()
            return

        # Handle dialog response
        if response_id == Gtk.ResponseType.OK:
            default_prefix = settings_dialog.entry_default_prefix.get_text()
            validation_result = self.validate_settings_fields(settings_dialog, default_prefix)
            if not validation_result:
                return

            settings_dialog.update_config_file()
            self.manage_autostart_file(settings_dialog.checkbox_start_boot.get_active())
            settings_dialog.update_system_tray()

            if validation_result:
                combobox_language = settings_dialog.combobox_language.get_active_text()
                if self.interface_mode != settings_dialog.combobox_interface.get_active_text():
                    subprocess.Popen([sys.executable, __file__])
                    self.destroy()
                if self.show_labels != settings_dialog.checkbox_show_labels.get_active():
                    subprocess.Popen([sys.executable, __file__])
                    self.destroy()
                if self.smaller_banners != settings_dialog.checkbox_smaller_banners.get_active():
                    subprocess.Popen([sys.executable, __file__])
                    self.destroy()
                if self.language != settings_dialog.lang_codes.get(combobox_language, "en_US"):
                    subprocess.Popen([sys.executable, __file__])
                    self.destroy()
                if self.mono_icon != settings_dialog.checkbox_mono_icon.get_active():
                    subprocess.Popen([sys.executable, __file__])
                    self.destroy()

                settings_dialog.update_envar_file()

            self.load_config()
            settings_dialog.destroy()

        else:
            settings_dialog.destroy()

    def validate_settings_fields(self, settings_dialog, default_prefix):
        settings_dialog.entry_default_prefix.get_style_context().remove_class("entry")

        if settings_dialog.combobox_interface.get_active_text() == "Banners":
            if not default_prefix:
                if not default_prefix:
                    settings_dialog.entry_default_prefix.get_style_context().add_class("entry")
                return False
            return True
        elif not default_prefix:
            settings_dialog.entry_default_prefix.get_style_context().add_class("entry")
            return False
        else:
            return True

    def manage_autostart_file(self, checkbox_start_boot):
        # Define the path for the autostart file
        autostart_path = os.path.expanduser('~/.config/autostart/faugus-launcher.desktop')
        autostart_dir = os.path.dirname(autostart_path)

        # Ensure the autostart directory exists
        if not os.path.exists(autostart_dir):
            os.makedirs(autostart_dir)

        if checkbox_start_boot:
            # Create the autostart file if it does not exist
            if not os.path.exists(autostart_path):
                with open(autostart_path, "w") as f:
                    if IS_FLATPAK:
                        f.write(
                            "[Desktop Entry]\n"
                            "Categories=Utility;\n"
                            "Exec=flatpak run io.github.Faugus.faugus-launcher --hide\n"
                            "Icon=io.github.Faugus.faugus-launcher\n"
                            "MimeType=application/x-ms-dos-executable;application/x-msi;application/x-ms-shortcut;application/x-bat;text/x-ms-regedit\n"
                            "Name=Faugus Launcher\n"
                            "Type=Application\n"
                        )
                    else:
                        f.write(
                            "[Desktop Entry]\n"
                            "Categories=Utility;\n"
                            "Exec=faugus-launcher --hide\n"
                            "Icon=faugus-launcher\n"
                            "MimeType=application/x-ms-dos-executable;application/x-msi;application/x-ms-shortcut;application/x-bat;text/x-ms-regedit\n"
                            "Name=Faugus Launcher\n"
                            "Type=Application\n"
                        )
        else:
            # Delete the autostart file if it exists
            if os.path.exists(autostart_path):
                os.remove(autostart_path)

    def on_button_play_clicked(self, widget):
        selected_children = self.flowbox.get_selected_children()
        selected_child = selected_children[0]
        hbox = selected_child.get_child()
        game_label = hbox.get_children()[1]
        title = game_label.get_text()

        processos = self.load_processes_from_file()
        self.button_locked[title] = True

        if title in processos:
            data = processos[title]

            for key in ("umu", "main"):
                pid = data.get(key)
                if pid:
                    try:
                        proc = psutil.Process(pid)
                        for child in proc.children(recursive=True):
                            child.terminate()
                        proc.terminate()
                    except psutil.NoSuchProcess:
                        continue

            return

        # Find the selected game object
        game = next((j for j in self.games if j.title == title), None)
        if game:
            # Format the title for command execution
            game_directory = os.path.dirname(game.path)

            # Save the game title to the latest_games.txt file
            self.update_latest_games_file(title)

            if self.close_on_launch:
                if IS_FLATPAK:
                    subprocess.Popen([sys.executable, faugus_run, "--game", game.gameid], stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, cwd=game_directory)
                    sys.exit()
                else:
                    self.processo = subprocess.Popen([sys.executable, faugus_run, "--game", game.gameid], cwd=game_directory)

                    self.menu_item_play.set_sensitive(False)
                    self.button_play.set_sensitive(False)
                    self.button_play.set_image(Gtk.Image.new_from_icon_name("faugus-stop-symbolic", Gtk.IconSize.BUTTON))

                    def check_pid_timeout():
                        if self.find_pid(game):
                            sys.exit()
                        return True

                    GLib.timeout_add(1000, check_pid_timeout)

            else:
                self.processo = subprocess.Popen([sys.executable, faugus_run, "--game", game.gameid], cwd=game_directory)

                self.menu_item_play.set_sensitive(False)
                self.button_play.set_sensitive(False)
                self.button_play.set_image(Gtk.Image.new_from_icon_name("faugus-stop-symbolic", Gtk.IconSize.BUTTON))

                if IS_FLATPAK:
                    self.processos[title] = self.processo
                else:
                    def check_pid_periodically():
                        if self.find_pid(game):
                            return False
                        return True

                    GLib.timeout_add(1000, check_pid_periodically)

    def find_pid(self, game):
        try:
            parent = psutil.Process(self.processo.pid)
            all_descendants = parent.children(recursive=True)
        except psutil.NoSuchProcess:
            return False

        umu_run_pid = None

        for proc in all_descendants:
            try:
                name = os.path.splitext(proc.name())[0].lower()
                if name == "umu-run":
                    umu_run_pid = proc.pid
                    break
            except psutil.NoSuchProcess:
                continue

        self.save_process_to_file(
            game.title,
            main_pid=self.processo.pid,
            umu_pid=umu_run_pid
        )

        self.menu_item_play.set_sensitive(True)
        self.button_play.set_sensitive(True)
        self.button_play.set_image(Gtk.Image.new_from_icon_name("faugus-stop-symbolic", Gtk.IconSize.BUTTON))
        if game.title in self.button_locked:
            del self.button_locked[game.title]

        return True

    def save_process_to_file(self, title, main_pid, umu_pid=None):
        os.makedirs(os.path.dirname(running_games), exist_ok=True)

        try:
            with open(running_games, "r") as f:
                processos = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            processos = {}

        processos[title] = {
            "main": main_pid,
            "umu": umu_pid
        }

        with open(running_games, "w") as f:
            json.dump(processos, f, indent=2)

    def update_latest_games_file(self, title):
        # Read the existing games from the file, if it exists
        try:
            with open(latest_games, 'r') as f:
                games = f.read().splitlines()
        except FileNotFoundError:
            games = []

        # Remove the game if it already exists in the list and add it to the top
        if title in games:
            games.remove(title)
        games.insert(0, title)

        # Keep only the 5 most recent games
        games = games[:5]

        # Write the updated list back to the file
        with open(latest_games, 'w') as f:
            f.write('\n'.join(games))
        self.indicator.set_menu(self.create_tray_menu())

    def on_button_kill_clicked(self, widget):
        # Handle kill button click event
        subprocess.run(r"""
    for pid in $(ls -l /proc/*/exe 2>/dev/null | grep -E 'wine(64)?-preloader|wineserver|winedevice.exe' | awk -F'/' '{print $3}'); do
        kill -9 "$pid"
    done
""", shell=True)
        self.game_running = False
        self.button_locked.clear()

    def on_button_add_clicked(self, widget):
        file_path = ""
        # Handle add button click event
        add_game_dialog = AddGame(self, self.game_running, file_path, self.interface_mode)
        add_game_dialog.connect("response", self.on_dialog_response, add_game_dialog)

        add_game_dialog.show()

    def on_button_edit_clicked(self, widget):
        file_path = ""

        selected_children = self.flowbox.get_selected_children()
        selected_child = selected_children[0]
        hbox = selected_child.get_child()
        game_label = hbox.get_children()[1]
        title = game_label.get_text()

        if game := next((j for j in self.games if j.title == title), None):
            processos = self.load_processes_from_file()
            if game.title in processos:
                self.game_running = True
            else:
                self.game_running = False
            edit_game_dialog = AddGame(self, self.game_running, file_path, self.interface_mode)
            edit_game_dialog.connect("response", self.on_edit_dialog_response, edit_game_dialog, game)

            model_runner = edit_game_dialog.combobox_runner.get_model()
            model_lossless = edit_game_dialog.combobox_lossless.get_model()
            index_runner = 0
            index_lossless = 0
            game_runner = game.runner

            if game.runner == "GE-Proton":
                game_runner = "GE-Proton Latest (default)"
            if game.runner == "":
                game_runner = "UMU-Proton Latest"
            if game.runner == "Proton-EM":
                game_runner = "Proton-EM Latest"
            if game_runner == "Linux-Native":
                edit_game_dialog.combobox_launcher.set_active(1)

            if game.lossless == "":
                game.lossless = "Off"
            if game.lossless == "LSFG_LEGACY=1 LSFG_MULTIPLIER=1":
                game.lossless = "X1"
            if game.lossless == "LSFG_LEGACY=1 LSFG_MULTIPLIER=2":
                game.lossless = "X2"
            if game.lossless == "LSFG_LEGACY=1 LSFG_MULTIPLIER=3":
                game.lossless = "X3"
            if game.lossless == "LSFG_LEGACY=1 LSFG_MULTIPLIER=4":
                game.lossless = "X4"

            for i, row in enumerate(model_runner):
                if row[0] == game_runner:
                    index_runner = i
                    break
            if not game_runner:
                index_runner = 1

            for i, row in enumerate(model_lossless):
                if row[0] == game.lossless:
                    index_lossless = i
                    break
            if not game.lossless:
                index_lossless = 0

            edit_game_dialog.combobox_runner.set_active(index_runner)
            edit_game_dialog.combobox_lossless.set_active(index_lossless)
            edit_game_dialog.entry_title.set_text(game.title)
            edit_game_dialog.entry_path.set_text(game.path)
            edit_game_dialog.entry_prefix.set_text(game.prefix)
            edit_game_dialog.entry_launch_arguments.set_text(game.launch_arguments)
            edit_game_dialog.entry_game_arguments.set_text(game.game_arguments)
            edit_game_dialog.set_title(_("Edit %s") % game.title)
            edit_game_dialog.entry_protonfix.set_text(game.protonfix)
            edit_game_dialog.entry_addapp.set_text(game.addapp)
            edit_game_dialog.grid_launcher.set_visible(False)

            if not os.path.isfile(game.banner):
                game.banner = faugus_banner
            shutil.copyfile(game.banner, edit_game_dialog.banner_path_temp)
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(game.banner, 260, 390, True)
            edit_game_dialog.image_banner.set_from_pixbuf(pixbuf)
            edit_game_dialog.image_banner2.set_from_pixbuf(pixbuf)

            mangohud_enabled = os.path.exists(mangohud_dir)
            if mangohud_enabled:
                if game.mangohud == "MANGOHUD=1":
                    edit_game_dialog.checkbox_mangohud.set_active(True)
                else:
                    edit_game_dialog.checkbox_mangohud.set_active(False)

            gamemode_enabled = os.path.exists(gamemoderun) or os.path.exists("/usr/games/gamemoderun")
            if gamemode_enabled:
                if game.gamemode == "gamemoderun":
                    edit_game_dialog.checkbox_gamemode.set_active(True)
                else:
                    edit_game_dialog.checkbox_gamemode.set_active(False)

            if game.disable_hidraw == "PROTON_DISABLE_HIDRAW=1":
                edit_game_dialog.checkbox_disable_hidraw.set_active(True)
            else:
                edit_game_dialog.checkbox_disable_hidraw.set_active(False)

            if game.addapp_checkbox == "addapp_enabled":
                edit_game_dialog.checkbox_addapp.set_active(True)
            else:
                edit_game_dialog.checkbox_addapp.set_active(False)

            self.updated_steam_id = detect_steam_id()
            if self.updated_steam_id is not None:
                if self.check_steam_shortcut(title):
                    edit_game_dialog.checkbox_shortcut_steam.set_active(True)
                else:
                    edit_game_dialog.checkbox_shortcut_steam.set_active(False)
            else:
                edit_game_dialog.checkbox_shortcut_steam.set_active(False)
                edit_game_dialog.checkbox_shortcut_steam.set_sensitive(False)
                edit_game_dialog.checkbox_shortcut_steam.set_tooltip_text(
                    _("Add or remove a shortcut from Steam. Steam needs to be restarted. NO STEAM USERS FOUND."))

            edit_game_dialog.check_existing_shortcut()

            image = self.set_image_shortcut_icon(game.title, edit_game_dialog.icons_path, edit_game_dialog.icon_temp)
            edit_game_dialog.button_shortcut_icon.set_image(image)
            edit_game_dialog.entry_title.set_sensitive(False)

            if self.game_running:
                edit_game_dialog.button_winecfg.set_sensitive(False)
                edit_game_dialog.button_winecfg.set_tooltip_text(_("%s is running. Please close it first.") % game.title)
                edit_game_dialog.button_winetricks.set_sensitive(False)
                edit_game_dialog.button_winetricks.set_tooltip_text(_("%s is running. Please close it first.") % game.title)
                edit_game_dialog.button_run.set_sensitive(False)
                edit_game_dialog.button_run.set_tooltip_text(_("%s is running. Please close it first.") % game.title)

            edit_game_dialog.show()

    def check_steam_shortcut(self, title):
        if os.path.exists(steam_shortcuts_path):
            try:
                with open(steam_shortcuts_path, 'rb') as f:
                    shortcuts = vdf.binary_load(f)
                for game in shortcuts["shortcuts"].values():
                    if isinstance(game, dict) and "AppName" in game and game["AppName"] == title:
                        return True
                return False
            except SyntaxError:
                return False
        return False

    def set_image_shortcut_icon(self, title, icons_path, icon_temp):
        title_formatted = format_title(title)

        # Check if the icon file exists
        icon_path = os.path.join(icons_path, f"{title_formatted}.ico")

        if os.path.exists(icon_path):
            shutil.copyfile(icon_path, icon_temp)
        if not os.path.exists(icon_path):
            icon_temp = faugus_png

        pixbuf = GdkPixbuf.Pixbuf.new_from_file(icon_temp)
        scaled_pixbuf = pixbuf.scale_simple(50, 50, GdkPixbuf.InterpType.BILINEAR)

        image = Gtk.Image.new_from_file(icon_temp)
        image.set_from_pixbuf(scaled_pixbuf)

        return image

    def on_button_delete_clicked(self, widget):
        selected_children = self.flowbox.get_selected_children()
        selected_child = selected_children[0]
        hbox = selected_child.get_child()
        game_label = hbox.get_children()[1]
        title = game_label.get_text()

        if game := next((j for j in self.games if j.title == title), None):
            # Display confirmation dialog
            confirmation_dialog = ConfirmationDialog(self, title, game.prefix)
            response = confirmation_dialog.run()

            if response == Gtk.ResponseType.YES:
                processos = self.load_processes_from_file()
                if title in processos:
                    data = processos[title]
                    pid = data.get("main")
                    if pid:
                        parent = psutil.Process(pid)
                        children = parent.children(recursive=True)

                        for child in children:
                            child.terminate()

                        parent.terminate()

                # Remove game and associated files if required
                if confirmation_dialog.get_remove_prefix_state():
                    game_prefix = game.prefix
                    prefix_path = os.path.expanduser(game_prefix)
                    while True:
                        try:
                            shutil.rmtree(prefix_path)
                            break
                        except FileNotFoundError:
                            break
                        except OSError:
                            continue

                # Remove the shortcut
                self.remove_shortcut(game, "both")
                self.remove_steam_shortcut(title)
                self.remove_banner(game)

                self.games.remove(game)
                self.save_games()
                self.update_list()

                # Remove the game from the latest-games file if it exists
                self.remove_game_from_latest_games(title)

                if self.flowbox.get_children():
                    self.flowbox.select_child(self.flowbox.get_children()[0])
                    self.on_item_selected(self.flowbox, self.flowbox.get_children()[0])

            confirmation_dialog.destroy()

    def remove_steam_shortcut(self, title):
        if os.path.exists(steam_shortcuts_path):
            try:
                with open(steam_shortcuts_path, 'rb') as f:
                    shortcuts = vdf.binary_load(f)

                to_remove = [app_id for app_id, game in shortcuts["shortcuts"].items() if
                             isinstance(game, dict) and "AppName" in game and game["AppName"] == title]
                for app_id in to_remove:
                    del shortcuts["shortcuts"][app_id]

                with open(steam_shortcuts_path, 'wb') as f:
                    vdf.binary_dump(shortcuts, f)
            except SyntaxError:
                pass

    def remove_game_from_latest_games(self, title):
        try:
            # Read the current list of recent games
            with open(latest_games, 'r') as f:
                recent_games = f.read().splitlines()

            # Remove the game title if it exists in the list
            if title in recent_games:
                recent_games.remove(title)

                # Write the updated list back, maintaining max 5 entries
                with open(latest_games, 'w') as f:
                    f.write("\n".join(recent_games[:5]))
            self.indicator.set_menu(self.create_tray_menu())

        except FileNotFoundError:
            pass  # Ignore if the file doesn't exist yet

    def show_warning_dialog(self, parent, title):
        dialog = Gtk.Dialog(title="Faugus Launcher", transient_for=parent, modal=True)
        dialog.set_resizable(False)
        dialog.set_icon_from_file(faugus_png)
        subprocess.Popen(["canberra-gtk-play", "-f", faugus_notification])

        label = Gtk.Label()
        label.set_label(title)
        label.set_halign(Gtk.Align.CENTER)

        button_yes = Gtk.Button(label=_("Ok"))
        button_yes.set_size_request(150, -1)
        button_yes.connect("clicked", lambda x: dialog.response(Gtk.ResponseType.YES))

        content_area = dialog.get_content_area()
        content_area.set_border_width(0)
        content_area.set_halign(Gtk.Align.CENTER)
        content_area.set_valign(Gtk.Align.CENTER)
        content_area.set_vexpand(True)
        content_area.set_hexpand(True)

        box_top = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box_top.set_margin_start(20)
        box_top.set_margin_end(20)
        box_top.set_margin_top(20)
        box_top.set_margin_bottom(20)

        box_bottom = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box_bottom.set_margin_start(10)
        box_bottom.set_margin_end(10)
        box_bottom.set_margin_bottom(10)

        box_top.pack_start(label, True, True, 0)
        box_bottom.pack_start(button_yes, True, True, 0)

        content_area.add(box_top)
        content_area.add(box_bottom)

        dialog.show_all()
        dialog.run()
        dialog.destroy()

    def on_dialog_response(self, dialog, response_id, add_game_dialog):
        # Handle dialog response
        if response_id == Gtk.ResponseType.OK:
            if not add_game_dialog.validate_fields(entry="path+prefix"):
                # If fields are not validated, return and keep the dialog open
                return True

            # Proceed with adding the game
            # Get game information from dialog fields
            prefix = add_game_dialog.entry_prefix.get_text()
            if add_game_dialog.combobox_launcher.get_active() == 0 or add_game_dialog.combobox_launcher.get_active() == 1:
                title = add_game_dialog.entry_title.get_text()
            else:
                title = add_game_dialog.combobox_launcher.get_active_text()

            if any(game.title == title for game in self.games):
                # Display an error message and prevent the dialog from closing
                self.show_warning_dialog(add_game_dialog, _("%s already exists.") % title)
                return True

            path = add_game_dialog.entry_path.get_text()
            launch_arguments = add_game_dialog.entry_launch_arguments.get_text()
            game_arguments = add_game_dialog.entry_game_arguments.get_text()
            protonfix = add_game_dialog.entry_protonfix.get_text()
            runner = add_game_dialog.combobox_runner.get_active_text()
            addapp = add_game_dialog.entry_addapp.get_text()
            lossless = add_game_dialog.combobox_lossless.get_active_text()

            title_formatted = format_title(title)

            addapp_bat = f"{os.path.dirname(path)}/faugus-{title_formatted}.bat"

            if self.interface_mode == "Banners":
                banner = os.path.join(banners_dir, f"{title_formatted}.png")
                temp_banner_path = add_game_dialog.banner_path_temp
                try:
                    # Use `magick` to resize the image
                    command_magick = shutil.which("magick") or shutil.which("convert")
                    subprocess.run([command_magick, temp_banner_path, "-resize", "230x345!", banner], check=True)
                except subprocess.CalledProcessError as e:
                    print(f"Error resizing banner: {e}")
            else:
                banner = ""

            if runner == "UMU-Proton Latest":
                runner = ""
            if runner == "GE-Proton Latest (default)":
                runner = "GE-Proton"
            if runner == "Proton-EM Latest":
                runner = "Proton-EM"
            if add_game_dialog.combobox_launcher.get_active() == 1:
                runner = "Linux-Native"

            if lossless == "Off":
                lossless = ""
            if lossless == "X1":
                lossless = "LSFG_LEGACY=1 LSFG_MULTIPLIER=1"
            if lossless == "X2":
                lossless = "LSFG_LEGACY=1 LSFG_MULTIPLIER=2"
            if lossless == "X3":
                lossless = "LSFG_LEGACY=1 LSFG_MULTIPLIER=3"
            if lossless == "X4":
                lossless = "LSFG_LEGACY=1 LSFG_MULTIPLIER=4"

            # Determine mangohud and gamemode status
            mangohud = "MANGOHUD=1" if add_game_dialog.checkbox_mangohud.get_active() else ""
            gamemode = "gamemoderun" if add_game_dialog.checkbox_gamemode.get_active() else ""
            disable_hidraw = "PROTON_DISABLE_HIDRAW=1" if add_game_dialog.checkbox_disable_hidraw.get_active() else ""
            addapp_checkbox = "addapp_enabled" if add_game_dialog.checkbox_addapp.get_active() else ""

            # Create Game object and update UI
            game = Game(title_formatted, title, path, prefix, launch_arguments, game_arguments, mangohud, gamemode, disable_hidraw,
                        protonfix, runner, addapp_checkbox, addapp, addapp_bat, banner, lossless)

            # Determine the state of the shortcut checkbox
            desktop_shortcut_state = add_game_dialog.checkbox_shortcut_desktop.get_active()
            appmenu_shortcut_state = add_game_dialog.checkbox_shortcut_appmenu.get_active()
            steam_shortcut_state = add_game_dialog.checkbox_shortcut_steam.get_active()

            icon_temp = os.path.expanduser(add_game_dialog.icon_temp)
            icon_final = f'{add_game_dialog.icons_path}/{title_formatted}.ico'

            def check_internet_connection():
                try:
                    socket.create_connection(("8.8.8.8", 53), timeout=5)
                    return True
                except socket.gaierror:
                    return False
                except OSError as e:
                    if e.errno == 101:
                        return False
                    raise

            if add_game_dialog.combobox_launcher.get_active() != 0 and add_game_dialog.combobox_launcher.get_active() != 1:
                if not check_internet_connection():
                    self.show_warning_dialog(add_game_dialog, _("No internet connection."))
                    return True
                else:
                    if add_game_dialog.combobox_launcher.get_active() == 2:
                        add_game_dialog.destroy()
                        self.launcher_screen(title, "2", title_formatted, runner, prefix, umu_run, game, desktop_shortcut_state, appmenu_shortcut_state, steam_shortcut_state, icon_temp, icon_final)

                    if add_game_dialog.combobox_launcher.get_active() == 3:
                        add_game_dialog.destroy()
                        self.launcher_screen(title, "3", title_formatted, runner, prefix, umu_run, game, desktop_shortcut_state, appmenu_shortcut_state, steam_shortcut_state, icon_temp, icon_final)

                    if add_game_dialog.combobox_launcher.get_active() == 4:
                        add_game_dialog.destroy()
                        self.launcher_screen(title, "4", title_formatted, runner, prefix, umu_run, game, desktop_shortcut_state, appmenu_shortcut_state, steam_shortcut_state, icon_temp, icon_final)

                    if add_game_dialog.combobox_launcher.get_active() == 5:
                        add_game_dialog.destroy()
                        self.launcher_screen(title, "5", title_formatted, runner, prefix, umu_run, game, desktop_shortcut_state, appmenu_shortcut_state, steam_shortcut_state, icon_temp, icon_final)

            game_info = {"gameid": title_formatted, "title": title, "path": path, "prefix": prefix, "launch_arguments": launch_arguments,
                "game_arguments": game_arguments, "mangohud": mangohud, "gamemode": gamemode, "disable_hidraw": disable_hidraw,
                "protonfix": protonfix, "runner": runner, "addapp_checkbox": addapp_checkbox, "addapp": addapp,
                "addapp_bat": addapp_bat, "banner": banner, "lossless": lossless, }

            games = []
            if os.path.exists("games.json"):
                try:
                    with open("games.json", "r", encoding="utf-8") as file:
                        games = json.load(file)
                except json.JSONDecodeError as e:
                    print(f"Error reading the JSON file: {e}")

            games.append(game_info)

            with open("games.json", "w", encoding="utf-8") as file:
                json.dump(games, file, ensure_ascii=False, indent=4)

            self.games.append(game)

            if add_game_dialog.combobox_launcher.get_active() == 0 or add_game_dialog.combobox_launcher.get_active() == 1:
                # Call add_remove_shortcut method
                self.add_shortcut(game, desktop_shortcut_state, "desktop", icon_temp, icon_final)
                self.add_shortcut(game, appmenu_shortcut_state, "appmenu", icon_temp, icon_final)
                self.add_steam_shortcut(game, steam_shortcut_state, icon_temp, icon_final)

                if game.addapp_checkbox == True:
                    with open(game.addapp_bat, "w") as bat_file:
                        bat_file.write(f'start "" "z:{game.addapp}"\n')
                        if game_arguments:
                            bat_file.write(f'start "" "z:{path}" {game_arguments}\n')
                        else:
                            bat_file.write(f'start "" "z:{path}"\n')

                self.add_item_list(game)
                self.update_list()

                # Select the added game
                self.select_game_by_title(title)

        else:
            if os.path.isfile(add_game_dialog.icon_temp):
                os.remove(add_game_dialog.icon_temp)
            if os.path.isdir(add_game_dialog.icon_directory):
                shutil.rmtree(add_game_dialog.icon_directory)
            add_game_dialog.destroy()
        if os.path.isfile(add_game_dialog.banner_path_temp):
            os.remove(add_game_dialog.banner_path_temp)
        # Ensure the dialog is destroyed when canceled
        add_game_dialog.destroy()

    def launcher_screen(self, title, launcher, title_formatted, runner, prefix, umu_run, game, desktop_shortcut_state, appmenu_shortcut_state, steam_shortcut_state, icon_temp, icon_final):
        self.box_launcher = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.box_launcher.set_hexpand(True)
        self.box_launcher.set_vexpand(True)

        self.bar_download = Gtk.ProgressBar()
        self.bar_download.set_margin_start(20)
        self.bar_download.set_margin_end(20)
        self.bar_download.set_margin_bottom(40)

        grid_launcher = Gtk.Grid()
        grid_launcher.set_halign(Gtk.Align.CENTER)
        grid_launcher.set_valign(Gtk.Align.CENTER)

        grid_labels = Gtk.Grid()
        grid_labels.set_size_request(-1, 128)

        self.box_launcher.pack_start(grid_launcher, True, True, 0)

        self.label_download = Gtk.Label()
        self.label_download.set_margin_start(20)
        self.label_download.set_margin_end(20)
        self.label_download.set_margin_bottom(20)
        self.label_download.set_text(_("Installing %s...") % title)
        self.label_download.set_size_request(256, -1)

        self.label_download2 = Gtk.Label()
        self.label_download2.set_margin_start(20)
        self.label_download2.set_margin_end(20)
        self.label_download2.set_margin_bottom(20)
        self.label_download2.set_text("")
        self.label_download2.set_visible(False)
        self.label_download2.set_size_request(256, -1)

        self.button_finish_install = Gtk.Button(label=_("Finish installation"))
        self.button_finish_install.connect("clicked", self.on_button_finish_install_clicked)
        self.button_finish_install.set_size_request(150, -1)
        self.button_finish_install.set_halign(Gtk.Align.CENTER)

        if launcher == "2":
            image_path = battle_icon
            self.label_download.set_text(_("Downloading Battle.net..."))
            self.download_launcher("battle", title, title_formatted, runner, prefix, umu_run, game, desktop_shortcut_state, appmenu_shortcut_state, steam_shortcut_state, icon_temp, icon_final)

        elif launcher == "3":
            image_path = ea_icon
            self.label_download.set_text(_("Downloading EA App..."))
            self.download_launcher("ea", title, title_formatted, runner, prefix, umu_run, game, desktop_shortcut_state, appmenu_shortcut_state, steam_shortcut_state, icon_temp, icon_final)

        elif launcher == "4":
            image_path = epic_icon
            self.label_download.set_text(_("Downloading Epic Games..."))
            self.download_launcher("epic", title, title_formatted, runner, prefix, umu_run, game, desktop_shortcut_state, appmenu_shortcut_state, steam_shortcut_state, icon_temp, icon_final)

        elif launcher == "5":
            image_path = ubisoft_icon
            self.label_download.set_text(_("Downloading Ubisoft Connect..."))
            self.download_launcher("ubisoft", title, title_formatted, runner, prefix, umu_run, game, desktop_shortcut_state, appmenu_shortcut_state, steam_shortcut_state, icon_temp, icon_final)
        else:
            image_path = faugus_png

        pixbuf = GdkPixbuf.Pixbuf.new_from_file(image_path)
        pixbuf = pixbuf.scale_simple(128, 128, GdkPixbuf.InterpType.BILINEAR)

        image = Gtk.Image.new_from_pixbuf(pixbuf)
        image.set_margin_top(20)
        image.set_margin_start(20)
        image.set_margin_end(20)
        image.set_margin_bottom(20)

        grid_launcher.attach(image, 0, 0, 1, 1)
        grid_launcher.attach(grid_labels, 0, 1, 1, 1)

        grid_labels.attach(self.label_download, 0, 0, 1, 1)
        grid_labels.attach(self.bar_download, 0, 1, 1, 1)
        grid_labels.attach(self.label_download2, 0, 2, 1, 1)
        grid_labels.attach(self.button_finish_install, 0, 3, 1, 1)

        self.box_main.add(self.box_launcher)
        self.box_main.remove(self.box_top)
        self.box_main.remove(self.box_bottom)
        self.box_main.show_all()
        self.button_finish_install.set_visible(False)

    def on_button_finish_install_clicked(self):
        self.on_button_kill_clicked(widget)

    def monitor_process(self, processo, game, desktop_shortcut_state, appmenu_shortcut_state, steam_shortcut_state, icon_temp, icon_final, title):
        retcode = processo.poll()

        if retcode is not None:
            print(f"{title} installed.")

            if os.path.exists(faugus_temp):
                shutil.rmtree(faugus_temp)

            self.add_shortcut(game, desktop_shortcut_state, "desktop", icon_temp, icon_final)
            self.add_shortcut(game, appmenu_shortcut_state, "appmenu", icon_temp, icon_final)
            self.add_steam_shortcut(game, steam_shortcut_state, icon_temp, icon_final)

            self.add_item_list(game)
            self.update_list()
            self.select_game_by_title(title)

            self.box_main.pack_start(self.box_top, True, True, 0)
            self.box_main.pack_end(self.box_bottom, False, True, 0)
            self.box_main.remove(self.box_launcher)
            self.box_launcher.destroy()
            self.box_main.show_all()
            if self.interface_mode != "List":
                if self.fullscreen_activated:
                    self.fullscreen_activated = True
                    self.grid_corner.set_visible(True)
                    self.grid_left.set_margin_start(70)
                else:
                    self.fullscreen_activated = False
                    self.grid_corner.set_visible(False)
                    self.grid_left.set_margin_start(0)

            return False

        return True

    def download_launcher(self, launcher, title, title_formatted, runner, prefix, umu_run, game, desktop_shortcut_state, appmenu_shortcut_state, steam_shortcut_state, icon_temp, icon_final):
            urls = {"ea": "https://origin-a.akamaihd.net/EA-Desktop-Client-Download/installer-releases/EAappInstaller.exe",
                "epic": "https://launcher-public-service-prod06.ol.epicgames.com/launcher/api/installer/download/EpicGamesLauncherInstaller.msi",
                "battle": "https://downloader.battle.net/download/getInstaller?os=win&installer=Battle.net-Setup.exe",
                "ubisoft": "https://static3.cdn.ubi.com/orbit/launcher_installer/UbisoftConnectInstaller.exe"}

            file_name = {"ea": "EAappInstaller.exe", "epic": "EpicGamesLauncherInstaller.msi",
                "battle": "Battle.net-Setup.exe", "ubisoft": "UbisoftConnectInstaller.exe"}

            if launcher not in urls:
                return None

            os.makedirs(faugus_temp, exist_ok=True)
            file_path = os.path.join(faugus_temp, file_name[launcher])

            def report_progress(block_num, block_size, total_size):
                if total_size > 0:
                    downloaded = block_num * block_size
                    percent = min(downloaded / total_size, 1.0)
                    GLib.idle_add(self.bar_download.set_fraction, percent)
                    GLib.idle_add(self.bar_download.set_text, f"{int(percent * 100)}%")

            def start_download():
                try:
                    urllib.request.urlretrieve(urls[launcher], file_path, reporthook=report_progress)
                    GLib.idle_add(self.bar_download.set_fraction, 1.0)
                    GLib.idle_add(self.bar_download.set_text, _("Download complete"))
                    GLib.idle_add(on_download_complete)
                except Exception as e:
                    GLib.idle_add(self.show_warning_dialog, self, _("Error during download: %s") % e)

            def on_download_complete():
                self.label_download.set_text(_("Installing %s...") % title)
                if launcher == "battle":
                    self.label_download2.set_text(_("Please close the login window and wait..."))
                    command = f"FAUGUS_LOG={title_formatted} WINE_SIMULATE_WRITECOPY=1 WINEPREFIX='{prefix}' GAMEID={title_formatted} {umu_run} '{file_path}' --installpath='C:\\Program Files (x86)\\Battle.net' --lang=enUS"
                elif launcher == "ea":
                    self.label_download2.set_text(_("Please close the login window and wait..."))
                    command = f"FAUGUS_LOG={title_formatted} WINEPREFIX='{prefix}' GAMEID={title_formatted} {umu_run} '{file_path}' /S"
                elif launcher == "epic":
                    self.label_download2.set_text("")
                    command = f"FAUGUS_LOG={title_formatted} WINEPREFIX='{prefix}' GAMEID={title_formatted} {umu_run} msiexec /i '{file_path}' /passive"
                elif launcher == "ubisoft":
                    self.label_download2.set_text("")
                    command = f"FAUGUS_LOG={title_formatted} WINEPREFIX='{prefix}' GAMEID={title_formatted} {umu_run} '{file_path}' /S"

                if runner:
                    command = f"PROTONPATH={runner} {command}"

                self.bar_download.set_visible(False)
                self.label_download2.set_visible(True)
                processo = subprocess.Popen([sys.executable, faugus_run, command])
                GLib.timeout_add(100, self.monitor_process, processo, game, desktop_shortcut_state, appmenu_shortcut_state, steam_shortcut_state, icon_temp, icon_final, title)

            threading.Thread(target=start_download).start()

            return file_path

    def select_game_by_title(self, title):
        # Selects an item from the FlowBox based on the title
        for child in self.flowbox.get_children():
            hbox = child.get_children()[0]  # The first item is the hbox containing the label
            game_label = hbox.get_children()[1]  # The second item is the title label
            if game_label.get_text() == title:
                # Selects the child in the FlowBox
                self.flowbox.select_child(child)
                break

        # Calls the item selection method to ensure the buttons are updated
        self.on_item_selected(self.flowbox, child)

    def on_edit_dialog_response(self, dialog, response_id, edit_game_dialog, game):
        # Handle edit dialog response
        if response_id == Gtk.ResponseType.OK:
            if not edit_game_dialog.validate_fields(entry="path+prefix"):
                # If fields are not validated, return and keep the dialog open
                return True
            # Update game object with new information
            game.title = edit_game_dialog.entry_title.get_text()
            game.path = edit_game_dialog.entry_path.get_text()
            game.prefix = edit_game_dialog.entry_prefix.get_text()
            game.launch_arguments = edit_game_dialog.entry_launch_arguments.get_text()
            game.game_arguments = edit_game_dialog.entry_game_arguments.get_text()
            game.mangohud = edit_game_dialog.checkbox_mangohud.get_active()
            game.gamemode = edit_game_dialog.checkbox_gamemode.get_active()
            game.disable_hidraw = edit_game_dialog.checkbox_disable_hidraw.get_active()
            game.protonfix = edit_game_dialog.entry_protonfix.get_text()
            game.runner = edit_game_dialog.combobox_runner.get_active_text()
            game.addapp_checkbox = edit_game_dialog.checkbox_addapp.get_active()
            game.addapp = edit_game_dialog.entry_addapp.get_text()
            game.lossless = edit_game_dialog.combobox_lossless.get_active_text()

            title_formatted = format_title(game.title)

            game.gameid = title_formatted
            game.addapp_bat = f"{os.path.dirname(game.path)}/faugus-{title_formatted}.bat"

            if self.interface_mode == "Banners":
                banner = os.path.join(banners_dir, f"{title_formatted}.png")
                temp_banner_path = edit_game_dialog.banner_path_temp
                try:
                    # Use `magick` to resize the image
                    command_magick = shutil.which("magick") or shutil.which("convert")
                    subprocess.run([command_magick, temp_banner_path, "-resize", "230x345!", banner], check=True)
                    game.banner = banner
                except subprocess.CalledProcessError as e:
                    print(f"Error resizing banner: {e}")

            if game.runner == "UMU-Proton Latest":
                game.runner = ""
            if game.runner == "GE-Proton Latest (default)":
                game.runner = "GE-Proton"
            if game.runner == "Proton-EM Latest":
                game.runner = "Proton-EM"
            if edit_game_dialog.combobox_launcher.get_active() == 1:
                game.runner = "Linux-Native"

            if game.lossless == "Off":
                game.lossless = ""
            if game.lossless == "X1":
                game.lossless = "LSFG_LEGACY=1 LSFG_MULTIPLIER=1"
            if game.lossless == "X2":
                game.lossless = "LSFG_LEGACY=1 LSFG_MULTIPLIER=2"
            if game.lossless == "X3":
                game.lossless = "LSFG_LEGACY=1 LSFG_MULTIPLIER=3"
            if game.lossless == "X4":
                game.lossless = "LSFG_LEGACY=1 LSFG_MULTIPLIER=4"

            icon_temp = os.path.expanduser(edit_game_dialog.icon_temp)
            icon_final = f'{edit_game_dialog.icons_path}/{title_formatted}.ico'

            # Determine the state of the shortcut checkbox
            desktop_shortcut_state = edit_game_dialog.checkbox_shortcut_desktop.get_active()
            appmenu_shortcut_state = edit_game_dialog.checkbox_shortcut_appmenu.get_active()
            steam_shortcut_state = edit_game_dialog.checkbox_shortcut_steam.get_active()

            # Call add_remove_shortcut method
            self.add_shortcut(game, desktop_shortcut_state, "desktop", icon_temp, icon_final)
            self.add_shortcut(game, appmenu_shortcut_state, "appmenu", icon_temp, icon_final)
            self.add_steam_shortcut(game, steam_shortcut_state, icon_temp, icon_final)

            if game.addapp_checkbox == True:
                with open(game.addapp_bat, "w") as bat_file:
                    bat_file.write(f'start "" "z:{game.addapp}"\n')
                    if game.game_arguments:
                        bat_file.write(f'start "" "z:{game.path}" {game.game_arguments}\n')
                    else:
                        bat_file.write(f'start "" "z:{game.path}"\n')

            # Save changes and update UI
            self.save_games()
            self.update_list()

            # Select the game that was edited
            self.select_game_by_title(game.title)
        else:
            if os.path.isfile(edit_game_dialog.icon_temp):
                os.remove(edit_game_dialog.icon_temp)

        if os.path.isdir(edit_game_dialog.icon_directory):
            shutil.rmtree(edit_game_dialog.icon_directory)
        os.remove(edit_game_dialog.banner_path_temp)
        edit_game_dialog.destroy()

    def add_shortcut(self, game, shortcut_state, shortcut, icon_temp, icon_final):
        applications_shortcut_path = f"{app_dir}/{game.gameid}.desktop"
        desktop_shortcut_path = f"{desktop_dir}/{game.gameid}.desktop"

        # Check if the shortcut checkbox is checked
        if shortcut == "desktop" and not shortcut_state:
            # Remove existing shortcut if it exists
            self.remove_shortcut(game, shortcut)
            if os.path.isfile(os.path.expanduser(icon_temp)):
                os.rename(os.path.expanduser(icon_temp), icon_final)
            return
        if shortcut == "appmenu" and not shortcut_state:
            # Remove existing shortcut if it exists
            self.remove_shortcut(game, shortcut)
            if os.path.isfile(os.path.expanduser(icon_temp)):
                os.rename(os.path.expanduser(icon_temp), icon_final)
            return

        if os.path.isfile(os.path.expanduser(icon_temp)):
            os.rename(os.path.expanduser(icon_temp), icon_final)

        # Check if the icon file exists
        new_icon_path = f"{icons_dir}/{game.gameid}.ico"
        if not os.path.exists(new_icon_path):
            new_icon_path = faugus_png

        # Get the directory containing the executable
        game_directory = os.path.dirname(game.path)

        # Create a .desktop file
        if IS_FLATPAK:
            desktop_file_content = (
                f'[Desktop Entry]\n'
                f'Name={game.title}\n'
                f'Exec=flatpak run --command={faugus_run} io.github.Faugus.faugus-launcher --game {game.gameid}\n'
                f'Icon={new_icon_path}\n'
                f'Type=Application\n'
                f'Categories=Game;\n'
                f'Path={game_directory}\n'
            )
        else:
            desktop_file_content = (
                f'[Desktop Entry]\n'
                f'Name={game.title}\n'
                f'Exec={faugus_run} --game {game.gameid}\n'
                f'Icon={new_icon_path}\n'
                f'Type=Application\n'
                f'Categories=Game;\n'
                f'Path={game_directory}\n'
            )

        # Check if the destination directory exists and create if it doesn't
        if not os.path.exists(app_dir):
            os.makedirs(app_dir)

        if not os.path.exists(desktop_dir):
            os.makedirs(desktop_dir)

        if shortcut == "appmenu":
            with open(applications_shortcut_path, 'w') as appmenu_file:
                appmenu_file.write(desktop_file_content)
            os.chmod(applications_shortcut_path, 0o755)

        if shortcut == "desktop":
            with open(desktop_shortcut_path, 'w') as desktop_file:
                desktop_file.write(desktop_file_content)
            os.chmod(desktop_shortcut_path, 0o755)

    def add_steam_shortcut(self, game, steam_shortcut_state, icon_temp, icon_final):
        def add_game_to_steam(title, game_directory, icon):
            # Load existing shortcuts
            shortcuts = load_shortcuts(title)

            # Check if the game already exists
            existing_app_id = None
            for app_id, game_info in shortcuts["shortcuts"].items():
                if isinstance(game_info, dict) and "AppName" in game_info and game_info["AppName"] == title:
                    existing_app_id = app_id
                    break

            if existing_app_id:
                # Update only the necessary fields without replacing the entire entry
                game_info = shortcuts["shortcuts"][existing_app_id]
                if IS_FLATPAK:
                    if IS_STEAM_FLATPAK:
                        game_info["Exe"] = f'"flatpak-spawn"'
                        game_info["LaunchOptions"] = f'--host flatpak run --command=/app/bin/faugus-run io.github.Faugus.faugus-launcher --game {game.gameid}'
                    else:
                        game_info["Exe"] = f'"flatpak"'
                        game_info["LaunchOptions"] = f'run --command=/app/bin/faugus-run io.github.Faugus.faugus-launcher --game {game.gameid}'
                else:
                    game_info["Exe"] = f'"{faugus_run}"'
                    game_info["LaunchOptions"] = f'--game {game.gameid}'
                game_info["StartDir"] = game_directory
                game_info["icon"] = icon
            else:
                # Generate a new ID for the game
                new_app_id = max([int(k) for k in shortcuts["shortcuts"].keys() if k.isdigit()] or [0]) + 1

                # Add the new game
                if IS_FLATPAK:
                    if IS_STEAM_FLATPAK:
                        shortcuts["shortcuts"][str(new_app_id)] = {
                            "appid": new_app_id,
                            "AppName": title,
                            "Exe": f'"flatpak-spawn"',
                            "StartDir": game_directory,
                            "icon": icon,
                            "ShortcutPath": "",
                            "LaunchOptions": f'--host flatpak run --command=/app/bin/faugus-run io.github.Faugus.faugus-launcher --game {game.gameid}',
                            "IsHidden": 0,
                            "AllowDesktopConfig": 1,
                            "AllowOverlay": 1,
                            "OpenVR": 0,
                            "Devkit": 0,
                            "DevkitGameID": "",
                            "LastPlayTime": 0,
                            "FlatpakAppID": "",
                        }
                    else:
                        shortcuts["shortcuts"][str(new_app_id)] = {
                            "appid": new_app_id,
                            "AppName": title,
                            "Exe": f'"flatpak"',
                            "StartDir": game_directory,
                            "icon": icon,
                            "ShortcutPath": "",
                            "LaunchOptions": f'run --command=/app/bin/faugus-run io.github.Faugus.faugus-launcher --game {game.gameid}',
                            "IsHidden": 0,
                            "AllowDesktopConfig": 1,
                            "AllowOverlay": 1,
                            "OpenVR": 0,
                            "Devkit": 0,
                            "DevkitGameID": "",
                            "LastPlayTime": 0,
                            "FlatpakAppID": "",
                        }
                else:
                    shortcuts["shortcuts"][str(new_app_id)] = {
                        "appid": new_app_id,
                        "AppName": title,
                        "Exe": f'"{faugus_run}"',
                        "StartDir": game_directory,
                        "icon": icon,
                        "ShortcutPath": "",
                        "LaunchOptions": f'--game {game.gameid}',
                        "IsHidden": 0,
                        "AllowDesktopConfig": 1,
                        "AllowOverlay": 1,
                        "OpenVR": 0,
                        "Devkit": 0,
                        "DevkitGameID": "",
                        "LastPlayTime": 0,
                        "FlatpakAppID": "",
                    }

            # Save shortcuts back to the file
            save_shortcuts(shortcuts)

        def remove_shortcuts(shortcuts, title):
            # Find and remove existing shortcuts with the same title
            if os.path.exists(steam_shortcuts_path):
                to_remove = [app_id for app_id, game in shortcuts["shortcuts"].items() if
                             isinstance(game, dict) and "AppName" in game and game["AppName"] == title]
                for app_id in to_remove:
                    del shortcuts["shortcuts"][app_id]
                save_shortcuts(shortcuts)

        def load_shortcuts(title):
            # Check if the file exists
            if os.path.exists(steam_shortcuts_path):
                try:
                    # Attempt to load existing shortcuts
                    with open(steam_shortcuts_path, 'rb') as f:
                        return vdf.binary_load(f)
                except SyntaxError:
                    # If the file is corrupted, create a new one
                    return {"shortcuts": {}}
            else:
                # If the file does not exist, create a new one
                return {"shortcuts": {}}

        def save_shortcuts(shortcuts):
            if not os.path.exists(steam_shortcuts_path):
                open(steam_shortcuts_path, 'wb').close()

            with open(steam_shortcuts_path, 'wb') as f:
                vdf.binary_dump(shortcuts, f)

        # Check if the shortcut checkbox is checked
        if not steam_shortcut_state:
            # Remove existing shortcut if it exists
            shortcuts = load_shortcuts(game.title)
            remove_shortcuts(shortcuts, game.title)
            if os.path.isfile(os.path.expanduser(icon_temp)):
                os.rename(os.path.expanduser(icon_temp), icon_final)
            return

        if os.path.isfile(os.path.expanduser(icon_temp)):
            os.rename(os.path.expanduser(icon_temp), icon_final)

        # Check if the icon file exists
        new_icon_path = f"{icons_dir}/{game.gameid}.ico"
        if not os.path.exists(new_icon_path):
            new_icon_path = faugus_png

        # Get the directory containing the executable
        game_directory = os.path.dirname(game.path)

        add_game_to_steam(game.title, game_directory, new_icon_path)

    def update_preview(self, dialog):
        if file_path := dialog.get_preview_filename():
            try:
                # Create an image widget for the thumbnail
                pixbuf = GdkPixbuf.Pixbuf.new_from_file(file_path)

                # Resize the thumbnail if it's too large, maintaining the aspect ratio
                max_width = 400
                max_height = 400
                width = pixbuf.get_width()
                height = pixbuf.get_height()

                if width > max_width or height > max_height:
                    # Calculate the new width and height while maintaining the aspect ratio
                    ratio = min(max_width / width, max_height / height)
                    new_width = int(width * ratio)
                    new_height = int(height * ratio)
                    pixbuf = pixbuf.scale_simple(new_width, new_height, GdkPixbuf.InterpType.BILINEAR)

                image = Gtk.Image.new_from_pixbuf(pixbuf)
                dialog.set_preview_widget(image)
                dialog.set_preview_widget_active(True)
                dialog.get_preview_widget().set_size_request(max_width, max_height)
            except GLib.Error:
                dialog.set_preview_widget_active(False)
        else:
            dialog.set_preview_widget_active(False)

    def remove_banner(self, game):
        banner_file_path = f"{banners_dir}/{game.gameid}.png"
        if os.path.exists(banner_file_path):
            os.remove(banner_file_path)

    def remove_shortcut(self, game, shortcut):
        applications_shortcut_path = f"{app_dir}/{game.gameid}.desktop"
        desktop_shortcut_path = f"{desktop_dir}/{game.gameid}.desktop"
        if shortcut == "appmenu":
            if os.path.exists(applications_shortcut_path):
                os.remove(applications_shortcut_path)
        if shortcut == "desktop":
            if os.path.exists(desktop_shortcut_path):
                os.remove(desktop_shortcut_path)
        if shortcut == "both":
            if os.path.exists(applications_shortcut_path):
                os.remove(applications_shortcut_path)
            if os.path.exists(desktop_shortcut_path):
                os.remove(desktop_shortcut_path)

    def update_list(self):
        for child in self.flowbox.get_children():
            self.flowbox.remove(child)

        self.games.clear()
        self.load_games()
        self.entry_search.set_text("")
        self.show_all()
        if self.interface_mode != "List":
            if self.fullscreen_activated:
                self.fullscreen_activated = True
                self.grid_corner.set_visible(True)
                self.grid_left.set_margin_start(70)
            else:
                self.fullscreen_activated = False
                self.grid_corner.set_visible(False)
                self.grid_left.set_margin_start(0)

    def save_games(self):
        games_data = []
        for game in self.games:
            game_info = {"gameid": game.gameid, "title": game.title, "path": game.path, "prefix": game.prefix,
                "launch_arguments": game.launch_arguments, "game_arguments": game.game_arguments,
                "mangohud": "MANGOHUD=1" if game.mangohud else "", "gamemode": "gamemoderun" if game.gamemode else "",
                "disable_hidraw": "PROTON_DISABLE_HIDRAW=1" if game.disable_hidraw else "", "protonfix": game.protonfix,
                "runner": game.runner, "addapp_checkbox": "addapp_enabled" if game.addapp_checkbox else "",
                "addapp": game.addapp, "addapp_bat": game.addapp_bat, "banner": game.banner, "lossless": game.lossless, }
            games_data.append(game_info)

        with open("games.json", "w", encoding="utf-8") as file:
            json.dump(games_data, file, ensure_ascii=False, indent=4)

class Settings(Gtk.Dialog):
    def __init__(self, parent):
        # Initialize the Settings dialog
        super().__init__(title=_("Settings"), transient_for=parent, modal=True)
        self.set_resizable(False)
        self.set_icon_from_file(faugus_png)
        self.parent = parent

        css_provider = Gtk.CssProvider()
        css = """
        .entry {
            border-color: Red;
        }
        .paypal {
            color: white;
            background: #001C64;
        }
        .kofi {
            color: white;
            background: #1AC0FF;
        }
        """
        css_provider.load_from_data(css.encode('utf-8'))
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), css_provider,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_USER)

        self.LANG_NAMES = {
            "af": "Afrikaans",
            "am": "Amharic",
            "ar": "Arabic",
            "az": "Azerbaijani",
            "be": "Belarusian",
            "bg": "Bulgarian",
            "bn": "Bengali",
            "bs": "Bosnian",
            "ca": "Catalan",
            "cs": "Czech",
            "cy": "Welsh",
            "da": "Danish",
            "de": "German",
            "el": "Greek",
            "en_US": "English",
            "eo": "Esperanto",
            "es": "Spanish",
            "et": "Estonian",
            "eu": "Basque",
            "fa": "Persian",
            "fi": "Finnish",
            "fil": "Filipino",
            "fr": "French",
            "ga": "Irish",
            "gl": "Galician",
            "gu": "Gujarati",
            "he": "Hebrew",
            "hi": "Hindi",
            "hr": "Croatian",
            "ht": "Haitian Creole",
            "hu": "Hungarian",
            "hy": "Armenian",
            "id": "Indonesian",
            "is": "Icelandic",
            "it": "Italian",
            "ja": "Japanese",
            "jv": "Javanese",
            "ka": "Georgian",
            "kk": "Kazakh",
            "km": "Khmer",
            "kn": "Kannada",
            "ko": "Korean",
            "ku": "Kurdish (Kurmanji)",
            "ky": "Kyrgyz",
            "lo": "Lao",
            "lt": "Lithuanian",
            "lv": "Latvian",
            "mg": "Malagasy",
            "mi": "Maori",
            "mk": "Macedonian",
            "ml": "Malayalam",
            "mn": "Mongolian",
            "mr": "Marathi",
            "ms": "Malay",
            "mt": "Maltese",
            "my": "Burmese",
            "nb": "Norwegian (Bokmål)",
            "ne": "Nepali",
            "nl": "Dutch",
            "nn": "Norwegian (Nynorsk)",
            "pa": "Punjabi",
            "pl": "Polish",
            "ps": "Pashto",
            "pt": "Portuguese (Portugal)",
            "pt_BR": "Portuguese (Brazil)",
            "ro": "Romanian",
            "ru": "Russian",
            "sd": "Sindhi",
            "si": "Sinhala",
            "sk": "Slovak",
            "sl": "Slovenian",
            "so": "Somali",
            "sq": "Albanian",
            "sr": "Serbian",
            "sv": "Swedish",
            "sw": "Swahili",
            "ta": "Tamil",
            "te": "Telugu",
            "tg": "Tajik",
            "th": "Thai",
            "tk": "Turkmen",
            "tl": "Tagalog",
            "tr": "Turkish",
            "tt": "Tatar",
            "ug": "Uyghur",
            "uk": "Ukrainian",
            "ur": "Urdu",
            "uz": "Uzbek",
            "vi": "Vietnamese",
            "xh": "Xhosa",
            "yi": "Yiddish",
            "zh_CN": "Chinese (Simplified)",
            "zh_TW": "Chinese (Traditional)",
            "zu": "Zulu",
        }

        self.lang_codes = {}

        # Widgets for Interface mode
        self.label_language = Gtk.Label(label=_("Language"))
        self.label_language.set_halign(Gtk.Align.START)
        self.combobox_language = Gtk.ComboBoxText()

        # Widgets for Interface mode
        self.label_interface = Gtk.Label(label=_("Interface Mode"))
        self.label_interface.set_halign(Gtk.Align.START)
        self.combobox_interface = Gtk.ComboBoxText()
        self.combobox_interface.connect("changed", self.on_combobox_interface_changed)
        self.combobox_interface.append_text("List")
        self.combobox_interface.append_text("Blocks")
        self.combobox_interface.append_text("Banners")

        # Create checkbox for 'Start maximized' option
        self.checkbox_start_maximized = Gtk.CheckButton(label=_("Start maximized"))
        self.checkbox_start_maximized.set_active(False)
        self.checkbox_start_maximized.connect("toggled", self.on_checkbox_toggled, "maximized")

        # Create checkbox for 'Start fullscreen' option
        self.checkbox_start_fullscreen = Gtk.CheckButton(label=_("Start in fullscreen"))
        self.checkbox_start_fullscreen.set_active(False)
        self.checkbox_start_fullscreen.connect("toggled", self.on_checkbox_toggled, "fullscreen")
        self.checkbox_start_fullscreen.set_tooltip_text(_("Alt+Enter toggles fullscreen"))

        self.checkbox_show_labels = Gtk.CheckButton(label=_("Show labels"))
        self.checkbox_show_labels.set_active(False)

        self.checkbox_smaller_banners = Gtk.CheckButton(label=_("Smaller banners"))
        self.checkbox_smaller_banners.set_active(False)

        # Widgets for prefix
        self.label_default_prefix = Gtk.Label(label=_("Default Prefixes Location"))
        self.label_default_prefix.set_halign(Gtk.Align.START)

        self.entry_default_prefix = Gtk.Entry()
        self.entry_default_prefix.set_tooltip_text(_("/path/to/the/prefix"))
        self.entry_default_prefix.set_has_tooltip(True)
        self.entry_default_prefix.connect("query-tooltip", self.on_entry_query_tooltip)
        self.entry_default_prefix.connect("changed", self.on_entry_changed, self.entry_default_prefix)

        self.button_search_prefix = Gtk.Button()
        self.button_search_prefix.set_image(Gtk.Image.new_from_icon_name("system-search-symbolic", Gtk.IconSize.BUTTON))
        self.button_search_prefix.connect("clicked", self.on_button_search_prefix_clicked)
        self.button_search_prefix.set_size_request(50, -1)

        self.label_lossless = Gtk.Label(label=_("Lossless Scaling Location"))
        self.label_lossless.set_halign(Gtk.Align.START)

        self.entry_lossless = Gtk.Entry()
        self.entry_lossless.set_tooltip_text(_("/path/to/Lossless.dll"))
        self.entry_lossless.set_has_tooltip(True)
        self.entry_lossless.connect("query-tooltip", self.on_entry_query_tooltip)

        self.button_search_lossless = Gtk.Button()
        self.button_search_lossless.set_image(Gtk.Image.new_from_icon_name("system-search-symbolic", Gtk.IconSize.BUTTON))
        self.button_search_lossless.connect("clicked", self.on_button_search_lossless_clicked)
        self.button_search_lossless.set_size_request(50, -1)

        self.label_default_prefix_tools = Gtk.Label(label=_("Default Prefix Tools"))
        self.label_default_prefix_tools.set_halign(Gtk.Align.START)
        self.label_default_prefix_tools.set_margin_start(10)
        self.label_default_prefix_tools.set_margin_end(10)
        self.label_default_prefix_tools.set_margin_top(10)

        # Widgets for runner
        self.label_runner = Gtk.Label(label=_("Default Proton"))
        self.label_runner.set_halign(Gtk.Align.START)
        self.combobox_runner = Gtk.ComboBoxText()

        self.button_proton_manager = Gtk.Button(label=_("Proton Manager"))
        self.button_proton_manager.connect("clicked", self.on_button_proton_manager_clicked)

        self.label_miscellaneous = Gtk.Label(label=_("Miscellaneous"))
        self.label_miscellaneous.set_halign(Gtk.Align.START)
        self.label_miscellaneous.set_margin_start(10)
        self.label_miscellaneous.set_margin_end(10)
        self.label_miscellaneous.set_margin_top(10)

        # Create checkbox for 'Use discrete GPU' option
        self.checkbox_discrete_gpu = Gtk.CheckButton(label=_("Use discrete GPU"))
        self.checkbox_discrete_gpu.set_active(False)

        # Create checkbox for 'Close after launch' option
        self.checkbox_close_after_launch = Gtk.CheckButton(label=_("Close when running a game/app"))
        self.checkbox_close_after_launch.set_active(False)

        # Create checkbox for 'System tray' option
        self.checkbox_system_tray = Gtk.CheckButton(label=_("System tray icon"))
        self.checkbox_system_tray.set_active(False)
        self.checkbox_system_tray.connect("toggled", self.on_checkbox_system_tray_toggled)

        # Create checkbox for 'Start on boot' option
        self.checkbox_start_boot = Gtk.CheckButton(label=_("Start on boot"))
        self.checkbox_start_boot.set_active(False)
        self.checkbox_start_boot.set_sensitive(False)

        self.checkbox_mono_icon = Gtk.CheckButton(label=_("Monochrome icon"))
        self.checkbox_mono_icon.set_active(False)
        self.checkbox_mono_icon.set_sensitive(False)

        # Create checkbox for 'Splash screen' option
        self.checkbox_splash_disable = Gtk.CheckButton(label=_("Disable splash window"))
        self.checkbox_splash_disable.set_active(False)

        # Create checkbox for 'Enable logging' option
        self.checkbox_enable_logging = Gtk.CheckButton(label=_("Enable logging"))
        self.checkbox_enable_logging.set_active(False)

        self.checkbox_wayland_driver = Gtk.CheckButton(label=_("Use Wayland driver (experimental)"))
        self.checkbox_wayland_driver.set_active(False)
        self.checkbox_wayland_driver.set_tooltip_text(_("Only works with GE-Proton10 or Proton-EM-10."))
        self.checkbox_wayland_driver.connect("toggled", self.on_checkbox_wayland_driver_toggled)

        self.checkbox_enable_hdr = Gtk.CheckButton(label=_("Enable HDR (experimental)"))
        self.checkbox_enable_hdr.set_active(False)
        self.checkbox_enable_hdr.set_tooltip_text(_("Only works with GE-Proton10 or Proton-EM-10."))

        self.checkbox_enable_ntsync = Gtk.CheckButton(label=_("Enable NTsync (experimental)"))
        self.checkbox_enable_ntsync.set_active(False)
        self.checkbox_enable_ntsync.set_tooltip_text(_("Only works with GE-Proton10-9 or superior and Proton-EM-10-24 or superior."))

        self.checkbox_enable_wow64 = Gtk.CheckButton(label=_("Enable WOW64 (experimental)"))
        self.checkbox_enable_wow64.set_active(False)
        self.checkbox_enable_wow64.set_tooltip_text(_("Only works with GE-Proton10-9 or superior and Proton-EM-10-24 or superior."))

        # Button Winetricks
        self.button_winetricks_default = Gtk.Button(label="Winetricks")
        self.button_winetricks_default.connect("clicked", self.on_button_winetricks_default_clicked)
        self.button_winetricks_default.set_size_request(120, -1)

        # Button Winecfg
        self.button_winecfg_default = Gtk.Button(label="Winecfg")
        self.button_winecfg_default.connect("clicked", self.on_button_winecfg_default_clicked)
        self.button_winecfg_default.set_size_request(120, -1)

        # Button for Run
        self.button_run_default = Gtk.Button(label=_("Run"))
        self.button_run_default.set_size_request(120, -1)
        self.button_run_default.connect("clicked", self.on_button_run_default_clicked)
        self.button_run_default.set_tooltip_text(_("Run a file inside the prefix"))

        # Checkboxes for optional features
        self.checkbox_mangohud = Gtk.CheckButton(label="MangoHud")
        self.checkbox_mangohud.set_tooltip_text(
            _("Shows an overlay for monitoring FPS, temperatures, CPU/GPU load and more."))
        self.checkbox_gamemode = Gtk.CheckButton(label="GameMode")
        self.checkbox_gamemode.set_tooltip_text(_("Tweaks your system to improve performance."))
        self.checkbox_disable_hidraw = Gtk.CheckButton(label=_("Disable Hidraw"))
        self.checkbox_disable_hidraw.set_tooltip_text(
            _("May fix controller issues with some games. Only works with GE-Proton10 or Proton-EM-10."))

        self.label_support = Gtk.Label(label=_("Support the Project"))
        self.label_support.set_halign(Gtk.Align.START)
        self.label_support.set_margin_start(10)
        self.label_support.set_margin_end(10)
        self.label_support.set_margin_top(10)

        button_kofi = Gtk.Button(label="Ko-fi")
        button_kofi.connect("clicked", self.on_button_kofi_clicked)
        button_kofi.get_style_context().add_class("kofi")

        button_paypal = Gtk.Button(label="PayPal")
        button_paypal.connect("clicked", self.on_button_paypal_clicked)
        button_paypal.get_style_context().add_class("paypal")

        # Button Cancel
        self.button_cancel = Gtk.Button(label=_("Cancel"))
        self.button_cancel.connect("clicked", lambda widget: self.response(Gtk.ResponseType.CANCEL))
        self.button_cancel.set_size_request(150, -1)

        # Button Ok
        self.button_ok = Gtk.Button(label=_("Ok"))
        self.button_ok.connect("clicked", lambda widget: self.response(Gtk.ResponseType.OK))
        self.button_ok.set_size_request(150, -1)

        self.label_settings = Gtk.Label(label=_("Backup/Restore Settings"))
        self.label_settings.set_halign(Gtk.Align.START)
        self.label_settings.set_margin_start(10)
        self.label_settings.set_margin_end(10)
        self.label_settings.set_margin_top(10)

        # Button Backup
        button_backup = Gtk.Button(label=_("Backup"))
        button_backup.connect("clicked", self.on_button_backup_clicked)

        # Button Restore
        button_restore = Gtk.Button(label=_("Restore"))
        button_restore.connect("clicked", self.on_button_restore_clicked)

        self.label_envar = Gtk.Label(label=_("Global Environment Variables"))
        self.label_envar.set_halign(Gtk.Align.START)

        self.liststore = Gtk.ListStore(str)
        self.liststore.append([""])

        treeview = Gtk.TreeView(model=self.liststore)
        treeview.set_has_tooltip(True)
        treeview.connect("query-tooltip", self.on_query_tooltip)

        renderer = Gtk.CellRendererText()
        renderer.set_property("editable", True)
        renderer.set_property("ellipsize", 3)
        renderer.connect("edited", self.on_cell_edited, 0)

        column = Gtk.TreeViewColumn("", renderer, text=0)
        treeview.set_headers_visible(False)

        treeview.append_column(column)

        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled_window.set_min_content_height(130)
        scrolled_window.add(treeview)

        self.box = self.get_content_area()
        self.box.set_margin_start(0)
        self.box.set_margin_end(0)
        self.box.set_margin_top(0)
        self.box.set_margin_bottom(0)
        self.box.set_halign(Gtk.Align.CENTER)
        self.box.set_valign(Gtk.Align.CENTER)
        self.box.set_vexpand(True)
        self.box.set_hexpand(True)

        frame = Gtk.Frame()
        frame.set_margin_start(10)
        frame.set_margin_end(10)
        frame.set_margin_top(10)
        frame.set_margin_bottom(10)

        box_main = Gtk.Grid()
        box_main.set_column_homogeneous(True)
        box_main.set_column_spacing(10)
        box_left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box_mid = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box_right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        grid_language = Gtk.Grid()
        grid_language.set_row_spacing(10)
        grid_language.set_column_spacing(10)
        grid_language.set_margin_start(10)
        grid_language.set_margin_end(10)
        grid_language.set_margin_top(10)
        grid_language.set_margin_bottom(10)

        grid_prefix = Gtk.Grid()
        grid_prefix.set_row_spacing(10)
        grid_prefix.set_column_spacing(10)
        grid_prefix.set_margin_start(10)
        grid_prefix.set_margin_end(10)
        grid_prefix.set_margin_top(10)
        grid_prefix.set_margin_bottom(10)

        grid_runner = Gtk.Grid()
        grid_runner.set_row_spacing(10)
        grid_runner.set_column_spacing(10)
        grid_runner.set_margin_start(10)
        grid_runner.set_margin_end(10)
        grid_runner.set_margin_top(10)
        grid_runner.set_margin_bottom(10)

        grid_lossless = Gtk.Grid()
        grid_lossless.set_row_spacing(10)
        grid_lossless.set_column_spacing(10)
        grid_lossless.set_margin_start(10)
        grid_lossless.set_margin_end(10)
        grid_lossless.set_margin_top(10)
        grid_lossless.set_margin_bottom(10)

        grid_tools = Gtk.Grid()
        grid_tools.set_row_spacing(10)
        grid_tools.set_column_spacing(10)
        grid_tools.set_margin_start(10)
        grid_tools.set_margin_end(10)
        grid_tools.set_margin_top(10)
        grid_tools.set_margin_bottom(10)

        grid_miscellaneous = Gtk.Grid()
        grid_miscellaneous.set_row_spacing(10)
        grid_miscellaneous.set_column_spacing(10)
        grid_miscellaneous.set_margin_start(10)
        grid_miscellaneous.set_margin_end(10)
        grid_miscellaneous.set_margin_top(10)
        grid_miscellaneous.set_margin_bottom(10)

        grid_envar = Gtk.Grid()
        grid_envar.set_row_spacing(10)
        grid_envar.set_column_spacing(10)
        grid_envar.set_margin_start(10)
        grid_envar.set_margin_end(10)
        grid_envar.set_margin_top(10)
        grid_envar.set_margin_bottom(10)

        grid_interface_mode = Gtk.Grid()
        grid_interface_mode.set_row_spacing(10)
        grid_interface_mode.set_column_spacing(10)
        grid_interface_mode.set_margin_start(10)
        grid_interface_mode.set_margin_end(10)
        grid_interface_mode.set_margin_top(10)
        grid_interface_mode.set_margin_bottom(10)

        grid_support = Gtk.Grid()
        grid_support.set_column_homogeneous(True)
        grid_support.set_row_spacing(10)
        grid_support.set_column_spacing(10)
        grid_support.set_margin_start(10)
        grid_support.set_margin_end(10)
        grid_support.set_margin_top(10)
        grid_support.set_margin_bottom(10)

        grid_backup = Gtk.Grid()
        grid_backup.set_column_homogeneous(True)
        grid_backup.set_row_spacing(10)
        grid_backup.set_column_spacing(10)
        grid_backup.set_margin_start(10)
        grid_backup.set_margin_end(10)
        grid_backup.set_margin_top(10)
        grid_backup.set_margin_bottom(10)

        self.grid_big_interface = Gtk.Grid()
        self.grid_big_interface.set_row_spacing(10)
        self.grid_big_interface.set_column_spacing(10)
        self.grid_big_interface.set_margin_start(10)
        self.grid_big_interface.set_margin_end(10)
        self.grid_big_interface.set_margin_bottom(10)

        grid_language.attach(self.label_language, 0, 0, 1, 1)
        grid_language.attach(self.combobox_language, 0, 1, 1, 1)
        self.combobox_language.set_hexpand(True)

        grid_prefix.attach(self.label_default_prefix, 0, 0, 1, 1)
        grid_prefix.attach(self.entry_default_prefix, 0, 1, 3, 1)
        self.entry_default_prefix.set_hexpand(True)
        grid_prefix.attach(self.button_search_prefix, 3, 1, 1, 1)

        grid_runner.attach(self.label_runner, 0, 6, 1, 1)
        grid_runner.attach(self.combobox_runner, 0, 7, 1, 1)
        grid_runner.attach(self.button_proton_manager, 0, 8, 1, 1)

        grid_lossless.attach(self.label_lossless, 0, 0, 1, 1)
        grid_lossless.attach(self.entry_lossless, 0, 1, 3, 1)
        self.entry_default_prefix.set_hexpand(True)
        grid_lossless.attach(self.button_search_lossless, 3, 1, 1, 1)

        self.combobox_runner.set_hexpand(True)
        self.button_proton_manager.set_hexpand(True)
        self.entry_lossless.set_hexpand(True)

        grid_tools.attach(self.checkbox_mangohud, 0, 0, 1, 1)
        self.checkbox_mangohud.set_hexpand(True)
        grid_tools.attach(self.checkbox_gamemode, 0, 1, 1, 1)
        grid_tools.attach(self.checkbox_disable_hidraw, 0, 2, 1, 1)
        grid_tools.attach(self.button_winetricks_default, 1, 0, 1, 1)
        grid_tools.attach(self.button_winecfg_default, 1, 1, 1, 1)
        grid_tools.attach(self.button_run_default, 1, 2, 1, 1)

        grid_miscellaneous.attach(self.checkbox_discrete_gpu, 0, 2, 1, 1)
        grid_miscellaneous.attach(self.checkbox_splash_disable, 0, 3, 1, 1)
        grid_miscellaneous.attach(self.checkbox_system_tray, 0, 4, 1, 1)
        grid_miscellaneous.attach(self.checkbox_start_boot, 0, 5, 1, 1)
        grid_miscellaneous.attach(self.checkbox_mono_icon, 0, 6, 1, 1)
        grid_miscellaneous.attach(self.checkbox_close_after_launch, 0, 7, 1, 1)
        grid_miscellaneous.attach(self.checkbox_enable_logging, 0, 8, 1, 1)
        grid_miscellaneous.attach(self.checkbox_wayland_driver, 0, 9, 1, 1)
        grid_miscellaneous.attach(self.checkbox_enable_hdr, 0, 10, 1, 1)
        grid_miscellaneous.attach(self.checkbox_enable_ntsync, 0, 11, 1, 1)
        grid_miscellaneous.attach(self.checkbox_enable_wow64, 0, 12, 1, 1)

        grid_interface_mode.attach(self.label_interface, 0, 0, 1, 1)
        grid_interface_mode.attach(self.combobox_interface, 0, 1, 1, 1)
        self.combobox_interface.set_hexpand(True)

        grid_envar.attach(self.label_envar, 0, 0, 1, 1)
        grid_envar.attach(scrolled_window, 0, 1, 1, 1)
        scrolled_window.set_hexpand(True)

        grid_backup.attach(button_backup, 0, 1, 1, 1)
        grid_backup.attach(button_restore, 1, 1, 1, 1)

        self.grid_big_interface.attach(self.checkbox_start_maximized, 0, 0, 1, 1)
        self.grid_big_interface.attach(self.checkbox_start_fullscreen, 0, 1, 1, 1)
        self.grid_big_interface.attach(self.checkbox_show_labels, 0, 2, 1, 1)
        self.grid_big_interface.attach(self.checkbox_smaller_banners, 0, 3, 1, 1)

        grid_support.attach(button_kofi, 0, 1, 1, 1)
        grid_support.attach(button_paypal, 1, 1, 1, 1)

        box_left.pack_start(grid_prefix, False, False, 0)
        box_left.pack_start(grid_runner, False, False, 0)
        box_left.pack_start(self.label_default_prefix_tools, False, False, 0)
        box_left.pack_start(grid_tools, False, False, 0)
        box_left.pack_start(grid_lossless, False, False, 0)
        box_left.pack_end(grid_language, False, False, 0)

        box_mid.pack_start(self.label_miscellaneous, False, False, 0)
        box_mid.pack_start(grid_miscellaneous, False, False, 0)
        box_mid.pack_end(grid_support, False, False, 0)
        box_mid.pack_end(self.label_support, False, False, 0)

        box_right.pack_start(grid_envar, False, False, 0)
        box_right.pack_start(grid_interface_mode, False, False, 0)
        box_right.pack_start(self.grid_big_interface, False, False, 0)
        box_right.pack_end(grid_backup, False, False, 0)
        box_right.pack_end(self.label_settings, False, False, 0)

        box_main.attach(box_left, 0, 0, 1, 1)
        box_main.attach(box_mid, 1, 0, 1, 1)
        box_main.attach(box_right, 2, 0, 1, 1)
        box_left.set_hexpand(True)
        box_mid.set_hexpand(True)
        frame.add(box_main)

        box_bottom = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box_bottom.set_margin_start(10)
        box_bottom.set_margin_end(10)
        box_bottom.set_margin_bottom(10)
        self.button_cancel.set_hexpand(True)
        self.button_ok.set_hexpand(True)

        box_bottom.pack_start(self.button_cancel, True, True, 0)
        box_bottom.pack_start(self.button_ok, True, True, 0)

        self.box.add(frame)
        self.box.add(box_bottom)

        self.populate_combobox_with_runners()
        self.populate_languages()
        self.load_config()

        self.show_all()
        self.on_combobox_interface_changed(self.combobox_interface)

        # Check if optional features are available and enable/disable accordingly
        self.mangohud_enabled = os.path.exists(mangohud_dir)
        if not self.mangohud_enabled:
            self.checkbox_mangohud.set_sensitive(False)
            self.checkbox_mangohud.set_active(False)
            self.checkbox_mangohud.set_tooltip_text(
                _("Shows an overlay for monitoring FPS, temperatures, CPU/GPU load and more. NOT INSTALLED."))

        self.gamemode_enabled = os.path.exists(gamemoderun) or os.path.exists("/usr/games/gamemoderun")
        if not self.gamemode_enabled:
            self.checkbox_gamemode.set_sensitive(False)
            self.checkbox_gamemode.set_active(False)
            self.checkbox_gamemode.set_tooltip_text(_("Tweaks your system to improve performance. NOT INSTALLED."))

    def on_query_tooltip(self, widget, x, y, keyboard_mode, tooltip):
        result = widget.get_path_at_pos(x, y)
        if result is not None:
            path, column, cell_x, cell_y = result
            tree_iter = self.liststore.get_iter(path)
            value = self.liststore.get_value(tree_iter, 0)
            if value.strip():
                tooltip.set_text(value)
                return True
        return False

    def on_cell_edited(self, widget, path, text, column_index):
        self.liststore[path][column_index] = text
        self.adjust_rows()

    def adjust_rows(self):
        filled_rows = [row[0] for row in self.liststore if row[0].strip() != ""]
        self.liststore.clear()

        for value in filled_rows:
            self.liststore.append([value])

        self.liststore.append([""])

    def populate_languages(self):
        self.combobox_language.remove_all()
        self.combobox_language.append_text("English")

        if not os.path.isdir(LOCALE_DIR):
            return

        for lang in sorted(os.listdir(LOCALE_DIR)):
            mo_file = os.path.join(LOCALE_DIR, lang, "LC_MESSAGES", "faugus-launcher.mo")
            if os.path.isfile(mo_file):
                lang_name = self.LANG_NAMES.get(lang, lang)
                self.combobox_language.append_text(lang_name)
                self.lang_codes[lang_name] = lang

        self.combobox_language.set_active(0)

    def on_entry_query_tooltip(self, widget, x, y, keyboard_mode, tooltip):
        current_text = widget.get_text()
        if current_text.strip():
            tooltip.set_text(current_text)
        else:
            tooltip.set_text(widget.get_tooltip_text())
        return True

    def on_checkbox_toggled(self, checkbox, option):
        if checkbox.get_active():
            if option == "maximized":
                self.checkbox_start_fullscreen.set_active(False)
            elif option == "fullscreen":
                self.checkbox_start_maximized.set_active(False)

    def on_combobox_interface_changed(self, combobox):
        active_index = combobox.get_active()
        if active_index == 0:
            self.grid_big_interface.set_visible(False)
        if active_index == 1:
            self.grid_big_interface.set_visible(True)
            self.checkbox_show_labels.set_visible(False)
            self.checkbox_smaller_banners.set_visible(False)
        if active_index == 2:
            self.grid_big_interface.set_visible(True)
            self.checkbox_show_labels.set_visible(True)
            self.checkbox_smaller_banners.set_visible(True)

    def on_checkbox_system_tray_toggled(self, widget):
        if not widget.get_active():
            self.checkbox_start_boot.set_active(False)
            self.checkbox_start_boot.set_sensitive(False)
            self.checkbox_mono_icon.set_active(False)
            self.checkbox_mono_icon.set_sensitive(False)
        else:
            self.checkbox_start_boot.set_sensitive(True)
            self.checkbox_mono_icon.set_sensitive(True)

    def on_checkbox_wayland_driver_toggled(self, widget):
        if not widget.get_active():
            self.checkbox_enable_hdr.set_active(False)
            self.checkbox_enable_hdr.set_sensitive(False)
        else:
            self.checkbox_enable_hdr.set_sensitive(True)

    def populate_combobox_with_runners(self):
        # List of default entries
        self.combobox_runner.append_text("GE-Proton Latest (default)")
        self.combobox_runner.append_text("UMU-Proton Latest")
        self.combobox_runner.append_text("Proton-EM Latest")

        # Path to the directory containing the folders
        if IS_FLATPAK:
            runner_path = Path(os.path.expanduser("~/.local/share/Steam/compatibilitytools.d"))
        else:
            runner_path = f'{share_dir}/Steam/compatibilitytools.d/'

        try:
            # Check if the directory exists
            if os.path.exists(runner_path):
                # List to hold version directories
                versions = []
                # Iterate over the folders in the directory
                for entry in os.listdir(runner_path):
                    entry_path = os.path.join(runner_path, entry)
                    # Add to list only if it's a directory and not "UMU-Latest"
                    if os.path.isdir(entry_path) and entry != "UMU-Latest" and entry != "LegacyRuntime":
                        versions.append(entry)

                # Sort versions in descending order
                def version_key(v):
                    # Remove 'GE-Proton' and split the remaining part into segments of digits and non-digits
                    v_parts = re.split(r'(\d+)', v.replace('GE-Proton', ''))
                    # Convert numeric parts to integers for proper sorting
                    return [int(part) if part.isdigit() else part for part in v_parts]

                versions.sort(key=version_key, reverse=True)

                # Add sorted versions to ComboBox
                for version in versions:
                    self.combobox_runner.append_text(version)

        except Exception as e:
            print(f"Error accessing the directory: {e}")

        # Set the active item, if desired
        self.combobox_runner.set_active(0)

        cell_renderer = self.combobox_runner.get_cells()[0]
        cell_renderer.set_property("ellipsize", Pango.EllipsizeMode.END)
        cell_renderer.set_property("max-width-chars", 20)

    def on_entry_changed(self, widget, entry):
        if entry.get_text():
            entry.get_style_context().remove_class("entry")

    def update_config_file(self):
        combobox_language = self.combobox_language.get_active_text()
        entry_default_prefix = self.entry_default_prefix.get_text()
        combobox_default_runner = self.get_default_runner()
        entry_lossless = self.entry_lossless.get_text()
        checkbox_mangohud = self.checkbox_mangohud.get_active()
        checkbox_gamemode = self.checkbox_gamemode.get_active()
        checkbox_disable_hidraw = self.checkbox_disable_hidraw.get_active()
        checkbox_discrete_gpu_state = self.checkbox_discrete_gpu.get_active()
        checkbox_splash_disable = self.checkbox_splash_disable.get_active()
        checkbox_system_tray = self.checkbox_system_tray.get_active()
        checkbox_start_boot = self.checkbox_start_boot.get_active()
        checkbox_mono_icon = self.checkbox_mono_icon.get_active()
        checkbox_close_after_launcher = self.checkbox_close_after_launch.get_active()
        checkbox_enable_logging = self.checkbox_enable_logging.get_active()
        checkbox_wayland_driver = self.checkbox_wayland_driver.get_active()
        checkbox_enable_hdr = self.checkbox_enable_hdr.get_active()
        checkbox_enable_ntsync = self.checkbox_enable_ntsync.get_active()
        checkbox_enable_wow64 = self.checkbox_enable_wow64.get_active()
        combobox_interface = self.combobox_interface.get_active_text()
        checkbox_start_maximized = self.checkbox_start_maximized.get_active()
        checkbox_start_fullscreen = self.checkbox_start_fullscreen.get_active()
        checkbox_show_labels = self.checkbox_show_labels.get_active()
        checkbox_smaller_banners = self.checkbox_smaller_banners.get_active()

        language = self.lang_codes.get(combobox_language, "en_US")

        config = ConfigManager()
        config.save_with_values(
            checkbox_close_after_launcher,
            entry_default_prefix,
            checkbox_mangohud,
            checkbox_gamemode,
            checkbox_disable_hidraw,
            combobox_default_runner,
            entry_lossless,
            checkbox_discrete_gpu_state,
            checkbox_splash_disable,
            checkbox_system_tray,
            checkbox_start_boot,
            checkbox_mono_icon,
            combobox_interface,
            checkbox_start_maximized,
            checkbox_start_fullscreen,
            checkbox_show_labels,
            checkbox_smaller_banners,
            checkbox_enable_logging,
            checkbox_wayland_driver,
            checkbox_enable_hdr,
            checkbox_enable_ntsync,
            checkbox_enable_wow64,
            language
        )

        self.set_sensitive(False)

    def get_default_runner(self):
        default_runner = self.combobox_runner.get_active_text()

        if default_runner == "UMU-Proton Latest":
            default_runner = ""
        if default_runner == "GE-Proton Latest (default)":
            default_runner = "GE-Proton"
        if default_runner == "Proton-EM Latest":
            default_runner = "Proton-EM"
        return default_runner

    def update_system_tray(self):
        checkbox_system_tray = self.checkbox_system_tray.get_active()

        if checkbox_system_tray:
            self.parent.indicator.set_status(AyatanaAppIndicator3.IndicatorStatus.ACTIVE)
            if not hasattr(self, "window_delete_event_connected") or not self.window_delete_event_connected:
                self.connect("delete-event", self.parent.on_window_delete_event)
                self.parent.window_delete_event_connected = True
            self.parent.indicator.set_menu(self.parent.create_tray_menu())
        else:
            self.parent.indicator.set_status(AyatanaAppIndicator3.IndicatorStatus.PASSIVE)
            if hasattr(self, "window_delete_event_connected") and self.window_delete_event_connected:
                self.disconnect_by_func(self.parent.on_window_delete_event)
                self.parent.window_delete_event_connected = False

    def update_envar_file(self):
        if hasattr(self, "liststore"):
            values = [row[0] for row in self.liststore if row[0].strip() != ""]
            with open(envar_dir, "w", encoding="utf-8") as f:
                for val in values:
                    f.write(val + "\n")

    def on_button_proton_manager_clicked(self, widget):
        if self.entry_default_prefix.get_text() == "":
            self.entry_default_prefix.get_style_context().add_class("entry")
        else:
            self.update_envar_file()
            self.update_config_file()
            proton_manager = faugus_proton_manager
            self.update_system_tray()

            def run_command():
                process = subprocess.Popen([sys.executable, proton_manager])
                process.wait()
                GLib.idle_add(self.set_sensitive, True)
                GLib.idle_add(self.parent.set_sensitive, True)
                GLib.idle_add(self.blocking_window.destroy)

                GLib.idle_add(lambda: self.combobox_runner.remove_all())
                GLib.idle_add(self.populate_combobox_with_runners)
                GLib.idle_add(lambda: self.load_config())

            self.blocking_window = Gtk.Window()
            self.blocking_window.set_transient_for(self.parent)
            self.blocking_window.set_decorated(False)
            self.blocking_window.set_modal(True)

            command_thread = threading.Thread(target=run_command)
            command_thread.start()

    def on_button_winetricks_default_clicked(self, widget):
        if self.entry_default_prefix.get_text() == "":
            self.entry_default_prefix.get_style_context().add_class("entry")
        else:
            self.update_envar_file()
            self.update_config_file()
            self.parent.manage_autostart_file(self.checkbox_start_boot.get_active())
            default_runner = self.get_default_runner()
            self.update_system_tray()
            command_parts = []

            # Add command parts if they are not empty
            command_parts.append(f'FAUGUS_LOG=default')
            command_parts.append(f'GAMEID=winetricks-gui')
            command_parts.append(f'STORE=none')
            if default_runner:
                command_parts.append(f'PROTONPATH={default_runner}')

            # Add the fixed command and remaining arguments
            command_parts.append(f'"{umu_run}"')
            command_parts.append('""')

            # Join all parts into a single command
            command = ' '.join(command_parts)

            print(command)

            # faugus-run path
            faugus_run_path = faugus_run

            def run_command():
                process = subprocess.Popen([sys.executable, faugus_run_path, command, "winetricks"])
                process.wait()
                GLib.idle_add(self.set_sensitive, True)
                GLib.idle_add(self.parent.set_sensitive, True)
                GLib.idle_add(self.blocking_window.destroy)

            self.blocking_window = Gtk.Window()
            self.blocking_window.set_transient_for(self.parent)
            self.blocking_window.set_decorated(False)
            self.blocking_window.set_modal(True)

            command_thread = threading.Thread(target=run_command)
            command_thread.start()

    def on_button_winecfg_default_clicked(self, widget):
        if self.entry_default_prefix.get_text() == "":
            self.entry_default_prefix.get_style_context().add_class("entry")
        else:
            self.update_envar_file()
            self.update_config_file()
            self.parent.manage_autostart_file(self.checkbox_start_boot.get_active())
            default_runner = self.get_default_runner()
            self.update_system_tray()
            command_parts = []

            # Add command parts if they are not empty
            command_parts.append(f'FAUGUS_LOG=default')
            command_parts.append(f'GAMEID=default')
            if default_runner:
                command_parts.append(f'PROTONPATH={default_runner}')

            # Add the fixed command and remaining arguments
            command_parts.append(f'"{umu_run}"')
            command_parts.append('"winecfg"')

            # Join all parts into a single command
            command = ' '.join(command_parts)

            print(command)

            # faugus-run path
            faugus_run_path = faugus_run

            def run_command():
                process = subprocess.Popen([sys.executable, faugus_run_path, command])
                process.wait()
                GLib.idle_add(self.set_sensitive, True)
                GLib.idle_add(self.parent.set_sensitive, True)
                GLib.idle_add(self.blocking_window.destroy)

            self.blocking_window = Gtk.Window()
            self.blocking_window.set_transient_for(self.parent)
            self.blocking_window.set_decorated(False)
            self.blocking_window.set_modal(True)

            command_thread = threading.Thread(target=run_command)
            command_thread.start()

    def on_button_run_default_clicked(self, widget):
        if self.entry_default_prefix.get_text() == "":
            self.entry_default_prefix.get_style_context().add_class("entry")
        else:
            self.update_envar_file()
            self.update_config_file()
            self.parent.manage_autostart_file(self.checkbox_start_boot.get_active())
            default_runner = self.get_default_runner()
            self.update_system_tray()

            dialog = Gtk.Dialog(title=_("Select a file to run inside the prefix"), parent=self, flags=0)
            dialog.set_size_request(720, 720)

            filechooser = Gtk.FileChooserWidget(action=Gtk.FileChooserAction.OPEN)
            filechooser.set_current_folder(os.path.expanduser("~/"))
            filechooser.connect("file-activated", lambda widget: dialog.response(Gtk.ResponseType.OK))

            windows_filter = Gtk.FileFilter()
            windows_filter.set_name(_("Windows files"))
            windows_filter.add_pattern("*.exe")
            windows_filter.add_pattern("*.msi")
            windows_filter.add_pattern("*.bat")
            windows_filter.add_pattern("*.lnk")
            windows_filter.add_pattern("*.reg")

            all_files_filter = Gtk.FileFilter()
            all_files_filter.set_name(_("All files"))
            all_files_filter.add_pattern("*")

            filter_combobox = Gtk.ComboBoxText()
            filter_combobox.append("windows", _("Windows files"))
            filter_combobox.append("all", _("All files"))
            filter_combobox.set_active(0)
            filter_combobox.set_size_request(150, -1)

            def on_filter_changed(combobox):
                active_id = combobox.get_active_id()
                if active_id == "windows":
                    filechooser.set_filter(windows_filter)
                elif active_id == "all":
                    filechooser.set_filter(all_files_filter)

            filter_combobox.connect("changed", on_filter_changed)
            filechooser.set_filter(windows_filter)

            button_open = Gtk.Button.new_with_label(_("Open"))
            button_open.connect("clicked", lambda w: dialog.response(Gtk.ResponseType.OK))
            button_open.set_size_request(150, -1)

            button_cancel = Gtk.Button.new_with_label(_("Cancel"))
            button_cancel.connect("clicked", lambda w: dialog.response(Gtk.ResponseType.CANCEL))
            button_cancel.set_size_request(150, -1)

            button_grid = Gtk.Grid()
            button_grid.set_row_spacing(10)
            button_grid.set_column_spacing(10)
            button_grid.set_margin_start(10)
            button_grid.set_margin_end(10)
            button_grid.set_margin_top(10)
            button_grid.set_margin_bottom(10)
            button_grid.attach(button_open, 1, 1, 1, 1)
            button_grid.attach(button_cancel, 0, 1, 1, 1)
            button_grid.attach(filter_combobox, 1, 0, 1, 1)

            button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            button_box.pack_end(button_grid, False, False, 0)

            dialog.vbox.pack_start(filechooser, True, True, 0)
            dialog.vbox.pack_start(button_box, False, False, 0)

            dialog.show_all()
            response = dialog.run()

            if response == Gtk.ResponseType.OK:

                command_parts = []
                file_run = filechooser.get_filename()
                command_parts.append(f'FAUGUS_LOG=default')
                if not file_run.endswith(".reg"):
                    if file_run:
                        command_parts.append(f'GAMEID=default')
                    if default_runner:
                        command_parts.append(f'PROTONPATH={default_runner}')
                    command_parts.append(f'"{umu_run}" "{file_run}"')
                else:
                    if file_run:
                        command_parts.append(f'GAMEID=default')
                    if default_runner:
                        command_parts.append(f'PROTONPATH={default_runner}')
                    command_parts.append(f'"{umu_run}" regedit "{file_run}"')

                # Join all parts into a single command
                command = ' '.join(command_parts)

                print(command)

                # faugus-run path
                faugus_run_path = faugus_run

                def run_command():
                    process = subprocess.Popen([sys.executable, faugus_run_path, command])
                    process.wait()
                    GLib.idle_add(self.set_sensitive, True)
                    GLib.idle_add(self.parent.set_sensitive, True)
                    GLib.idle_add(self.blocking_window.destroy)

                self.blocking_window = Gtk.Window()
                self.blocking_window.set_transient_for(self.parent)
                self.blocking_window.set_decorated(False)
                self.blocking_window.set_modal(True)

                command_thread = threading.Thread(target=run_command)
                command_thread.start()

            else:
                self.set_sensitive(True)
            dialog.destroy()

    def on_button_backup_clicked(self, widget):
        self.response(Gtk.ResponseType.OK)
        self.show_warning_dialog(self, _("Prefixes and runners will not be backed up!"))

        items = ["banners", "icons", "config.ini", "games.json", "latest-games.txt"]

        temp_dir = os.path.join(faugus_launcher_dir, "temp-backup")
        os.makedirs(temp_dir, exist_ok=True)

        for item in items:
            src = os.path.join(faugus_launcher_dir, item)
            dst = os.path.join(temp_dir, item)
            if os.path.isdir(src):
                shutil.copytree(src, dst, dirs_exist_ok=True)
            elif os.path.isfile(src):
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)

        marker_path = os.path.join(temp_dir, ".faugus_marker")
        with open(marker_path, "w") as f:
            f.write("faugus-launcher-backup")

        zip_path = os.path.join(faugus_launcher_dir, "faugus-launcher-backup")
        shutil.make_archive(zip_path, 'zip', temp_dir)

        shutil.rmtree(temp_dir)

        dialog = Gtk.Dialog(title=_("Save the backup file as..."), parent=self, flags=0)
        dialog.set_size_request(720, 720)

        filechooser = Gtk.FileChooserWidget(action=Gtk.FileChooserAction.SAVE)
        filechooser.set_current_folder(os.path.expanduser("~/"))
        filechooser.set_current_name("faugus-launcher-backup.zip")

        button_open = Gtk.Button.new_with_label(_("Save"))
        button_open.connect("clicked", lambda w: dialog.response(Gtk.ResponseType.OK))
        button_open.set_size_request(150, -1)

        button_cancel = Gtk.Button.new_with_label(_("Cancel"))
        button_cancel.connect("clicked", lambda w: dialog.response(Gtk.ResponseType.CANCEL))
        button_cancel.set_size_request(150, -1)

        button_grid = Gtk.Grid()
        button_grid.set_row_spacing(10)
        button_grid.set_column_spacing(10)
        button_grid.set_margin_start(10)
        button_grid.set_margin_end(10)
        button_grid.set_margin_top(10)
        button_grid.set_margin_bottom(10)
        button_grid.attach(button_open, 1, 1, 1, 1)
        button_grid.attach(button_cancel, 0, 1, 1, 1)

        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        button_box.pack_end(button_grid, False, False, 0)

        dialog.vbox.pack_start(filechooser, True, True, 0)
        dialog.vbox.pack_start(button_box, False, False, 0)

        dialog.show_all()
        response = dialog.run()

        if response == Gtk.ResponseType.OK:
            dest = filechooser.get_filename()
            shutil.copy2(zip_path + ".zip", dest)

        dialog.destroy()
        os.remove(zip_path + ".zip")

    def on_button_restore_clicked(self, widget):
        dialog = Gtk.Dialog(title=_("Select a backup file to restore"), parent=self, flags=0)
        dialog.set_size_request(720, 720)

        filechooser = Gtk.FileChooserWidget(action=Gtk.FileChooserAction.OPEN)
        filechooser.set_current_folder(os.path.expanduser("~/"))
        filechooser.connect("file-activated", lambda widget: dialog.response(Gtk.ResponseType.OK))

        zip_filter = Gtk.FileFilter()
        zip_filter.set_name("ZIP files")
        zip_filter.add_pattern("*.zip")

        filechooser.set_filter(zip_filter)

        button_open = Gtk.Button.new_with_label(_("Open"))
        button_open.connect("clicked", lambda w: dialog.response(Gtk.ResponseType.OK))
        button_open.set_size_request(150, -1)

        button_cancel = Gtk.Button.new_with_label(_("Cancel"))
        button_cancel.connect("clicked", lambda w: dialog.response(Gtk.ResponseType.CANCEL))
        button_cancel.set_size_request(150, -1)

        button_grid = Gtk.Grid()
        button_grid.set_row_spacing(10)
        button_grid.set_column_spacing(10)
        button_grid.set_margin_start(10)
        button_grid.set_margin_end(10)
        button_grid.set_margin_top(10)
        button_grid.set_margin_bottom(10)
        button_grid.attach(button_open, 1, 1, 1, 1)
        button_grid.attach(button_cancel, 0, 1, 1, 1)

        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        button_box.pack_end(button_grid, False, False, 0)

        dialog.vbox.pack_start(filechooser, True, True, 0)
        dialog.vbox.pack_start(button_box, False, False, 0)

        dialog.show_all()
        response = dialog.run()

        if response == Gtk.ResponseType.OK:
            zip_file = filechooser.get_filename()
            if not os.path.isfile(zip_file):
                dialog.destroy()
                self.show_warning_dialog(self, _("This is not a valid Faugus Launcher backup file."))
                return
            temp_dir = os.path.join(faugus_launcher_dir, "temp-restore")

            shutil.unpack_archive(zip_file, temp_dir, 'zip')

            marker_path = os.path.join(temp_dir, ".faugus_marker")
            if not os.path.exists(marker_path):
                shutil.rmtree(temp_dir)
                dialog.destroy()
                self.show_warning_dialog(self, _("This is not a valid Faugus Launcher backup file."))
                return

            if self.show_warning_dialog2(self, _("Are you sure you want to overwrite the settings?")):
                for item in os.listdir(temp_dir):
                    if item == ".faugus_marker":
                        continue
                    src = os.path.join(temp_dir, item)
                    dst = os.path.join(faugus_launcher_dir, item)

                    if os.path.isdir(dst):
                        shutil.rmtree(dst)
                    elif os.path.isfile(dst):
                        os.remove(dst)

                    if os.path.isdir(src):
                        shutil.copytree(src, dst)
                    elif os.path.isfile(src):
                        shutil.copy2(src, dst)

                shutil.rmtree(temp_dir)
                global faugus_backup
                faugus_backup = True
                self.response(Gtk.ResponseType.OK)

        dialog.destroy()

    def show_warning_dialog(self, parent, title):
        dialog = Gtk.Dialog(title="Faugus Launcher", transient_for=parent, modal=True)
        dialog.set_resizable(False)
        dialog.set_icon_from_file(faugus_png)
        subprocess.Popen(["canberra-gtk-play", "-f", faugus_notification])

        label = Gtk.Label()
        label.set_label(title)
        label.set_halign(Gtk.Align.CENTER)

        button_yes = Gtk.Button(label=_("Ok"))
        button_yes.set_size_request(150, -1)
        button_yes.connect("clicked", lambda x: dialog.destroy())

        content_area = dialog.get_content_area()
        content_area.set_border_width(0)
        content_area.set_halign(Gtk.Align.CENTER)
        content_area.set_valign(Gtk.Align.CENTER)
        content_area.set_vexpand(True)
        content_area.set_hexpand(True)

        box_top = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box_top.set_margin_start(20)
        box_top.set_margin_end(20)
        box_top.set_margin_top(20)
        box_top.set_margin_bottom(20)

        box_bottom = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box_bottom.set_margin_start(10)
        box_bottom.set_margin_end(10)
        box_bottom.set_margin_bottom(10)

        box_top.pack_start(label, True, True, 0)
        box_bottom.pack_start(button_yes, True, True, 0)

        content_area.add(box_top)
        content_area.add(box_bottom)

        dialog.show_all()
        dialog.run()
        dialog.destroy()

    def show_warning_dialog2(self, parent, title):
        dialog = Gtk.Dialog(title="Faugus Launcher", transient_for=parent, modal=True)
        dialog.set_resizable(False)
        dialog.set_icon_from_file(faugus_png)
        subprocess.Popen(["canberra-gtk-play", "-f", faugus_notification])

        label = Gtk.Label()
        label.set_label(title)
        label.set_halign(Gtk.Align.CENTER)

        button_no = Gtk.Button(label=_("No"))
        button_no.set_size_request(150, -1)
        button_no.connect("clicked", lambda x: dialog.response(Gtk.ResponseType.CANCEL))

        button_yes = Gtk.Button(label=_("Yes"))
        button_yes.set_size_request(150, -1)
        button_yes.connect("clicked", lambda x: dialog.response(Gtk.ResponseType.OK))

        content_area = dialog.get_content_area()
        content_area.set_border_width(0)
        content_area.set_halign(Gtk.Align.CENTER)
        content_area.set_valign(Gtk.Align.CENTER)
        content_area.set_vexpand(True)
        content_area.set_hexpand(True)

        box_top = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box_top.set_margin_start(20)
        box_top.set_margin_end(20)
        box_top.set_margin_top(20)
        box_top.set_margin_bottom(20)

        box_bottom = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box_bottom.set_margin_start(10)
        box_bottom.set_margin_end(10)
        box_bottom.set_margin_bottom(10)

        box_top.pack_start(label, True, True, 0)
        box_bottom.pack_start(button_no, True, True, 0)
        box_bottom.pack_start(button_yes, True, True, 0)

        content_area.add(box_top)
        content_area.add(box_bottom)

        dialog.show_all()
        response = dialog.run()
        dialog.destroy()

        return response == Gtk.ResponseType.OK

    def on_button_kofi_clicked(self, widget):
        webbrowser.open("https://ko-fi.com/K3K210EMDU")

    def on_button_paypal_clicked(self, widget):
        webbrowser.open("https://www.paypal.com/donate/?business=57PP9DVD3VWAN&no_recurring=0&currency_code=USD")

    def on_button_search_prefix_clicked(self, widget):
        dialog = Gtk.Dialog(title=_("Select a prefix location"), parent=self, flags=0)
        dialog.set_size_request(720, 720)

        filechooser = Gtk.FileChooserWidget(action=Gtk.FileChooserAction.SELECT_FOLDER)
        filechooser.set_current_folder(os.path.expanduser(self.default_prefix))
        filechooser.connect("file-activated", lambda widget: dialog.response(Gtk.ResponseType.OK))

        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        button_box.set_margin_start(10)
        button_box.set_margin_end(10)
        button_box.set_margin_top(10)
        button_box.set_margin_bottom(10)

        button_open = Gtk.Button.new_with_label(_("Open"))
        button_open.connect("clicked", lambda w: dialog.response(Gtk.ResponseType.OK))
        button_open.set_size_request(150, -1)
        button_box.pack_end(button_open, False, False, 0)

        button_cancel = Gtk.Button.new_with_label(_("Cancel"))
        button_cancel.connect("clicked", lambda w: dialog.response(Gtk.ResponseType.CANCEL))
        button_cancel.set_size_request(150, -1)
        button_box.pack_end(button_cancel, False, False, 0)

        dialog.vbox.pack_start(filechooser, True, True, 0)
        dialog.vbox.pack_start(button_box, False, False, 0)

        dialog.show_all()
        response = dialog.run()

        if response == Gtk.ResponseType.OK:
            self.entry_default_prefix.set_text(filechooser.get_filename())

        dialog.destroy()

    def on_button_search_lossless_clicked(self, widget):
        dialog = Gtk.Dialog(title=_("Select the Lossless.dll file"), parent=self, flags=0)
        dialog.set_size_request(720, 720)

        filechooser = Gtk.FileChooserWidget(action=Gtk.FileChooserAction.OPEN)

        filter_dll = Gtk.FileFilter()
        filter_dll.set_name("Lossless.dll")
        filter_dll.add_pattern("Lossless.dll")
        filechooser.add_filter(filter_dll)

        filechooser.connect("file-activated", lambda widget: dialog.response(Gtk.ResponseType.OK))

        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        button_box.set_margin_start(10)
        button_box.set_margin_end(10)
        button_box.set_margin_top(10)
        button_box.set_margin_bottom(10)

        button_open = Gtk.Button.new_with_label(_("Open"))
        button_open.connect("clicked", lambda w: dialog.response(Gtk.ResponseType.OK))
        button_open.set_size_request(150, -1)
        button_box.pack_end(button_open, False, False, 0)

        button_cancel = Gtk.Button.new_with_label(_("Cancel"))
        button_cancel.connect("clicked", lambda w: dialog.response(Gtk.ResponseType.CANCEL))
        button_cancel.set_size_request(150, -1)
        button_box.pack_end(button_cancel, False, False, 0)

        dialog.vbox.pack_start(filechooser, True, True, 0)
        dialog.vbox.pack_start(button_box, False, False, 0)

        dialog.show_all()
        response = dialog.run()

        if response == Gtk.ResponseType.OK:
            selected_file = filechooser.get_filename()
            if os.path.basename(selected_file) == "Lossless.dll":
                self.entry_lossless.set_text(selected_file)

        dialog.destroy()

    def load_config(self):
        cfg = ConfigManager()

        close_on_launch = cfg.config.get('close-onlaunch', 'False') == 'True'
        self.default_prefix = cfg.config.get('default-prefix', '').strip('"')
        mangohud = cfg.config.get('mangohud', 'False') == 'True'
        gamemode = cfg.config.get('gamemode', 'False') == 'True'
        disable_hidraw = cfg.config.get('disable-hidraw', 'False') == 'True'
        self.default_runner = cfg.config.get('default-runner', '').strip('"')
        lossless_location = cfg.config.get('lossless-location', '').strip('"')
        discrete_gpu = cfg.config.get('discrete-gpu', 'False') == 'True'
        splash_disable = cfg.config.get('splash-disable', 'False') == 'True'
        system_tray = cfg.config.get('system-tray', 'False') == 'True'
        self.start_boot = cfg.config.get('start-boot', 'False') == 'True'
        self.mono_icon = cfg.config.get('mono-icon', 'False') == 'True'
        start_maximized = cfg.config.get('start-maximized', 'False') == 'True'
        self.interface_mode = cfg.config.get('interface-mode', '').strip('"')
        start_fullscreen = cfg.config.get('start-fullscreen', 'False') == 'True'
        show_labels = cfg.config.get('show-labels', 'False') == 'True'
        smaller_banners = cfg.config.get('smaller-banners', 'False') == 'True'
        enable_logging = cfg.config.get('enable-logging', 'False') == 'True'
        wayland_driver = cfg.config.get('wayland-driver', 'False') == 'True'
        enable_hdr = cfg.config.get('enable-hdr', 'False') == 'True'
        enable_ntsync = cfg.config.get('enable-ntsync', 'False') == 'True'
        enable_wow64 = cfg.config.get('enable-wow64', 'False') == 'True'
        self.language = cfg.config.get('language', '')

        self.checkbox_close_after_launch.set_active(close_on_launch)
        self.entry_default_prefix.set_text(self.default_prefix)

        self.checkbox_mangohud.set_active(mangohud)
        self.checkbox_gamemode.set_active(gamemode)
        self.checkbox_disable_hidraw.set_active(disable_hidraw)

        lossless_dll_path = find_lossless_dll()
        if not lossless_location:
            if lossless_dll_path:
                self.entry_lossless.set_text(str(lossless_dll_path))
        else:
            self.entry_lossless.set_text(lossless_location)

        if self.default_runner == "":
            self.default_runner = "UMU-Proton Latest"
        if self.default_runner == "GE-Proton":
            self.default_runner = "GE-Proton Latest (default)"
        if self.default_runner == "Proton-EM":
            self.default_runner = "Proton-EM Latest"
        model_runner = self.combobox_runner.get_model()
        index_runner = 0
        for i, row in enumerate(model_runner):
            if row[0] == self.default_runner:
                index_runner = i
                break

        self.combobox_runner.set_active(index_runner)
        self.checkbox_discrete_gpu.set_active(discrete_gpu)
        self.checkbox_splash_disable.set_active(splash_disable)
        self.checkbox_system_tray.set_active(system_tray)
        self.checkbox_start_boot.set_active(self.start_boot)
        self.checkbox_mono_icon.set_active(self.mono_icon)
        self.checkbox_start_maximized.set_active(start_maximized)
        self.checkbox_start_fullscreen.set_active(start_fullscreen)
        self.checkbox_show_labels.set_active(show_labels)
        self.checkbox_smaller_banners.set_active(smaller_banners)
        self.checkbox_enable_logging.set_active(enable_logging)
        self.checkbox_wayland_driver.set_active(wayland_driver)
        self.checkbox_enable_hdr.set_active(enable_hdr)
        self.checkbox_enable_ntsync.set_active(enable_ntsync)
        self.checkbox_enable_wow64.set_active(enable_wow64)

        model_interface = self.combobox_interface.get_model()
        index_interface = 0
        for i, row in enumerate(model_interface):
            if row[0] == self.interface_mode:
                index_interface = i
                break

        self.combobox_interface.set_active(index_interface)

        model_language = self.combobox_language.get_model()
        index_language = 0

        if self.language == "":
            self.combobox_language.set_active(index_language)
        else:
            for i, row in enumerate(model_language):
                lang_name = row[0]
                lang_code = self.lang_codes.get(lang_name, "")
                if lang_code == self.language:
                    index_language = i
                    break

            self.combobox_language.set_active(index_language)
        self.load_liststore_from_file(envar_dir)

    def load_liststore_from_file(self, filename=envar_dir):
        self.liststore.clear()

        try:
            with open(filename, "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f.readlines() if line.strip()]
        except FileNotFoundError:
            lines = []

        for line in lines:
            self.liststore.append([line])

        self.liststore.append([""])

class Game:
    def __init__(self, gameid, title, path, prefix, launch_arguments, game_arguments, mangohud, gamemode, disable_hidraw, protonfix,
                 runner, addapp_checkbox, addapp, addapp_bat, banner, lossless):
        # Initialize a Game object with various attributes
        self.gameid = gameid
        self.title = title  # Title of the game
        self.path = path  # Path to the game executable
        self.launch_arguments = launch_arguments  # Arguments to launch the game
        self.game_arguments = game_arguments  # Arguments specific to the game
        self.mangohud = mangohud  # Boolean indicating whether Mangohud is enabled
        self.gamemode = gamemode  # Boolean indicating whether Gamemode is enabled
        self.prefix = prefix  # Prefix for Wine games
        self.disable_hidraw = disable_hidraw
        self.protonfix = protonfix
        self.runner = runner
        self.addapp_checkbox = addapp_checkbox
        self.addapp = addapp
        self.addapp_bat = addapp_bat
        self.banner = banner
        self.lossless = lossless


class DuplicateDialog(Gtk.Dialog):
    def __init__(self, parent, title):
        super().__init__(title=_("Duplicate %s") % title, transient_for=parent, modal=True)
        self.set_resizable(False)
        self.set_icon_from_file(faugus_png)

        label_title = Gtk.Label(label=_("Title"))
        label_title.set_halign(Gtk.Align.START)
        self.entry_title = Gtk.Entry()
        self.entry_title.set_tooltip_text(_("Game Title"))

        button_cancel = Gtk.Button(label=_("Cancel"))
        button_cancel.connect("clicked", lambda widget: self.response(Gtk.ResponseType.CANCEL))
        button_cancel.set_size_request(150, -1)

        button_ok = Gtk.Button(label=_("Ok"))
        button_ok.connect("clicked", lambda widget: self.response(Gtk.ResponseType.OK))
        button_ok.set_size_request(150, -1)

        content_area = self.get_content_area()
        content_area.set_border_width(0)
        content_area.set_halign(Gtk.Align.CENTER)
        content_area.set_valign(Gtk.Align.CENTER)
        content_area.set_vexpand(True)
        content_area.set_hexpand(True)

        box_top = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box_top.set_margin_start(10)
        box_top.set_margin_end(10)
        box_top.set_margin_top(10)
        box_top.set_margin_bottom(20)

        box_bottom = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box_bottom.set_margin_start(10)
        box_bottom.set_margin_end(10)
        box_bottom.set_margin_bottom(10)

        box_top.pack_start(label_title, True, True, 0)
        box_top.pack_start(self.entry_title, True, True, 0)

        box_bottom.pack_start(button_cancel, True, True, 0)
        box_bottom.pack_start(button_ok, True, True, 0)

        content_area.add(box_top)
        content_area.add(box_bottom)

        self.show_all()

    def show_warning_dialog(self, parent, title):
        dialog = Gtk.Dialog(title="Faugus Launcher", transient_for=parent, modal=True)
        dialog.set_resizable(False)
        dialog.set_icon_from_file(faugus_png)
        subprocess.Popen(["canberra-gtk-play", "-f", faugus_notification])

        label = Gtk.Label()
        label.set_label(title)
        label.set_halign(Gtk.Align.CENTER)

        button_yes = Gtk.Button(label=_("Ok"))
        button_yes.set_size_request(150, -1)
        button_yes.connect("clicked", lambda x: dialog.destroy())

        content_area = dialog.get_content_area()
        content_area.set_border_width(0)
        content_area.set_halign(Gtk.Align.CENTER)
        content_area.set_valign(Gtk.Align.CENTER)
        content_area.set_vexpand(True)
        content_area.set_hexpand(True)

        box_top = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box_top.set_margin_start(20)
        box_top.set_margin_end(20)
        box_top.set_margin_top(20)
        box_top.set_margin_bottom(20)

        box_bottom = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box_bottom.set_margin_start(10)
        box_bottom.set_margin_end(10)
        box_bottom.set_margin_bottom(10)

        box_top.pack_start(label, True, True, 0)
        box_bottom.pack_start(button_yes, True, True, 0)

        content_area.add(box_top)
        content_area.add(box_bottom)

        dialog.show_all()
        dialog.run()
        dialog.destroy()


class ConfirmationDialog(Gtk.Dialog):
    def __init__(self, parent, title, prefix):
        super().__init__(title=_("Delete %s") % title, transient_for=parent, modal=True)
        self.set_resizable(False)
        self.set_icon_from_file(faugus_png)
        subprocess.Popen(["canberra-gtk-play", "-f", faugus_notification])

        label = Gtk.Label()
        label.set_label(_("Are you sure you want to delete %s?") % title)
        label.set_halign(Gtk.Align.CENTER)

        button_no = Gtk.Button(label=_("No"))
        button_no.set_size_request(150, -1)
        button_no.connect("clicked", lambda x: self.response(Gtk.ResponseType.NO))

        button_yes = Gtk.Button(label=_("Yes"))
        button_yes.set_size_request(150, -1)
        button_yes.connect("clicked", lambda x: self.response(Gtk.ResponseType.YES))

        self.checkbox = Gtk.CheckButton(label=_("Also remove the prefix"))
        self.checkbox.set_halign(Gtk.Align.CENTER)

        content_area = self.get_content_area()
        content_area.set_border_width(0)
        content_area.set_halign(Gtk.Align.CENTER)
        content_area.set_valign(Gtk.Align.CENTER)
        content_area.set_vexpand(True)
        content_area.set_hexpand(True)

        box_top = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        box_top.set_margin_start(20)
        box_top.set_margin_end(20)
        box_top.set_margin_top(20)
        box_top.set_margin_bottom(20)

        box_bottom = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box_bottom.set_margin_start(10)
        box_bottom.set_margin_end(10)
        box_bottom.set_margin_bottom(10)

        box_top.pack_start(label, True, True, 0)
        if os.path.basename(prefix) != "default":
            box_top.pack_start(self.checkbox, True, True, 0)

        box_bottom.pack_start(button_no, True, True, 0)
        box_bottom.pack_start(button_yes, True, True, 0)

        content_area.add(box_top)
        content_area.add(box_bottom)

        self.show_all()

    def get_remove_prefix_state(self):
        # Get the state of the checkbox
        return self.checkbox.get_active()


class AddGame(Gtk.Dialog):
    def __init__(self, parent, game_running2, file_path, interface_mode):
        # Initialize the AddGame dialog
        super().__init__(title=_("New Game/App"), parent=parent)
        self.set_resizable(False)
        self.set_modal(True)
        self.parent_window = parent
        self.set_icon_from_file(faugus_png)
        self.interface_mode = interface_mode
        self.updated_steam_id = None

        if not os.path.exists(banners_dir):
            os.makedirs(banners_dir)

        self.banner_path_temp = os.path.join(banners_dir, "banner_temp.png")
        shutil.copyfile(faugus_banner, self.banner_path_temp)
        self.icon_directory = f"{icons_dir}/icon_temp/"

        if not os.path.exists(self.icon_directory):
            os.makedirs(self.icon_directory)

        self.icons_path = icons_dir
        self.icon_extracted = os.path.expanduser(f'{self.icons_path}/icon_temp/icon.ico')
        self.icon_converted = os.path.expanduser(f'{self.icons_path}/icon_temp/icon.png')
        self.icon_temp = f'{self.icons_path}/icon_temp.ico'

        self.box = self.get_content_area()
        self.box.set_margin_start(0)
        self.box.set_margin_end(0)
        self.box.set_margin_top(0)
        self.box.set_margin_bottom(0)
        self.content_area = self.get_content_area()
        self.content_area.set_border_width(0)
        self.content_area.set_halign(Gtk.Align.CENTER)
        self.content_area.set_valign(Gtk.Align.CENTER)
        self.content_area.set_vexpand(True)
        self.content_area.set_hexpand(True)

        grid_page1 = Gtk.Grid()
        grid_page1.set_column_homogeneous(True)
        grid_page1.set_column_spacing(10)
        grid_page2 = Gtk.Grid()
        grid_page2.set_column_homogeneous(True)
        grid_page2.set_column_spacing(10)

        self.grid_launcher = Gtk.Grid()
        self.grid_launcher.set_row_spacing(10)
        self.grid_launcher.set_column_spacing(10)
        self.grid_launcher.set_margin_start(10)
        self.grid_launcher.set_margin_end(10)
        self.grid_launcher.set_margin_top(10)

        self.grid_title = Gtk.Grid()
        self.grid_title.set_row_spacing(10)
        self.grid_title.set_column_spacing(10)
        self.grid_title.set_margin_start(10)
        self.grid_title.set_margin_end(10)
        self.grid_title.set_margin_top(10)

        self.grid_path = Gtk.Grid()
        self.grid_path.set_row_spacing(10)
        self.grid_path.set_column_spacing(10)
        self.grid_path.set_margin_start(10)
        self.grid_path.set_margin_end(10)
        self.grid_path.set_margin_top(10)

        self.grid_prefix = Gtk.Grid()
        self.grid_prefix.set_row_spacing(10)
        self.grid_prefix.set_column_spacing(10)
        self.grid_prefix.set_margin_start(10)
        self.grid_prefix.set_margin_end(10)
        self.grid_prefix.set_margin_top(10)

        self.grid_runner = Gtk.Grid()
        self.grid_runner.set_row_spacing(10)
        self.grid_runner.set_column_spacing(10)
        self.grid_runner.set_margin_start(10)
        self.grid_runner.set_margin_end(10)
        self.grid_runner.set_margin_top(10)

        self.grid_shortcut = Gtk.Grid(orientation=Gtk.Orientation.VERTICAL)
        self.grid_shortcut.set_row_spacing(10)
        self.grid_shortcut.set_column_spacing(10)
        self.grid_shortcut.set_margin_start(10)
        self.grid_shortcut.set_margin_end(10)
        self.grid_shortcut.set_margin_top(10)
        self.grid_shortcut.set_margin_bottom(10)

        self.grid_shortcut_icon = Gtk.Grid(orientation=Gtk.Orientation.VERTICAL)
        self.grid_shortcut_icon.set_row_spacing(10)
        self.grid_shortcut_icon.set_column_spacing(10)
        self.grid_shortcut_icon.set_margin_start(10)
        self.grid_shortcut_icon.set_margin_end(10)
        self.grid_shortcut_icon.set_margin_top(10)
        self.grid_shortcut_icon.set_margin_bottom(10)

        self.grid_protonfix = Gtk.Grid()
        self.grid_protonfix.set_row_spacing(10)
        self.grid_protonfix.set_column_spacing(10)
        self.grid_protonfix.set_margin_start(10)
        self.grid_protonfix.set_margin_end(10)
        self.grid_protonfix.set_margin_top(10)

        self.grid_launch_arguments = Gtk.Grid()
        self.grid_launch_arguments.set_row_spacing(10)
        self.grid_launch_arguments.set_column_spacing(10)
        self.grid_launch_arguments.set_margin_start(10)
        self.grid_launch_arguments.set_margin_end(10)
        self.grid_launch_arguments.set_margin_top(10)

        self.grid_game_arguments = Gtk.Grid()
        self.grid_game_arguments.set_row_spacing(10)
        self.grid_game_arguments.set_column_spacing(10)
        self.grid_game_arguments.set_margin_start(10)
        self.grid_game_arguments.set_margin_end(10)
        self.grid_game_arguments.set_margin_top(10)

        self.grid_lossless = Gtk.Grid()
        self.grid_lossless.set_row_spacing(10)
        self.grid_lossless.set_column_spacing(10)
        self.grid_lossless.set_margin_start(10)
        self.grid_lossless.set_margin_end(10)
        self.grid_lossless.set_margin_top(10)

        self.grid_addapp = Gtk.Grid()
        self.grid_addapp.set_row_spacing(10)
        self.grid_addapp.set_column_spacing(10)
        self.grid_addapp.set_margin_start(10)
        self.grid_addapp.set_margin_end(10)
        self.grid_addapp.set_margin_top(10)

        self.grid_tools = Gtk.Grid()
        self.grid_tools.set_row_spacing(10)
        self.grid_tools.set_column_spacing(10)
        self.grid_tools.set_margin_start(10)
        self.grid_tools.set_margin_end(10)
        self.grid_tools.set_margin_top(10)
        self.grid_tools.set_margin_bottom(10)

        css_provider = Gtk.CssProvider()
        css = """
        .entry {
            border-color: Red;
        }
        """
        css_provider.load_from_data(css.encode('utf-8'))
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), css_provider,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_USER)

        self.combobox_launcher = Gtk.ComboBoxText()

        # Widgets for title
        self.label_title = Gtk.Label(label=_("Title"))
        self.label_title.set_halign(Gtk.Align.START)
        self.entry_title = Gtk.Entry()
        self.entry_title.connect("changed", self.on_entry_changed, self.entry_title)
        if interface_mode == "Banners":
            self.entry_title.connect("focus-out-event", self.on_entry_focus_out)
        self.entry_title.set_tooltip_text(_("Game Title"))
        self.entry_title.set_has_tooltip(True)
        self.entry_title.connect("query-tooltip", self.on_entry_query_tooltip)

        # Widgets for path
        self.label_path = Gtk.Label(label=_("Path"))
        self.label_path.set_halign(Gtk.Align.START)
        self.entry_path = Gtk.Entry()
        self.entry_path.connect("changed", self.on_entry_changed, self.entry_path)
        if file_path:
            self.entry_path.set_text(file_path)
        self.entry_path.set_tooltip_text(_("/path/to/the/exe"))
        self.entry_path.set_has_tooltip(True)
        self.entry_path.connect("query-tooltip", self.on_entry_query_tooltip)
        self.button_search = Gtk.Button()
        self.button_search.set_image(Gtk.Image.new_from_icon_name("system-search-symbolic", Gtk.IconSize.BUTTON))
        self.button_search.connect("clicked", self.on_button_search_clicked)
        self.button_search.set_size_request(50, -1)

        # Widgets for prefix
        self.label_prefix = Gtk.Label(label=_("Prefix"))
        self.label_prefix.set_halign(Gtk.Align.START)
        self.entry_prefix = Gtk.Entry()
        self.entry_prefix.connect("changed", self.on_entry_changed, self.entry_prefix)
        self.entry_prefix.set_tooltip_text(_("/path/to/the/prefix"))
        self.entry_prefix.set_has_tooltip(True)
        self.entry_prefix.connect("query-tooltip", self.on_entry_query_tooltip)
        self.button_search_prefix = Gtk.Button()
        self.button_search_prefix.set_image(Gtk.Image.new_from_icon_name("system-search-symbolic", Gtk.IconSize.BUTTON))
        self.button_search_prefix.connect("clicked", self.on_button_search_prefix_clicked)
        self.button_search_prefix.set_size_request(50, -1)

        # Widgets for runner
        self.label_runner = Gtk.Label(label=_("Proton"))
        self.label_runner.set_halign(Gtk.Align.START)
        self.combobox_runner = Gtk.ComboBoxText()

        # Widgets for protonfix
        self.label_protonfix = Gtk.Label(label="Protonfix")
        self.label_protonfix.set_halign(Gtk.Align.START)
        self.entry_protonfix = Gtk.Entry()
        self.entry_protonfix.set_tooltip_text("UMU ID")
        self.entry_protonfix.set_has_tooltip(True)
        self.entry_protonfix.connect("query-tooltip", self.on_entry_query_tooltip)
        self.button_search_protonfix = Gtk.Button()
        self.button_search_protonfix.set_image(
            Gtk.Image.new_from_icon_name("system-search-symbolic", Gtk.IconSize.BUTTON))
        self.button_search_protonfix.connect("clicked", self.on_button_search_protonfix_clicked)
        self.button_search_protonfix.set_size_request(50, -1)

        # Widgets for launch arguments
        self.label_launch_arguments = Gtk.Label(label=_("Launch Arguments"))
        self.label_launch_arguments.set_halign(Gtk.Align.START)
        self.entry_launch_arguments = Gtk.Entry()
        self.entry_launch_arguments.set_tooltip_text(_("e.g.: PROTON_USE_WINED3D=1 gamescope -W 2560 -H 1440"))
        self.entry_launch_arguments.set_has_tooltip(True)
        self.entry_launch_arguments.connect("query-tooltip", self.on_entry_query_tooltip)

        # Widgets for game arguments
        self.label_game_arguments = Gtk.Label(label=_("Game Arguments"))
        self.label_game_arguments.set_halign(Gtk.Align.START)
        self.entry_game_arguments = Gtk.Entry()
        self.entry_game_arguments.set_tooltip_text(_("e.g.: -d3d11 -fullscreen"))
        self.entry_game_arguments.set_has_tooltip(True)
        self.entry_game_arguments.connect("query-tooltip", self.on_entry_query_tooltip)

        # Widgets for lossless scaling
        self.label_lossless = Gtk.Label(label=_("Lossless Scaling Frame Generation"))
        self.label_lossless.set_halign(Gtk.Align.START)
        self.combobox_lossless = Gtk.ComboBoxText()

        # Widgets for extra executable
        self.checkbox_addapp = Gtk.CheckButton(label=_("Additional Application"))
        self.checkbox_addapp.set_tooltip_text(
            _("Additional application to run with the game, like Cheat Engine, Trainers, Mods..."))
        self.checkbox_addapp.connect("toggled", self.on_checkbox_addapp_toggled)
        self.entry_addapp = Gtk.Entry()
        self.entry_addapp.set_tooltip_text(_("/path/to/the/app"))
        self.entry_addapp.set_has_tooltip(True)
        self.entry_addapp.connect("query-tooltip", self.on_entry_query_tooltip)
        self.entry_addapp.set_sensitive(False)
        self.button_search_addapp = Gtk.Button()
        self.button_search_addapp.set_image(Gtk.Image.new_from_icon_name("system-search-symbolic", Gtk.IconSize.BUTTON))
        self.button_search_addapp.connect("clicked", self.on_button_search_addapp_clicked)
        self.button_search_addapp.set_size_request(50, -1)
        self.button_search_addapp.set_sensitive(False)

        # Checkboxes for optional features
        self.checkbox_mangohud = Gtk.CheckButton(label="MangoHud")
        self.checkbox_mangohud.set_tooltip_text(
            _("Shows an overlay for monitoring FPS, temperatures, CPU/GPU load and more."))
        self.checkbox_gamemode = Gtk.CheckButton(label="GameMode")
        self.checkbox_gamemode.set_tooltip_text(_("Tweaks your system to improve performance."))
        self.checkbox_disable_hidraw = Gtk.CheckButton(label=_("Disable Hidraw"))
        self.checkbox_disable_hidraw.set_tooltip_text(
            _("May fix controller issues with some games. Only works with GE-Proton10 or Proton-EM-10."))

        # Button for Winecfg
        self.button_winecfg = Gtk.Button(label="Winecfg")
        self.button_winecfg.set_size_request(120, -1)
        self.button_winecfg.connect("clicked", self.on_button_winecfg_clicked)

        # Button for Winetricks
        self.button_winetricks = Gtk.Button(label="Winetricks")
        self.button_winetricks.set_size_request(120, -1)
        self.button_winetricks.connect("clicked", self.on_button_winetricks_clicked)

        # Button for Run
        self.button_run = Gtk.Button(label=_("Run"))
        self.button_run.set_size_request(120, -1)
        self.button_run.connect("clicked", self.on_button_run_clicked)
        self.button_run.set_tooltip_text(_("Run a file inside the prefix"))

        # Button for creating shortcut
        self.label_shortcut = Gtk.Label(label=_("Shortcut"))
        self.label_shortcut.set_margin_start(10)
        self.label_shortcut.set_margin_end(10)
        self.label_shortcut.set_margin_top(10)
        self.label_shortcut.set_halign(Gtk.Align.START)
        self.checkbox_shortcut_desktop = Gtk.CheckButton(label=_("Desktop"))
        self.checkbox_shortcut_desktop.set_tooltip_text(
            _("Add or remove a shortcut from the Desktop."))
        self.checkbox_shortcut_appmenu = Gtk.CheckButton(label=_("App Menu"))
        self.checkbox_shortcut_appmenu.set_tooltip_text(
            _("Add or remove a shortcut from the Application Menu."))
        self.checkbox_shortcut_steam = Gtk.CheckButton(label=_("Steam"))
        self.checkbox_shortcut_steam.set_tooltip_text(
            _("Add or remove a shortcut from Steam. Steam needs to be restarted."))

        # Button for selection shortcut icon
        self.button_shortcut_icon = Gtk.Button()
        self.button_shortcut_icon.set_size_request(120, -1)
        self.button_shortcut_icon.connect("clicked", self.on_button_shortcut_icon_clicked)
        self.button_shortcut_icon.set_tooltip_text(_("Select an icon for the shortcut"))

        # Button Cancel
        self.button_cancel = Gtk.Button(label=_("Cancel"))
        self.button_cancel.connect("clicked", lambda widget: self.response(Gtk.ResponseType.CANCEL))
        self.button_cancel.set_size_request(150, -1)

        # Button Ok
        self.button_ok = Gtk.Button(label=_("Ok"))
        self.button_ok.connect("clicked", lambda widget: self.response(Gtk.ResponseType.OK))
        self.button_ok.set_size_request(150, -1)

        self.load_config()

        self.entry_title.connect("changed", self.update_prefix_entry)

        self.notebook = Gtk.Notebook()
        self.notebook.set_margin_start(10)
        self.notebook.set_margin_end(10)
        self.notebook.set_margin_top(10)
        self.notebook.set_margin_bottom(10)
        # notebook.set_show_border(False)

        self.box.add(self.notebook)

        self.image_banner = Gtk.Image()
        self.image_banner.set_margin_top(10)
        self.image_banner.set_margin_bottom(10)
        self.image_banner.set_margin_start(10)
        self.image_banner.set_margin_end(10)
        self.image_banner.set_vexpand(True)
        self.image_banner.set_valign(Gtk.Align.CENTER)

        self.image_banner2 = Gtk.Image()
        self.image_banner2.set_margin_top(10)
        self.image_banner2.set_margin_bottom(10)
        self.image_banner2.set_margin_start(10)
        self.image_banner2.set_margin_end(10)
        self.image_banner2.set_vexpand(True)
        self.image_banner2.set_valign(Gtk.Align.CENTER)

        event_box = Gtk.EventBox()
        event_box.add(self.image_banner)
        event_box.connect("button-press-event", self.on_image_clicked)

        event_box2 = Gtk.EventBox()
        event_box2.add(self.image_banner2)
        event_box2.connect("button-press-event", self.on_image_clicked)

        self.menu = Gtk.Menu()

        refresh_item = Gtk.MenuItem(label=_("Refresh"))
        refresh_item.connect("activate", self.on_refresh)
        self.menu.append(refresh_item)

        load_item = Gtk.MenuItem(label=_("Load from file"))
        load_item.connect("activate", self.on_load_file)
        self.menu.append(load_item)

        self.menu.show_all()

        page1 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        tab_box1 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        tab_label1 = Gtk.Label(label=_("Game/App"))
        tab_label1.set_width_chars(8)
        tab_label1.set_xalign(0.5)
        tab_box1.pack_start(tab_label1, True, True, 0)
        tab_box1.set_hexpand(True)

        grid_page1.attach(page1, 0, 0, 1, 1)
        if interface_mode == "Banners":
            grid_page1.attach(event_box, 1, 0, 1, 1)
        page1.set_hexpand(True)
        event_box.set_hexpand(True)

        self.notebook.append_page(grid_page1, tab_box1)

        page2 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        tab_box2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        tab_label2 = Gtk.Label(label=_("Tools"))
        tab_label2.set_width_chars(8)
        tab_label2.set_xalign(0.5)
        tab_box2.pack_start(tab_label2, True, True, 0)
        tab_box2.set_hexpand(True)

        grid_page2.attach(page2, 0, 0, 1, 1)
        if interface_mode == "Banners":
            grid_page2.attach(event_box2, 1, 0, 1, 1)
        page2.set_hexpand(True)
        event_box2.set_hexpand(True)

        self.notebook.append_page(grid_page2, tab_box2)

        self.grid_launcher.attach(self.combobox_launcher, 1, 0, 1, 1)
        self.combobox_launcher.set_hexpand(True)
        self.combobox_launcher.set_valign(Gtk.Align.CENTER)

        self.grid_title.attach(self.label_title, 0, 0, 4, 1)
        self.grid_title.attach(self.entry_title, 0, 1, 4, 1)
        self.entry_title.set_hexpand(True)

        self.grid_path.attach(self.label_path, 0, 0, 1, 1)
        self.grid_path.attach(self.entry_path, 0, 1, 3, 1)
        self.entry_path.set_hexpand(True)
        self.grid_path.attach(self.button_search, 3, 1, 1, 1)

        self.grid_prefix.attach(self.label_prefix, 0, 0, 1, 1)
        self.grid_prefix.attach(self.entry_prefix, 0, 1, 3, 1)
        self.entry_prefix.set_hexpand(True)
        self.grid_prefix.attach(self.button_search_prefix, 3, 1, 1, 1)

        self.grid_runner.attach(self.label_runner, 0, 0, 1, 1)
        self.grid_runner.attach(self.combobox_runner, 0, 1, 1, 1)
        self.combobox_runner.set_hexpand(True)

        self.label_shortcut.set_hexpand(True)
        self.grid_shortcut.add(self.checkbox_shortcut_desktop)
        self.grid_shortcut.add(self.checkbox_shortcut_appmenu)
        self.grid_shortcut.add(self.checkbox_shortcut_steam)
        self.grid_shortcut_icon.add(self.button_shortcut_icon)
        self.grid_shortcut_icon.set_valign(Gtk.Align.CENTER)

        self.box_shortcut = Gtk.Box()
        self.box_shortcut.pack_start(self.grid_shortcut, False, False, 0)
        self.box_shortcut.pack_end(self.grid_shortcut_icon, False, False, 0)

        page1.add(self.grid_launcher)
        page1.add(self.grid_title)
        page1.add(self.grid_path)
        page1.add(self.grid_prefix)
        page1.add(self.grid_runner)
        page1.add(self.label_shortcut)
        page1.add(self.box_shortcut)

        self.grid_protonfix.attach(self.label_protonfix, 0, 0, 1, 1)
        self.grid_protonfix.attach(self.entry_protonfix, 0, 1, 3, 1)
        self.entry_protonfix.set_hexpand(True)
        self.grid_protonfix.attach(self.button_search_protonfix, 3, 1, 1, 1)

        self.grid_launch_arguments.attach(self.label_launch_arguments, 0, 0, 4, 1)
        self.grid_launch_arguments.attach(self.entry_launch_arguments, 0, 1, 4, 1)
        self.entry_launch_arguments.set_hexpand(True)

        self.grid_game_arguments.attach(self.label_game_arguments, 0, 0, 4, 1)
        self.grid_game_arguments.attach(self.entry_game_arguments, 0, 1, 4, 1)
        self.entry_game_arguments.set_hexpand(True)

        self.grid_lossless.attach(self.label_lossless, 0, 0, 1, 1)
        self.grid_lossless.attach(self.combobox_lossless, 0, 1, 1, 1)
        self.combobox_lossless.set_hexpand(True)

        self.grid_addapp.attach(self.checkbox_addapp, 0, 0, 1, 1)
        self.grid_addapp.attach(self.entry_addapp, 0, 1, 3, 1)
        self.entry_addapp.set_hexpand(True)
        self.grid_addapp.attach(self.button_search_addapp, 3, 1, 1, 1)

        self.grid_tools.attach(self.checkbox_mangohud, 0, 0, 1, 1)
        self.checkbox_mangohud.set_hexpand(True)
        self.grid_tools.attach(self.checkbox_gamemode, 0, 1, 1, 1)
        self.checkbox_gamemode.set_hexpand(True)
        self.grid_tools.attach(self.checkbox_disable_hidraw, 0, 2, 1, 1)
        self.checkbox_disable_hidraw.set_hexpand(True)
        self.grid_tools.attach(self.button_winetricks, 2, 0, 1, 1)
        self.grid_tools.attach(self.button_winecfg, 2, 1, 1, 1)
        self.grid_tools.attach(self.button_run, 2, 2, 1, 1)

        page2.add(self.grid_protonfix)
        page2.add(self.grid_launch_arguments)
        page2.add(self.grid_game_arguments)
        page2.add(self.grid_addapp)
        page2.add(self.grid_lossless)
        page2.add(self.grid_tools)

        bottom_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        bottom_box.set_margin_start(10)
        bottom_box.set_margin_end(10)
        bottom_box.set_margin_bottom(10)
        self.button_cancel.set_hexpand(True)
        self.button_ok.set_hexpand(True)

        bottom_box.pack_start(self.button_cancel, True, True, 0)
        bottom_box.pack_start(self.button_ok, True, True, 0)

        self.box.add(bottom_box)

        self.populate_combobox_with_launchers()
        self.combobox_launcher.set_active(0)
        self.combobox_launcher.connect("changed", self.on_combobox_changed)

        self.populate_combobox_with_runners()
        self.populate_combobox_with_lossless()
        self.combobox_lossless.set_active(0)

        model = self.combobox_runner.get_model()
        index_to_activate = 0

        if self.default_runner == "":
            self.default_runner = "UMU-Proton Latest"
        if self.default_runner == "GE-Proton":
            self.default_runner = "GE-Proton Latest (default)"
        if self.default_runner == "Proton-EM":
            self.default_runner = "Proton-EM Latest"

        for i, row in enumerate(model):
            if row[0] == self.default_runner:
                index_to_activate = i
                break
        self.combobox_runner.set_active(index_to_activate)

        # Check if optional features are available and enable/disable accordingly
        self.mangohud_enabled = os.path.exists(mangohud_dir)
        if not self.mangohud_enabled:
            self.checkbox_mangohud.set_sensitive(False)
            self.checkbox_mangohud.set_active(False)
            self.checkbox_mangohud.set_tooltip_text(
                _("Shows an overlay for monitoring FPS, temperatures, CPU/GPU load and more. NOT INSTALLED."))

        self.gamemode_enabled = os.path.exists(gamemoderun) or os.path.exists("/usr/games/gamemoderun")
        if not self.gamemode_enabled:
            self.checkbox_gamemode.set_sensitive(False)
            self.checkbox_gamemode.set_active(False)
            self.checkbox_gamemode.set_tooltip_text(_("Tweaks your system to improve performance. NOT INSTALLED."))

        self.updated_steam_id = detect_steam_id()
        if not self.updated_steam_id:
            self.checkbox_shortcut_steam.set_sensitive(False)
            self.checkbox_shortcut_steam.set_tooltip_text(
                _("Add or remove a shortcut from Steam. Steam needs to be restarted. NO STEAM USERS FOUND."))

        self.lossless_location = ConfigManager().config.get('lossless-location', '')
        lossless_dll_path = find_lossless_dll()
        if os.path.exists(lsfgvk_path):
            if lossless_dll_path or os.path.exists(self.lossless_location):
                self.combobox_lossless.set_sensitive(True)
            else:
                self.combobox_lossless.set_sensitive(False)
                self.combobox_lossless.set_active(0)
                self.combobox_lossless.set_tooltip_text(_("Lossless.dll NOT FOUND. If it's installed, go to Faugus Launcher's settings and set the location."))
        else:
            self.combobox_lossless.set_sensitive(False)
            self.combobox_lossless.set_active(0)
            self.combobox_lossless.set_tooltip_text(_("Lossless Scaling Vulkan Layer NOT INSTALLED."))

        self.button_shortcut_icon.set_image(self.set_image_shortcut_icon())

        tab_box1.show_all()
        tab_box2.show_all()
        self.show_all()
        if interface_mode != "Banners":
            self.image_banner.set_visible(False)
            self.image_banner2.set_visible(False)
        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(self.banner_path_temp, 260, 390, True)
        self.image_banner.set_from_pixbuf(pixbuf)
        self.image_banner2.set_from_pixbuf(pixbuf)

    def check_steam_shortcut(self, title):
        if os.path.exists(steam_shortcuts_path):
            try:
                with open(steam_shortcuts_path, 'rb') as f:
                    shortcuts = vdf.binary_load(f)
                for game in shortcuts["shortcuts"].values():
                    if isinstance(game, dict) and "AppName" in game and game["AppName"] == title:
                        return True
                return False
            except SyntaxError:
                return False
        return False

    def on_entry_query_tooltip(self, widget, x, y, keyboard_mode, tooltip):
        current_text = widget.get_text()
        if current_text.strip():
            tooltip.set_text(current_text)
        else:
            tooltip.set_text(widget.get_tooltip_text())
        return True

    def on_image_clicked(self, widget, event):
        self.menu.popup_at_pointer(event)

    def on_refresh(self, widget):
        if self.entry_title.get_text() != "":
            self.get_banner()
        else:
            shutil.copyfile(faugus_banner, self.banner_path_temp)
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(self.banner_path_temp, 260, 390, True)
            self.image_banner.set_from_pixbuf(pixbuf)
            self.image_banner2.set_from_pixbuf(pixbuf)

    def on_load_file(self, widget):
        self.set_sensitive(False)

        def show_error_message(message):
            error_dialog = Gtk.MessageDialog(parent=dialog, flags=0, message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.OK, text=message)
            error_dialog.set_title(_("Invalid Image"))
            error_dialog.run()
            error_dialog.destroy()

        def is_valid_image(file_path):
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file(file_path)
                return pixbuf is not None
            except Exception:
                return False

        dialog = Gtk.Dialog(title=_("Select an image for the banner"), parent=self, flags=0)
        dialog.set_size_request(720, 720)

        filechooser = Gtk.FileChooserWidget(action=Gtk.FileChooserAction.OPEN)
        filechooser.set_current_folder(os.path.expanduser("~/"))
        filechooser.connect("file-activated", lambda widget: dialog.response(Gtk.ResponseType.OK))

        filter_ico = Gtk.FileFilter()
        filter_ico.set_name(_("Image files"))
        filter_ico.add_mime_type("image/*")
        filechooser.set_filter(filter_ico)

        filter_combobox = Gtk.ComboBoxText()
        filter_combobox.append("image", _("Image files"))
        filter_combobox.set_active(0)
        filter_combobox.set_size_request(150, -1)

        button_open = Gtk.Button.new_with_label(_("Open"))
        button_open.set_size_request(150, -1)
        button_open.connect("clicked", lambda w: dialog.response(Gtk.ResponseType.OK))

        button_cancel = Gtk.Button.new_with_label(_("Cancel"))
        button_cancel.set_size_request(150, -1)
        button_cancel.connect("clicked", lambda w: dialog.response(Gtk.ResponseType.CANCEL))

        button_grid = Gtk.Grid()
        button_grid.set_row_spacing(10)
        button_grid.set_column_spacing(10)
        button_grid.set_margin_start(10)
        button_grid.set_margin_end(10)
        button_grid.set_margin_top(10)
        button_grid.set_margin_bottom(10)
        button_grid.attach(button_open, 1, 1, 1, 1)
        button_grid.attach(button_cancel, 0, 1, 1, 1)
        button_grid.attach(filter_combobox, 1, 0, 1, 1)

        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        button_box.pack_end(button_grid, False, False, 0)

        dialog.vbox.pack_start(filechooser, True, True, 0)
        dialog.vbox.pack_start(button_box, False, False, 0)

        filechooser.connect("update-preview", self.update_preview)

        dialog.show_all()

        while True:
            response = dialog.run()
            if response == Gtk.ResponseType.OK:
                file_path = filechooser.get_filename()
                if not file_path or not is_valid_image(file_path):
                    dialog_image = Gtk.Dialog(title="Faugus Launcher", transient_for=dialog, modal=True)
                    dialog_image.set_resizable(False)
                    dialog_image.set_icon_from_file(faugus_png)
                    subprocess.Popen(["canberra-gtk-play", "-f", faugus_notification])

                    label = Gtk.Label()
                    label.set_label(_("The selected file is not a valid image."))
                    label.set_halign(Gtk.Align.CENTER)

                    label2 = Gtk.Label()
                    label2.set_label(_("Please choose another one."))
                    label2.set_halign(Gtk.Align.CENTER)

                    button_yes = Gtk.Button(label=_("Ok"))
                    button_yes.set_size_request(150, -1)
                    button_yes.connect("clicked", lambda x: dialog_image.response(Gtk.ResponseType.YES))

                    content_area = dialog_image.get_content_area()
                    content_area.set_border_width(0)
                    content_area.set_halign(Gtk.Align.CENTER)
                    content_area.set_valign(Gtk.Align.CENTER)
                    content_area.set_vexpand(True)
                    content_area.set_hexpand(True)

                    box_top = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
                    box_top.set_margin_start(20)
                    box_top.set_margin_end(20)
                    box_top.set_margin_top(20)
                    box_top.set_margin_bottom(20)

                    box_bottom = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
                    box_bottom.set_margin_start(10)
                    box_bottom.set_margin_end(10)
                    box_bottom.set_margin_bottom(10)

                    box_top.pack_start(label, True, True, 0)
                    box_top.pack_start(label2, True, True, 0)
                    box_bottom.pack_start(button_yes, True, True, 0)

                    content_area.add(box_top)
                    content_area.add(box_bottom)

                    dialog_image.show_all()
                    dialog_image.run()
                    dialog_image.destroy()
                    continue
                else:
                    shutil.copyfile(file_path, self.banner_path_temp)
                    self.update_image_banner()
                    break
            else:
                break

        dialog.destroy()
        self.set_sensitive(True)

    def get_banner(self):
        def fetch_banner():
            game_name = self.entry_title.get_text().strip()
            if not game_name:
                return

            api_url = f"https://steamgrid.usebottles.com/api/search/{game_name}"
            try:
                response = requests.get(api_url)
                response.raise_for_status()
                image_url = response.text.strip('"')

                with open(self.banner_path_temp, "wb") as image_file:
                    image_file.write(requests.get(image_url).content)

                GLib.idle_add(self.update_image_banner)

            except requests.RequestException as e:
                print(f"Error fetching the banner: {e}")

        # Start the thread
        threading.Thread(target=fetch_banner, daemon=True).start()

    def update_image_banner(self):
        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(self.banner_path_temp, 260, 390, True)
        self.image_banner.set_from_pixbuf(pixbuf)
        self.image_banner2.set_from_pixbuf(pixbuf)

    def on_entry_focus_out(self, entry_title, event):
        if entry_title.get_text() != "":
            self.get_banner()
        else:
            shutil.copyfile(faugus_banner, self.banner_path_temp)
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(self.banner_path_temp, 260, 390, True)
            self.image_banner.set_from_pixbuf(pixbuf)
            self.image_banner2.set_from_pixbuf(pixbuf)

    def on_checkbox_addapp_toggled(self, checkbox):
        is_active = checkbox.get_active()
        self.entry_addapp.set_sensitive(is_active)
        self.button_search_addapp.set_sensitive(is_active)

    def on_button_search_addapp_clicked(self, widget):
        dialog = Gtk.Dialog(title=_("Select an additional application"), parent=self, flags=0)
        dialog.set_size_request(720, 720)

        filechooser = Gtk.FileChooserWidget(action=Gtk.FileChooserAction.OPEN)
        filechooser.set_current_folder(os.path.expanduser("~/"))
        filechooser.connect("file-activated", lambda widget: dialog.response(Gtk.ResponseType.OK))

        windows_filter = Gtk.FileFilter()
        windows_filter.set_name(_("Windows files"))
        windows_filter.add_pattern("*.exe")
        windows_filter.add_pattern("*.msi")
        windows_filter.add_pattern("*.bat")
        windows_filter.add_pattern("*.lnk")
        windows_filter.add_pattern("*.reg")

        all_files_filter = Gtk.FileFilter()
        all_files_filter.set_name(_("All files"))
        all_files_filter.add_pattern("*")

        filter_combobox = Gtk.ComboBoxText()
        filter_combobox.append("windows", _("Windows files"))
        filter_combobox.append("all", _("All files"))
        filter_combobox.set_active(0)
        filter_combobox.set_size_request(150, -1)

        def on_filter_changed(combobox):
            active_id = combobox.get_active_id()
            if active_id == "windows":
                filechooser.set_filter(windows_filter)
            elif active_id == "all":
                filechooser.set_filter(all_files_filter)

        filter_combobox.connect("changed", on_filter_changed)
        filechooser.set_filter(windows_filter)

        button_open = Gtk.Button.new_with_label(_("Open"))
        button_open.connect("clicked", lambda w: dialog.response(Gtk.ResponseType.OK))
        button_open.set_size_request(150, -1)

        button_cancel = Gtk.Button.new_with_label(_("Cancel"))
        button_cancel.connect("clicked", lambda w: dialog.response(Gtk.ResponseType.CANCEL))
        button_cancel.set_size_request(150, -1)

        button_grid = Gtk.Grid()
        button_grid.set_row_spacing(10)
        button_grid.set_column_spacing(10)
        button_grid.set_margin_start(10)
        button_grid.set_margin_end(10)
        button_grid.set_margin_top(10)
        button_grid.set_margin_bottom(10)
        button_grid.attach(button_open, 1, 1, 1, 1)
        button_grid.attach(button_cancel, 0, 1, 1, 1)
        button_grid.attach(filter_combobox, 1, 0, 1, 1)

        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        button_box.pack_end(button_grid, False, False, 0)

        dialog.vbox.pack_start(filechooser, True, True, 0)
        dialog.vbox.pack_start(button_box, False, False, 0)

        dialog.show_all()
        response = dialog.run()

        if response == Gtk.ResponseType.OK:
            self.entry_addapp.set_text(filechooser.get_filename())

        dialog.destroy()

    def on_combobox_changed(self, combobox):
        active_index = combobox.get_active()

        def cleanup_fields():
            self.entry_title.set_text("")
            self.entry_launch_arguments.set_text("")
            self.entry_path.set_text("")
            self.entry_prefix.set_text("")
            self.checkbox_shortcut_desktop.set_active(False)
            self.checkbox_shortcut_appmenu.set_active(False)
            self.checkbox_shortcut_steam.set_active(False)
            self.entry_protonfix.set_text("")
            self.entry_launch_arguments.set_text("")
            self.entry_game_arguments.set_text("")
            self.checkbox_addapp.set_active(False)
            self.entry_addapp.set_text("")
            self.combobox_lossless.set_active(0)
            self.checkbox_mangohud.set_active(False)
            self.checkbox_gamemode.set_active(False)
            self.checkbox_disable_hidraw.set_active(False)

        cleanup_fields()

        if active_index == 0:
            self.grid_title.set_visible(True)
            self.grid_path.set_visible(True)
            self.grid_runner.set_visible(True)
            self.grid_prefix.set_visible(True)
            self.button_winetricks.set_visible(True)
            self.button_winecfg.set_visible(True)
            self.button_run.set_visible(True)
            self.grid_protonfix.set_visible(True)
            self.grid_addapp.set_visible(True)
            self.checkbox_disable_hidraw.set_visible(True)
            self.button_shortcut_icon.set_image(self.set_image_shortcut_icon())
        if active_index == 1:
            self.grid_title.set_visible(True)
            self.grid_path.set_visible(True)
            self.grid_runner.set_visible(False)
            self.grid_prefix.set_visible(False)
            self.button_winetricks.set_visible(False)
            self.button_winecfg.set_visible(False)
            self.button_run.set_visible(False)
            self.grid_protonfix.set_visible(False)
            self.grid_addapp.set_visible(False)
            self.checkbox_disable_hidraw.set_visible(False)
            self.button_shortcut_icon.set_image(self.set_image_shortcut_icon())
        elif active_index == 2:
            self.grid_title.set_visible(False)
            self.grid_path.set_visible(False)
            self.grid_runner.set_visible(True)
            self.grid_prefix.set_visible(True)
            self.button_winetricks.set_visible(True)
            self.button_winecfg.set_visible(True)
            self.button_run.set_visible(True)
            self.grid_protonfix.set_visible(True)
            self.grid_addapp.set_visible(True)
            self.checkbox_disable_hidraw.set_visible(True)
            self.entry_launch_arguments.set_text("WINE_SIMULATE_WRITECOPY=1")
            self.entry_title.set_text(self.combobox_launcher.get_active_text())
            self.entry_path.set_text(
                f"{self.entry_prefix.get_text()}/drive_c/Program Files (x86)/Battle.net/Battle.net.exe")
            shutil.copyfile(battle_icon, os.path.expanduser(self.icon_temp))
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(self.icon_temp)
            scaled_pixbuf = pixbuf.scale_simple(50, 50, GdkPixbuf.InterpType.BILINEAR)
            image = Gtk.Image.new_from_file(self.icon_temp)
            image.set_from_pixbuf(scaled_pixbuf)
            self.button_shortcut_icon.set_image(image)
        elif active_index == 3:
            self.grid_title.set_visible(False)
            self.grid_path.set_visible(False)
            self.grid_runner.set_visible(True)
            self.grid_prefix.set_visible(True)
            self.button_winetricks.set_visible(True)
            self.button_winecfg.set_visible(True)
            self.button_run.set_visible(True)
            self.grid_protonfix.set_visible(True)
            self.grid_addapp.set_visible(True)
            self.checkbox_disable_hidraw.set_visible(True)
            self.entry_title.set_text(self.combobox_launcher.get_active_text())
            self.entry_path.set_text(
                f"{self.entry_prefix.get_text()}/drive_c/Program Files/Electronic Arts/EA Desktop/EA Desktop/EALauncher.exe")
            shutil.copyfile(ea_icon, os.path.expanduser(self.icon_temp))
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(self.icon_temp)
            scaled_pixbuf = pixbuf.scale_simple(50, 50, GdkPixbuf.InterpType.BILINEAR)
            image = Gtk.Image.new_from_file(self.icon_temp)
            image.set_from_pixbuf(scaled_pixbuf)
            self.button_shortcut_icon.set_image(image)
        elif active_index == 4:
            self.grid_title.set_visible(False)
            self.grid_path.set_visible(False)
            self.grid_runner.set_visible(True)
            self.grid_prefix.set_visible(True)
            self.button_winetricks.set_visible(True)
            self.button_winecfg.set_visible(True)
            self.button_run.set_visible(True)
            self.grid_protonfix.set_visible(True)
            self.grid_addapp.set_visible(True)
            self.checkbox_disable_hidraw.set_visible(True)
            self.entry_title.set_text(self.combobox_launcher.get_active_text())
            self.entry_path.set_text(
                f"{self.entry_prefix.get_text()}/drive_c/Program Files (x86)/Epic Games/Launcher/Portal/Binaries/Win32/EpicGamesLauncher.exe")
            shutil.copyfile(epic_icon, os.path.expanduser(self.icon_temp))
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(self.icon_temp)
            scaled_pixbuf = pixbuf.scale_simple(50, 50, GdkPixbuf.InterpType.BILINEAR)
            image = Gtk.Image.new_from_file(self.icon_temp)
            image.set_from_pixbuf(scaled_pixbuf)
            self.button_shortcut_icon.set_image(image)
        elif active_index == 5:
            self.grid_title.set_visible(False)
            self.grid_path.set_visible(False)
            self.grid_runner.set_visible(True)
            self.grid_prefix.set_visible(True)
            self.button_winetricks.set_visible(True)
            self.button_winecfg.set_visible(True)
            self.button_run.set_visible(True)
            self.grid_protonfix.set_visible(True)
            self.grid_addapp.set_visible(True)
            self.checkbox_disable_hidraw.set_visible(True)
            self.entry_title.set_text(self.combobox_launcher.get_active_text())
            self.entry_path.set_text(
                f"{self.entry_prefix.get_text()}/drive_c/Program Files (x86)/Ubisoft/Ubisoft Game Launcher/UbisoftConnect.exe")
            shutil.copyfile(ubisoft_icon, os.path.expanduser(self.icon_temp))
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(self.icon_temp)
            scaled_pixbuf = pixbuf.scale_simple(50, 50, GdkPixbuf.InterpType.BILINEAR)
            image = Gtk.Image.new_from_file(self.icon_temp)
            image.set_from_pixbuf(scaled_pixbuf)
            self.button_shortcut_icon.set_image(image)
        if self.interface_mode == "Banners":
            if self.entry_title.get_text() != "":
                self.get_banner()
            else:
                shutil.copyfile(faugus_banner, self.banner_path_temp)
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(self.banner_path_temp, 260, 390, True)
                self.image_banner.set_from_pixbuf(pixbuf)
                self.image_banner2.set_from_pixbuf(pixbuf)

    def populate_combobox_with_lossless(self):
        self.combobox_lossless.append_text("Off")
        self.combobox_lossless.append_text("X1")
        self.combobox_lossless.append_text("X2")
        self.combobox_lossless.append_text("X3")
        self.combobox_lossless.append_text("X4")

    def populate_combobox_with_launchers(self):
        self.combobox_launcher.append_text(_("Windows Game"))
        self.combobox_launcher.append_text(_("Linux Game"))
        self.combobox_launcher.append_text("Battle.net")
        self.combobox_launcher.append_text("EA App")
        self.combobox_launcher.append_text("Epic Games")
        self.combobox_launcher.append_text("Ubisoft Connect")  # self.combobox_launcher.append_text("HoYoPlay")

    def populate_combobox_with_runners(self):
        # List of default entries
        self.combobox_runner.append_text("GE-Proton Latest (default)")
        self.combobox_runner.append_text("UMU-Proton Latest")
        self.combobox_runner.append_text("Proton-EM Latest")

        # Path to the directory containing the folders
        if IS_FLATPAK:
            runner_path = Path(os.path.expanduser("~/.local/share/Steam/compatibilitytools.d"))
        else:
            runner_path = f'{share_dir}/Steam/compatibilitytools.d/'

        try:
            # Check if the directory exists
            if os.path.exists(runner_path):
                # List to hold version directories
                versions = []
                # Iterate over the folders in the directory
                for entry in os.listdir(runner_path):
                    entry_path = os.path.join(runner_path, entry)
                    # Add to list only if it's a directory and not "UMU-Latest"
                    if os.path.isdir(entry_path) and entry != "UMU-Latest" and entry != "LegacyRuntime":
                        versions.append(entry)

                # Sort versions in descending order
                def version_key(v):
                    # Remove 'GE-Proton' and split the remaining part into segments of digits and non-digits
                    v_parts = re.split(r'(\d+)', v.replace('GE-Proton', ''))
                    # Convert numeric parts to integers for proper sorting
                    return [int(part) if part.isdigit() else part for part in v_parts]

                versions.sort(key=version_key, reverse=True)

                # Add sorted versions to ComboBox
                for version in versions:
                    self.combobox_runner.append_text(version)

        except Exception as e:
            print(f"Error accessing the directory: {e}")

        # Set the active item, if desired
        self.combobox_runner.set_active(0)

        cell_renderer = self.combobox_runner.get_cells()[0]
        cell_renderer.set_property("ellipsize", Pango.EllipsizeMode.END)
        cell_renderer.set_property("max-width-chars", 20)

    def on_entry_changed(self, widget, entry):
        if entry.get_text():
            entry.get_style_context().remove_class("entry")

    def load_config(self):
        cfg = ConfigManager()

        self.default_runner = cfg.config.get('default-runner', '')
        self.default_prefix = cfg.config.get('default-prefix', '')

    def on_button_run_clicked(self, widget):
        self.set_sensitive(False)
        # Handle the click event of the Run button
        validation_result = self.validate_fields(entry="prefix")
        if not validation_result:
            self.set_sensitive(True)
            return

        dialog = Gtk.Dialog(title=_("Select a file to run inside the prefix"), parent=self, flags=0)
        dialog.set_size_request(720, 720)

        filechooser = Gtk.FileChooserWidget(action=Gtk.FileChooserAction.OPEN)
        filechooser.set_current_folder(os.path.expanduser("~/"))
        filechooser.connect("file-activated", lambda widget: dialog.response(Gtk.ResponseType.OK))

        windows_filter = Gtk.FileFilter()
        windows_filter.set_name(_("Windows files"))
        windows_filter.add_pattern("*.exe")
        windows_filter.add_pattern("*.msi")
        windows_filter.add_pattern("*.bat")
        windows_filter.add_pattern("*.lnk")
        windows_filter.add_pattern("*.reg")

        all_files_filter = Gtk.FileFilter()
        all_files_filter.set_name(_("All files"))
        all_files_filter.add_pattern("*")

        filter_combobox = Gtk.ComboBoxText()
        filter_combobox.append("windows", _("Windows files"))
        filter_combobox.append("all", _("All files"))
        filter_combobox.set_active(0)
        filter_combobox.set_size_request(150, -1)

        def on_filter_changed(combobox):
            active_id = combobox.get_active_id()
            if active_id == "windows":
                filechooser.set_filter(windows_filter)
            elif active_id == "all":
                filechooser.set_filter(all_files_filter)

        filter_combobox.connect("changed", on_filter_changed)
        filechooser.set_filter(windows_filter)

        button_open = Gtk.Button.new_with_label(_("Open"))
        button_open.connect("clicked", lambda w: dialog.response(Gtk.ResponseType.OK))
        button_open.set_size_request(150, -1)

        button_cancel = Gtk.Button.new_with_label(_("Cancel"))
        button_cancel.connect("clicked", lambda w: dialog.response(Gtk.ResponseType.CANCEL))
        button_cancel.set_size_request(150, -1)

        button_grid = Gtk.Grid()
        button_grid.set_row_spacing(10)
        button_grid.set_column_spacing(10)
        button_grid.set_margin_start(10)
        button_grid.set_margin_end(10)
        button_grid.set_margin_top(10)
        button_grid.set_margin_bottom(10)
        button_grid.attach(button_open, 1, 1, 1, 1)
        button_grid.attach(button_cancel, 0, 1, 1, 1)
        button_grid.attach(filter_combobox, 1, 0, 1, 1)

        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        button_box.pack_end(button_grid, False, False, 0)

        dialog.vbox.pack_start(filechooser, True, True, 0)
        dialog.vbox.pack_start(button_box, False, False, 0)

        dialog.show_all()

        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            title = self.entry_title.get_text()
            prefix = self.entry_prefix.get_text()
            title_formatted = format_title(title)
            runner = self.combobox_runner.get_active_text()

            if runner == "UMU-Proton Latest":
                runner = ""
            if runner == "GE-Proton Latest (default)":
                runner = "GE-Proton"
            if runner == "Proton-EM Latest":
                runner = "Proton-EM"

            command_parts = []

            # Add command parts if they are not empty
            file_run = filechooser.get_filename()
            if title_formatted:
                command_parts.append(f'FAUGUS_LOG="{title_formatted}"')
            if prefix:
                command_parts.append(f'WINEPREFIX="{prefix}"')
            if title_formatted:
                command_parts.append(f'GAMEID={title_formatted}')
            if runner:
                command_parts.append(f'PROTONPATH={runner}')
            if not file_run.endswith(".reg"):
                command_parts.append(f'"{umu_run}" "{file_run}"')
            else:
                command_parts.append(f'"{umu_run}" regedit "{file_run}"')

            # Join all parts into a single command
            command = ' '.join(command_parts)

            print(command)

            # faugus-run path
            faugus_run_path = faugus_run

            def run_command():
                process = subprocess.Popen([sys.executable, faugus_run_path, command])
                process.wait()
                GLib.idle_add(self.set_sensitive, True)
                GLib.idle_add(self.parent_window.set_sensitive, True)
                GLib.idle_add(self.blocking_window.destroy)

            self.blocking_window = Gtk.Window()
            self.blocking_window.set_transient_for(self.parent_window)
            self.blocking_window.set_decorated(False)
            self.blocking_window.set_modal(True)

            command_thread = threading.Thread(target=run_command)
            command_thread.start()

        else:
            self.set_sensitive(True)
        dialog.destroy()

    def on_button_search_protonfix_clicked(self, widget):
        webbrowser.open("https://umu.openwinecomponents.org/")

    def set_image_shortcut_icon(self):

        image_path = faugus_png
        shutil.copyfile(image_path, self.icon_temp)

        pixbuf = GdkPixbuf.Pixbuf.new_from_file(self.icon_temp)
        scaled_pixbuf = pixbuf.scale_simple(50, 50, GdkPixbuf.InterpType.BILINEAR)

        image = Gtk.Image.new_from_file(self.icon_temp)
        image.set_from_pixbuf(scaled_pixbuf)

        return image

    def on_button_shortcut_icon_clicked(self, widget):
        self.set_sensitive(False)

        validation_result = self.validate_fields(entry="path")
        if not validation_result:
            self.set_sensitive(True)
            return

        path = self.entry_path.get_text()

        if not os.path.exists(self.icon_directory):
            os.makedirs(self.icon_directory)

        try:
            command = f'icoextract "{path}" "{self.icon_extracted}"'
            result = subprocess.run(command, shell=True, text=True, capture_output=True)

            if result.returncode != 0:
                if "NoIconsAvailableError" in result.stderr or "PEFormatError" in result.stderr:
                    print("The file does not contain icons.")
                    self.button_shortcut_icon.set_image(self.set_image_shortcut_icon())
                else:
                    print(f"Error extracting icon: {result.stderr}")
            else:
                command_magick = shutil.which("magick") or shutil.which("convert")
                os.system(f'{command_magick} "{self.icon_extracted}" "{self.icon_converted}"')
                if os.path.isfile(self.icon_extracted):
                    os.remove(self.icon_extracted)

        except Exception as e:
            print(f"An error occurred: {e}")

        def show_error_message(message):
            error_dialog = Gtk.MessageDialog(parent=dialog, flags=0, message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.OK, text=message)
            error_dialog.set_title(_("Invalid Image"))
            error_dialog.run()
            error_dialog.destroy()

        def is_valid_image(file_path):
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file(file_path)
                return pixbuf is not None
            except Exception:
                return False

        dialog = Gtk.Dialog(title=_("Select an icon for the shortcut"), parent=self, flags=0)
        dialog.set_size_request(720, 720)

        filechooser = Gtk.FileChooserWidget(action=Gtk.FileChooserAction.OPEN)
        filechooser.set_current_folder(os.path.expanduser("~/"))
        filechooser.connect("file-activated", lambda widget: dialog.response(Gtk.ResponseType.OK))

        filter_ico = Gtk.FileFilter()
        filter_ico.set_name(_("Image files"))
        filter_ico.add_mime_type("image/*")
        filechooser.set_filter(filter_ico)

        filter_combobox = Gtk.ComboBoxText()
        filter_combobox.append("image", _("Image files"))
        filter_combobox.set_active(0)
        filter_combobox.set_size_request(150, -1)

        button_open = Gtk.Button.new_with_label(_("Open"))
        button_open.set_size_request(150, -1)
        button_open.connect("clicked", lambda w: dialog.response(Gtk.ResponseType.OK))

        button_cancel = Gtk.Button.new_with_label(_("Cancel"))
        button_cancel.set_size_request(150, -1)
        button_cancel.connect("clicked", lambda w: dialog.response(Gtk.ResponseType.CANCEL))

        button_grid = Gtk.Grid()
        button_grid.set_row_spacing(10)
        button_grid.set_column_spacing(10)
        button_grid.set_margin_start(10)
        button_grid.set_margin_end(10)
        button_grid.set_margin_top(10)
        button_grid.set_margin_bottom(10)
        button_grid.attach(button_open, 1, 1, 1, 1)
        button_grid.attach(button_cancel, 0, 1, 1, 1)
        button_grid.attach(filter_combobox, 1, 0, 1, 1)

        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        button_box.pack_end(button_grid, False, False, 0)

        dialog.vbox.pack_start(filechooser, True, True, 0)
        dialog.vbox.pack_start(button_box, False, False, 0)

        filechooser.set_current_folder(self.icon_directory)
        filechooser.connect("update-preview", self.update_preview)

        dialog.show_all()

        while True:
            response = dialog.run()
            if response == Gtk.ResponseType.OK:
                file_path = filechooser.get_filename()
                if not file_path or not is_valid_image(file_path):
                    dialog_image = Gtk.Dialog(title="Faugus Launcher", transient_for=dialog, modal=True)
                    dialog_image.set_resizable(False)
                    dialog_image.set_icon_from_file(faugus_png)
                    subprocess.Popen(["canberra-gtk-play", "-f", faugus_notification])

                    label = Gtk.Label()
                    label.set_label(_("The selected file is not a valid image."))
                    label.set_halign(Gtk.Align.CENTER)

                    label2 = Gtk.Label()
                    label2.set_label(_("Please choose another one."))
                    label2.set_halign(Gtk.Align.CENTER)

                    button_yes = Gtk.Button(label=_("Ok"))
                    button_yes.set_size_request(150, -1)
                    button_yes.connect("clicked", lambda x: dialog_image.response(Gtk.ResponseType.YES))

                    content_area = dialog_image.get_content_area()
                    content_area.set_border_width(0)
                    content_area.set_halign(Gtk.Align.CENTER)
                    content_area.set_valign(Gtk.Align.CENTER)
                    content_area.set_vexpand(True)
                    content_area.set_hexpand(True)

                    box_top = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
                    box_top.set_margin_start(20)
                    box_top.set_margin_end(20)
                    box_top.set_margin_top(20)
                    box_top.set_margin_bottom(20)

                    box_bottom = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
                    box_bottom.set_margin_start(10)
                    box_bottom.set_margin_end(10)
                    box_bottom.set_margin_bottom(10)

                    box_top.pack_start(label, True, True, 0)
                    box_top.pack_start(label2, True, True, 0)
                    box_bottom.pack_start(button_yes, True, True, 0)

                    content_area.add(box_top)
                    content_area.add(box_bottom)

                    dialog_image.show_all()
                    dialog_image.run()
                    dialog_image.destroy()
                    continue
                else:
                    shutil.copyfile(file_path, self.icon_temp)
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file(self.icon_temp)
                    scaled_pixbuf = pixbuf.scale_simple(50, 50, GdkPixbuf.InterpType.BILINEAR)
                    image = Gtk.Image.new_from_file(self.icon_temp)
                    image.set_from_pixbuf(scaled_pixbuf)
                    self.button_shortcut_icon.set_image(image)
                    break
            else:
                break

        if os.path.isdir(self.icon_directory):
            shutil.rmtree(self.icon_directory)
        dialog.destroy()
        self.set_sensitive(True)

    def find_largest_resolution(self, directory):
        largest_image = None
        largest_resolution = (0, 0)  # (width, height)

        # Define a set of valid image extensions
        valid_image_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff'}

        for file_name in os.listdir(directory):
            file_path = os.path.join(directory, file_name)
            if os.path.isfile(file_path):
                # Check if the file has a valid image extension
                if os.path.splitext(file_name)[1].lower() in valid_image_extensions:
                    try:
                        with Image.open(file_path) as img:
                            width, height = img.size
                            if width * height > largest_resolution[0] * largest_resolution[1]:
                                largest_resolution = (width, height)
                                largest_image = file_path
                    except IOError:
                        print(f"Unable to open {file_path}")

        return largest_image

    def update_preview(self, dialog):
        if file_path := dialog.get_preview_filename():
            try:
                # Create an image widget for the thumbnail
                pixbuf = GdkPixbuf.Pixbuf.new_from_file(file_path)

                # Resize the thumbnail if it's too large, maintaining the aspect ratio
                max_width = 400
                max_height = 400
                width = pixbuf.get_width()
                height = pixbuf.get_height()

                if width > max_width or height > max_height:
                    # Calculate the new width and height while maintaining the aspect ratio
                    ratio = min(max_width / width, max_height / height)
                    new_width = int(width * ratio)
                    new_height = int(height * ratio)
                    pixbuf = pixbuf.scale_simple(new_width, new_height, GdkPixbuf.InterpType.BILINEAR)

                image = Gtk.Image.new_from_pixbuf(pixbuf)
                dialog.set_preview_widget(image)
                dialog.set_preview_widget_active(True)
                dialog.get_preview_widget().set_size_request(max_width, max_height)
            except GLib.Error:
                dialog.set_preview_widget_active(False)
        else:
            dialog.set_preview_widget_active(False)

    def check_existing_shortcut(self):
        # Check if the shortcut already exists and mark or unmark the checkbox
        title = self.entry_title.get_text().strip()
        if not title:
            return  # If there's no title, there's no shortcut to check

        title_formatted = format_title(title)
        desktop_file_path = f"{desktop_dir}/{title_formatted}.desktop"
        applications_shortcut_path = f"{app_dir}/{title_formatted}.desktop"

        # Mark the checkbox if the shortcut exists
        self.checkbox_shortcut_desktop.set_active(os.path.exists(desktop_file_path))
        self.checkbox_shortcut_appmenu.set_active(os.path.exists(applications_shortcut_path))

    def update_prefix_entry(self, entry):
        # Update the prefix entry based on the title and self.default_prefix
        title_formatted = format_title(entry.get_text())
        prefix = os.path.expanduser(self.default_prefix) + "/" + title_formatted
        self.entry_prefix.set_text(prefix)

    def on_button_winecfg_clicked(self, widget):
        self.set_sensitive(False)
        # Handle the click event of the Winetricks button
        validation_result = self.validate_fields(entry="prefix")
        if not validation_result:
            self.set_sensitive(True)
            return

        title = self.entry_title.get_text()
        prefix = self.entry_prefix.get_text()
        title_formatted = format_title(title)
        runner = self.combobox_runner.get_active_text()

        if runner == "UMU-Proton Latest":
            runner = ""
        if runner == "GE-Proton Latest (default)":
            runner = "GE-Proton"
        if runner == "Proton-EM Latest":
            runner = "Proton-EM"

        command_parts = []

        # Add command parts if they are not empty
        if title_formatted:
            command_parts.append(f'FAUGUS_LOG="{title_formatted}"')
        if prefix:
            command_parts.append(f'WINEPREFIX="{prefix}"')
        if title_formatted:
            command_parts.append(f'GAMEID={title_formatted}')
        if runner:
            command_parts.append(f'PROTONPATH={runner}')

        # Add the fixed command and remaining arguments
        command_parts.append(f'"{umu_run}"')
        command_parts.append('"winecfg"')

        # Join all parts into a single command
        command = ' '.join(command_parts)

        print(command)

        # faugus-run path
        faugus_run_path = faugus_run

        def run_command():
            process = subprocess.Popen([sys.executable, faugus_run_path, command])
            process.wait()
            GLib.idle_add(self.set_sensitive, True)
            GLib.idle_add(self.parent_window.set_sensitive, True)
            GLib.idle_add(self.blocking_window.destroy)

        self.blocking_window = Gtk.Window()
        self.blocking_window.set_transient_for(self.parent_window)
        self.blocking_window.set_decorated(False)
        self.blocking_window.set_modal(True)

        command_thread = threading.Thread(target=run_command)
        command_thread.start()

    def on_button_winetricks_clicked(self, widget):
        self.set_sensitive(False)
        # Handle the click event of the Winetricks button
        validation_result = self.validate_fields(entry="prefix")
        if not validation_result:
            self.set_sensitive(True)
            return

        title = self.entry_title.get_text()
        prefix = self.entry_prefix.get_text()
        title_formatted = format_title(title)
        runner = self.combobox_runner.get_active_text()

        if runner == "UMU-Proton Latest":
            runner = ""
        if runner == "GE-Proton Latest (default)":
            runner = "GE-Proton"
        if runner == "Proton-EM Latest":
            runner = "Proton-EM"

        command_parts = []

        # Add command parts if they are not empty
        if title_formatted:
            command_parts.append(f'FAUGUS_LOG="{title_formatted}"')
        if prefix:
            command_parts.append(f'WINEPREFIX="{prefix}"')
        command_parts.append(f'GAMEID=winetricks-gui')
        command_parts.append(f'STORE=none')
        if runner:
            command_parts.append(f'PROTONPATH={runner}')

        # Add the fixed command and remaining arguments
        command_parts.append(f'"{umu_run}"')
        command_parts.append('""')

        # Join all parts into a single command
        command = ' '.join(command_parts)

        print(command)

        # faugus-run path
        faugus_run_path = faugus_run

        def run_command():
            process = subprocess.Popen([sys.executable, faugus_run_path, command, "winetricks"])
            process.wait()
            GLib.idle_add(self.set_sensitive, True)
            GLib.idle_add(self.parent_window.set_sensitive, True)
            GLib.idle_add(self.blocking_window.destroy)

        self.blocking_window = Gtk.Window()
        self.blocking_window.set_transient_for(self.parent_window)
        self.blocking_window.set_decorated(False)
        self.blocking_window.set_modal(True)

        command_thread = threading.Thread(target=run_command)
        command_thread.start()

    def on_button_search_clicked(self, widget):
        dialog = Gtk.Dialog(title=_("Select the game's .exe"), parent=self, flags=0)
        dialog.set_size_request(720, 720)

        filechooser = Gtk.FileChooserWidget(action=Gtk.FileChooserAction.OPEN)
        filechooser.set_current_folder(os.path.expanduser("~/"))
        filechooser.connect("file-activated", lambda widget: dialog.response(Gtk.ResponseType.OK))

        if self.combobox_launcher.get_active() != 1:
            windows_filter = Gtk.FileFilter()
            windows_filter.set_name(_("Windows files"))
            windows_filter.add_pattern("*.exe")
            windows_filter.add_pattern("*.msi")
            windows_filter.add_pattern("*.bat")
            windows_filter.add_pattern("*.lnk")
            windows_filter.add_pattern("*.reg")

            all_files_filter = Gtk.FileFilter()
            all_files_filter.set_name(_("All files"))
            all_files_filter.add_pattern("*")

            filter_combobox = Gtk.ComboBoxText()
            filter_combobox.append("windows", _("Windows files"))
            filter_combobox.append("all", _("All files"))
            filter_combobox.set_active(0)
            filter_combobox.set_size_request(150, -1)

            def on_filter_changed(combobox):
                active_id = combobox.get_active_id()
                if active_id == "windows":
                    filechooser.set_filter(windows_filter)
                elif active_id == "all":
                    filechooser.set_filter(all_files_filter)

            filter_combobox.connect("changed", on_filter_changed)
            filechooser.set_filter(windows_filter)

        button_open = Gtk.Button.new_with_label(_("Open"))
        button_open.connect("clicked", lambda w: dialog.response(Gtk.ResponseType.OK))
        button_open.set_size_request(150, -1)

        button_cancel = Gtk.Button.new_with_label(_("Cancel"))
        button_cancel.connect("clicked", lambda w: dialog.response(Gtk.ResponseType.CANCEL))
        button_cancel.set_size_request(150, -1)

        button_grid = Gtk.Grid()
        button_grid.set_row_spacing(10)
        button_grid.set_column_spacing(10)
        button_grid.set_margin_start(10)
        button_grid.set_margin_end(10)
        button_grid.set_margin_top(10)
        button_grid.set_margin_bottom(10)
        button_grid.attach(button_open, 1, 1, 1, 1)
        button_grid.attach(button_cancel, 0, 1, 1, 1)
        if self.combobox_launcher.get_active() != 1:
            button_grid.attach(filter_combobox, 1, 0, 1, 1)

        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        button_box.pack_end(button_grid, False, False, 0)

        dialog.vbox.pack_start(filechooser, True, True, 0)
        dialog.vbox.pack_start(button_box, False, False, 0)

        dialog.show_all()

        if not self.entry_path.get_text():
            filechooser.set_current_folder(os.path.expanduser("~/"))
        else:
            filechooser.set_current_folder(os.path.dirname(self.entry_path.get_text()))

        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            path = filechooser.get_filename()

            if not os.path.exists(self.icon_directory):
                os.makedirs(self.icon_directory)

            try:
                # Attempt to extract the icon
                command = f'icoextract "{path}" "{self.icon_extracted}"'
                result = subprocess.run(command, shell=True, text=True, capture_output=True)

                # Check if there was an error in executing the command
                if result.returncode != 0:
                    if "NoIconsAvailableError" in result.stderr or "PEFormatError" in result.stderr:
                        print("The file does not contain icons.")
                        self.button_shortcut_icon.set_image(self.set_image_shortcut_icon())
                    else:
                        print(f"Error extracting icon: {result.stderr}")
                else:
                    # Convert the extracted icon to PNG
                    command_magick = shutil.which("magick") or shutil.which("convert")
                    os.system(f'{command_magick} "{self.icon_extracted}" "{self.icon_converted}"')
                    if os.path.isfile(self.icon_extracted):
                        os.remove(self.icon_extracted)

                    largest_image = self.find_largest_resolution(self.icon_directory)
                    shutil.move(largest_image, os.path.expanduser(self.icon_temp))

                    pixbuf = GdkPixbuf.Pixbuf.new_from_file(self.icon_temp)
                    scaled_pixbuf = pixbuf.scale_simple(50, 50, GdkPixbuf.InterpType.BILINEAR)
                    image = Gtk.Image.new_from_file(self.icon_temp)
                    image.set_from_pixbuf(scaled_pixbuf)

                    self.button_shortcut_icon.set_image(image)

            except Exception as e:
                print(f"An error occurred: {e}")

            self.entry_path.set_text(filechooser.get_filename())

        if os.path.isdir(self.icon_directory):
            shutil.rmtree(self.icon_directory)

        dialog.destroy()

    def on_button_search_prefix_clicked(self, widget):
        dialog = Gtk.Dialog(title=_("Select a prefix location"), parent=self, flags=0)
        dialog.set_size_request(720, 720)

        filechooser = Gtk.FileChooserWidget(action=Gtk.FileChooserAction.SELECT_FOLDER)
        filechooser.set_current_folder(os.path.expanduser(self.default_prefix))
        filechooser.connect("file-activated", lambda widget: dialog.response(Gtk.ResponseType.OK))

        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        button_box.set_margin_start(10)
        button_box.set_margin_end(10)
        button_box.set_margin_top(10)
        button_box.set_margin_bottom(10)

        button_open = Gtk.Button.new_with_label(_("Open"))
        button_open.connect("clicked", lambda w: dialog.response(Gtk.ResponseType.OK))
        button_open.set_size_request(150, -1)
        button_box.pack_end(button_open, False, False, 0)

        button_cancel = Gtk.Button.new_with_label(_("Cancel"))
        button_cancel.connect("clicked", lambda w: dialog.response(Gtk.ResponseType.CANCEL))
        button_cancel.set_size_request(150, -1)
        button_box.pack_end(button_cancel, False, False, 0)

        dialog.vbox.pack_start(filechooser, True, True, 0)
        dialog.vbox.pack_start(button_box, False, False, 0)

        if not self.entry_prefix.get_text():
            filechooser.set_current_folder(os.path.expanduser(self.default_prefix))
        else:
            filechooser.set_current_folder(self.entry_prefix.get_text())

        dialog.show_all()
        response = dialog.run()

        if response == Gtk.ResponseType.OK:
            new_prefix = filechooser.get_filename()
            self.default_prefix = new_prefix
            # self.entry_title.emit("changed")
            self.entry_prefix.set_text(self.default_prefix)

        dialog.destroy()

    def validate_fields(self, entry):
        # Validate the input fields for title, prefix and path
        title = self.entry_title.get_text()
        prefix = self.entry_prefix.get_text()
        path = self.entry_path.get_text()

        self.entry_title.get_style_context().remove_class("entry")
        self.entry_prefix.get_style_context().remove_class("entry")
        self.entry_path.get_style_context().remove_class("entry")

        if entry == "prefix":
            if not title or not prefix:
                if not title:
                    self.entry_title.get_style_context().add_class("entry")
                    self.notebook.set_current_page(0)

                if not prefix:
                    self.entry_prefix.get_style_context().add_class("entry")
                    self.notebook.set_current_page(0)

                return False

        if entry == "path":
            if not title or not path:
                if not title:
                    self.entry_title.get_style_context().add_class("entry")
                    self.notebook.set_current_page(0)

                if not path:
                    self.entry_path.get_style_context().add_class("entry")
                    self.notebook.set_current_page(0)

                return False

        if entry == "path+prefix":
            if not title or not path or not prefix:
                if not title:
                    self.entry_title.get_style_context().add_class("entry")
                    self.notebook.set_current_page(0)

                if not path:
                    self.entry_path.get_style_context().add_class("entry")
                    self.notebook.set_current_page(0)

                if not prefix:
                    self.entry_prefix.get_style_context().add_class("entry")
                    self.notebook.set_current_page(0)

                return False

        return True


class CreateShortcut(Gtk.Window):
    def __init__(self, file_path):
        super().__init__(title="Faugus Launcher")
        self.file_path = file_path
        self.set_resizable(False)
        self.set_icon_from_file(faugus_png)

        game_title = os.path.basename(file_path)
        self.set_title(game_title)
        print(self.file_path)

        self.icon_directory = f"{icons_dir}/icon_temp/"

        if not os.path.exists(self.icon_directory):
            os.makedirs(self.icon_directory)

        self.icons_path = icons_dir
        self.icon_extracted = os.path.expanduser(f'{self.icons_path}/icon_temp/icon.ico')
        self.icon_converted = os.path.expanduser(f'{self.icons_path}/icon_temp/icon.png')
        self.icon_temp = f'{self.icons_path}/icon_temp.ico'

        self.default_prefix = ""

        self.label_title = Gtk.Label(label=_("Title"))
        self.label_title.set_halign(Gtk.Align.START)
        self.entry_title = Gtk.Entry()
        self.entry_title.connect("changed", self.on_entry_changed, self.entry_title)
        self.entry_title.set_tooltip_text(_("Game Title"))

        self.label_protonfix = Gtk.Label(label="Protonfix")
        self.label_protonfix.set_halign(Gtk.Align.START)
        self.entry_protonfix = Gtk.Entry()
        self.entry_protonfix.set_tooltip_text("UMU ID")
        self.button_search_protonfix = Gtk.Button()
        self.button_search_protonfix.set_image(
            Gtk.Image.new_from_icon_name("system-search-symbolic", Gtk.IconSize.BUTTON))
        self.button_search_protonfix.connect("clicked", self.on_button_search_protonfix_clicked)
        self.button_search_protonfix.set_size_request(50, -1)

        self.label_launch_arguments = Gtk.Label(label=_("Launch Arguments"))
        self.label_launch_arguments.set_halign(Gtk.Align.START)
        self.entry_launch_arguments = Gtk.Entry()
        self.entry_launch_arguments.set_tooltip_text(_("e.g.: PROTON_USE_WINED3D=1 gamescope -W 2560 -H 1440"))

        self.label_game_arguments = Gtk.Label(label=_("Game Arguments"))
        self.label_game_arguments.set_halign(Gtk.Align.START)
        self.entry_game_arguments = Gtk.Entry()
        self.entry_game_arguments.set_tooltip_text(_("e.g.: -d3d11 -fullscreen"))

        self.label_lossless = Gtk.Label(label=_("Lossless Scaling Frame Generation"))
        self.label_lossless.set_halign(Gtk.Align.START)
        self.combobox_lossless = Gtk.ComboBoxText()

        self.label_addapp = Gtk.Label(label=_("Additional Application"))
        self.label_addapp.set_halign(Gtk.Align.START)
        self.entry_addapp = Gtk.Entry()
        self.entry_addapp.set_tooltip_text(_("/path/to/the/app"))
        self.button_search_addapp = Gtk.Button()
        self.button_search_addapp.set_image(Gtk.Image.new_from_icon_name("system-search-symbolic", Gtk.IconSize.BUTTON))
        self.button_search_addapp.connect("clicked", self.on_button_search_addapp_clicked)
        self.button_search_addapp.set_size_request(50, -1)

        self.button_shortcut_icon = Gtk.Button()
        self.button_shortcut_icon.set_size_request(120, -1)
        self.button_shortcut_icon.set_tooltip_text(_("Select an icon for the shortcut"))
        self.button_shortcut_icon.connect("clicked", self.on_button_shortcut_icon_clicked)

        self.checkbox_mangohud = Gtk.CheckButton(label="MangoHud")
        self.checkbox_mangohud.set_tooltip_text(
            _("Shows an overlay for monitoring FPS, temperatures, CPU/GPU load and more."))
        self.checkbox_gamemode = Gtk.CheckButton(label="GameMode")
        self.checkbox_gamemode.set_tooltip_text(_("Tweaks your system to improve performance."))
        self.checkbox_disable_hidraw = Gtk.CheckButton(label=_("Disable Hidraw"))
        self.checkbox_disable_hidraw.set_tooltip_text(
            _("May fix controller issues with some games. Only works with GE-Proton10 or Proton-EM-10."))

        # Button Cancel
        self.button_cancel = Gtk.Button(label=_("Cancel"))
        self.button_cancel.connect("clicked", self.on_cancel_clicked)
        self.button_cancel.set_size_request(150, -1)

        # Button Ok
        self.button_ok = Gtk.Button(label=_("Ok"))
        self.button_ok.connect("clicked", self.on_ok_clicked)
        self.button_ok.set_size_request(150, -1)

        css_provider = Gtk.CssProvider()
        css = """
        .entry {
            border-color: Red;
        }
        """
        css_provider.load_from_data(css.encode('utf-8'))
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), css_provider,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_USER)

        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.box.set_margin_start(0)
        self.box.set_margin_end(0)
        self.box.set_margin_top(0)
        self.box.set_margin_bottom(0)

        frame = Gtk.Frame()
        frame.set_margin_start(10)
        frame.set_margin_end(10)
        frame.set_margin_top(10)
        frame.set_margin_bottom(10)

        self.grid_title = Gtk.Grid()
        self.grid_title.set_row_spacing(10)
        self.grid_title.set_column_spacing(10)
        self.grid_title.set_margin_start(10)
        self.grid_title.set_margin_end(10)
        self.grid_title.set_margin_top(10)

        self.grid_protonfix = Gtk.Grid()
        self.grid_protonfix.set_row_spacing(10)
        self.grid_protonfix.set_column_spacing(10)
        self.grid_protonfix.set_margin_start(10)
        self.grid_protonfix.set_margin_end(10)
        self.grid_protonfix.set_margin_top(10)

        self.grid_launch_arguments = Gtk.Grid()
        self.grid_launch_arguments.set_row_spacing(10)
        self.grid_launch_arguments.set_column_spacing(10)
        self.grid_launch_arguments.set_margin_start(10)
        self.grid_launch_arguments.set_margin_end(10)
        self.grid_launch_arguments.set_margin_top(10)

        self.grid_game_arguments = Gtk.Grid()
        self.grid_game_arguments.set_row_spacing(10)
        self.grid_game_arguments.set_column_spacing(10)
        self.grid_game_arguments.set_margin_start(10)
        self.grid_game_arguments.set_margin_end(10)
        self.grid_game_arguments.set_margin_top(10)

        self.grid_lossless = Gtk.Grid()
        self.grid_lossless.set_row_spacing(10)
        self.grid_lossless.set_column_spacing(10)
        self.grid_lossless.set_margin_start(10)
        self.grid_lossless.set_margin_end(10)
        self.grid_lossless.set_margin_top(10)

        self.grid_addapp = Gtk.Grid()
        self.grid_addapp.set_row_spacing(10)
        self.grid_addapp.set_column_spacing(10)
        self.grid_addapp.set_margin_start(10)
        self.grid_addapp.set_margin_end(10)
        self.grid_addapp.set_margin_top(10)

        self.grid_title.attach(self.label_title, 0, 0, 4, 1)
        self.grid_title.attach(self.entry_title, 0, 1, 4, 1)
        self.entry_title.set_hexpand(True)

        self.grid_protonfix.attach(self.label_protonfix, 0, 0, 1, 1)
        self.grid_protonfix.attach(self.entry_protonfix, 0, 1, 3, 1)
        self.entry_protonfix.set_hexpand(True)
        self.grid_protonfix.attach(self.button_search_protonfix, 3, 1, 1, 1)

        self.grid_launch_arguments.attach(self.label_launch_arguments, 0, 0, 4, 1)
        self.grid_launch_arguments.attach(self.entry_launch_arguments, 0, 1, 4, 1)
        self.entry_launch_arguments.set_hexpand(True)

        self.grid_game_arguments.attach(self.label_game_arguments, 0, 0, 4, 1)
        self.grid_game_arguments.attach(self.entry_game_arguments, 0, 1, 4, 1)
        self.entry_game_arguments.set_hexpand(True)

        self.grid_addapp.attach(self.label_addapp, 0, 0, 1, 1)
        self.grid_addapp.attach(self.entry_addapp, 0, 1, 3, 1)
        self.entry_addapp.set_hexpand(True)
        self.grid_addapp.attach(self.button_search_addapp, 3, 1, 1, 1)

        self.grid_lossless.attach(self.label_lossless, 0, 0, 1, 1)
        self.grid_lossless.attach(self.combobox_lossless, 0, 1, 1, 1)
        self.combobox_lossless.set_hexpand(True)

        self.grid_tools = Gtk.Grid(orientation=Gtk.Orientation.VERTICAL)
        self.grid_tools.set_row_spacing(10)
        self.grid_tools.set_column_spacing(10)
        self.grid_tools.set_margin_start(10)
        self.grid_tools.set_margin_end(10)
        self.grid_tools.set_margin_top(10)
        self.grid_tools.set_margin_bottom(10)

        self.grid_shortcut_icon = Gtk.Grid(orientation=Gtk.Orientation.VERTICAL)
        self.grid_shortcut_icon.set_row_spacing(10)
        self.grid_shortcut_icon.set_column_spacing(10)
        self.grid_shortcut_icon.set_margin_start(10)
        self.grid_shortcut_icon.set_margin_end(10)
        self.grid_shortcut_icon.set_margin_top(10)
        self.grid_shortcut_icon.set_margin_bottom(10)

        self.grid_tools.add(self.checkbox_mangohud)
        self.grid_tools.add(self.checkbox_gamemode)
        self.grid_tools.add(self.checkbox_disable_hidraw)

        self.grid_shortcut_icon.add(self.button_shortcut_icon)
        self.grid_shortcut_icon.set_valign(Gtk.Align.CENTER)

        self.box_tools = Gtk.Box()
        self.box_tools.pack_start(self.grid_tools, False, False, 0)
        self.box_tools.pack_end(self.grid_shortcut_icon, False, False, 0)

        bottom_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        bottom_box.set_margin_start(10)
        bottom_box.set_margin_end(10)
        # botton_box.set_margin_top(10)
        bottom_box.set_margin_bottom(10)

        self.button_cancel.set_hexpand(True)
        self.button_ok.set_hexpand(True)

        bottom_box.pack_start(self.button_cancel, True, True, 0)
        bottom_box.pack_start(self.button_ok, True, True, 0)

        self.main_grid = Gtk.Grid(orientation=Gtk.Orientation.VERTICAL)
        self.main_grid.add(self.grid_title)
        self.main_grid.add(self.grid_protonfix)
        self.main_grid.add(self.grid_launch_arguments)
        self.main_grid.add(self.grid_game_arguments)
        self.main_grid.add(self.grid_addapp)
        self.main_grid.add(self.grid_lossless)
        self.main_grid.add(self.box_tools)

        self.load_config()
        self.populate_combobox_with_lossless()

        self.mangohud_enabled = os.path.exists(mangohud_dir)
        if not self.mangohud_enabled:
            self.checkbox_mangohud.set_sensitive(False)
            self.checkbox_mangohud.set_active(False)
            self.checkbox_mangohud.set_tooltip_text(
                _("Shows an overlay for monitoring FPS, temperatures, CPU/GPU load and more. NOT INSTALLED."))

        self.gamemode_enabled = os.path.exists(gamemoderun) or os.path.exists("/usr/games/gamemoderun")
        if not self.gamemode_enabled:
            self.checkbox_gamemode.set_sensitive(False)
            self.checkbox_gamemode.set_active(False)
            self.checkbox_gamemode.set_tooltip_text(_("Tweaks your system to improve performance. NOT INSTALLED."))

        lossless_dll_path = find_lossless_dll()
        if os.path.exists(lsfgvk_path):
            if lossless_dll_path or os.path.exists(self.lossless_location):
                self.combobox_lossless.set_sensitive(True)
            else:
                self.combobox_lossless.set_sensitive(False)
                self.combobox_lossless.set_active(0)
                self.combobox_lossless.set_tooltip_text(_("Lossless.dll NOT FOUND. If it's installed, go to Faugus Launcher's settings and set the location."))
        else:
            self.combobox_lossless.set_sensitive(False)
            self.combobox_lossless.set_active(0)
            self.combobox_lossless.set_tooltip_text(_("Lossless Scaling Vulkan Layer NOT INSTALLED."))

        frame.add(self.main_grid)
        self.box.add(frame)
        self.box.add(bottom_box)
        self.add(self.box)
        self.combobox_lossless.set_active(0)

        if not os.path.exists(self.icon_directory):
            os.makedirs(self.icon_directory)

        try:
            # Attempt to extract the icon
            command = f'icoextract "{file_path}" "{self.icon_extracted}"'
            result = subprocess.run(command, shell=True, text=True, capture_output=True)

            # Check if there was an error in executing the command
            if result.returncode != 0:
                if "NoIconsAvailableError" in result.stderr or "PEFormatError" in result.stderr:
                    print("The file does not contain icons.")
                    self.button_shortcut_icon.set_image(self.set_image_shortcut_icon())
                else:
                    print(f"Error extracting icon: {result.stderr}")
            else:
                # Convert the extracted icon to PNG
                command_magick = shutil.which("magick") or shutil.which("convert")
                os.system(f'{command_magick} "{self.icon_extracted}" "{self.icon_converted}"')
                if os.path.isfile(self.icon_extracted):
                    os.remove(self.icon_extracted)

                largest_image = self.find_largest_resolution(self.icon_directory)
                shutil.move(largest_image, os.path.expanduser(self.icon_temp))

                pixbuf = GdkPixbuf.Pixbuf.new_from_file(self.icon_temp)
                scaled_pixbuf = pixbuf.scale_simple(50, 50, GdkPixbuf.InterpType.BILINEAR)
                image = Gtk.Image.new_from_file(self.icon_temp)
                image.set_from_pixbuf(scaled_pixbuf)

                self.button_shortcut_icon.set_image(image)

        except Exception as e:
            print(f"An error occurred: {e}")

        shutil.rmtree(self.icon_directory)

        # Connect the destroy signal to Gtk.main_quit
        self.connect("destroy", Gtk.main_quit)

    def populate_combobox_with_lossless(self):
        self.combobox_lossless.append_text("Off")
        self.combobox_lossless.append_text("X1")
        self.combobox_lossless.append_text("X2")
        self.combobox_lossless.append_text("X3")
        self.combobox_lossless.append_text("X4")

    def on_button_search_addapp_clicked(self, widget):
        dialog = Gtk.Dialog(title=_("Select an additional application"), parent=self, flags=0)
        dialog.set_size_request(720, 720)

        filechooser = Gtk.FileChooserWidget(action=Gtk.FileChooserAction.OPEN)
        filechooser.set_current_folder(os.path.expanduser("~/"))
        filechooser.connect("file-activated", lambda widget: dialog.response(Gtk.ResponseType.OK))

        windows_filter = Gtk.FileFilter()
        windows_filter.set_name(_("Windows files"))
        windows_filter.add_pattern("*.exe")
        windows_filter.add_pattern("*.msi")
        windows_filter.add_pattern("*.bat")
        windows_filter.add_pattern("*.lnk")
        windows_filter.add_pattern("*.reg")

        all_files_filter = Gtk.FileFilter()
        all_files_filter.set_name(_("All files"))
        all_files_filter.add_pattern("*")

        filter_combobox = Gtk.ComboBoxText()
        filter_combobox.append("windows", _("Windows files"))
        filter_combobox.append("all", _("All files"))
        filter_combobox.set_active(0)
        filter_combobox.set_size_request(150, -1)

        def on_filter_changed(combobox):
            active_id = combobox.get_active_id()
            if active_id == "windows":
                filechooser.set_filter(windows_filter)
            elif active_id == "all":
                filechooser.set_filter(all_files_filter)

        filter_combobox.connect("changed", on_filter_changed)
        filechooser.set_filter(windows_filter)

        button_open = Gtk.Button.new_with_label(_("Open"))
        button_open.connect("clicked", lambda w: dialog.response(Gtk.ResponseType.OK))
        button_open.set_size_request(150, -1)

        button_cancel = Gtk.Button.new_with_label(_("Cancel"))
        button_cancel.connect("clicked", lambda w: dialog.response(Gtk.ResponseType.CANCEL))
        button_cancel.set_size_request(150, -1)

        button_grid = Gtk.Grid()
        button_grid.set_row_spacing(10)
        button_grid.set_column_spacing(10)
        button_grid.set_margin_start(10)
        button_grid.set_margin_end(10)
        button_grid.set_margin_top(10)
        button_grid.set_margin_bottom(10)
        button_grid.attach(button_open, 1, 1, 1, 1)
        button_grid.attach(button_cancel, 0, 1, 1, 1)
        button_grid.attach(filter_combobox, 1, 0, 1, 1)

        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        button_box.pack_end(button_grid, False, False, 0)

        dialog.vbox.pack_start(filechooser, True, True, 0)
        dialog.vbox.pack_start(button_box, False, False, 0)

        dialog.show_all()
        response = dialog.run()

        if response == Gtk.ResponseType.OK:
            self.entry_addapp.set_text(filechooser.get_filename())

        dialog.destroy()

    def find_largest_resolution(self, directory):
        largest_image = None
        largest_resolution = (0, 0)  # (width, height)

        # Define a set of valid image extensions
        valid_image_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff'}

        for file_name in os.listdir(directory):
            file_path = os.path.join(directory, file_name)
            if os.path.isfile(file_path):
                # Check if the file has a valid image extension
                if os.path.splitext(file_name)[1].lower() in valid_image_extensions:
                    try:
                        with Image.open(file_path) as img:
                            width, height = img.size
                            if width * height > largest_resolution[0] * largest_resolution[1]:
                                largest_resolution = (width, height)
                                largest_image = file_path
                    except IOError:
                        print(f"Unable to open {file_path}")

        return largest_image

    def on_button_search_protonfix_clicked(self, widget):
        webbrowser.open("https://umu.openwinecomponents.org/")

    def load_config(self):
        cfg = ConfigManager()

        self.default_prefix = cfg.config.get('default-prefix', '').strip('"')
        mangohud = cfg.config.get('mangohud', 'False') == 'True'
        gamemode = cfg.config.get('gamemode', 'False') == 'True'
        disable_hidraw = cfg.config.get('disable-hidraw', 'False') == 'True'
        self.default_runner = cfg.config.get('default-runner', '').strip('"')
        self.lossless_location = cfg.config.get('lossless-location', '')

        self.checkbox_mangohud.set_active(mangohud)
        self.checkbox_gamemode.set_active(gamemode)
        self.checkbox_disable_hidraw.set_active(disable_hidraw)

    def on_cancel_clicked(self, widget):
        if os.path.isfile(self.icon_temp):
            os.remove(self.icon_temp)
        if os.path.isdir(self.icon_directory):
            shutil.rmtree(self.icon_directory)
        self.destroy()

    def on_ok_clicked(self, widget):

        validation_result = self.validate_fields()
        if not validation_result:
            self.set_sensitive(True)
            return

        title = self.entry_title.get_text()
        title_formatted = format_title(title)

        addapp = self.entry_addapp.get_text()
        addapp_bat = f"{os.path.dirname(self.file_path)}/faugus-{title_formatted}.bat"

        if self.entry_addapp.get_text():
            with open(addapp_bat, "w") as bat_file:
                bat_file.write(f'start "" "z:{addapp}"\n')
                bat_file.write(f'start "" "z:{self.file_path}"\n')

        if os.path.isfile(os.path.expanduser(self.icon_temp)):
            os.rename(os.path.expanduser(self.icon_temp), f'{self.icons_path}/{title_formatted}.ico')

        # Check if the icon file exists
        new_icon_path = f"{icons_dir}/{title_formatted}.ico"
        if not os.path.exists(new_icon_path):
            new_icon_path = faugus_png

        protonfix = self.entry_protonfix.get_text()
        launch_arguments = self.entry_launch_arguments.get_text()
        game_arguments = self.entry_game_arguments.get_text()
        lossless = self.combobox_lossless.get_active_text()

        mangohud = "MANGOHUD=1" if self.checkbox_mangohud.get_active() else ""
        gamemode = "gamemoderun" if self.checkbox_gamemode.get_active() else ""
        disable_hidraw = "PROTON_DISABLE_HIDRAW=1" if self.checkbox_disable_hidraw.get_active() else ""

        # Get the directory containing the executable
        game_directory = os.path.dirname(self.file_path)

        if lossless == "Off":
            lossless = ""
        if lossless == "X1":
            lossless = "LSFG_LEGACY=1 LSFG_MULTIPLIER=1"
        if lossless == "X2":
            lossless = "LSFG_LEGACY=1 LSFG_MULTIPLIER=2"
        if lossless == "X3":
            lossless = "LSFG_LEGACY=1 LSFG_MULTIPLIER=3"
        if lossless == "X4":
            lossless = "LSFG_LEGACY=1 LSFG_MULTIPLIER=4"

        command_parts = []

        # Add command parts if they are not empty
        if mangohud:
            command_parts.append(mangohud)
        if disable_hidraw:
            command_parts.append(disable_hidraw)

        # command_parts.append(f'WINEPREFIX={self.default_prefix}/default')

        if protonfix:
            command_parts.append(f'GAMEID={protonfix}')
        else:
            command_parts.append(f'GAMEID={title_formatted}')

        if gamemode:
            command_parts.append(gamemode)
        if launch_arguments:
            command_parts.append(launch_arguments)
        if lossless:
            command_parts.append(lossless)

        # Add the fixed command and remaining arguments
        command_parts.append(f"'{umu_run}'")
        if self.entry_addapp.get_text():
            command_parts.append(f"'{addapp_bat}'")
        elif self.file_path:
            command_parts.append(f"'{self.file_path}'")
        if game_arguments:
            command_parts.append(f"{game_arguments}")

        # Join all parts into a single command
        command = ' '.join(command_parts)

        # Create a .desktop file
        if IS_FLATPAK:
            desktop_file_content = (
                f'[Desktop Entry]\n'
                f'Name={title}\n'
                f'Exec=flatpak run --command={faugus_run} io.github.Faugus.faugus-launcher "{command}"\n'
                f'Icon={new_icon_path}\n'
                f'Type=Application\n'
                f'Categories=Game;\n'
                f'Path={game_directory}\n'
            )
        else:
            desktop_file_content = (
                f'[Desktop Entry]\n'
                f'Name={title}\n'
                f'Exec={faugus_run} "{command}"\n'
                f'Icon={new_icon_path}\n'
                f'Type=Application\n'
                f'Categories=Game;\n'
                f'Path={game_directory}\n'
            )

        # Check if the destination directory exists and create if it doesn't
        applications_directory = app_dir
        if not os.path.exists(applications_directory):
            os.makedirs(applications_directory)

        desktop_directory = desktop_dir
        if not os.path.exists(desktop_directory):
            os.makedirs(desktop_directory)

        applications_shortcut_path = f"{app_dir}/{title_formatted}.desktop"

        with open(applications_shortcut_path, 'w') as desktop_file:
            desktop_file.write(desktop_file_content)

        # Make the .desktop file executable
        os.chmod(applications_shortcut_path, 0o755)

        # Copy the shortcut to Desktop
        desktop_shortcut_path = f"{desktop_dir}/{title_formatted}.desktop"
        shutil.copyfile(applications_shortcut_path, desktop_shortcut_path)
        os.chmod(desktop_shortcut_path, 0o755)

        if os.path.isfile(self.icon_temp):
            os.remove(self.icon_temp)
        if os.path.isdir(self.icon_directory):
            shutil.rmtree(self.icon_directory)
        self.destroy()

    def on_entry_changed(self, widget, entry):
        if entry.get_text():
            entry.get_style_context().remove_class("entry")

    def set_image_shortcut_icon(self):
        image_path = faugus_png

        pixbuf = GdkPixbuf.Pixbuf.new_from_file(image_path)
        scaled_pixbuf = pixbuf.scale_simple(50, 50, GdkPixbuf.InterpType.BILINEAR)

        image = Gtk.Image.new_from_pixbuf(scaled_pixbuf)
        return image

    def on_button_shortcut_icon_clicked(self, widget):
        self.set_sensitive(False)

        path = self.file_path

        if not os.path.exists(self.icon_directory):
            os.makedirs(self.icon_directory)

        try:
            command = f'icoextract "{path}" "{self.icon_extracted}"'
            result = subprocess.run(command, shell=True, text=True, capture_output=True)

            if result.returncode != 0:
                if "NoIconsAvailableError" in result.stderr or "PEFormatError" in result.stderr:
                    print("The file does not contain icons.")
                    self.button_shortcut_icon.set_image(self.set_image_shortcut_icon())
                else:
                    print(f"Error extracting icon: {result.stderr}")
            else:
                command_magick = shutil.which("magick") or shutil.which("convert")
                os.system(f'{command_magick} "{self.icon_extracted}" "{self.icon_converted}"')
                if os.path.isfile(self.icon_extracted):
                    os.remove(self.icon_extracted)

        except Exception as e:
            print(f"An error occurred: {e}")

        def show_error_message(message):
            error_dialog = Gtk.MessageDialog(parent=dialog, flags=0, message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.OK, text=message)
            error_dialog.set_title(_("Invalid Image"))
            error_dialog.run()
            error_dialog.destroy()

        def is_valid_image(file_path):
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file(file_path)
                return pixbuf is not None
            except Exception:
                return False

        dialog = Gtk.Dialog(title=_("Select an icon for the shortcut"), parent=self, flags=0)
        dialog.set_size_request(720, 720)

        filechooser = Gtk.FileChooserWidget(action=Gtk.FileChooserAction.OPEN)
        filechooser.set_current_folder(os.path.expanduser("~/"))
        filechooser.connect("file-activated", lambda widget: dialog.response(Gtk.ResponseType.OK))

        filter_ico = Gtk.FileFilter()
        filter_ico.set_name(_("Image files"))
        filter_ico.add_mime_type("image/*")
        filechooser.set_filter(filter_ico)

        filter_combobox = Gtk.ComboBoxText()
        filter_combobox.append("image", _("Image files"))
        filter_combobox.set_active(0)
        filter_combobox.set_size_request(150, -1)

        button_open = Gtk.Button.new_with_label(_("Open"))
        button_open.set_size_request(150, -1)
        button_open.connect("clicked", lambda w: dialog.response(Gtk.ResponseType.OK))

        button_cancel = Gtk.Button.new_with_label(_("Cancel"))
        button_cancel.set_size_request(150, -1)
        button_cancel.connect("clicked", lambda w: dialog.response(Gtk.ResponseType.CANCEL))

        button_grid = Gtk.Grid()
        button_grid.set_row_spacing(10)
        button_grid.set_column_spacing(10)
        button_grid.set_margin_start(10)
        button_grid.set_margin_end(10)
        button_grid.set_margin_top(10)
        button_grid.set_margin_bottom(10)
        button_grid.attach(button_open, 1, 1, 1, 1)
        button_grid.attach(button_cancel, 0, 1, 1, 1)
        button_grid.attach(filter_combobox, 1, 0, 1, 1)

        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        button_box.pack_end(button_grid, False, False, 0)

        dialog.vbox.pack_start(filechooser, True, True, 0)
        dialog.vbox.pack_start(button_box, False, False, 0)

        filechooser.set_current_folder(self.icon_directory)
        filechooser.connect("update-preview", self.update_preview)

        dialog.show_all()

        while True:
            response = dialog.run()
            if response == Gtk.ResponseType.OK:
                file_path = filechooser.get_filename()
                if not file_path or not is_valid_image(file_path):
                    dialog_image = Gtk.Dialog(title="Faugus Launcher", transient_for=dialog, modal=True)
                    dialog_image.set_resizable(False)
                    dialog_image.set_icon_from_file(faugus_png)
                    subprocess.Popen(["canberra-gtk-play", "-f", faugus_notification])

                    label = Gtk.Label()
                    label.set_label(_("The selected file is not a valid image."))
                    label.set_halign(Gtk.Align.CENTER)

                    label2 = Gtk.Label()
                    label2.set_label(_("Please choose another one."))
                    label2.set_halign(Gtk.Align.CENTER)

                    button_yes = Gtk.Button(label=_("Ok"))
                    button_yes.set_size_request(150, -1)
                    button_yes.connect("clicked", lambda x: dialog_image.response(Gtk.ResponseType.YES))

                    content_area = dialog_image.get_content_area()
                    content_area.set_border_width(0)
                    content_area.set_halign(Gtk.Align.CENTER)
                    content_area.set_valign(Gtk.Align.CENTER)
                    content_area.set_vexpand(True)
                    content_area.set_hexpand(True)

                    box_top = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
                    box_top.set_margin_start(20)
                    box_top.set_margin_end(20)
                    box_top.set_margin_top(20)
                    box_top.set_margin_bottom(20)

                    box_bottom = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
                    box_bottom.set_margin_start(10)
                    box_bottom.set_margin_end(10)
                    box_bottom.set_margin_bottom(10)

                    box_top.pack_start(label, True, True, 0)
                    box_top.pack_start(label2, True, True, 0)
                    box_bottom.pack_start(button_yes, True, True, 0)

                    content_area.add(box_top)
                    content_area.add(box_bottom)

                    dialog_image.show_all()
                    dialog_image.run()
                    dialog_image.destroy()
                    continue
                else:
                    shutil.copyfile(file_path, self.icon_temp)
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file(self.icon_temp)
                    scaled_pixbuf = pixbuf.scale_simple(50, 50, GdkPixbuf.InterpType.BILINEAR)
                    image = Gtk.Image.new_from_file(self.icon_temp)
                    image.set_from_pixbuf(scaled_pixbuf)
                    self.button_shortcut_icon.set_image(image)
                    break
            else:
                break

        if os.path.isdir(self.icon_directory):
            shutil.rmtree(self.icon_directory)
        dialog.destroy()
        self.set_sensitive(True)

    def update_preview(self, dialog):
        if file_path := dialog.get_preview_filename():
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file(file_path)
                max_width = 400
                max_height = 400
                width = pixbuf.get_width()
                height = pixbuf.get_height()

                if width > max_width or height > max_height:
                    ratio = min(max_width / width, max_height / height)
                    new_width = int(width * ratio)
                    new_height = int(height * ratio)
                    pixbuf = pixbuf.scale_simple(new_width, new_height, GdkPixbuf.InterpType.BILINEAR)

                image = Gtk.Image.new_from_pixbuf(pixbuf)
                dialog.set_preview_widget(image)
                dialog.set_preview_widget_active(True)
                dialog.get_preview_widget().set_size_request(max_width, max_height)
            except GLib.Error:
                dialog.set_preview_widget_active(False)
        else:
            dialog.set_preview_widget_active(False)

    def validate_fields(self):

        title = self.entry_title.get_text()

        self.entry_title.get_style_context().remove_class("entry")

        if not title:
            self.entry_title.get_style_context().add_class("entry")
            return False

        return True

def run_file(file_path):
    cfg = ConfigManager()

    default_prefix = cfg.config.get('default-prefix', '').strip('"')
    mangohud = cfg.config.get('mangohud', 'False') == 'True'
    gamemode = cfg.config.get('gamemode', 'False') == 'True'
    disable_hidraw = cfg.config.get('disable-hidraw', 'False') == 'True'
    default_runner = cfg.config.get('default-runner', '').strip('"')

    if not file_path.endswith(".reg"):
        mangohud = "MANGOHUD=1" if mangohud else ""
        gamemode = "gamemoderun" if gamemode else ""
        disable_hidraw = "PROTON_DISABLE_HIDRAW=1" if disable_hidraw else ""

    # Get the directory of the file
    file_dir = os.path.dirname(os.path.abspath(file_path))

    # Define paths
    faugus_run_path = faugus_run

    if not file_path.endswith(".reg"):
        mangohud_enabled = os.path.exists(mangohud_dir)
        gamemode_enabled = os.path.exists(gamemoderun) or os.path.exists("/usr/games/gamemoderun")

    if default_runner == "UMU-Proton Latest":
        default_runner = ""
    if default_runner == "GE-Proton Latest (default)":
        default_runner = "GE-Proton"
    if default_runner == "Proton-EM Latest":
        default_runner = "Proton-EM"

    command_parts = []

    command_parts.append(f'FAUGUS_LOG=default')
    if not file_path.endswith(".reg"):
        # Add command parts if they are not empty
        if mangohud_enabled and mangohud:
            command_parts.append(mangohud)
        if disable_hidraw:
            command_parts.append(disable_hidraw)
    command_parts.append(os.path.expanduser(f'WINEPREFIX="{default_prefix}/default"'))
    command_parts.append('GAMEID=default')
    if default_runner:
        command_parts.append(f'PROTONPATH={default_runner}')
    if not file_path.endswith(".reg"):
        if gamemode_enabled and gamemode:
            command_parts.append(gamemode)

    # Add the fixed command and remaining arguments
    command_parts.append(f'"{umu_run}"')
    if file_path.endswith(".reg"):
        command_parts.append(f'regedit "{file_path}"')
    else:
        command_parts.append(f'"{file_path}"')

    # Join all parts into a single command
    command = ' '.join(command_parts)

    # Run the command in the directory of the file
    subprocess.run([faugus_run_path, command], cwd=file_dir)

def apply_dark_theme():
    if IS_FLATPAK:
        if (os.environ.get("XDG_CURRENT_DESKTOP")) == "KDE":
            Gtk.Settings.get_default().set_property("gtk-theme-name", "Breeze")
        try:
            proxy = Gio.DBusProxy.new_sync(
                Gio.bus_get_sync(Gio.BusType.SESSION, None), 0, None,
                "org.freedesktop.portal.Desktop",
                "/org/freedesktop/portal/desktop",
                "org.freedesktop.portal.Settings", None)
            is_dark = proxy.call_sync(
                "Read", GLib.Variant("(ss)", ("org.freedesktop.appearance", "color-scheme")),
                0, -1, None).unpack()[0] == 1
        except:
            is_dark = False
        Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", is_dark)
    else:
        desktop_env = Gio.Settings.new("org.gnome.desktop.interface")
        try:
            is_dark_theme = desktop_env.get_string("color-scheme") == "prefer-dark"
        except Exception:
            is_dark_theme = "-dark" in desktop_env.get_string("gtk-theme")
        if is_dark_theme:
            Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", True)

def update_games_file():
    if not os.path.exists(games_json):
        return
    with open(games_json, "r", encoding="utf-8") as f:
        games = json.load(f)
    for game in games:
        if not game.get("gameid"):
            game["gameid"] = format_title(game["title"])
    with open(games_json, "w", encoding="utf-8") as f:
        json.dump(games, f, indent=4, ensure_ascii=False)

def faugus_launcher():
    update_games_file()
    apply_dark_theme()

    if len(sys.argv) == 1:
        app = Main()
        app.connect("destroy", app.on_destroy)
        Gtk.main()

    elif len(sys.argv) == 2:
        if sys.argv[1] == "--hide":
            app = Main()
            app.hide()
            app.connect("destroy", app.on_destroy)
            Gtk.main()

    elif len(sys.argv) == 3 and sys.argv[1] == "--shortcut":
        app = CreateShortcut(sys.argv[2])
        app.show_all()
        Gtk.main()

    else:
        print("Invalid arguments")

def main():
    if len(sys.argv) == 2 and sys.argv[1] != "--hide":
        run_file(sys.argv[1])
    elif len(sys.argv) == 3 and sys.argv[1] == "--shortcut":
        faugus_launcher()
    else:
        try:
            with lock:
                faugus_launcher()
        except Timeout:
            print("Faugus Launcher is already running.")

if __name__ == "__main__":
    main()
