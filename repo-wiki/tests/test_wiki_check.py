import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/wiki_check.py'
spec = importlib.util.spec_from_file_location('wiki_check', SCRIPT)
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)


class WikiCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        self.wiki = self.repo / 'wiki'
        (self.repo / 'src').mkdir()
        (self.repo / 'src/a.c').write_text('int a;\nint b;\n')
        (self.wiki / 'content').mkdir(parents=True)
        (self.wiki / 'content/a.md').write_text('# A\n[src](../../src/a.c#L1-L2)\n')
        self.page = {'path': 'content/a.md', 'questions': ['Who writes a?'],
                     'sources': ['src/a.c'], 'watch': ['src'], 'depends_on': []}
        self.plan = {'pages': [self.page]}
        w.save(self.wiki / '_meta/plan.json', self.plan)

    def snap(self, saved=None):
        errors, snap = w.inputs(self.repo, self.wiki, self.page, saved or {})
        self.assertEqual(errors, [])
        return snap

    def test_valid_range_and_stable(self):
        snap = self.snap()
        self.assertEqual(w.freshness(self.plan, {'content/a.md': ([], snap)}, {'content/a.md': snap}), {'content/a.md': []})

    def test_out_of_range_rejected(self):
        (self.wiki / 'content/a.md').write_text('[src](../../src/a.c#L1-L9)')
        self.assertTrue(w.inputs(self.repo, self.wiki, self.page, {})[0])

    def test_dirty_input_detected(self):
        old = self.snap()
        (self.repo / 'src/a.c').write_text('int changed;\nint b;\n')
        now = self.snap()
        self.assertIn('sources_or_cards_changed', w.freshness(self.plan, {'content/a.md': ([], now)}, {'content/a.md': old})['content/a.md'])

    def test_new_file_and_deletion_detected(self):
        old = self.snap()
        (self.repo / 'src/new.c').write_text('int new;')
        now = self.snap()
        self.assertNotEqual(old['inputs'], now['inputs'])
        (self.repo / 'src/new.c').unlink()
        self.assertEqual(old['inputs'], self.snap()['inputs'])

    def test_source_deletion_fails(self):
        (self.repo / 'src/a.c').unlink()
        self.assertTrue(w.inputs(self.repo, self.wiki, self.page, {})[0])

    def test_manual_edit_preserved(self):
        args = ['python3', str(SCRIPT), 'checkpoint', '--repo', str(self.repo), '--wiki', str(self.wiki), '--page', 'content/a.md']
        self.assertEqual(subprocess.run(args, capture_output=True).returncode, 0)
        p = self.wiki / 'content/a.md'
        p.write_text(p.read_text() + '\nmanual addition')
        before = p.read_bytes()
        self.assertEqual(subprocess.run(args, capture_output=True).returncode, 2)
        self.assertEqual(p.read_bytes(), before)
        self.assertEqual(subprocess.run(args + ['--accept-edits'], capture_output=True).returncode, 0)

    def test_card_change_detected(self):
        (self.wiki / '_meta/cards').mkdir()
        card = self.wiki / '_meta/cards/a.md'
        card.write_text('a')
        self.page['cards'] = ['_meta/cards/a.md']
        old = self.snap()
        card.write_text('b')
        self.assertNotEqual(old['inputs'], self.snap()['inputs'])

    def test_dependency_still_stale_after_parent_checkpoint(self):
        old = self.snap()
        child = dict(self.page, path='content/b.md', depends_on=['content/a.md'])
        (self.wiki / 'content/b.md').write_text('[src](../../src/a.c#L1-L2)')
        saved = {'content/a.md': old}
        saved['content/b.md'] = w.inputs(self.repo, self.wiki, child, saved)[1]
        (self.repo / 'src/new.c').write_text('new')
        saved['content/a.md'] = self.snap(saved)
        plan = {'pages': [self.page, child]}
        now = w.inspect_all(self.repo, self.wiki, plan, saved)
        result = w.freshness(plan, now, saved)
        self.assertIn('dependency_checkpoint_changed', result['content/b.md'])

    def test_external_symlink_rejected(self):
        (self.repo / 'src/external').symlink_to('/etc/hosts')
        self.assertTrue(w.inputs(self.repo, self.wiki, self.page, {})[0])

    def test_path_escape_rejected(self):
        with self.assertRaises(ValueError):
            w.local(self.wiki, '../src/a.c')

    def test_quoted_space_path(self):
        (self.repo / 'src/with (space).c').write_text('int x;')
        (self.wiki / 'content/a.md').write_text('[src](<../../src/with (space).c#L1>)')
        self.snap()

    def test_unclosed_fence(self):
        p = self.wiki / 'content/a.md'
        p.write_text(p.read_text() + '\n```c\nint a;')
        self.assertIn('unclosed code fence', w.inputs(self.repo, self.wiki, self.page, {})[0])


    def v4(self):
        plan = json.loads(json.dumps(self.plan))
        plan['schema_version'] = 4
        plan['scope'] = {'request': '完整解释 src 的调度模块', 'roots': ['src'], 'user_exclusions': []}
        plan['coverage'] = [{'area': '调度模块', 'paths': ['src'], 'pages': ['content/a.md'],
                             'status': 'complete', 'gaps': []}]
        plan['pages'][0].update(title='调度机制', kind='design', sections=['时间模型', '窗口例子'],
                                parent=None, next='')
        return plan

    def cli(self, command, *extra):
        return subprocess.run(['python3', str(SCRIPT), command, '--repo', str(self.repo),
                               '--wiki', str(self.wiki), *extra], capture_output=True, text=True)

    def test_v4_mechanical_completion_requires_v5_content_reviews(self):
        w.save(self.wiki / '_meta/plan.json', self.v4())
        self.assertEqual(self.cli('checkpoint', '--page', 'content/a.md').returncode, 0)
        result = self.cli('finish')
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertTrue(json.loads(result.stdout)['declared_scope_and_files_complete'])
        self.assertFalse(json.loads(result.stdout)['ready_for_delivery'])

    def test_finished_pages_do_not_erase_pending_area(self):
        plan = self.v4()
        plan['scope']['roots'].append('tools')
        plan['coverage'].append({'area': '配置编辑器', 'paths': ['tools'], 'pages': [],
                                 'status': 'planned', 'gaps': ['GUI、schema、插件未写']})
        w.save(self.wiki / '_meta/plan.json', plan)
        self.assertEqual(self.cli('checkpoint', '--page', 'content/a.md').returncode, 0)
        result = self.cli('finish')
        self.assertEqual(result.returncode, 1)
        self.assertIn('配置编辑器', result.stdout)
        self.assertEqual(self.cli('plan').returncode, 0)

    def test_false_complete_with_gaps_rejected(self):
        plan = self.v4()
        plan['coverage'][0]['gaps'] = ['尚未读配置验证器']
        self.assertTrue(w.coverage_issues(plan, True))

    def test_declared_root_missing_coverage(self):
        plan = self.v4()
        plan['scope']['roots'].append('ConfigTool')
        self.assertTrue(any('no coverage area' in e for e in w.coverage_issues(plan, False)))

    def test_self_exclusion_rejected(self):
        plan = self.v4()
        plan['coverage'][0].update(status='excluded', pages=[])
        self.assertTrue(any('no matching user exclusion' in e for e in w.coverage_issues(plan, True)))

    def test_user_excluded_scope_can_be_accounted_for(self):
        plan = self.v4()
        plan['scope']['roots'].append('vendor')
        plan['scope']['user_exclusions'] = [{'path': 'vendor', 'reason': '用户明确只看接口不生成此目录文档'}]
        plan['coverage'].append({'area': '厂商内部', 'paths': ['vendor'], 'pages': [],
                                 'status': 'excluded', 'gaps': []})
        self.assertEqual(w.coverage_issues(plan, True), [])

    def test_coverage_unknown_page(self):
        plan = self.v4()
        plan['coverage'][0]['pages'].append('content/missing.md')
        self.assertTrue(any('unknown page' in e for e in w.coverage_issues(plan, True)))

    def test_legacy_read_checks_work_but_finish_refuses(self):
        self.assertEqual(self.cli('check').returncode, 0)
        self.assertEqual(self.cli('finish').returncode, 1)
        self.assertIn('legacy checkpoints', self.cli('finish').stdout)

    def test_finish_detects_stale_source(self):
        w.save(self.wiki / '_meta/plan.json', self.v4())
        self.assertEqual(self.cli('checkpoint', '--page', 'content/a.md').returncode, 0)
        (self.repo / 'src/a.c').write_text('int other;\nint b;\n')
        result = self.cli('finish')
        self.assertEqual(result.returncode, 1)
        self.assertIn('sources_or_cards_changed', result.stdout)

    def test_finish_detects_pending_action(self):
        plan = self.v4()
        plan['pages'][0]['next'] = '补充 ISR 边界例子'
        self.assertTrue(any('unfinished action' in e for e in w.coverage_issues(plan, True)))

    def test_parent_cycle_rejected(self):
        plan = self.v4()
        plan['pages'][0]['parent'] = 'content/a.md'
        self.assertTrue(any('parent cycle' in e for e in w.coverage_issues(plan, False)))

    def test_finish_cannot_be_narrowed_to_one_page(self):
        w.save(self.wiki / '_meta/plan.json', self.v4())
        result = self.cli('finish', '--page', 'content/a.md')
        self.assertEqual(result.returncode, 2)
        self.assertIn('whole requested scope', result.stdout)


if __name__ == '__main__':
    unittest.main(verbosity=2)
