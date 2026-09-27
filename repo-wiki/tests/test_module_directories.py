"""Physical output layout must match the module catalogue, including nested modules."""
import copy
from pathlib import Path
import tempfile
import unittest

import test_quality_gates as fixture

g = fixture.w.gates


class ModuleDirectories(unittest.TestCase):
    def setUp(self):
        self.plan = {'pages': [{'path': 'content/system/scheduler/README.md'},
                               {'path': 'content/tool/editor/README.md'}],
                     'modules': [{'id': 'scheduler', 'directory': 'content/system/scheduler',
                                  'pages': ['content/system/scheduler/README.md']},
                                 {'id': 'editor', 'directory': 'content/tool/editor',
                                  'pages': ['content/tool/editor/README.md']}]}

    def test_separate_module_folders_accepted(self):
        self.assertEqual(g.module_directory_issues(self.plan), [])

    def test_missing_directory_rejected(self):
        del self.plan['modules'][0]['directory']
        self.assertTrue(g.module_directory_issues(self.plan))

    def test_flat_module_pages_rejected(self):
        self.plan['modules'][0]['pages'] = ['content/scheduler.md']
        self.plan['pages'][0]['path'] = 'content/scheduler.md'
        self.assertTrue(any('outside its directory' in i for i in g.module_directory_issues(self.plan)))

    def test_all_modules_cannot_claim_content_as_their_directory(self):
        self.plan['modules'][0]['directory'] = 'content'
        self.assertTrue(g.module_directory_issues(self.plan))

    def test_two_modules_cannot_share_folder_even_with_different_pages(self):
        for directory in ('content/system/scheduler', 'content/System/Scheduler'):
            with self.subTest(directory=directory):
                self.plan['modules'][1]['directory'] = directory
                self.assertTrue(any('already owned' in i for i in g.module_directory_issues(self.plan)))

    def test_unsafe_and_noncanonical_directories_rejected(self):
        for directory in ('/content/one', '../outside', 'content/../other', 'content//one',
                          'content/./one', 'content/one/', 'content\\one', 'C:/outside',
                          '_meta/one', 'content/_flows/one', 'content/_overview/one'):
            with self.subTest(directory=directory):
                self.plan['modules'][0]['directory'] = directory
                self.assertTrue(g.module_directory_issues(self.plan))

    def test_same_prefix_different_folder_does_not_count_as_containment(self):
        self.plan['modules'][0]['directory'] = 'content/system/schedule'
        self.assertTrue(g.module_directory_issues(self.plan))

    def test_nested_modules_have_distinct_owners(self):
        self.plan['modules'].append({'id': 'queue', 'directory': 'content/system/scheduler/queue',
                                    'pages': ['content/system/scheduler/queue/README.md']})
        self.plan['pages'].append({'path': 'content/system/scheduler/queue/README.md'})
        self.assertEqual(g.module_directory_issues(self.plan), [])
        self.plan['modules'][0]['pages'].append('content/system/scheduler/queue/README.md')
        self.assertTrue(any('multiple owners' in i for i in g.module_directory_issues(self.plan)))

    def test_page_under_module_folder_cannot_escape_ownership(self):
        self.plan['modules'][0]['pages'] = []
        self.assertTrue(any('nearest module directory' in i for i in g.module_directory_issues(self.plan)))

    def test_global_navigation_and_planned_shared_pages_allowed(self):
        for rel in ('README.md', 'REPORT.md', 'content/_overview/architecture.md', 'content/_flows/startup.md'):
            self.plan['pages'].append({'path': rel})
        self.assertEqual(g.module_directory_issues(self.plan), [])
        self.plan['pages'].append({'path': 'content/misc.md'})
        self.assertTrue(g.module_directory_issues(self.plan))

    def test_case_variant_pages_collide(self):
        self.plan['pages'].append({'path': 'content/System/Scheduler/readme.md'})
        self.assertTrue(any('collide' in i for i in g.module_directory_issues(self.plan)))

    def test_actual_unplanned_markdown_is_not_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki = Path(tmp)
            (wiki / '_meta').mkdir()
            (wiki / '_meta/research.md').write_text('Working notes')
            (wiki / 'README.md').write_text('Navigation')
            self.assertEqual(g.module_directory_issues(self.plan, wiki, check_files=True), [])
            (wiki / 'orphan.md').write_text('Unclassified module prose')
            self.assertTrue(any('unplanned Wiki page' in i for i in g.module_directory_issues(self.plan, wiki, check_files=True)))

    def test_directory_cannot_be_file_or_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki = Path(tmp)
            folder = wiki / 'content/system/scheduler'; folder.parent.mkdir(parents=True)
            folder.write_text('file, not module folder')
            self.assertTrue(any('is a file' in i for i in g.module_directory_issues(self.plan, wiki)))
            folder.unlink()
            folder.symlink_to(folder.parent, target_is_directory=True)
            self.assertTrue(any('cannot alias' in i for i in g.module_directory_issues(self.plan, wiki)))

    def test_gates_reject_missing_folder_declaration_through_cli(self):
        f = fixture.QualityGates('runTest'); f.setUp()
        self.addCleanup(f.doCleanups)
        f.complete()
        del f.module['directory']; f.persist()
        for command in ('plan', 'check', 'finish'):
            with self.subTest(command=command):
                self.assertNotEqual(f.cli(command).returncode, 0)
        self.assertNotEqual(f.checkpoint().returncode, 0)


if __name__ == '__main__':
    unittest.main()
