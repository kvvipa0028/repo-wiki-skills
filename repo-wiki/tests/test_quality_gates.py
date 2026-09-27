import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/wiki_check.py'
spec = importlib.util.spec_from_file_location('quality_check', SCRIPT)
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)


class QualityGates(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        self.wiki = self.repo / 'wiki'
        (self.repo / 'src').mkdir()
        (self.repo / 'src/a.c').write_text('int get(void) { return 3; }\n')
        (self.repo / 'README.md').write_text('The public API is get().\n')
        (self.wiki / 'content/getter').mkdir(parents=True)
        self.body = ('# Getter\n## Result\nget() returns 3 without state changes.\n[src](../../../src/a.c#L1)\n'
                     '## Calls\n```mermaid\nflowchart LR\n    A[get - no internal calls]\n```\n'
                     '## Sequence\n```mermaid\nsequenceDiagram\n    participant API as get\n'
                     '    Note over API: returns constant 3 without internal calls\n```\n')
        self.page = {'path': 'content/getter/a.md', 'title': 'Getter', 'kind': 'reference',
                     'objective': 'Use the return value of get()', 'questions': ['What is returned?'],
                     'sections': ['## Result'], 'sources': ['src/a.c'], 'watch': ['src/a.c'],
                     'parent': None, 'depends_on': [], 'next': ''}
        self.plan = {'schema_version': 7, 'scope': {'request': 'Explain all src capabilities',
                     'roots': ['.'], 'user_exclusions': []}, 'coverage': [
                     {'area': 'Getter', 'paths': ['src'], 'pages': ['content/getter/a.md'], 'status': 'complete', 'gaps': []}],
                     'pages': [self.page]}
        self.module = {'id': 'getter', 'directory': 'content/getter', 'name': 'Getter', 'paths': ['src', 'README.md'],
                       'pages': ['content/getter/a.md'], 'diagrams': {
                           'call': {'page': 'content/getter/a.md', 'section': '## Calls'},
                           'sequence': {'page': 'content/getter/a.md', 'section': '## Sequence'}}}
        self.module['capabilities'] = [{'id': 'get-result', 'page': 'content/getter/a.md', 'section': '## Result',
            'question': 'What is returned?', 'diagram_coverage': {'call': 'get is the only API; no nested calls.',
            'sequence': 'API returns constant 3 without state.'}}]
        self.plan['modules'] = [self.module]
        self.review = {'answers': [{'question': 'What is returned?', 'section': '## Result',
                         'conclusion': 'The only return statement yields 3; the page explains no state changes.',
                         'sources': ['src/a.c']}],
                       'checks': {name: {'status': 'pass', 'evidence': 'Checked the one return statement and the matching public result description.'}
                                  for name in w.REVIEW_CHECKS}, 'open_findings': []}
        self.review['checks']['diagrams'] = {'status': 'pass', 'evidence': 'Call graph shows no internal calls; sequence note describes the constant-return boundary, not an invented caller.'}
        self.anchor = {'path': 'src/a.c', 'start': 1, 'end': 1, 'quote': 'return 3;'}
        self.review['answers'][0].update(body_quote='get() returns 3 without state changes.', source_anchors=[self.anchor])
        self.review['diagram_reviews'] = [
            {'module': 'getter', 'kind': 'call', 'section': '## Calls', 'status': 'pass',
             'entry_and_binding': 'Public get has no runtime registration.', 'edge_meaning': 'Single API node; no calls.',
             'non_edges': 'Do not connect initialization to execution.', 'source_anchors': [self.anchor]},
            {'module': 'getter', 'kind': 'sequence', 'section': '## Sequence', 'status': 'pass',
             'scenario': 'One invocation of get.', 'ordering_and_state': 'Returns 3 without changing state.',
             'failure_and_exit': 'No failure branch in this constant getter.', 'source_anchors': [self.anchor]}]
        self.scope = {'areas': [{'area': 'Getter', 'pages': ['content/getter/a.md'],
                       'assessment': 'src contains only the getter; its public result is explained.'}],
                      'discovery_sources': ['README.md', 'src/a.c'],
                      'cross_page_checks': 'Single page; verified the README API maps to its source and result section.',
                      'open_findings': []}
        self.scope['capability_checks'] = [{'id': 'get-result', 'status': 'pass',
            'assessment': 'README and src declare just one API; its return and call boundary are explained.',
            'source_anchors': [self.anchor]}]
        self.review_file = self.wiki / '_meta/reviews/a.json'
        self.scope_file = self.wiki / '_meta/reviews/scope.json'
        self.persist()
        (self.wiki / '_meta/overview.md').write_text('Getter is a standalone constant-return API; README declares it.\n')
        (self.wiki / '_meta/planning.md').write_text('Complete catalogue: Getter API with call and sequence diagrams.\n')
        self.analysis = {'schema_version': 7, 'scope': self.plan['scope'], 'modules': [dict(
            id='getter', name='Getter', paths=['src', 'README.md'], summary='The whole source is a constant getter, without internal calls.')],
            'files': [{'path': rel, 'status': 'read', 'method': 'full_text', 'modules': ['getter'], 'evidence': 'Read the complete single-line declaration or implementation.'}
                      for rel in ['README.md', 'src/a.c']], 'open_findings': []}
        self.analysis['modules'][0]['capabilities'] = [{'id': 'get-result', 'name': 'Constant getter',
            'description': 'Return the fixed integer without side effects.', 'source_anchors': [self.anchor]}]
        for rel in ['README.md', 'src/a.c']:
            self.assertEqual(self.cli('read', '--source', rel).returncode, 0)
        # Test double verifies renderer protocol/caching; real mmdc is tested separately.
        self.renderer = self.wiki / '_meta/mock-mmdc'
        self.renderer.write_text('#!' + sys.executable + '\nimport sys\nfrom pathlib import Path\n'
            'if \"--version\" in sys.argv: print(\"TEST-DOUBLE\")\n'
            'else: Path(sys.argv[sys.argv.index(\"-o\")+1]).write_text(\"<svg>fixture</svg>\")\n')
        self.renderer.chmod(0o755)
        self.analysis_file = self.wiki / '_meta/analysis-review.json'
        w.save(self.analysis_file, self.analysis)
        r = self.cli('analyze', '--review-file', str(self.analysis_file))
        self.assertEqual(r.returncode, 0, r.stdout)
        r = self.cli('plan'); self.assertEqual(r.returncode, 0, r.stdout)
        (self.wiki / 'content/getter/a.md').write_text(self.body)
        r = self.cli('render', '--renderer', str(self.renderer))
        self.assertEqual(r.returncode, 0, r.stdout)

    def persist(self):
        w.save(self.wiki / '_meta/plan.json', self.plan)
        w.save(self.review_file, self.review)
        w.save(self.scope_file, self.scope)

    def cli(self, command, *args):
        return subprocess.run([sys.executable, str(SCRIPT), command, '--repo', str(self.repo),
                               '--wiki', str(self.wiki), *args], capture_output=True, text=True)

    def checkpoint(self, *args):
        self.persist()
        return self.cli('checkpoint', '--page', 'content/getter/a.md', '--review-file', str(self.review_file), *args)

    def accept_scope(self):
        w.save(self.scope_file, self.scope)
        return self.cli('scope-review', '--review-file', str(self.scope_file))

    def complete(self):
        r = self.checkpoint(); self.assertEqual(r.returncode, 0, r.stdout)
        r = self.accept_scope(); self.assertEqual(r.returncode, 0, r.stdout)
        r = self.cli('finish'); self.assertEqual(r.returncode, 0, r.stdout)
        self.assertTrue(json.loads(r.stdout)['ready_for_delivery'])

    def test_reviewed_current_scope_can_finish(self):
        self.complete()

    def test_mechanical_pass_cannot_checkpoint_without_review(self):
        self.assertEqual(self.cli('check').returncode, 0)
        self.assertEqual(self.cli('checkpoint', '--page', 'content/getter/a.md').returncode, 2)
        self.assertFalse((self.wiki / '_meta/state.json').exists())

    def test_missing_or_duplicate_question_rejected(self):
        for answers in ([], self.review['answers'] * 2):
            self.review['answers'] = answers
            self.assertEqual(self.checkpoint().returncode, 1)

    def test_unknown_question_rejected(self):
        self.review['answers'][0]['question'] = 'Invented question'
        self.assertEqual(self.checkpoint().returncode, 1)

    def test_missing_answer_location_rejected(self):
        self.review['answers'][0]['section'] = '## Missing'
        self.assertEqual(self.checkpoint().returncode, 1)

    def test_heading_inside_code_is_not_an_answer_location(self):
        p = self.wiki / 'content/getter/a.md'
        p.write_text(p.read_text() + '\n```md\n## Fake\n```\n')
        self.review['answers'][0]['section'] = '## Fake'
        self.assertEqual(self.checkpoint().returncode, 1)

    def test_uncaptured_source_not_evidence(self):
        self.review['answers'][0]['sources'] = ['README.md']
        self.assertEqual(self.checkpoint().returncode, 1)

    def test_open_content_findings_block_checkpoint(self):
        self.review['open_findings'] = ['The boundary example is wrong.']
        self.assertEqual(self.checkpoint().returncode, 1)

    def test_missing_or_unsupported_check_blocks_checkpoint(self):
        del self.review['checks']['explanation']
        self.assertEqual(self.checkpoint().returncode, 1)
        self.review['checks']['explanation'] = {'status': 'not_applicable', 'evidence': 'Skipped explanation.'}
        self.assertEqual(self.checkpoint().returncode, 1)

    def test_empty_check_reason_not_accepted(self):
        self.review['checks']['diagrams']['evidence'] = ' '
        self.assertEqual(self.checkpoint().returncode, 1)

    def test_missing_scope_review_blocks_finish(self):
        self.assertEqual(self.checkpoint().returncode, 0)
        r = self.cli('finish')
        self.assertEqual(r.returncode, 1)
        self.assertFalse(json.loads(r.stdout)['ready_for_delivery'])

    def test_scope_cannot_bypass_unreviewed_pages(self):
        self.assertEqual(self.accept_scope().returncode, 1)
        self.assertFalse((self.wiki / '_meta/scope-review.json').exists())

    def test_scope_requires_all_areas_and_pages(self):
        self.assertEqual(self.checkpoint().returncode, 0)
        self.scope['areas'] = []
        self.assertEqual(self.accept_scope().returncode, 2)

    def test_scope_rejects_open_findings(self):
        self.assertEqual(self.checkpoint().returncode, 0)
        self.scope['open_findings'] = ['Undocumented public interface']
        self.assertEqual(self.accept_scope().returncode, 2)

    def test_discovery_cannot_only_cite_generated_wiki(self):
        self.assertEqual(self.checkpoint().returncode, 0)
        self.scope['discovery_sources'] = ['wiki/content/getter/a.md']
        self.assertEqual(self.accept_scope().returncode, 2)

    def test_new_module_outside_page_watch_invalidates_scope(self):
        self.complete()
        (self.repo / 'src/new_module.c').write_text('int new_api(void);\n')
        r = self.cli('finish')
        self.assertEqual(r.returncode, 1)
        self.assertIn('scope review stale', r.stdout)
        self.assertEqual(json.loads(r.stdout)['pages_needing_review'], {})

    def test_discovery_content_change_invalidates_scope(self):
        self.complete()
        (self.repo / 'README.md').write_text('New feature needs documentation.\n')
        self.assertIn('scope review stale', self.cli('finish').stdout)

    def test_body_change_requires_re_review_and_new_scope_acceptance(self):
        self.complete()
        p = self.wiki / 'content/getter/a.md'; p.write_text(p.read_text() + '\nManual note.\n')
        self.assertEqual(self.cli('finish').returncode, 1)
        self.assertEqual(self.checkpoint().returncode, 2)
        self.assertEqual(self.checkpoint('--accept-edits').returncode, 0)
        self.assertEqual(self.cli('finish').returncode, 1)
        self.assertEqual(self.accept_scope().returncode, 0)
        self.assertEqual(self.cli('finish').returncode, 0)

    def test_changed_question_requires_new_answer(self):
        self.complete()
        self.page['questions'].append('What changes?')
        self.assertEqual(self.checkpoint().returncode, 1)

    def test_invalid_objective_is_caught_at_plan_stage(self):
        del self.page['objective']; self.persist()
        self.assertEqual(self.cli('plan').returncode, 1)

    def test_failed_review_keeps_prior_evidence_but_blocks_delivery(self):
        self.complete()
        path = self.wiki / '_meta/state.json'; before = w.read_json(path)['content/getter/a.md']
        self.review['open_findings'] = ['Need to recheck return value.']
        self.assertEqual(self.checkpoint().returncode, 1)
        after = w.read_json(path)['content/getter/a.md']
        self.assertEqual(after['body'], before['body'])
        self.assertEqual(after['review'], before['review'])
        self.assertTrue(after['review_pending'])
        self.assertEqual(self.cli('finish').returncode, 1)
        self.review['open_findings'] = []
        self.review['resolutions'] = [{'finding': 'Need to recheck return value.',
            'change': 'Rechecked the single return expression against the example.', 'source_anchors': [self.anchor]}]
        self.assertEqual(self.checkpoint().returncode, 0)
        self.assertNotIn('review_pending', w.read_json(path)['content/getter/a.md'])

    def test_failed_scope_re_review_invalidates_earlier_acceptance(self):
        self.complete()
        self.scope['open_findings'] = ['A public capability was missed.']
        self.assertEqual(self.accept_scope().returncode, 2)
        self.assertEqual(self.cli('finish').returncode, 1)
        self.scope['open_findings'] = []
        self.scope['resolutions'] = [{'finding': 'A public capability was missed.',
            'change': 'Reconciled all public entrypoints with the sole get-result capability.', 'source_anchors': [self.anchor]}]
        self.assertEqual(self.accept_scope().returncode, 0)
        self.assertEqual(self.cli('finish').returncode, 0)

    def analyze_again(self):
        for rel in ['README.md', 'src/a.c']:
            self.cli('read', '--source', rel)
        w.save(self.analysis_file, self.analysis)
        return self.cli('analyze', '--review-file', str(self.analysis_file), '--reuse-existing', '--reason', 'Refresh the analysis of existing fixture pages')

    def test_missing_analysis_prevents_checkpoint(self):
        (self.wiki / '_meta/analysis.json').unlink()
        self.assertEqual(self.checkpoint().returncode, 1)

    def test_missing_catalogue_prevents_checkpoint(self):
        (self.wiki / '_meta/workflow.json').unlink()
        self.assertEqual(self.checkpoint().returncode, 1)

    def test_inventory_does_not_claim_reading_or_capture_its_own_wiki(self):
        result = json.loads(self.cli('inventory').stdout)
        self.assertEqual(set(result['files']), {'src/a.c', 'README.md'})
        self.assertEqual(result['reading_status'], 'inventory_only_not_read')

    def test_omitted_input_rejects_analysis_and_invalidates_prior_acceptance(self):
        self.complete()
        self.analysis['files'].pop()
        self.assertEqual(self.analyze_again().returncode, 2)
        self.assertTrue(w.read_json(self.wiki / '_meta/analysis.json')['review_pending'])
        self.assertEqual(self.cli('finish').returncode, 1)

    def test_duplicate_read_record_does_not_cover_an_omitted_file(self):
        self.analysis['files'] = [self.analysis['files'][0]] * 2
        self.assertEqual(self.analyze_again().returncode, 2)

    def test_unread_and_blocked_are_not_complete_analysis(self):
        for state in ('unread', 'blocked'):
            self.analysis['files'][0]['status'] = state
            self.assertEqual(self.analyze_again().returncode, 2)

    def test_user_exclusion_cannot_be_invented_in_reading_ledger(self):
        self.analysis['files'][0].update(status='user_excluded', modules=[])
        self.assertEqual(self.analyze_again().returncode, 2)

    def test_module_cannot_be_supported_only_by_nonsemantic_files(self):
        for f in self.analysis['files']:
            f.update(status='nonsemantic', modules=[])
        self.assertEqual(self.analyze_again().returncode, 2)

    def test_analysis_needs_whole_project_explanation(self):
        (self.wiki / '_meta/overview.md').write_text(' ')
        self.assertEqual(self.analyze_again().returncode, 2)

    def test_source_change_requires_analysis_refresh(self):
        (self.repo / 'README.md').write_text('A changed project description.\n')
        self.assertEqual(self.checkpoint().returncode, 1)
        self.assertIn('current full-text read receipts', self.cli('check').stdout)
        self.assertEqual(self.analyze_again().returncode, 0)
        self.assertEqual(self.checkpoint().returncode, 1)  # catalogue must be confirmed again
        self.assertEqual(self.cli('plan').returncode, 0)
        self.assertEqual(self.checkpoint().returncode, 0)

    def test_new_body_before_analysis_is_not_accepted_as_new_generation(self):
        r = self.cli('analyze', '--review-file', str(self.analysis_file))
        self.assertEqual(r.returncode, 2)
        self.assertIn('body already exists', r.stdout)

    def test_body_written_between_analysis_and_first_catalogue_is_rejected(self):
        (self.wiki / '_meta/workflow.json').unlink()
        r = self.cli('plan')
        self.assertEqual(r.returncode, 1)
        self.assertIn('before the first complete catalogue', r.stdout)

    def test_explicit_migration_preserves_old_body_baseline(self):
        before = (self.wiki / 'content/getter/a.md').read_bytes()
        self.assertEqual(self.analyze_again().returncode, 0)
        record = w.read_json(self.wiki / '_meta/analysis.json')
        self.assertEqual(record['mode'], 'reuse_existing')
        self.assertIn('content/getter/a.md', record['existing_pages'])
        self.assertEqual(self.cli('plan').returncode, 0)
        self.assertEqual((self.wiki / 'content/getter/a.md').read_bytes(), before)

    def test_incomplete_or_renamed_module_catalogue_rejected(self):
        self.plan['modules'] = []; self.persist()
        self.assertEqual(self.cli('plan').returncode, 1)
        self.plan['modules'] = [self.module]
        self.module['name'] = 'A made-up grouping'; self.persist()
        self.assertEqual(self.cli('plan').returncode, 1)

    def test_catalogue_change_requires_confirmation_before_more_pages(self):
        self.page['objective'] = 'A revised reading goal'
        self.assertEqual(self.checkpoint().returncode, 1)
        self.assertEqual(self.cli('plan').returncode, 0)
        self.assertEqual(self.checkpoint().returncode, 0)

    def test_progress_updates_do_not_invalidate_catalogue(self):
        self.plan['coverage'][0].update(status='partial', gaps=['Review is still in progress'])
        self.page['next'] = 'Review the example'; self.persist()
        self.assertEqual(w.workflow_issues(self.repo, self.wiki, self.plan), [])

    def test_module_requires_both_diagram_locations(self):
        del self.module['diagrams']['sequence']; self.persist()
        self.assertEqual(self.cli('plan').returncode, 1)
        self.assertEqual(self.cli('check').returncode, 1)

    def test_two_modules_cannot_share_the_same_diagrams(self):
        second = json.loads(json.dumps(self.module)); second['id'] = 'other'
        self.plan['modules'].append(second)
        self.assertTrue(any('own location' in s for s in w.module_plan_issues(self.plan)))

    def test_call_and_sequence_cannot_share_one_section(self):
        self.module['diagrams']['sequence']['section'] = '## Calls'
        self.assertTrue(w.module_plan_issues(self.plan))

    def test_flowchart_cannot_substitute_for_sequence_diagram(self):
        p = self.wiki / 'content/getter/a.md'
        p.write_text(self.body.replace('sequenceDiagram', 'flowchart LR'))
        r = self.cli('check')
        self.assertEqual(r.returncode, 1)
        self.assertIn('sequence Mermaid', r.stdout)

    def test_missing_call_graph_blocks_checkpoint_and_finish(self):
        self.complete()
        p = self.wiki / 'content/getter/a.md'
        p.write_text(self.body.replace('flowchart LR', 'stateDiagram-v2'))
        self.assertEqual(self.checkpoint('--accept-edits').returncode, 1)
        r = self.cli('finish')
        self.assertEqual(r.returncode, 1)
        self.assertTrue(json.loads(r.stdout)['diagram_issues'])

    def test_empty_or_comment_only_mermaid_is_rejected(self):
        p = self.wiki / 'content/getter/a.md'
        p.write_text(self.body.replace('    A[get - no internal calls]', '    %% no diagram content'))
        self.assertEqual(self.cli('check').returncode, 1)

    def test_participants_alone_are_not_a_sequence(self):
        p = self.wiki / 'content/getter/a.md'
        p.write_text(self.body.replace('    Note over API: returns constant 3 without internal calls\n', ''))
        self.assertEqual(self.cli('check').returncode, 1)

    def test_sequence_with_real_messages_and_no_note_is_accepted(self):
        p = self.wiki / 'content/getter/a.md'
        p.write_text(self.body.replace('    Note over API: returns constant 3 without internal calls',
                                       '    Caller->>API: get()\n    API-->>Caller: 3'))
        self.assertEqual(self.cli('render', '--renderer', str(self.renderer)).returncode, 0)
        self.assertEqual(self.cli('check').returncode, 0)

    def test_mermaid_inside_a_quoted_code_example_does_not_count(self):
        p = self.wiki / 'content/getter/a.md'
        p.write_text('# Getter\n[src](../../../src/a.c#L1)\n````markdown\n' + self.body + '\n````\n')
        self.assertEqual(self.cli('check').returncode, 1)

    def test_svg_link_does_not_replace_inline_module_mermaid(self):
        p = self.wiki / 'content/getter/a.md'
        (self.wiki / 'content/getter/graph.svg').write_text('<svg/>')
        p.write_text('# Getter\n[src](../../../src/a.c#L1)\n## Calls\n[graph](graph.svg)\n## Sequence\n[graph](graph.svg)\n')
        self.assertEqual(self.cli('check').returncode, 1)

    def test_required_module_diagrams_cannot_be_not_applicable(self):
        self.review['checks']['diagrams']['status'] = 'not_applicable'
        self.assertEqual(self.checkpoint().returncode, 1)

    def test_changing_diagram_location_invalidates_its_page_review(self):
        self.complete()
        self.module['diagrams']['call']['section'] = '## New calls'
        self.persist()
        self.assertEqual(self.cli('plan').returncode, 0)
        r = self.cli('status')
        self.assertIn('module_diagram_task_changed', r.stdout)

    def test_legacy_v5_cannot_finish_under_v6_contract(self):
        self.complete()
        self.plan['schema_version'] = 5; self.persist()
        r = self.cli('finish')
        self.assertEqual(r.returncode, 1)
        self.assertTrue(json.loads(r.stdout)['workflow_issues'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
