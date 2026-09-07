"""Same-user scheduling for explicitly enabled release maintenance."""
import os
from pathlib import Path
import plistlib
import subprocess
import sys

LABEL = 'org.session-harness.auto-update'
UNIT = 'session-harness-auto-update'


def platform():
    if sys.platform == 'darwin':
        return 'launchd'
    if sys.platform.startswith('linux'):
        return 'systemd'
    raise ValueError('Automatic scheduling supports macOS and Linux; use explicit updates here')


def environment():
    env = dict(os.environ)
    if sys.platform.startswith('linux'):
        root = Path('/run/user') / str(os.getuid())
        if (root / 'bus').is_socket():
            env.setdefault('XDG_RUNTIME_DIR', str(root))
            env.setdefault('DBUS_SESSION_BUS_ADDRESS', 'unix:path=' + str(root / 'bus'))
    return env


def command(args, check=True):
    return subprocess.run(args, capture_output=True, text=True, timeout=30,
                          env=environment(), check=check)


def definitions(home, python):
    launcher = home / '.local/bin/ai-session'
    state = home / '.local/state/session-harness'
    if not launcher.is_file() or not Path(python).is_absolute():
        raise ValueError('Install the stable ai-session launcher before enabling scheduling')
    if platform() == 'launchd':
        value = {'Label': LABEL, 'ProgramArguments': [python, str(launcher), 'auto-update', 'run'],
                 'StartInterval': 3600, 'RunAtLoad': True,
                 'EnvironmentVariables': {'HOME': str(home), 'PATH': '/usr/bin:/bin:/usr/sbin:/sbin'},
                 'StandardOutPath': str(state / 'auto-update.stdout.log'),
                 'StandardErrorPath': str(state / 'auto-update.stderr.log')}
        return {home / 'Library/LaunchAgents' / (LABEL + '.plist'): plistlib.dumps(value)}
    def quoted(value):
        if any(c in value for c in '\n\r\x00'):
            raise ValueError('Invalid scheduler path')
        return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%').replace('$', '$$') + '"'
    directory = home / '.config/systemd/user'
    service = ('[Unit]\nDescription=Session harness automatic stable updates\n\n[Service]\nType=oneshot\n'
               'ExecStart=' + ' '.join(quoted(v) for v in [python, str(launcher), 'auto-update', 'run']) +
               '\nTimeoutStartSec=15min\n')
    timer = ('[Unit]\nDescription=Check session harness update policy hourly\n\n[Timer]\n'
             'OnBootSec=5min\nOnUnitActiveSec=1h\nPersistent=true\n\n[Install]\nWantedBy=timers.target\n')
    return {directory / (UNIT + '.service'): service.encode(), directory / (UNIT + '.timer'): timer.encode()}


def status(home):
    selected = platform()
    if selected == 'launchd':
        result = command(['/bin/launchctl', 'print', f'gui/{os.getuid()}/{LABEL}'], check=False)
        return {'kind': selected, 'loaded': result.returncode == 0,
                'delivery': 'during user login; checks resume after wake/login'}
    loaded = command(['systemctl', '--user', 'is-enabled', UNIT + '.timer'], check=False)
    active = command(['systemctl', '--user', 'is-active', UNIT + '.timer'], check=False)
    linger = command(['loginctl', 'show-user', str(os.getuid()), '--property=Linger', '--value'], check=False)
    return {'kind': selected, 'loaded': loaded.returncode == active.returncode == 0,
            'linger': linger.stdout.strip() == 'yes',
            'delivery': 'after logout' if linger.stdout.strip() == 'yes' else 'while user manager runs; enable linger for logout delivery'}


def install(home, python, previous):
    desired = definitions(home, python)
    known = (previous or {}).get('files', {})
    import auto_update
    for path, raw in desired.items():
        if path.is_symlink() or (path.exists() and path.read_bytes() != raw
                                and auto_update.sha(path.read_bytes()) != known.get(str(path))):
            raise ValueError('Unmanaged scheduler file; reconcile before enabling: ' + str(path))
    for path, raw in desired.items():
        auto_update.atomic(path, raw)
    if platform() == 'launchd':
        domain = f'gui/{os.getuid()}'
        if status(home)['loaded']:
            command(['/bin/launchctl', 'bootout', domain + '/' + LABEL])
        command(['/bin/launchctl', 'bootstrap', domain, str(next(iter(desired)))])
    else:
        command(['systemctl', '--user', 'daemon-reload'])
        command(['systemctl', '--user', 'enable', '--now', UNIT + '.timer'])
    return {'files': {str(path): auto_update.sha(raw) for path, raw in desired.items()},
            'python': python, **status(home)}


def uninstall(home, previous):
    import auto_update
    known = (previous or {}).get('files', {})
    desired = definitions(home, (previous or {}).get('python', sys.executable))
    for path in desired:
        if path.is_symlink() or (path.exists() and auto_update.sha(path.read_bytes()) != known.get(str(path))):
            raise ValueError('Changed scheduler retained; flag is disabled: ' + str(path))
    if platform() == 'launchd':
        if status(home)['loaded']:
            command(['/bin/launchctl', 'bootout', f'gui/{os.getuid()}/{LABEL}'])
    else:
        command(['systemctl', '--user', 'disable', '--now', UNIT + '.timer'])
    for path in desired:
        path.unlink(missing_ok=True)
    if platform() == 'systemd':
        command(['systemctl', '--user', 'daemon-reload'])
