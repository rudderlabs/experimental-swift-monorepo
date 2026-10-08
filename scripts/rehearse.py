"""Repeatable local release lifecycle using real Git tags and fresh Swift consumers."""
import argparse
from datetime import datetime, timezone
import fcntl
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile

from common import ROOT, CONSUMER_NAME, RELEASE_BRANCH, allowlist, commit, git, inventory, load, run, write_json
from project import export
from publish import publish, publication_lock
from release_plan import affected, from_outputs, shared_markers
from dependency_policy import markers as dependency_markers, sync_inventory

NAMES = allowlist()  # old demo layout until the rehearsal is rewritten


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def rehearse(ios=False, consumer_template=None):
    if git(ROOT, 'status', '--porcelain'):
        raise ValueError('Commit source changes before the rehearsal')
    consumer_template = consumer_template or ROOT.parent / CONSUMER_NAME
    directory = ROOT / '.lab' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    directory.mkdir(parents=True)
    source, remotes = directory/'source', directory/'remotes'
    run(['git', 'clone', '--no-local', ROOT, source])
    git(source, 'checkout', '-B', RELEASE_BRANCH)
    remotes.mkdir()
    # Keep a protected bootstrap default separate from the publication branch.
    locked_branch = 'locked-bootstrap' if RELEASE_BRANCH == 'main' else 'main'
    seed = directory/'locked-main-seed'
    run(['git', 'init', '--initial-branch=' + locked_branch, seed])
    (seed/'README.md').write_text('Locked organization bootstrap branch. Do not publish here.\n')
    locked_main_sha = commit(seed, 'test: sdk-5388 model locked organization main')
    for name in NAMES.values():
        remote = remotes/(name+'.git')
        run(['git', 'init', '--bare', '--initial-branch=' + locked_branch, remote])
        git(seed, 'push', remote, locked_branch)
        hook = remote/'hooks/pre-receive'
        hook.write_text('#!/bin/sh\nwhile read old new ref; do\n  if [ "$ref" = refs/heads/' + locked_branch + ' ]; then\n    echo "main is locked by the organization" >&2\n    exit 1\n  fi\ndone\n')
        hook.chmod(0o755)
    records = {'mode': 'local Git; GitHub Release metadata modeled, Release Please intent supplied by rehearsal',
               'sourceTemplateCommit': git(source, 'rev-parse', 'HEAD'), 'branch': RELEASE_BRANCH,
               'lockedMainCommit': locked_main_sha, 'scenarios': [], 'failures': [],
               'swift': run(['swift', '--version']), 'xcode': run(['xcodebuild', '-version'])}
    write_json(ROOT/'.lab/latest.json', {'path': str(directory)})
    def save():
        write_json(directory/'evidence.json', records)
    def expected_failure(name, action, fragment):
        before = {key: git(remotes/(repo+'.git'), 'show-ref') for key, repo in NAMES.items()}
        try:
            action()
        except (ValueError, RuntimeError) as error:
            if fragment not in str(error):
                raise AssertionError(f'{name}: unexpected failure {error}') from error
            records['failures'].append({'name': name, 'result': 'blocked', 'reason': str(error).splitlines()[0]})
        else:
            raise AssertionError(f'{name}: expected failure did not occur')
        after = {key: git(remotes/(repo+'.git'), 'show-ref') for key, repo in NAMES.items()}
        assert before == after, name + ' changed publication refs'
        save()
        print('PASS guard: ' + name, flush=True)
    versions = {k: load(source/'.release-please-manifest.json')[p['path']]
                for k, p in inventory(source).items()}
    def consumer(name, requested=None, build_ios=False, branches=()):
        folder = directory / 'consumers' / name
        run(['git', 'clone', '--no-local', '--branch', RELEASE_BRANCH, consumer_template, folder])
        deps = module(folder/'scripts/dependencies.py', 'consumer_dependencies')
        deps.render(folder, [f'{k}={v}' for k,v in (requested or versions).items()], branches=branches)
        verify = module(folder/'scripts/verify.py', 'consumer_verify')
        evidence = verify.verify(folder, remotes, build_ios)
        write_json(directory/'evidence'/f'{name}-consumer.json', evidence)
        if name != 'baseline':
            # Keep a concrete upgrade diff that can be reviewed from the consumer perspective.
            commit(folder, 'test: sdk-5388 select experimental package versions')
        return {'path': str(folder), 'runtime': evidence['runtime']}
    def release_scenario(name, selected, build_ios=False, release_source=None):
        print('RUN scenario: ' + name, flush=True)
        before = {key: git(remotes/(repo+'.git'), 'tag', '--list') for key, repo in NAMES.items()}
        result = [publish(key, versions[key], remotes, release_source or source) for key in selected]
        for key in set(NAMES)-set(selected):
            assert before[key] == git(remotes/(NAMES[key]+'.git'), 'tag', '--list'), 'unrelated package released'
        records['scenarios'].append({'name': name, 'published': result, 'consumer': consumer(name, build_ios=build_ios)})
        save()
        print('PASS scenario: ' + name, flush=True)
    def bump(selected, sdk_minimum=None):
        config = load(source/'release/packages.json')
        manifest = load(source/'.release-please-manifest.json')
        for key, version in selected.items():
            p = config['packages'][key]
            old = versions[key]
            versions[key] = version
            (source/p['path']/'version.txt').write_text(version+'\n')
            vf = source/p['path']/'Sources'/p['target']/'Version.swift'
            vf.write_text(vf.read_text().replace('"'+old+'"', '"'+version+'"'))
            manifest[p['path']] = version
            changelog = source/p['path']/'CHANGELOG.md'
            changelog.write_text(changelog.read_text()+f'\n## {version}\n\nLocal lifecycle rehearsal.\n')
            if sdk_minimum and key != 'sdk':
                p['sdkMinimum'] = sdk_minimum
        write_json(source/'.release-please-manifest.json', manifest)
        write_json(source/'release/packages.json', config)
        dependency_markers(source)
        commit(source, 'chore: sdk-5388 prepare reviewed experimental release versions')
    # Reset versions only in the new disposable source fixture, never in the real repository.
    bump({k: '0.1.0' for k in NAMES})
    release_scenario('baseline', list(NAMES), build_ios=ios)
    for name in NAMES.values():
        remote = remotes/(name+'.git')
        git(remote, 'symbolic-ref', 'HEAD', 'refs/heads/' + RELEASE_BRANCH)
        git(remote, 'branch', 'develop', '0.1.0')
    baseline_refs = {key: git(remotes/(name+'.git'), 'show-ref') for key, name in NAMES.items()}
    records['publicationDefaults'] = 'main; protected bootstrap and frozen develop refs retained separately'

    # Verify deterministic exports against the entire generated tree, including provenance.
    with tempfile.TemporaryDirectory() as temp:
        a, b = Path(temp)/'a', Path(temp)/'b'
        export('firebase', '0.1.0', a, source)
        export('firebase', '0.1.0', b, source)
        assert {p.relative_to(a):p.read_bytes() for p in a.rglob('*') if p.is_file()} == {p.relative_to(b):p.read_bytes() for p in b.rglob('*') if p.is_file()}
    records['deterministicExport'] = 'passed'
    initial_refs = git(remotes/(NAMES['sprig']+'.git'), 'show-ref')
    retry = publish('sprig', '0.1.0', remotes, source)
    assert retry['reusedTag'] and initial_refs == git(remotes/(NAMES['sprig']+'.git'), 'show-ref')
    records['sameReleaseRetry'] = 'passed without a new commit or tag'
    expected_failure('wrong version', lambda: publish('sdk','9.9.9',remotes,source), 'differs from version.txt')
    missing = directory/'missing-remotes'; missing.mkdir()
    expected_failure('missing repository', lambda: publish('sdk','0.1.0',missing,source), 'missing or is not bare')
    with publication_lock(remotes, 'sprig'):
        expected_failure('concurrent publisher', lambda: publish('sprig','0.1.0',remotes,source), 'already running')
    policy_file = source/'release/packages.json'
    original_policy = policy_file.read_text()
    config = load(policy_file); del config['packages']['sprig']['policies']['DemoShared']
    write_json(policy_file,config); commit(source,'test: sdk-5388 inject missing dependency policy')
    expected_failure('unclassified shared dependency',lambda: publish('sprig','0.1.0',remotes,source),'Missing or rejected publication policy')
    policy_file.write_text(original_policy); commit(source,'test: sdk-5388 restore dependency policy')
    sprig_file = source/'Integrations/Sprig/Sources/DemoSprig/DemoSprig.swift'
    sprig_file.write_text('import Foundation\n'+sprig_file.read_text().replace('normalize(name)', 'normalize(name).trimmingCharacters(in: .punctuationCharacters)'))
    assert affected(['Integrations/Sprig/Sources/DemoSprig/DemoSprig.swift'],source)==['sprig']
    commit(source,'fix: sdk-5388 strip trailing event punctuation in sprig fixture')
    assert baseline_refs == {key: git(remotes/(name+'.git'), 'show-ref') for key, name in NAMES.items()}
    records['unreleasedSourceChange'] = {
        'sourceCommit': git(source, 'rev-parse', 'HEAD'),
        'publicationRefs': 'unchanged after source commit; real open Release Please PR remains a hosted gate',
        'versionConsumer': consumer('unreleased-source-version', {key:'0.1.0' for key in NAMES}),
        'mainConsumer': consumer('unreleased-source-main', {key:'0.1.0' for key in NAMES}, branches=['sprig=main']),
        'developConsumer': consumer('unreleased-source-develop', {key:'0.1.0' for key in NAMES}, branches=['sprig=develop'])}

    expected_failure('immutable tag conflicts',lambda: publish('sprig','0.1.0',remotes,source),'Existing tag conflicts')
    bump({'sprig':'0.1.1'})
    # Advance source main after approval, then publish only the approved commit.
    approved_sha = git(source, 'rev-parse', 'HEAD')
    approved_source = directory/'approved-release-source'
    run(['git', 'clone', '--no-local', source, approved_source])
    git(approved_source, 'checkout', '--detach', approved_sha)
    approved_text = sprig_file.read_text()
    sprig_file.write_text(approved_text + '\n// UNRELEASED_NEXT_CHANGE must not appear in the approved export.\n')
    advanced_sha = commit(source, 'fix: sdk-5388 model a later unapproved source change')
    assert baseline_refs == {key: git(remotes/(name+'.git'), 'show-ref') for key, name in NAMES.items()}
    # Recovery after a commit push must reuse the existing publication commit.

    try: publish('sprig','0.1.1',remotes,approved_source,interrupt='after-commit')
    except InterruptedError: pass
    else: raise AssertionError('interruption not injected')
    interrupted_sha = git(remotes/(NAMES['sprig']+'.git'),'rev-parse',RELEASE_BRANCH)
    assert not git(remotes/(NAMES['sprig']+'.git'), 'tag', '--list', '0.1.1')
    assert not (directory/'modeled-github-releases'/NAMES['sprig']/'0.1.1.json').exists()
    records['afterCommitState'] = 'publication main served; version tag absent; publication incomplete'
    retry_file = directory/'evidence/pinned-source-cli-retry.json'
    run([sys.executable, ROOT/'scripts/publish.py', 'sprig', '0.1.1',
         '--local-remotes', remotes, '--source-root', approved_source,
         '--result-file', retry_file])
    retry_result = load(retry_file)
    assert retry_result['status'] == 'published' and retry_result['sourceCommit'] == approved_sha
    release_scenario('sprig-only', ['sprig'], release_source=approved_source)
    generated_sprig = git(remotes/(NAMES['sprig']+'.git'), 'show', '0.1.1:Sources/DemoSprig/DemoSprig.swift')
    assert 'UNRELEASED_NEXT_CHANGE' not in generated_sprig
    provenance = json.loads(git(remotes/(NAMES['sprig']+'.git'), 'show', '0.1.1:.publication.json'))
    assert provenance['sourceCommit'] == approved_sha != advanced_sha
    records['approvedSourceCommit'] = {'approved': approved_sha, 'laterMain': advanced_sha,
                                      'exportUsesApprovedCommit': True, 'laterChangeExcluded': True}
    records['branchConsumersAfterRelease'] = {
        'main': consumer('released-main', branches=['sprig=main']),
        'develop': consumer('frozen-develop', {key:'0.1.0' for key in NAMES}, branches=['sprig=develop'])}
    sprig_file.write_text(approved_text)
    commit(source, 'test: sdk-5388 remove the later unapproved fixture change')

    assert interrupted_sha == git(remotes/(NAMES['sprig']+'.git'),'rev-parse','0.1.1')
    records['afterCommitRecovery'] = 'passed; reused generated commit'
    sdk_file = source/'Packages/DemoSDK/Sources/DemoSDK/DemoSDK.swift'
    sdk_file.write_text(sdk_file.read_text().replace('Bundle.module.url(forResource: "PrivacyInfo", withExtension: "xcprivacy") != nil', '(Bundle.module.url(forResource: "PrivacyInfo", withExtension: "xcprivacy").flatMap { try? Data(contentsOf: $0) }) != nil'))
    commit(source,'fix: sdk-5388 verify privacy resource can be read')
    bump({'sdk':'0.1.1'})
    release_scenario('sdk-only', ['sdk'])
    shared = source/'Shared/DemoShared/DemoNormalizer.swift'
    shared.write_text(shared.read_text().replace('.lowercased()', '.lowercased().precomposedStringWithCanonicalMapping'))
    assert shared_markers(source)==['sprig','firebase']
    assert affected(['Shared/DemoShared/DemoNormalizer.swift'],source)==['sprig','firebase']
    commit(source,'fix: sdk-5388 normalize unicode event names in shared source')
    bump({'sprig':'0.1.2','firebase':'0.1.1'})
    # Recovery after the tag push must recreate only the absent release record.
    try: publish('firebase','0.1.1',remotes,source,interrupt='after-tag')
    except InterruptedError: pass
    else: raise AssertionError('interruption not injected')
    assert git(remotes/(NAMES['firebase']+'.git'), 'tag', '--list', '0.1.1') == '0.1.1'
    assert not (directory/'modeled-github-releases'/NAMES['firebase']/'0.1.1.json').exists()
    records['afterTagState'] = 'SwiftPM version tag already served; GitHub release metadata incomplete'
    release_scenario('shared-source', ['sprig','firebase'])
    records['afterTagRecovery'] = 'passed; reused immutable tag and restored modeled release metadata'
    bump({'sdk':'0.2.0','sprig':'0.2.0','firebase':'0.2.0'}, sdk_minimum='0.2.0')
    valid_sdk = sdk_file.read_text()
    sdk_file.write_text(valid_sdk + '\nINVALID SWIFT SOURCE\n')
    commit(source, 'test: sdk-5388 inject a generated package build failure')
    failed_file = directory/'evidence/failed-publication.json'
    expected_failure('generated package build fails before public refs change',
                     lambda: run([sys.executable, ROOT/'scripts/publish.py', 'sdk', '0.2.0',
                                  '--local-remotes', remotes, '--source-root', source,
                                  '--result-file', failed_file]), 'Command failed')
    assert load(failed_file)['status'] == 'incomplete'
    sdk_file.write_text(valid_sdk)
    commit(source, 'test: sdk-5388 restore valid generated package source')
    expected_failure('missing required sdk tag',lambda: publish('sprig','0.2.0',remotes,source),'Command failed')
    release_scenario('coordinated', ['sdk','sprig','firebase'], build_ios=ios)
    # A real public vendor tag exercises manifest -> reviewed markers -> export -> consumer.
    package_manifest = source/'Package.swift'
    package_manifest.write_text(package_manifest.read_text().replace('exact: "1.1.4"', 'exact: "1.1.5"'))
    assert affected(['Package.swift'], source) == ['firebase']
    expected_failure('stale vendor export metadata',
                     lambda: export('firebase', '0.2.0', directory/'stale-vendor-export', source),
                     'Canonical manifest and export vendor metadata differ')
    assert sync_inventory(source) == ['firebase']
    dependency_markers(source, check=True)
    commit(source, 'fix: update firebase fixture vendor requirement and release marker')
    assert affected(['Package.swift'], source, base_ref='HEAD~1') == ['firebase']
    bump({'firebase': '0.2.1'})
    release_scenario('vendor-only', ['firebase'], build_ios=ios)
    vendor_consumer = load(directory/'evidence/vendor-only-consumer.json')
    vendor_pin = next(p for p in vendor_consumer['resolved']['pins'] if p['identity'] == 'swift-collections')
    assert vendor_pin['state']['version'] == '1.1.5'
    generated = git(remotes/(NAMES['firebase']+'.git'), 'show', '0.2.1:Package.swift')
    assert 'exact: "1.1.5"' in generated
    records['vendorOnlyUpdate'] = 'passed; stale metadata blocked, Firebase-only release, generated requirement and consumer vendor 1.1.5'
    records['oldConsumer'] = consumer('old-tags', {key:'0.1.0' for key in NAMES})
    drift = directory/'drift-checkout'
    run(['git','clone','--branch',RELEASE_BRANCH,remotes/(NAMES['sprig']+'.git'),drift])
    (seed/'README.md').write_text('Attempt a fast-forward update to the locked main branch.\n')
    commit(seed, 'test: sdk-5388 attempt a blocked main update')
    expected_failure('organization blocks main writes',
                     lambda: git(seed,'push',remotes/(NAMES['sprig']+'.git'),locked_branch),
                     'main is locked by the organization')
    (drift/'README.md').write_text('Injected manual drift\n')
    commit(drift,'test: sdk-5388 inject publication drift')
    git(drift,'push','origin',RELEASE_BRANCH)
    expected_failure('manual publication drift',lambda: publish('sprig','0.2.0',remotes,source),'manual drift')
    # The negative case remains intact for inspection. The consumer can still install immutable tags.
    records['note'] = 'The sprig publication branch in this disposable run intentionally retains the final drift injection.'
    for name in NAMES.values():
        assert git(remotes/(name+'.git'), 'rev-parse', 'refs/heads/' + locked_branch) == locked_main_sha
        assert git(remotes/(name+'.git'), 'symbolic-ref', 'HEAD') == 'refs/heads/' + RELEASE_BRANCH
    records['lockedMainUnchanged'] = 'passed for all three publication repositories; default main and frozen develop preserved'
    outputs = {}
    for key,p in inventory(source).items():
        outputs.update({p['path']+'--release_created':'true',p['path']+'--version':versions[key],p['path']+'--sha':git(source,'rev-parse','HEAD')})
    assert [x['package'] for x in from_outputs(outputs,source)]==['sdk','sprig','firebase']
    records['releasePleaseOutputAdapter'] = 'passed with fixture outputs; GitHub execution pending'
    records['status'] = 'passed'
    save()
    print(json.dumps({'status':'passed','evidence':str(directory/'evidence.json')},indent=2),flush=True)
    return directory


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--ios', action='store_true')
    parser.add_argument('--consumer-template', type=Path)
    args = parser.parse_args()
    rehearse(args.ios, args.consumer_template)
