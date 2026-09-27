"""Regression oracles from real audit failures; renderer protocol uses a test double."""
import contextlib
import io
import json
from pathlib import Path
import unittest

import test_quality_gates as fixture

g = fixture.w.gates


class EvidenceGates(unittest.TestCase):
    def setUp(self):
        self.f = fixture.QualityGates('runTest')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def test_sampled_or_ast_reading_never_passes_as_full(self):
        for method in ('sampled', 'ast', 'headers', None):
            self.f.analysis['files'][0]['method'] = method
            self.assertNotEqual(self.f.analyze_again().returncode, 0)

    def test_just_setting_read_flag_without_receipt_fails(self):
        path = self.f.wiki / '_meta/history.jsonl'
        # Remove the entire history rather than corrupt a hash chain: still cannot pass.
        path.unlink()
        r = self.f.cli('analyze', '--review-file', str(self.f.analysis_file), '--reuse-existing', '--reason', 'Migration')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('read receipts', r.stdout)

    def test_gap_in_line_ranges_is_not_full_reading(self):
        f = self.f
        (f.repo / 'README.md').write_text('one\ntwo\nthree\n')
        for line in (1, 3):
            f.cli('read', '--source', 'README.md', '--start-line', str(line), '--end-line', str(line))
        fixture.w.save(f.analysis_file, f.analysis)
        r = f.cli('analyze', '--review-file', str(f.analysis_file), '--reuse-existing', '--reason', 'Update')
        self.assertIn('next line 2', r.stdout)
        f.cli('read', '--source', 'README.md', '--start-line', '2', '--end-line', '2')
        self.assertEqual(f.analyze_again().returncode, 0)

    def test_text_source_cannot_be_laundered_as_structured_inspection(self):
        f = self.f
        report = f.wiki / '_meta/reading/report.md'; report.parent.mkdir()
        report.write_text('AST summary only')
        f.analysis['files'][0].update(method='structured', inspection={
            'source_sha256': g.sha(f.repo / 'README.md'), 'report': '_meta/reading/report.md',
            'report_sha256': g.sha(report), 'method': 'AST extraction'})
        self.assertIn('AST or symbol extraction', f.analyze_again().stdout)

    def test_source_cannot_be_hidden_as_nonsemantic(self):
        f = self.f
        f.analysis['files'][1].update(status='nonsemantic', category='duplicate', modules=[])
        self.assertIn('cannot be silently classified', f.analyze_again().stdout)

    def test_invalid_read_range_not_clamped(self):
        r = self.f.cli('read', '--source', 'src/a.c', '--end-line', '99')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('never clamp', r.stdout)

    def test_identical_source_copy_can_reuse_actual_reading(self):
        f = self.f
        (f.repo / 'src/copy.c').write_bytes((f.repo / 'src/a.c').read_bytes())
        f.analysis['files'].append({'path': 'src/copy.c', 'status': 'nonsemantic', 'category': 'duplicate',
            'duplicate_of': 'src/a.c', 'modules': [], 'evidence': 'Identical copied build input; original fully read.'})
        self.assertEqual(f.analyze_again().returncode, 0)
        (f.repo / 'src/copy.c').write_text('int other(void) { return 9; }\n')
        self.assertNotEqual(f.analyze_again().returncode, 0)

    def test_missing_capability_blocks_plan(self):
        self.f.module['capabilities'] = []
        self.f.persist()
        r = self.f.cli('plan')
        self.assertIn('independent capability', r.stdout)

    def test_capability_cannot_be_a_link_to_unplanned_question(self):
        self.f.module['capabilities'][0]['question'] = 'Unplanned placeholder'
        self.f.persist()
        self.assertNotEqual(self.f.cli('plan').returncode, 0)

    def test_capabilities_cannot_share_one_generic_section(self):
        f = self.f
        extra = dict(f.analysis['modules'][0]['capabilities'][0], id='other')
        f.analysis['modules'][0]['capabilities'].append(extra)
        self.assertEqual(f.analyze_again().returncode, 0)
        f.module['capabilities'].append(dict(f.module['capabilities'][0], id='other'))
        f.persist()
        self.assertIn('distinct explanation sections', f.cli('plan').stdout)

    def test_repeated_answer_conclusions_are_rejected(self):
        f = self.f
        f.page['questions'].append('Are there side effects?')
        f.review['answers'].append(dict(f.review['answers'][0], question='Are there side effects?'))
        f.persist(); self.assertEqual(f.cli('plan').returncode, 0)
        self.assertIn('same review conclusion', f.checkpoint().stdout)

    def test_quote_from_wrong_source_range_rejected(self):
        self.f.review['answers'][0]['source_anchors'] = [dict(self.f.anchor, quote='not in source')]
        self.assertIn('does not occur', self.f.checkpoint().stdout)

    def test_body_quote_must_be_in_actual_section(self):
        self.f.review['answers'][0]['body_quote'] = 'No source code supports this.'
        self.assertIn('body_quote', self.f.checkpoint().stdout)

    def test_stale_displayed_source_line_label_rejected(self):
        path = self.f.wiki / 'content/getter/a.md'
        path.write_text(self.f.body.replace('[src]', '[a.c L231-L243]'))
        self.assertIn('label range differs', self.f.cli('check').stdout)

    def test_each_diagram_needs_its_own_semantic_review(self):
        self.f.review['diagram_reviews'].pop()
        self.assertIn('each required module', self.f.checkpoint().stdout)

    def test_sequence_review_requires_failure_exit_analysis(self):
        del self.f.review['diagram_reviews'][1]['failure_and_exit']
        self.assertIn('failure_and_exit', self.f.checkpoint().stdout)

    def test_manual_rendered_flag_does_not_replace_actual_artifact(self):
        (self.f.wiki / '_meta/render.json').write_text('{"rendered":true}')
        self.assertNotEqual(self.f.checkpoint().returncode, 0)

    def test_missing_renderer_remains_unverified(self):
        (self.f.wiki / '_meta/render.json').unlink()
        r = self.f.cli('render', '--renderer', '/missing/mmdc')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('unverified', (self.f.wiki / '_meta/render.json').read_text())
        self.assertNotEqual(self.f.checkpoint().returncode, 0)

    def test_changed_diagram_needs_new_render(self):
        p = self.f.wiki / 'content/getter/a.md'
        p.write_text(self.f.body.replace('flowchart LR', 'flowchart TB'))
        self.assertIn('not rendered/current', self.f.checkpoint().stdout)

    def test_deleted_svg_invalidates_render_receipt(self):
        record = g.load(self.f.wiki / '_meta/render.json')['content/getter/a.md'][0]
        (self.f.wiki / record['svg']).unlink()
        self.assertNotEqual(self.f.checkpoint().returncode, 0)

    def test_auxiliary_navigation_diagram_cannot_escape_finish(self):
        self.f.complete()
        (self.f.wiki / 'README.md').write_text('# Navigation\n```mermaid\nflowchart LR\n A --> B\n```\n')
        r = self.f.cli('finish')
        self.assertIn('README.md block 0', r.stdout)
        self.assertFalse(json.loads(r.stdout)['ready_for_delivery'])

    def test_clearing_submitted_findings_is_not_a_fix(self):
        f = self.f
        f.review['open_findings'] = ['Runtime binding is invented.']
        self.assertNotEqual(f.checkpoint().returncode, 0)
        f.review['open_findings'] = []
        self.assertIn('explicit resolutions', f.checkpoint().stdout)

    def test_history_keeps_old_stages_and_rejected_review(self):
        f = self.f
        before = g.history(f.wiki)
        self.assertEqual(f.analyze_again().returncode, 0)
        after = g.history(f.wiki)
        self.assertEqual(after[:len(before)], before)
        attempts = [e for e in after if e.get('command') == 'analyze' and e['event'] == 'attempt']
        self.assertTrue(attempts[-1]['previous_stages']['analysis.json'])
        self.assertEqual(f.cli('plan').returncode, 0)
        f.review['open_findings'] = ['An actual unresolved claim']
        f.checkpoint()
        self.assertIn('An actual unresolved claim', (f.wiki / '_meta/history.jsonl').read_text())

    def test_migration_requires_explicit_reason(self):
        r = self.f.cli('analyze', '--review-file', str(self.f.analysis_file), '--reuse-existing')
        self.assertIn('requires --reason', r.stdout)

    def test_manual_stage_seal_edit_has_no_history_proof(self):
        p = self.f.wiki / '_meta/workflow.json'
        seal = g.load(p); seal['analysis_mode'] = 'invented'; g.save(p, seal)
        self.assertIn('matching successful history', self.f.checkpoint().stdout)

    def test_damaged_history_is_rejected(self):
        p = self.f.wiki / '_meta/history.jsonl'
        lines = p.read_text().splitlines()
        lines.pop(0); p.write_text('\n'.join(lines) + '\n')
        self.assertNotEqual(self.f.checkpoint().returncode, 0)

    def test_v6_schema_cannot_bypass_delivery_contract(self):
        self.f.complete()
        self.f.plan['schema_version'] = 6; self.f.persist()
        r = self.f.cli('finish')
        self.assertFalse(json.loads(r.stdout)['ready_for_delivery'])
        self.assertIn('v7 delivery', r.stdout)

    def test_scope_review_requires_capability_reconciliation(self):
        self.assertEqual(self.f.checkpoint().returncode, 0)
        self.f.scope['capability_checks'] = []
        self.assertNotEqual(self.f.accept_scope().returncode, 0)


if __name__ == '__main__':
    unittest.main()
