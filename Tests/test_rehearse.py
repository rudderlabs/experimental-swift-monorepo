"""The local lifecycle rehearsal: the modeled `gh`, and a fast real subset when Swift builds are enabled."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

os.environ["GIT_CONFIG_GLOBAL"] = os.devnull  # ignore personal git settings such as tag.gpgsign
os.environ.update(GIT_CONFIG_COUNT="3", GIT_CONFIG_KEY_0="gc.auto", GIT_CONFIG_VALUE_0="0",  # no background gc
                  GIT_CONFIG_KEY_1="gc.autoDetach", GIT_CONFIG_VALUE_1="false",  # racing temp-dir cleanup
                  GIT_CONFIG_KEY_2="maintenance.auto", GIT_CONFIG_VALUE_2="false")
os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from common import commit, git, load, run, write_json
from reviewed_publication import BOT
import rehearse

REPOSITORY = 'rudderlabs/experimental-integration-swift-sprig'


class ModeledGitHubTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        remote = self.root / 'remotes/experimental-integration-swift-sprig.git'
        run(['git', 'init', '--quiet', '--bare', '--initial-branch=main', remote])
        work = self.root / 'work'
        run(['git', 'clone', '--quiet', remote, work])
        (work / 'README.md').write_text('# Sprig\n')
        self.head = commit(work, 'test: publication branch')
        git(work, 'push', '--quiet', 'origin', 'HEAD:refs/heads/publication/sprig/0.1.0')
        write_json(self.root / 'github/state.json',
                   {'remotes': str(self.root / 'remotes'), 'pulls': {}, 'releases': {}})
        (self.root / 'body.md').write_text('Body\n')

    def gh(self, *args):
        output = io.StringIO()
        with patch.dict(os.environ, REHEARSAL_GITHUB=str(self.root / 'github')), contextlib.redirect_stdout(output):
            rehearse.github(list(args))
        return output.getvalue().strip()

    def test_bot_pr_round_trip(self):
        url = self.gh('pr', 'create', '--repo', REPOSITORY, '--base', 'main', '--head', 'publication/sprig/0.1.0',
                      '--title', 'T', '--body-file', str(self.root / 'body.md'))
        [[pr]] = json.loads(self.gh('api', '--paginate', '--slurp', f'repos/{REPOSITORY}/pulls?state=all'
                                    '&head=rudderlabs:publication/sprig/0.1.0&base=main&per_page=100'))
        self.assertEqual((pr['html_url'], pr['user']['login'], pr['head']['sha'], pr['state']),
                         (url, BOT, self.head, 'open'))
        self.assertEqual(json.loads(self.gh('api', f'repos/{REPOSITORY}/pulls/1'))['body'], 'Body\n')
        self.assertEqual(json.loads(self.gh('api', '--paginate', '--slurp', f'repos/{REPOSITORY}/releases')), [[]])

    def test_unmodeled_calls_and_unknown_repositories_fail(self):
        for args in (['api', 'user'], ['auth', 'status'], ['repo', 'view', 'rudderlabs/production-repo'],
                     ['release', 'create', '0.1.0', '--repo', REPOSITORY, '--verify-tag', '--title', 'T',
                      '--notes-file', str(self.root / 'body.md')]):
            with self.subTest(args=args), self.assertRaises((ValueError, RuntimeError)):
                self.gh(*args)


@unittest.skipUnless(os.environ.get("RUN_SWIFT_BUILD_TESTS") == "1", "set RUN_SWIFT_BUILD_TESTS=1 to run swift build")
class RehearsalTests(unittest.TestCase):
    """Setup, bootstrap, takeover and one integration release; `python3 scripts/rehearse.py` runs all nine steps."""

    def test_first_steps_pass_offline_and_leave_evidence(self):
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stdout(io.StringIO()):
            directory = rehearse.rehearse(base=temp, quick=True, through=3)
            evidence = load(directory / 'evidence.json')
            self.assertEqual(load(Path(temp) / 'latest.json'), {'path': str(directory)})
            self.assertEqual(evidence['status'], 'passed')
            self.assertEqual([(s['step'], s['status']) for s in evidence['steps']],
                             [(n, 'passed') for n in range(4)])
            self.assertEqual(git(directory / 'remotes/experimental-integration-swift-sprig.git', 'tag'), '0.1.1\n0.1.2')
            self.assertEqual(git(directory / 'remotes/experimental-rudder-sdk-swift.git', 'tag'), '0.1.0')

    def test_a_failing_step_stops_with_its_name(self):
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stdout(io.StringIO()), \
             patch('rehearse.queue', return_value=([], [])):
            with self.assertRaisesRegex(rehearse.RehearsalError,
                                        r'Step 1 \(bootstrap a README-only public repository\) failed: '
                                        'AssertionError: SDK bootstrap PR expected'):
                rehearse.rehearse(base=temp, quick=True, through=1)
            evidence = load(Path(load(Path(temp) / 'latest.json')['path']) / 'evidence.json')
            self.assertEqual((evidence['status'], evidence['steps'][-1]['status']), ('failed', 'failed'))


if __name__ == '__main__':
    unittest.main()
