"""Opt-in self-contained arcade packages with synthetic game media; never launches games.

MCL_ARCADE_TESTS=1 python3 -m unittest tests.test_arcade_installs
Uses official native software only for isolated prerequisite/command verification.
"""
import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
import zipfile

import dependencies
import installs
import jobs
import packages
import supermodel

PACKAGE_REPO = Path(__file__).resolve().parents[2] / 'momentum-packages'
IDS = ('virtua-cop-2', 'star-wars-trilogy-arcade', 'l-a-machineguns')


@unittest.skipUnless(os.environ.get('MCL_ARCADE_TESTS') == '1', 'opt-in real arcade package integration')
class ArcadeInstalls(unittest.TestCase):
    def wait(self, runner, jid):
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline and runner.get(jid)['status'] in jobs.RUNNING:
            time.sleep(.02)
        return runner.get(jid)

    def exercise(self, game_id, software_missing=False, wrong_build=False):
        version = {'virtua-cop-2': '0.1.3', 'star-wars-trilogy-arcade': '0.2.2',
                   'l-a-machineguns': '0.2.3'}[game_id]
        archive = PACKAGE_REPO / 'dist' / f'{game_id}-{version}.zip'
        source_package = PACKAGE_REPO / game_id / 'package'
        profile = json.loads((source_package / 'profile.json').read_text())
        runtime = profile['runtime']
        native = supermodel.detect() if runtime == 'supermodel' else None
        with tempfile.TemporaryDirectory(prefix='momentum-arcade-') as temporary:
            root = Path(temporary)
            home, app, source, tools = (root / p for p in ('home with spaces', 'launcher', 'source', 'tools'))
            for p in (home, app, source, tools):
                p.mkdir()
            if runtime == 'supermodel':
                if not native['installed']:
                    self.fail('Verified Supermodel is required for opt-in isolated integration')
                software = home / 'Games/Supermodel'
                for name in supermodel.RUNTIME_FILES:
                    target = software / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(Path(native['root']) / name, target)
                    target.chmod(supermodel.ASSET_INVENTORY[name][1])
                marker = root / 'native-ready'
                marker.touch()
                if software_missing:
                    software.rename(root / 'software-backup')
            else:
                marker = root / 'flatpak-ready'
                updated = root / 'flatpak-pinned'
                if not software_missing:
                    marker.touch()
                    updated.touch()
                facts = json.loads((Path(installs.__file__).parent / 'docs/hod2-target-evidence.json').read_text())
                version_info = f"    Version: {facts['emulator_version']}\n    Commit: {facts['emulator_commit']}"
                if wrong_build:
                    version_info = '    Version: untested\n    Commit: untested'
                app_metadata = ("[Application]\n"
                                "name=org.flycast.Flycast\n"
                                "runtime=org.freedesktop.Platform/x86_64/24.08\n"
                                "command=flycast\n")
                app_ref = "app/org.flycast.Flycast/x86_64/stable"
                runtime_ref = "org.freedesktop.Platform/x86_64/24.08"
                runtime_commit = 'a' * 64
                flatpak = tools / 'flatpak'
                flatpak.write_text(f"""#!{sys.executable}
import os
from pathlib import Path
import sys
ready=Path({str(marker)!r})
updated=Path({str(updated)!r})
app_ref={app_ref!r}
runtime_ref={runtime_ref!r}
runtime_commit={runtime_commit!r}
if sys.argv[1]=='ps': pass
elif sys.argv[1]=='remotes':
    print('flathub\\thttps://dl.flathub.org/repo/\\t' if 'FLATPAK_USER_DIR' in os.environ else 'flathub\\thttps://dl.flathub.org/repo/')
elif sys.argv[1]=='list':
    if '--columns=application' in sys.argv:
        if ready.exists(): print('org.flycast.Flycast')
    elif ready.exists():
        print(app_ref+'\\tflathub')
        print('runtime/'+runtime_ref+'\\tflathub')
elif sys.argv[1]=='remote-info':
    print({app_metadata!r} if '--show-metadata' in sys.argv else 'Commit: '+{facts['emulator_commit']!r})
elif sys.argv[1]=='info':
    if '--show-ref' in sys.argv:
        ref=sys.argv[sys.argv.index('--show-ref')+1]
        print('runtime/'+runtime_ref if ref==runtime_ref else app_ref)
    elif '--show-commit' in sys.argv:
        ref=sys.argv[sys.argv.index('--show-commit')+1]
        print(runtime_commit if ref==runtime_ref else
              ({facts['emulator_commit']!r} if updated.exists() else 'b'*64))
    elif '--show-origin' in sys.argv: print('flathub')
    elif '--show-runtime' in sys.argv: print(runtime_ref)
    elif '--show-metadata' in sys.argv: print({app_metadata!r})
    else:
        print({version_info!r} if updated.exists() or {wrong_build!r} else
              '    Version: v2.7\\n    Commit: '+'b'*64)
elif sys.argv[1]=='mask':
    if len(sys.argv)>2 and '--columns' not in sys.argv: print('org.flycast.Flycast')
elif sys.argv[1]=='remote-add': pass
elif sys.argv[1]=='install': ready.touch()
elif sys.argv[1]=='update': updated.touch()
else: sys.exit('Game/emulator launch prohibited in this test')
""")
                flatpak.chmod(0o755)
            if profile['media_type'] == 'gdi':
                lines = ['39']
                for n in range(1, 40):
                    track = f'track {n:02d}.bin'
                    (source / track).write_bytes(b'synthetic media' * 100)
                    lines.append(f'{n} {n * 45000} 4 2352 "{track}" 0')
                (source / profile['media']).write_text('\n'.join(lines) + '\n')
            else:
                with zipfile.ZipFile(source / profile['media'], 'w') as out:
                    out.writestr('synthetic.rom', b'synthetic ROM, not playable')
            (source / 'user-save').write_text('preserve original')
            catalog_path = app / 'games.json'
            catalog_path.write_text('[]')
            env = {'HOME': str(home), 'PATH': str(tools) + ':' + os.environ['PATH']}
            with contextlib.ExitStack() as overrides, mock.patch.dict(os.environ, env):
                info = packages.import_package(archive, app)
                if os.environ.get('MCL_CANDIDATE_EVIDENCE') == '1':
                    evidence_path = Path(installs.__file__).parent / 'docs/arcade-installer-evidence.json'
                    original_read = Path.read_text
                    evidence = json.loads(evidence_path.read_text())
                    record = copy.deepcopy(next(r for r in evidence['packages'] if r['id'] == game_id))
                    record.update(version=version, digest=info['digest'], gameplay='not-tested-for-this-package')
                    evidence['packages'].insert(0, record)

                    def read(path, *args, **kwargs):
                        return json.dumps(evidence) if path == evidence_path else original_read(path, *args, **kwargs)
                    overrides.enter_context(mock.patch.object(Path, 'read_text', read))
                runner = jobs.Jobs(app / 'jobs')
                inst = installs.Installs(app, threading.Lock(), lambda: json.loads(catalog_path.read_text()),
                                        lambda games: installs._write_atomic(catalog_path, json.dumps(games).encode()), runner)
                runner.on_success, runner.before_step = inst.on_success, inst.before_step
                try:
                    detail = inst.package_details(game_id, version)
                    self.assertEqual(detail['package_supported'], True, detail)
                    self.assertEqual(detail['install_enabled'], not (software_missing or wrong_build), detail)
                    jid = inst.submit_install(game_id, version, str(source), trusted_digest=info['digest'])
                    job = self.wait(runner, jid)
                    if wrong_build:
                        self.assertEqual(job['status'], 'needs-action', job)
                        self.assertTrue(job.get('approval_blocked') or job.get('actions'), job)
                        self.assertFalse((home / 'Games' / profile['destination_name']).exists())
                        self.assertEqual(json.loads(catalog_path.read_text()), [])
                        return
                    self.assertEqual(job['status'], 'awaiting-approval', job)
                    if software_missing:
                        self.assertEqual(job['plan']['operation'], 'prepare-dependency')
                        self.assertFalse((home / 'Games' / profile['destination_name']).exists())
                        self.assertIs(inst.approve(jid, job['plan_digest']), True)
                        job = self.wait(runner, jid)
                        self.assertEqual(job['status'], 'awaiting-approval', job)
                    # Saved review reconnects to identical immutable plan.
                    runner.close()
                    runner = jobs.Jobs(app / 'jobs', on_success=inst.on_success, before_step=inst.before_step)
                    inst.jobs = runner
                    self.assertEqual(runner.get(jid)['plan_digest'], job['plan_digest'])
                    self.assertIs(inst.approve(jid, job['plan_digest']), True)
                    completed = self.wait(runner, jid)
                    self.assertEqual(completed['status'], 'succeeded', completed)
                    receipt = inst._load_receipt(game_id)
                    self.assertEqual(receipt['readiness'], 'setup-required')
                    self.assertEqual(len(json.loads(catalog_path.read_text())), 1)
                    self.assertEqual((source / 'user-save').read_text(), 'preserve original')
                    # Construct exact launch command and seed isolated state WITHOUT execution.
                    support = Path(receipt['paths']['support'])
                    game = json.loads(catalog_path.read_text())[0]
                    manifest = json.loads((support / 'package.json').read_text())
                    self.assertEqual(game['description'], manifest['catalog']['description'])
                    for field, asset in installs.PRESENTATION_ASSETS.items():
                        self.assertTrue(game[field].startswith('media/'), game)
                        self.assertEqual((app / game[field]).read_bytes(), (support / asset).read_bytes())
                    spec = importlib.util.spec_from_file_location('arcade_launch', support / 'launch.py')
                    module = importlib.util.module_from_spec(spec)
                    with mock.patch.object(sys, 'dont_write_bytecode', True):
                        spec.loader.exec_module(module)
                    command, cwd = module.build_command(Path(receipt['game_directory']),
                                                       Path(receipt['paths']['state']),
                                                       inst.package_details(game_id, version)['dependencies'].get('supermodel', {}).get('root'))
                    self.assertNotIn('retroarch', ' '.join(command).lower())
                    if runtime == 'supermodel':
                        self.assertEqual(command[2:], profile['flags'])
                        self.assertEqual(cwd, Path(receipt['paths']['state']))
                        config = cwd / 'Config/Supermodel.ini'
                        self.assertEqual(config.read_bytes(), (support / 'presets/Supermodel.ini').read_bytes())
                        config.write_text('user settings')
                        module.build_command(Path(receipt['game_directory']), cwd,
                                             inst.package_details(game_id, version)['dependencies']['supermodel']['root'])
                        self.assertEqual(config.read_text(), 'user settings')
                        seed_name = 'swtrilgy.nv' if game_id.startswith('star-') else 'lamachin.nv'
                        nvram = cwd / 'NVRAM' / seed_name
                        self.assertEqual(nvram.read_bytes(), (support / 'presets' / seed_name).read_bytes())
                        nvram.write_bytes(b'player state')
                        module.build_command(Path(receipt['game_directory']), cwd,
                                             inst.package_details(game_id, version)['dependencies']['supermodel']['root'])
                        self.assertEqual(nvram.read_bytes(), b'player state')
                    else:
                        self.assertIn('--command=sh', command)
                        self.assertIn(str(receipt['paths']['state']), command)
                        self.assertIn('config:Dreamcast.Region=0', command)
                        self.assertIn('config:rend.ThreadedRendering=no', command)
                        mapping = Path(receipt['paths']['state']) / 'config/flycast/mappings/SDL_Default Mouse_HDR-0061.cfg'
                        self.assertEqual(mapping.read_bytes(), (support / 'presets' / mapping.name).read_bytes())
                        self.assertIn('bind1 = 1:reload', mapping.read_text())
                        mapping.write_text('personal binding')
                        module.build_command(Path(receipt['game_directory']), Path(receipt['paths']['state']))
                        self.assertEqual(mapping.read_text(), 'personal binding')
                    second = inst.submit_install(game_id, version, str(source), trusted_digest=info['digest'])
                    self.assertEqual(self.wait(runner, second)['status'], 'awaiting-approval')
                    runner.cancel(second)
                    self.assertEqual(inst._load_receipt(game_id), receipt)
                    with self.assertRaisesRegex(installs.InstallError, "Trust approval"):
                        inst.submit_uninstall(game_id, "sha256:" + "0" * 64)
                    with self.assertRaisesRegex(installs.InstallError, "Uninstall first"):
                        inst.remove_cached_package(game_id, version)
                    if game_id == 'virtua-cop-2':
                        # Historical installs may have lost their local intake cache.
                        packages.remove_package(app, game_id, version)
                    before_uninstall = inst._load_receipt(game_id)
                    cancelled = inst.submit_uninstall(game_id, info['digest'])
                    review = self.wait(runner, cancelled)
                    self.assertEqual(review['status'], 'awaiting-approval', review)
                    self.assertTrue(Path(receipt['paths']['launcher']).is_file())
                    runner.cancel(cancelled)
                    self.assertEqual(inst._load_receipt(game_id), before_uninstall)
                    custom = Path(receipt['game_directory']) / 'personal-file.txt'
                    custom.write_text('keep personal file')
                    wrapper = Path(receipt['paths']['launcher'])
                    wrapper.write_text('keep edited wrapper')
                    # Real public maintenance entrypoint, not a hand-constructed test job.
                    uninstall = inst.submit_uninstall(game_id, info['digest'])
                    review = self.wait(runner, uninstall)
                    self.assertEqual(review['status'], 'awaiting-approval', review)
                    self.assertEqual(review['plan']['operation'], 'uninstall')
                    if game_id == 'virtua-cop-2':
                        with mock.patch.object(inst, 'write_games', side_effect=OSError('catalog interrupted')):
                            self.assertIs(inst.approve(uninstall, review['plan_digest']), True)
                            interrupted = self.wait(runner, uninstall)
                            self.assertEqual(interrupted['status'], 'failed', interrupted)
                            self.assertTrue(interrupted['manual'])
                        inst.recover_pending_catalog()
                    else:
                        self.assertIs(inst.approve(uninstall, review['plan_digest']), True)
                    removed = self.wait(runner, uninstall)
                    self.assertEqual(removed['status'], 'succeeded', removed)
                    self.assertEqual(inst._load_receipt(game_id)['installation'], 'removed')
                    self.assertNotIn('exec', json.loads(catalog_path.read_text())[0])
                    if runtime == 'supermodel':
                        self.assertEqual(nvram.read_bytes(), b'player state')
                    else:
                        self.assertEqual(mapping.read_text(), 'personal binding')
                    self.assertEqual((source / 'user-save').read_text(), 'preserve original')
                    self.assertTrue(support.is_dir())
                    self.assertEqual(custom.read_text(), 'keep personal file')
                    self.assertEqual(wrapper.read_text(), 'keep edited wrapper')
                    self.assertNotIn(str(wrapper), {r['path'] for r in inst._load_receipt(game_id)['resources']})
                    inst.remove_cached_package(game_id, version)
                    self.assertEqual(packages.list_packages(app), [])
                    self.assertEqual(inst._load_receipt(game_id)['installation'], 'removed')
                finally:
                    runner.close()

    def test_virtua_cop_2(self):
        self.exercise('virtua-cop-2')

    def test_virtua_cop_2_missing_software(self):
        self.exercise('virtua-cop-2', software_missing=True)

    def test_virtua_cop_2_untested_software_cannot_apply(self):
        self.exercise('virtua-cop-2', wrong_build=True)

    def test_star_wars(self):
        self.exercise('star-wars-trilogy-arcade')

    def test_la_machineguns(self):
        self.exercise('l-a-machineguns')

    def test_star_wars_missing_software_downloads_then_game_review(self):
        self.exercise('star-wars-trilogy-arcade', software_missing=True)
