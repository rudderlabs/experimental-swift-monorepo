"""The customer check builds a generated consumer on the checked platforms each package supports."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ["GIT_CONFIG_GLOBAL"] = os.devnull
os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import verify_public_customer
from common import inventory
from verify_public_customer import platforms, write_consumer

PACKAGES = inventory()
URL = 'https://github.com/rudderlabs/experimental-integration-swift-sprig.git'


class PlatformsTests(unittest.TestCase):

    def test_only_checked_platforms_the_package_supports(self):
        self.assertEqual(platforms(PACKAGES['sprig']), ['iOS'])
        self.assertEqual(platforms(PACKAGES['firebase']), ['iOS', 'macOS'])
        self.assertEqual(platforms(PACKAGES['swift-sdk']), ['iOS', 'macOS'])

    def test_checked_order_not_inventory_order(self):
        self.assertEqual(platforms({'platforms': ['tvOS 15', 'macOS 12', 'iOS 15']}), ['iOS', 'macOS'])


class WriteConsumerTests(unittest.TestCase):

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name) / 'consumer'

    def test_manifest_pins_the_exact_public_version(self):
        write_consumer(self.folder, PACKAGES['firebase'], URL.replace('sprig', 'firebase'), '1.1.5')
        manifest = (self.folder / 'Package.swift').read_text()
        self.assertTrue(manifest.startswith('// swift-tools-version: 5.9\n'))
        self.assertIn('platforms: [.iOS(.v15), .macOS(.v12)]', manifest)
        self.assertIn('.package(url: "https://github.com/rudderlabs/experimental-integration-swift-firebase.git", '
                      'exact: "1.1.5")', manifest)
        self.assertIn('.product(name: "RudderIntegrationFirebase", package: "experimental-integration-swift-firebase")',
                      manifest)
        self.assertNotIn('tvOS', manifest)
        self.assertEqual((self.folder / 'Sources/Consumer/Consumer.swift').read_text(), 'import RudderIntegrationFirebase\n')

    def test_minor_versions_and_unsupported_packages(self):
        write_consumer(self.folder, {'target': 'T', 'platforms': ['iOS 15.4']}, URL, '1.0.0')
        self.assertIn('platforms: [.iOS(.v15_4)]', (self.folder / 'Package.swift').read_text())
        with self.assertRaisesRegex(ValueError, 'supports none'):
            write_consumer(self.folder, {'target': 'T', 'platforms': ['tvOS 15']}, URL, '1.0.0')


class VerifyTests(unittest.TestCase):
    """verify() with xcodebuild replaced by a fake that writes Package.resolved like xcodebuild does."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.destination = Path(temp.name) / 'evidence'

    def verify(self, key, version, pinned=None):
        built = []

        def build(folder, platform, state, env):
            built.append(platform)
            self.assertNotIn('GH_TOKEN', env)
            pins = {'experimental-rudder-sdk-swift': '1.5.0', PACKAGES[key]['repository']: pinned or version}
            (folder / 'Package.resolved').write_text(json.dumps(
                {'pins': [{'identity': k, 'state': {'version': v}} for k, v in pins.items()], 'version': 2}))

        with patch.object(verify_public_customer, 'build', side_effect=build):
            return verify_public_customer.verify(key, version, self.destination), built

    def test_each_package_builds_its_checked_platforms(self):
        for key, expected in (('sprig', ['iOS']), ('firebase', ['iOS', 'macOS']), ('swift-sdk', ['iOS', 'macOS'])):
            with self.subTest(key):
                result, built = self.verify(key, '1.5.0')
                self.assertEqual(built, expected)
                self.assertEqual(result['platforms'], expected)

    def test_evidence(self):
        result, _ = self.verify('sprig', '1.0.2')
        saved = json.loads((self.destination / 'customer-result.json').read_text())
        self.assertEqual(saved, result)
        self.assertEqual(saved['status'], 'passed')
        self.assertEqual(saved['transport'], 'anonymous-public-git')
        self.assertEqual(saved['resolved'], {'experimental-integration-swift-sprig': '1.0.2',
                                             'experimental-rudder-sdk-swift': '1.5.0'})
        self.assertIn('pins', json.loads((self.destination / 'Package.resolved').read_text()))

    def test_wrong_pin_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'resolved to 1.0.1, expected 1.0.2'):
            self.verify('sprig', '1.0.2', pinned='1.0.1')
        self.assertFalse((self.destination / 'customer-result.json').exists())


if __name__ == '__main__':
    unittest.main()
