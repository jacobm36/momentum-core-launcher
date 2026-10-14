#!/usr/bin/env python3
"""Pinned OpenBOR 6391 preparation from digest-bound local package payload.

Extracted native ELF uses its own $ORIGIN/../lib RUNPATH; FUSE is unnecessary.
No game launches, downloads, upgrades, elevation or shared config writes.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile

from dependencies import DependencyError, emit
from jobs import _write_durable, _fsync_dir

VERSION = '6391'
INDEX = json.loads(Path(__file__).with_name('docs').joinpath('openbor-runtime-index.json').read_text())
ASSET_SHA256 = INDEX['appimage_sha256']

LAYOUTS = ('legacy', 'build')

def target_root(layout='legacy'):
    # Legacy path is the published Marvel 0.2.0 contract and must never move.
    base = Path.home() / '.local/share/momentum-core/software/openbor'
    if layout == 'legacy': return base / VERSION
    if layout == 'build': return base / 'builds' / f"{VERSION}-{INDEX['archive_sha256'][:12]}"
    raise DependencyError(f'Unsupported OpenBOR runtime layout: {layout}')

def layout_of(facts):
    argv = facts.get('launch_argv')
    for layout in LAYOUTS:
        if argv == [str(target_root(layout)/'usr/bin/OpenBOR')]: return layout
    raise DependencyError('OpenBOR runtime path changed.')

def recovery_target(root):
    # First free side-by-side name; altered copies are preserved, never deleted.
    n = 1
    while (root.parent/f'{root.name}.altered-{n}').exists() or (root.parent/f'{root.name}.altered-{n}').is_symlink():
        n += 1
    return root.parent/f'{root.name}.altered-{n}'

def safe(path):
    path=Path(path)
    if (not path.is_absolute() or '..' in path.parts
            or any(ord(c) < 32 or ord(c) == 127 for c in str(path))
            or any(p.is_symlink() for p in [path,*path.parents])):
        raise DependencyError(f'Unsafe runtime path: {path}')
    return path

def verify(root):
    root=safe(root)
    if not root.is_dir(): return False
    expected={r['path']:r for r in INDEX['files']}
    seen=set()
    for p in [root, *root.rglob('*')]:
        safe(p)
        info=p.stat()
        if (info.st_uid != os.getuid() or info.st_mode & (stat.S_IWOTH|stat.S_ISUID|stat.S_ISGID)
                or info.st_mode & stat.S_IWGRP and info.st_gid != os.getgid()):
            return False
        if p.is_dir(): continue
        rel=p.relative_to(root).as_posix()
        r=expected.get(rel)
        if not stat.S_ISREG(info.st_mode) or not r or stat.S_IMODE(info.st_mode)!=r['mode']:
            return False
        if info.st_size!=r['size'] or hashlib.sha256(p.read_bytes()).hexdigest()!=r['sha256']:
            return False
        seen.add(rel)
    return seen==set(expected)

def supported():
    return platform.system()=='Linux' and platform.machine() in ('x86_64','AMD64')

def detect(layout='legacy'):
    root=safe(target_root(layout))
    installed=False;altered=False
    if root.exists() or root.is_symlink():
        if root.is_symlink() or not root.is_dir():
            raise DependencyError('Existing OpenBOR runtime path is not a plain directory; reconcile it manually.')
        if verify(root): installed=supported()
        elif layout=='legacy': raise DependencyError('Existing OpenBOR runtime changed; preserve and reconcile it manually.')
        else: altered=True
    exe=root/'usr/bin/OpenBOR'
    facts=dict(provider='appimage',scope='user',installed=installed,version=VERSION if installed else None,
               sha256=ASSET_SHA256 if installed else None,executable=str(exe),launch_argv=[str(exe)],
               capabilities_checked=False)
    if altered: facts['altered']=True
    return facts

def require(facts):
    if facts.get('installed') is not True or facts.get('version')!=VERSION or facts.get('sha256')!=ASSET_SHA256:
        raise DependencyError('Exact OpenBOR 6391 runtime is required.')
    if not verify(target_root(layout_of(facts))):
        raise DependencyError('OpenBOR runtime path or bytes changed.')

def check_host(facts):
    require(facts)
    return _check_host(target_root(layout_of(facts)))

def _check_host(root):
    exe=safe(root/'usr/bin/OpenBOR')
    with exe.open('rb') as stream:
        header=stream.read(64)
    if not supported() or header[:7]!=b'\x7fELF\x02\x01\x01' or header[18:20]!=b'\x3e\x00':
        raise DependencyError('OpenBOR requires Linux x86_64.')
    try:
        env={key: value for key, value in os.environ.items() if not key.startswith('LD_')}
        result=subprocess.run(['ldd',str(exe)],stdin=subprocess.DEVNULL,capture_output=True,text=True,
                              timeout=15,env={**env,'LC_ALL':'C'})
    except (OSError,subprocess.TimeoutExpired) as exc:
        raise DependencyError(f'Cannot inspect OpenBOR host libraries: {exc}') from exc
    output=result.stdout+result.stderr
    missing=re.findall(r'(\S+)\s+=>\s+not found',output)
    if missing:
        raise DependencyError('OpenBOR host libraries missing: ' + ', '.join(sorted(set(missing)))
                              + '. Install prerequisites with system tools; no elevation attempted.')
    if result.returncode or 'not found' in output:
        raise DependencyError('Cannot resolve OpenBOR host libraries: ' + output.strip())
    return dict(bytes_verified=True,elf_checked=True,architecture='x86_64',fuse_required=False,
                libraries_resolved=True,engine_launched=False,gameplay_checked=False)

def running(facts):
    for entry in Path('/proc').iterdir():
        if not entry.name.isdecimal(): continue
        try:
            if entry.stat().st_uid==os.getuid() and (entry/'comm').read_text().strip().lower()=='openbor':
                return True
        except FileNotFoundError: continue
        except PermissionError as exc: raise DependencyError('Cannot inspect same-user OpenBOR processes.') from exc
    return False

def requirement_layout(req):
    layout=req.get('layout','legacy')
    if layout not in LAYOUTS: raise DependencyError(f'Unsupported OpenBOR runtime layout: {layout}')
    return layout

def payload(context):
    return _payload(context)[0]

def _payload(context):
    root=safe(context['package_root'])
    # Intake creates an immutable package snapshot. Independently bind bytes here.
    import packages
    if packages.check(root)['digest']!=context['package_digest']:
        raise DependencyError('Dependency package snapshot changed.')
    man=json.loads((root/'package.json').read_text())
    req=man.get('requires',[])
    if man.get('id') not in packages.OPENBOR_PACKAGES or len(req)!=1 or req[0].get('id')!='openbor':
        raise DependencyError('Unsupported OpenBOR payload package.')
    layout=requirement_layout(req[0])
    archive=safe(root/'engine/runtime.tar.gz')
    if not archive.is_file() or archive.stat().st_size>16*1024*1024:
        raise DependencyError('Bundled OpenBOR runtime archive is absent or exceeds the size limit.')
    with archive.open('rb') as stream:
        data=stream.read(16*1024*1024+1)
    if len(data)>16*1024*1024 or hashlib.sha256(data).hexdigest()!=INDEX['archive_sha256']:
        raise DependencyError('Bundled OpenBOR runtime archive hash mismatch.')
    return data,layout

def check_payload_host(data,context,cancel):
    with tempfile.TemporaryDirectory(prefix='openbor-host-check-',
                                     dir=safe(context['result_file']).parent) as temporary:
        root=Path(temporary)
        extract(data,root,cancel)
        return _check_host(root)

def make_plan(facts,context,layout='legacy'):
    root=target_root(layout)
    publication=None
    if not facts['installed']:
        publication=dict(target=str(root),source='engine/runtime.tar.gz',sha256=INDEX['archive_sha256'])
        if facts.get('altered'):
            publication['preserve_altered']=dict(source=str(root),destination=str(recovery_target(root)))
    notes=['Exact local pinned runtime only; shared runtime retained on game removal.',
           'Extraction is native and requires no FUSE. Graphics/input/gameplay checks remain.']
    if facts.get('altered'):
        notes.insert(0,'The existing OpenBOR runtime copy was altered. Approving moves it aside unchanged to '
                     + Path(publication['preserve_altered']['destination']).name
                     + ' and publishes a fresh verified copy; nothing is deleted.')
    return dict(plan_version=1,operation='prepare-dependency',dependency='openbor',scope='user',
                dependencies={'openbor':facts},actions=[],dependency_commands=[],
                package_digest=context['package_digest'],package_root=context['package_root'],
                runtime_publication=publication,notes=notes)

def extract(data,stage,cancel):
    expected={r['path']:r for r in INDEX['files']}
    seen=set()
    with tarfile.open(fileobj=io.BytesIO(data),mode='r:gz') as tar:
        for member in tar:
            cancel()
            row=expected.get(member.name)
            if not row or member.name in seen or not member.isfile() or member.size!=row['size']:
                raise DependencyError('Unsupported/duplicate archive resource.')
            content=tar.extractfile(member).read(row['size']+1)
            if len(content)!=row['size'] or hashlib.sha256(content).hexdigest()!=row['sha256']:
                raise DependencyError('Runtime member hash mismatch.')
            p=safe(stage/member.name);p.parent.mkdir(parents=True,exist_ok=True)
            with p.open('xb') as f:
                f.write(content);os.fchmod(f.fileno(),row['mode']);f.flush();os.fsync(f.fileno())
            seen.add(member.name)
    if seen!=set(expected) or not verify(stage): raise DependencyError('Incomplete runtime extraction.')
    for p,_,_ in os.walk(stage,topdown=False): _fsync_dir(Path(p))

def _rename_noreplace(source,destination):
    # Linux atomic directory rename with NOREPLACE, never overwrite a competing directory.
    import ctypes
    libc=ctypes.CDLL(None,use_errno=True)
    if libc.renameat2(-100,os.fsencode(source),-100,os.fsencode(destination),1):
        err=ctypes.get_errno();raise OSError(err,os.strerror(err))

def run(context):
    phase=context['phase'];code=0;outcome='succeeded';plan=None;facts=None;completed=[];stage=None
    journal=Path(context['result_file']).parent/'dependency-transactions.json'
    def cancel():
        if Path(context['cancel_file']).exists(): raise InterruptedError('Cancelled at a runtime preparation boundary.')
    message='Exact OpenBOR 6391 prepared; target gameplay checks remain.'
    try:
        if phase not in ('preflight','apply'): raise DependencyError('Unsupported phase.')
        cancel();data,layout=_payload(context);facts=detect(layout)
        if not supported(): raise DependencyError('Linux x86_64 is required.')
        if facts['installed']:
            check_host(facts)
        else:
            check_payload_host(data,context,cancel)
        plan=make_plan(facts,context,layout)
        if phase=='preflight':
            message='Review pinned shared OpenBOR runtime publication or reuse.'
        else:
            if journal.exists(): raise DependencyError('Existing dependency journal requires reconciliation; use a new job.')
            raw=safe(context['approved_plan_file']).read_bytes();saved=json.loads(raw)
            if 'sha256:'+hashlib.sha256(raw).hexdigest()!=context['approved_plan_digest']:
                raise DependencyError('Saved dependency plan digest changed.')
            if (saved.get('job_id'),saved.get('phase'),saved.get('outcome'),saved.get('plan'))!=(context['job_id'],'preflight','succeeded',plan):
                code=30;outcome='conflicted';message='Dependency facts changed; review a new plan.'
            elif not facts['installed']:
                root=safe(target_root(layout));stage=root.parent/('.openbor-stage-'+secrets.token_hex(8))
                preserve=plan['runtime_publication'].get('preserve_altered')
                record=dict(job_id=context['job_id'],completed=[],active_command=['publish-openbor',str(root)],stage=str(stage))
                if preserve: record['preserve_altered']=preserve
                _write_durable(journal,(json.dumps(record)+'\n').encode())
                emit('step_started','Preparing verified local OpenBOR runtime.',step='resolve')
                missing=[];parent=root.parent
                while not parent.exists(): missing.append(parent);parent=parent.parent
                for p in reversed(missing): safe(p).mkdir(mode=0o755);_fsync_dir(p.parent)
                stage.mkdir(mode=0o755);extract(data,stage,cancel);cancel()
                if detect(layout)!=facts: raise DependencyError('Runtime facts changed before publication.')
                if preserve:
                    destination=safe(Path(preserve['destination']))
                    if Path(preserve['source'])!=root or destination.parent!=root.parent:
                        raise DependencyError('Unexpected OpenBOR recovery paths.')
                    record.update(active_command=['preserve-altered-openbor',str(root),str(destination)])
                    _write_durable(journal,(json.dumps(record)+'\n').encode())
                    _rename_noreplace(root,destination);_fsync_dir(root.parent)
                    completed.append(dict(preserved=str(root),destination=str(destination)))
                    record.update(completed=completed,active_command=['publish-openbor',str(root)])
                    _write_durable(journal,(json.dumps(record)+'\n').encode())
                    emit('step_completed','Altered OpenBOR runtime preserved unchanged beside the fresh copy.',step='resolve')
                _rename_noreplace(stage,root)
                stage=None;_fsync_dir(root.parent)
                completed.append(dict(target=str(root),sha256=INDEX['archive_sha256']))
                record.update(completed=completed,active_command=None,detection_pending=True)
                _write_durable(journal,(json.dumps(record)+'\n').encode())
                facts=detect(layout);require(facts)
                record.update(after=facts,detection_pending=False)
                _write_durable(journal,(json.dumps(record)+'\n').encode())
                emit('step_completed','Verified native runtime published; no game launched.',step='resolve')
                cancel()
    except InterruptedError as exc:
        code=130;outcome='cancelled';message=str(exc)
        # Journal remains conservative: runner reconciles any in-progress stage/publication.
    except (DependencyError,OSError,ValueError,KeyError,tarfile.TarError) as exc:
        code=40;outcome='failed';message=str(exc);print(message,file=sys.stderr)
    finally:
        if stage and stage.exists(): shutil.rmtree(stage);_fsync_dir(stage.parent)
    result=dict(result_version=1,job_id=context['job_id'],phase=phase,operation='prepare-dependency',
                outcome=outcome,message=message,dependencies={'openbor':facts},completed_transactions=completed)
    if plan is not None: result['plan']=plan
    _write_durable(Path(context['result_file']),(json.dumps(result,sort_keys=True)+'\n').encode())
    emit('result',message,outcome=outcome)
    return code

if __name__=='__main__':
    if len(sys.argv)!=3 or sys.argv[1]!='--context': sys.exit('Usage: openbor.py --context /absolute/context.json')
    sys.exit(run(json.loads(Path(sys.argv[2]).read_text())))
