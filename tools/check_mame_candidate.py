#!/usr/bin/env python3
"""Validate a private MAME candidate through the real runner in a new retained root.

The default reuses real existing MAME and real supplied media without launching
gameplay. --synthetic-managed tests missing/wrong-engine acquisition with a test
double; it is not evidence of real network acquisition.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import threading
import time
from unittest import mock
import zipfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import compatibility
import installs
import jobs
import mame
import packages


def fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--archive', type=Path,
                        default=Path(__file__).resolve().parents[2] /
                        'momentum-packages/dist/time-crisis-ii-0.1.0.zip')
    parser.add_argument('--source', type=Path)
    parser.add_argument('--synthetic-managed', choices=['missing', 'wrong'])
    args = parser.parse_args()
    root = args.root
    if (not root.is_absolute() or root.exists() or '..' in root.parts
            or any(p.is_symlink() for p in (root, *root.parents))):
        parser.error('Supply a new absolute nonsymlink validation root.')
    launcher = Path(__file__).resolve().parents[1]
    archive = args.archive.resolve()
    info = packages.check(archive)
    if info['id'] != 'time-crisis-ii':
        parser.error('The validation archive must be a Time Crisis II package.')
    version = info['version']
    normal_paths = [
        Path.home() / '.local/bin/time-crisis-ii-momentum',
        Path.home() / '.mame/cfg/timecrs2.cfg',
        Path.home() / '.mame/nvram/timecrs2/nvram',
        Path.home() / '.local/share/applications/time-crisis-ii-momentum.desktop',
        launcher / 'games.json',
    ]
    baseline = {str(p): fingerprint(p) for p in normal_paths if p.is_file()}
    root.mkdir(mode=0o700)
    home, app = root / 'home', root / 'launcher'
    home.mkdir()
    app.mkdir()
    source = args.source
    environment = {'HOME': str(home), 'XDG_DATA_HOME': str(home / '.local/share'),
                   'XDG_CONFIG_HOME': str(home / '.config'), 'XDG_CACHE_HOME': str(home / '.cache'),
                   'XDG_STATE_HOME': str(home / '.local/state'), 'MCL_TEST_ISOLATED_ENGINES': '0'}
    if args.synthetic_managed:
        (home / 'mock-engine.json').write_text(json.dumps({'existing': args.synthetic_managed}))
        source = root / 'synthetic-source'
        source.mkdir()
        with zipfile.ZipFile(source / 'timecrs2.zip', 'w') as out:
            out.writestr('synthetic.rom', b'synthetic only')
        tools = root / 'tools'
        tools.mkdir()
        binary = tools / 'flatpak'
        shutil.copyfile(launcher / 'tests/fixtures/mame-flatpak.py', binary)
        binary.chmod(0o755)
        environment.update(PATH=str(tools) + ':' + os.environ['PATH'])
    if source is None or not source.is_absolute() or not (source / 'timecrs2.zip').is_file():
        parser.error('Supply an absolute --source directory containing timecrs2.zip.')
    source_hash = fingerprint(source / 'timecrs2.zip')
    results = []

    def wait(runner, jid):
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            job = runner.get(jid)
            if job['status'] not in jobs.RUNNING:
                return job
            time.sleep(.05)
        raise RuntimeError('Runner timed out; retain job ' + jid)

    with mock.patch.dict(os.environ, environment):
        imported = packages.import_package(archive, app)
        provisional = {
            'id': 'time-crisis-ii', 'version': version, 'digest': imported['digest'],
            'runtime': 'mame', 'installer_validated': True, 'gameplay': 'not-tested-for-this-package',
            'software': {'provider': 'flatpak', 'scope': 'user', 'app_id': mame.APP,
                         'version': mame.VERSION, 'commit': mame.COMMIT},
            'limits': 'Provisional private validation harness only; not published acceptance.',
        }
        library = []
        catalog_path = app / 'games.json'
        def write_library(data):
            library[:] = data
            installs._write_atomic(catalog_path, json.dumps(data, indent=2).encode())
        runner = jobs.Jobs(app / 'jobs')
        inst = installs.Installs(app, threading.Lock(), lambda: library, write_library, runner)
        runner.on_success, runner.before_step = inst.on_success, inst.before_step
        original_find = compatibility.find_record
        def candidate_record(where, package_id, package_version, digest):
            if (package_id, package_version, digest) == ('time-crisis-ii', version, imported['digest']):
                return provisional
            return original_find(where, package_id, package_version, digest)
        try:
            with mock.patch.object(compatibility, 'find_record', side_effect=candidate_record):
                detail = inst.package_details('time-crisis-ii', version)
                assert detail['package_supported'], detail
                assert detail['install_enabled'] == (not bool(args.synthetic_managed)), detail

                def approve_all(jid):
                    while True:
                        job = wait(runner, jid)
                        if job['status'] != 'awaiting-approval':
                            if job['status'] != 'succeeded':
                                raise RuntimeError(json.dumps(job, indent=2))
                            results.append({'job': jid, 'title': job['title'], 'status': job['status']})
                            return job
                        approval = inst.approve(jid, job['plan_digest'])
                        if approval is not True:
                            raise RuntimeError('Approval failed: ' + str(approval))

                def install():
                    jid = inst.submit_install('time-crisis-ii', version, str(source),
                                              trusted_digest=imported['digest'])
                    approve_all(jid)
                    return jid

                first = install()
                receipt = inst._load_receipt('time-crisis-ii')
                game = Path(receipt['game_directory'])
                assert fingerprint(game / 'timecrs2.zip') == source_hash
                assert {p.name for p in game.iterdir()} == {'timecrs2.zip'}
                repeat = install()
                saved_plan = json.loads(runner.paths(repeat)['approved_plan_file'].read_text())['plan']
                assert saved_plan['actions'] == []
                template = copy.deepcopy(runner.jobs[repeat]['steps'][-1]['context'])
                meta = copy.deepcopy(runner.jobs[repeat]['meta'])

                def operation(name):
                    detail = inst.package_details('time-crisis-ii', version)
                    context = dict(template, operation=name,
                                   previous_receipt=inst._load_receipt('time-crisis-ii'),
                                   dependencies=detail['dependencies'])
                    steps = [{'name': name + ' ' + phase, 'protocol': True,
                              'approve_after': phase == 'preflight' and name != 'verify',
                              'declared_steps': detail['manifest']['operations'][name]['steps'],
                              'argv': ['bash', name + '.sh', '--context', '{context_file}', '--phase', phase],
                              'cwd': context['package_root'], 'context': dict(context, phase=phase)}
                             for phase in (('preflight',) if name == 'verify' else ('preflight', 'apply'))]
                    approve_all(runner.submit(name, steps, game='time-crisis-ii',
                                              meta=dict(meta, operation=name,
                                                        kind='verify' if name == 'verify' else 'install')))

                operation('verify')
                Path(receipt['paths']['launcher']).unlink()
                operation('repair')
                assert Path(receipt['paths']['launcher']).is_file()
                (game / 'timecrs2.zip').unlink()
                operation('repair')
                assert fingerprint(game / 'timecrs2.zip') == source_hash
                marker = game / 'user-progress'
                marker.write_text('keep')
                state = Path(receipt['paths']['state'])
                state.mkdir(parents=True, exist_ok=True)
                (state / 'save-marker').write_text('keep state')
                operation('uninstall')
                assert not (game / 'timecrs2.zip').exists()
                assert marker.read_text() == 'keep'
                assert (state / 'save-marker').read_text() == 'keep state'
                install()
                assert marker.read_text() == 'keep'
                assert (state / 'save-marker').read_text() == 'keep state'
                marker.unlink()
                operation('uninstall')
                assert not game.exists()
                install()
                assert len(library) == 1, library
                receipt = inst._load_receipt('time-crisis-ii')
                assert receipt['dependencies']['mame'].get('managed') is not None if args.synthetic_managed else (
                    receipt['dependencies']['mame']['scope'] == 'system')
        finally:
            runner.close()
    assert fingerprint(source / 'timecrs2.zip') == source_hash
    for path, expected in baseline.items():
        assert fingerprint(Path(path)) == expected, path
    report = {'status': 'passed', 'package_id': 'time-crisis-ii', 'version': version,
              'digest': imported['digest'], 'zip_sha256': fingerprint(archive),
              'synthetic_managed': args.synthetic_managed, 'jobs': results,
              'receipt': receipt, 'originals_unchanged': True,
              'limits': 'No graphical game launch. Synthetic acquisition is not real network evidence.'}
    (root / 'evidence.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'status': 'passed', 'evidence': str(root / 'evidence.json'),
                      'launcher': receipt['paths']['launcher'], 'digest': imported['digest']}))


if __name__ == '__main__':
    main()
