"""Pinned OpenBOR resolver and actual package/runner protocol integration checks."""
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tarfile
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import openbor, packages, installs, jobs, compatibility

REPO=Path(os.environ.get('MCL_PACKAGE_REPO',str(Path(__file__).resolve().parents[2]/'momentum-packages')))
PACKAGE=Path(os.environ.get('MIW_PACKAGE_DIR',str(REPO/'marvel-infinity-war/package')))
fixture=None
LAYOUT='legacy'
if (PACKAGE/'package.json').is_file():
    LAYOUT=openbor.requirement_layout(json.loads((PACKAGE/'package.json').read_text())['requires'][0])
if (PACKAGE/'tests/test_lifecycle.py').is_file():
    spec=importlib.util.spec_from_file_location('miw_fixture',PACKAGE/'tests/test_lifecycle.py')
    fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)

def provisional_record(digest):
    return {
        "id": "marvel-infinity-war", "version": fixture.PACKAGE_VERSION, "digest": digest,
        "runtime": "openbor", "installer_validated": True,
        "software": {"provider": "appimage", "scope": "user", "version": openbor.VERSION,
                     "sha256": openbor.ASSET_SHA256},
        "limits": "Provisional exact integration test only; no gameplay certification.",
    }

@unittest.skipUnless(fixture is not None, 'OpenBOR package source fixture is not available')
class OpenBORTests(unittest.TestCase):
    def setUp(self):
        self.f=fixture.Lifecycle('test_fresh_repeat_verify_and_seed');self.f.setUp()
        self.env=patch.dict(os.environ,{'HOME':str(self.f.home)});self.env.start()
        if os.environ.get("MCL_CANDIDATE_EVIDENCE") == "1":
            original = compatibility.find_record
            record = provisional_record(self.f.digest)
            def find(launcher, game, version, digest):
                if (game, version, digest) == (record["id"], record["version"], record["digest"]):
                    return record
                return original(launcher, game, version, digest)
            override = patch.object(compatibility, "find_record", side_effect=find)
            override.start()
            self.addCleanup(override.stop)

    def tearDown(self):self.env.stop();self.f.tearDown()

    def test_exact_reuse_host_checks_and_tamper(self):
        facts=openbor.detect(LAYOUT);self.assertTrue(facts['installed'])
        self.assertEqual(openbor.target_root(LAYOUT),self.f.runtime)
        self.assertFalse(openbor.check_host(facts)['engine_launched'])
        before=fixture.m.inventory(self.f.runtime);self.assertEqual(openbor.detect(LAYOUT),facts)
        self.assertEqual(fixture.m.inventory(self.f.runtime),before)
        (self.f.runtime/'usr/bin/OpenBOR').chmod(0o644)
        if LAYOUT=='legacy':
            with self.assertRaises(openbor.DependencyError):openbor.detect(LAYOUT)
        else:self.assertTrue(openbor.detect(LAYOUT)['altered'])

    def test_missing_runtime_preparation_and_repeat(self):
        shutil.rmtree(self.f.runtime);c=self.f.context();c.update(operation='prepare-dependency')
        self.assertEqual(openbor.run(c),0);self.f.approve(c);self.assertEqual(openbor.run(c),0)
        self.assertTrue(openbor.detect(LAYOUT)['installed']);self.assertTrue(openbor.verify(self.f.runtime))
        journal=json.loads((Path(c['result_file']).parent/'dependency-transactions.json').read_text())
        self.assertIsNone(journal['active_command']);self.assertFalse(journal['detection_pending'])
        c=self.f.context();c.update(operation='prepare-dependency')
        before=fixture.m.inventory(self.f.runtime);self.assertEqual(openbor.run(c),0)
        self.f.approve(c);self.assertEqual(openbor.run(c),0)
        self.assertEqual(fixture.m.inventory(self.f.runtime),before)

    def test_cancel_before_preparation_is_readonly(self):
        shutil.rmtree(self.f.runtime);c=self.f.context();c.update(operation='prepare-dependency')
        Path(c['cancel_file']).touch();self.assertEqual(openbor.run(c),130);self.assertFalse(self.f.runtime.exists())

    def _legacy_copy(self):
        legacy=openbor.target_root()
        if legacy!=self.f.runtime:shutil.copytree(self.f.runtime,legacy,symlinks=True)
        return legacy

    def test_legacy_layout_is_default_and_unchanged(self):
        self.assertEqual(openbor.target_root(),self.f.home/'.local/share/momentum-core/software/openbor/6391')
        self._legacy_copy();facts=openbor.detect();self.assertNotIn('altered',facts);self.assertEqual(openbor.layout_of(facts),'legacy')
        self.assertEqual(openbor.requirement_layout({}),'legacy')
        self.assertEqual(openbor.requirement_layout({'layout':'build'}),'build')
        with self.assertRaises(openbor.DependencyError):openbor.requirement_layout({'layout':'latest'})
        with self.assertRaises(openbor.DependencyError):openbor.layout_of(dict(facts,launch_argv=['/usr/bin/OpenBOR']))

    def _build_layout(self):
        original=openbor._payload
        return patch.object(openbor,'_payload',side_effect=lambda c:(original(c)[0],'build'))

    def _prepare(self):
        c=self.f.context();c.update(operation='prepare-dependency')
        self.assertEqual(openbor.run(c),0);self.f.approve(c);self.assertEqual(openbor.run(c),0)
        return json.loads(Path(c['result_file']).read_text())

    def test_build_layout_publishes_beside_legacy_runtime(self):
        legacy_root=self._legacy_copy();root=openbor.target_root('build')
        if root.exists():shutil.rmtree(root)
        legacy=fixture.m.inventory(legacy_root)
        self.assertEqual(root.parent.name,'builds');self.assertTrue(root.name.startswith('6391-'))
        with self._build_layout():result=self._prepare()
        self.assertEqual(result['outcome'],'succeeded')
        self.assertTrue(openbor.verify(root));self.assertEqual(fixture.m.inventory(legacy_root),legacy)
        facts=openbor.detect('build');self.assertTrue(facts['installed'])
        self.assertEqual(openbor.layout_of(facts),'build');self.assertTrue(openbor.check_host(facts)['bytes_verified'])

    def test_altered_build_runtime_is_preserved_side_by_side(self):
        root=openbor.target_root('build')
        with self._build_layout():
            self._prepare()
            for n in (1,2):
                target=root/'usr/bin/OpenBOR';target.write_bytes(target.read_bytes()+b'local edit')
                altered=fixture.m.inventory(root)
                facts=openbor.detect('build');self.assertTrue(facts['altered']);self.assertFalse(facts['installed'])
                c=self.f.context();c.update(operation='prepare-dependency');self.assertEqual(openbor.run(c),0)
                preserve=json.loads(Path(c['result_file']).read_text())['plan']['runtime_publication']['preserve_altered']
                destination=root.parent/f'{root.name}.altered-{n}'
                self.assertEqual(preserve,dict(source=str(root),destination=str(destination)))
                self.assertEqual(fixture.m.inventory(root),altered);self.assertFalse(destination.exists())
                self.f.approve(c);self.assertEqual(openbor.run(c),0)
                self.assertEqual(fixture.m.inventory(destination),altered);self.assertTrue(openbor.verify(root))
                journal=json.loads((Path(c['result_file']).parent/'dependency-transactions.json').read_text())
                self.assertEqual(journal['completed'][0],dict(preserved=str(root),destination=str(destination)))

    def test_altered_legacy_runtime_still_requires_manual_reconciliation(self):
        legacy=self._legacy_copy()
        target=legacy/'usr/bin/OpenBOR';target.write_bytes(target.read_bytes()+b'local edit')
        before=fixture.m.inventory(legacy)
        with self.assertRaises(openbor.DependencyError):openbor.detect()
        original=openbor._payload
        with patch.object(openbor,'_payload',side_effect=lambda c:(original(c)[0],'legacy')):
            c=self.f.context();c.update(operation='prepare-dependency');self.assertEqual(openbor.run(c),40)
        self.assertEqual(fixture.m.inventory(legacy),before)
        self.assertEqual(list(legacy.parent.glob('*.altered-*')),[])

    def test_unsafe_archive_member_rejected(self):
        buf=io.BytesIO()
        with tarfile.open(fileobj=buf,mode='w:gz') as tar:
            info=tarfile.TarInfo('../escape');info.type=tarfile.SYMTYPE;info.linkname='/etc/passwd';tar.addfile(info)
        stage=self.f.base/'stage';stage.mkdir()
        with self.assertRaises(openbor.DependencyError):openbor.extract(buf.getvalue(),stage,lambda:None)
        self.assertFalse((self.f.base/'escape').exists())

    def test_plan_change_rejected(self):
        shutil.rmtree(self.f.runtime);c=self.f.context();c.update(operation='prepare-dependency')
        openbor.run(c);self.f.approve(c)
        saved=Path(c['approved_plan_file']);saved.write_bytes(saved.read_bytes()+b' ')
        self.assertEqual(openbor.run(c),40);self.assertFalse(self.f.runtime.exists())

    def test_missing_host_library_blocks_publication(self):
        shutil.rmtree(self.f.runtime)
        c=self.f.context();c.update(operation='prepare-dependency')
        response=type('Result',(),dict(returncode=0,stdout='libGL.so.1 => not found',stderr=''))()
        with patch.object(openbor.subprocess,'run',return_value=response):
            self.assertEqual(openbor.run(c),40)
        self.assertFalse(self.f.runtime.exists())
        self.assertEqual(list(Path(c['result_file']).parent.glob('openbor-host-check-*')),[])
        result=json.loads(Path(c['result_file']).read_text())
        self.assertIn('libGL.so.1',result['message'])
        guidance=installs._runtime_prerequisite('openbor',result['message'])
        self.assertEqual(guidance['packages'],['libgl1'])

    def test_symlink_and_world_writable_runtime_are_not_reused(self):
        self.f.runtime.chmod(0o777)
        if LAYOUT=='legacy':
            with self.assertRaises(openbor.DependencyError):openbor.detect(LAYOUT)
        else:self.assertTrue(openbor.detect(LAYOUT)['altered'])
        self.f.runtime.chmod(0o755)
        link=self.f.base/'runtime-link';link.symlink_to(self.f.runtime,target_is_directory=True)
        with self.assertRaises(openbor.DependencyError):openbor.verify(link)

    def test_runner_evidence_and_missing_runtime_plan_context(self):
        class J:
            lock=threading.RLock()
            jobs={}
            def submit(_,label,steps,**kwargs):return dict(label=label,steps=steps,**kwargs)
        inst=installs.Installs(self.f.base,threading.RLock(),lambda:[],lambda g:None,J())
        with patch.object(packages,'snapshot_path',return_value=PACKAGE),patch.object(packages,'read_intake',return_value={'digest':self.f.digest}):
            detail=inst.package_details('marvel-infinity-war',fixture.PACKAGE_VERSION)
            self.assertTrue(detail['package_supported']);self.assertTrue(detail['install_enabled'])
            shutil.rmtree(self.f.runtime)
            detail=inst.package_details('marvel-infinity-war',fixture.PACKAGE_VERSION)
            self.assertTrue(detail['package_supported']);self.assertFalse(detail['install_enabled'])
            job=inst.submit_install('marvel-infinity-war',fixture.PACKAGE_VERSION,source_dir=str(self.f.source),
                games_root=str(self.f.home/'Games'),trusted_digest=self.f.digest)
            self.assertEqual(len(job['steps']),4)
            self.assertTrue(job['meta']['prepare_required_software'])
            for step in job['steps'][:2]:
                self.assertEqual(step['context']['package_digest'],self.f.digest)
                self.assertEqual(step['context']['package_root'],str(PACKAGE))

    def test_real_intake_journal_receipt_and_media(self):
        summary=packages.check(PACKAGE);self.assertEqual(summary['digest'],self.f.digest)
        c=self.f.context();c['intent_helper']=str(Path(installs.__file__).with_name('mcl_intent.py'))
        self.f.runjob(c);self.f.approve(c);result=self.f.runjob(c)
        class J:
            lock=threading.RLock()
            def paths(_,jid):
                d=Path(c['result_file']).parent
                return dict(job_dir=d,intent_file=Path(c['intent_file']),results_dir=d,approved_plan_file=Path(c['approved_plan_file']))
        games=[];here=self.f.base/'app';here.mkdir()
        inst=installs.Installs(here,threading.RLock(),lambda:games,lambda g:games.__setitem__(slice(None),g),J())
        meta=dict(kind='install',package_id='marvel-infinity-war',package_version=fixture.PACKAGE_VERSION,
                  package_digest=self.f.digest,operation='install',game_directory=str(self.f.game),paths=self.f.paths,
                  catalog_defaults={**json.loads((PACKAGE/'package.json').read_text())['catalog'],'name':'Marvel Infinity War','icon':self.f.paths['icon']})
        job=dict(id=c['job_id'],meta=meta,approved_plan_digest=c['approved_plan_digest'],
                 steps=[dict(context=c,declared_steps=['validate','dependencies','stage','configure','verify','commit'])])
        inst._validate_result(job,result)
        rec=inst._receipt_from(job,result);inst._commit_catalog(rec,result)
        self.assertEqual(len(games),1)
        for field in ('icon','cover','video'):
            self.assertTrue(games[0][field].startswith('media/'))
            self.assertTrue((here/games[0][field]).is_file())
        self.assertIn('marvel-infinity-war',games[0]['exec'])
        with patch.object(inst,'_load_receipt',return_value=rec):
            inst._validate_result(job,result)
        # Replay an allocated association after media resolution, before catalog publication.
        games[:]=[];rec['catalog']['associated_once']=False
        inst._commit_catalog(rec,result)
        self.assertTrue(games[0]['cover'].startswith('media/'))
        self.assertTrue(games[0]['video'].startswith('media/'))
        # Existing selected library media must survive first association too.
        games[:]=[dict(id='custom',icon='my-icon',cover='my-cover',video='my-video')]
        rec['catalog'].update(entry_id='custom',associated_once=False)
        result['catalog_proposal']['defaults']=meta['catalog_defaults'].copy()
        inst._commit_catalog(rec,result)
        self.assertEqual([games[0][k] for k in ('icon','cover','video')],['my-icon','my-cover','my-video'])

    def test_real_reconciliation_retains_edited_state_and_content(self):
        class J:
            lock=threading.RLock()
            def paths(_,jid):
                d=Path(current['result_file']).parent
                return dict(job_dir=d,intent_file=Path(current['intent_file']),results_dir=d,approved_plan_file=Path(current['approved_plan_file']))
        inst=installs.Installs(self.f.base,threading.RLock(),lambda:[],lambda g:None,J())
        manifest=json.loads((PACKAGE/'package.json').read_text())
        def operation(op):
            nonlocal current
            current=self.f.context(op);current['intent_helper']=str(Path(installs.__file__).with_name('mcl_intent.py'))
            self.f.runjob(current);self.f.approve(current);result=self.f.runjob(current)
            meta=dict(kind='install',package_id='marvel-infinity-war',package_version=fixture.PACKAGE_VERSION,
                package_digest=self.f.digest,operation=op,game_directory=str(self.f.game),paths=self.f.paths,
                catalog_defaults={**manifest['catalog'],'name':'Marvel Infinity War','icon':self.f.paths['icon']})
            job=dict(id=current['job_id'],meta=meta,approved_plan_digest=current['approved_plan_digest'],
                steps=[dict(context=current,declared_steps=manifest['operations'][op]['steps'])])
            inst._validate_result(job,result);self.f.commit(current,result)
            return result
        current=None;operation('install')
        cfg=self.f.game/'Saves/Marvel_Infinity_War.cfg';cfg.write_bytes(b'changed by player')
        operation('install');self.assertEqual(cfg.read_bytes(),b'changed by player')
        pak=self.f.game/'Paks'/fixture.m.PAK;pak.write_bytes(b'edited game content')
        self.f.runjob(self.f.context('uninstall'),30)
        self.assertEqual(pak.read_bytes(),b'edited game content')



    def test_online_frontend_inputs_and_gate_use_saved_plan(self):
        class J:
            lock=threading.RLock()
            jobs={}
            def submit(_,label,steps,**kwargs):return dict(label=label,steps=steps,**kwargs)
        inst=installs.Installs(self.f.base,threading.RLock(),lambda:[],lambda g:None,J())
        with patch.object(packages,'snapshot_path',return_value=PACKAGE),patch.object(packages,'read_intake',return_value={'digest':self.f.digest}):
            job=inst.submit_install('marvel-infinity-war',fixture.PACKAGE_VERSION,inputs={'download_game':True,'games_root':str(self.f.home/'Games')},trusted_digest=self.f.digest)
            self.assertEqual(len(job['steps']),2)
            preflight,apply=job['steps']
            self.assertTrue(preflight['approve_after']);self.assertEqual(preflight['context']['phase'],'preflight')
            self.assertEqual(apply['context']['phase'],'apply')
            inputs=preflight['context']['inputs']
            self.assertTrue(inputs['download_game'])
            self.assertNotIn('source_dir',inputs)
            c=self.f.context();c['inputs']=inputs
            with patch.object(fixture.m.download_game,'fetch',side_effect=AssertionError('no download in preflight')):
                result=self.f.runjob(c)
            self.assertEqual(result['plan']['network'][0]['url'],fixture.m.download_game.URL)
            self.assertFalse(self.f.game.exists())

if __name__=='__main__':unittest.main()
