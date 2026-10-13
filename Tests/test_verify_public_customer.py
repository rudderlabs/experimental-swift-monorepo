"""The customer check must call the consumer's dependencies.py with arguments it accepts."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch

os.environ["GIT_CONFIG_GLOBAL"] = os.devnull
os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import verify_public_customer
from verify_public_customer import dependency_args

# The consumer's interface: `--set` is repeatable and takes exactly one KEY=X.Y.Z per flag.
CONSUMER_DEPENDENCIES = textwrap.dedent('''\
    import argparse, json
    from pathlib import Path
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", action="append", default=[])
    parser.add_argument("--branch", action="append", default=[])
    args = parser.parse_args()
    path = Path("dependencies.json")
    deps = json.loads(path.read_text())
    for update in args.set:
        key, version = update.split("=", 1)
        deps[key]["version"] = version
    path.write_text(json.dumps(deps))
''')
CONSUMER_VERIFY = textwrap.dedent('''\
    import json
    from pathlib import Path
    deps = json.loads(Path("dependencies.json").read_text())
    print(json.dumps({"runtime": {k: d["version"] for k, d in deps.items()}, "transport": "anonymous-public-git"}))
''')


class DependencyArgsTests(unittest.TestCase):
    def test_one_set_flag_per_selection(self):
        self.assertEqual(dependency_args('sprig', '1.0.1', '1.0.0', '1.2.1'),
                         ['--set', 'sprig=1.0.1', '--set', 'sdk=1.2.1'])

    def test_no_sdk_raise_when_consumer_already_meets_minimum(self):
        self.assertEqual(dependency_args('firebase', '1.1.3', '1.4.1', '1.0.0'), ['--set', 'firebase=1.1.3'])
        self.assertEqual(dependency_args('sprig', '1.0.1', '1.2.1', '1.2.1'), ['--set', 'sprig=1.0.1'])

    def test_sdk_release_selects_only_itself(self):
        self.assertEqual(dependency_args('sdk', '1.4.1', '1.0.0', None), ['--set', 'sdk=1.4.1'])
        self.assertEqual(dependency_args('sdk', '1.4.1', '1.0.0', '1.2.1'), ['--set', 'sdk=1.4.1'])

    def test_versions_compare_numerically(self):
        self.assertEqual(dependency_args('sprig', '1.0.1', '1.10.0', '1.2.1'), ['--set', 'sprig=1.0.1'])


class VerifyCommandTests(unittest.TestCase):
    """verify() against a local consumer whose dependencies.py has the real argument contract."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.consumer = self.root / 'consumer'
        (self.consumer / 'scripts').mkdir(parents=True)
        (self.consumer / 'scripts/dependencies.py').write_text(CONSUMER_DEPENDENCIES)
        (self.consumer / 'scripts/verify.py').write_text(CONSUMER_VERIFY)
        (self.consumer / 'dependencies.json').write_text(json.dumps(
            {key: {'version': '1.0.0'} for key in ('sdk', 'sprig', 'firebase')}))
        (self.consumer / 'Package.resolved').write_text('{"pins": []}')
        lock = self.consumer / 'PublicationDemo.xcodeproj/project.xcworkspace/xcshareddata/swiftpm'
        lock.mkdir(parents=True)
        (lock / 'Package.resolved').write_text('{"pins": []}')
        subprocess.run(['git', 'init', '-q', self.consumer], check=True)
        subprocess.run(['git', '-C', self.consumer, '-c', 'user.name=t', '-c', 'user.email=t@example.com',
                        'commit', '-q', '--allow-empty', '-m', 'init'], check=True)
        self.destination = self.root / 'evidence'
        self.destination.mkdir()

    def verify(self, key, version):
        packages = {'sdk': {}, 'sprig': {'sdkMinimum': '1.2.1'}, 'firebase': {'sdkMinimum': '1.0.0'}}
        with patch.object(verify_public_customer, 'inventory', return_value=packages):
            return verify_public_customer.verify(key, version, self.destination, consumer_source=self.consumer)

    def test_integration_upgrade_with_sdk_minimum_is_accepted_by_the_consumer(self):
        result = self.verify('sprig', '1.0.1')
        self.assertEqual(result['runtime'], {'sdk': '1.2.1', 'sprig': '1.0.1', 'firebase': '1.0.0'})
        self.assertEqual(result['package'], 'sprig')
        saved = json.loads((self.destination / 'customer-result.json').read_text())
        self.assertEqual(saved['version'], '1.0.1')
        self.assertTrue((self.destination / 'Xcode-Package.resolved').exists())

    def test_sdk_upgrade(self):
        self.assertEqual(self.verify('sdk', '1.4.1')['runtime'], {'sdk': '1.4.1', 'sprig': '1.0.0', 'firebase': '1.0.0'})

    def test_local_consumer_is_copied_not_modified(self):
        self.verify('firebase', '1.1.3')
        self.assertEqual(json.loads((self.consumer / 'dependencies.json').read_text())['firebase']['version'], '1.0.0')


if __name__ == '__main__':
    unittest.main()
