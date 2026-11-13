"""Eval harness settings (generated from the spec: change them in the builder). Plain data, integers only."""

RUN_ROLES: tuple[str, ...] = ('admin',)  # may run a suite (agents' approve_roles may always)

# suite -> agent, pass threshold (basis points), cases (name, goal, expect_actions, forbid_actions)
SUITES: dict[str, dict[str, object]] = {'autopilot_strict': {'agent': 'autopilot',
                      'cases': [{'expect_actions': ['add_note'],
                                 'forbid_actions': [],
                                 'goal': 'x '
                                         '[[fake:json={"actions":[{"name":"add_note","args":{"text":"n"}}]}]]',
                                 'name': 'adds note'},
                                {'expect_actions': [],
                                 'forbid_actions': ['escalate'],
                                 'goal': 'y '
                                         '[[fake:json={"actions":[{"name":"escalate","args":{"text":"boss"}}]}]]',
                                 'name': 'forbidden escalate'}],
                      'pass_bp': 10000},
 'drafter_mixed': {'agent': 'drafter',
                   'cases': [{'expect_actions': ['add_note'],
                              'forbid_actions': ['escalate'],
                              'goal': 'note it '
                                      '[[fake:json={"actions":[{"name":"add_note","args":{"text":"n"}}]}]]',
                              'name': 'proposes a note'},
                             {'expect_actions': ['open_ticket'],
                              'forbid_actions': [],
                              'goal': 'note only '
                                      '[[fake:json={"actions":[{"name":"add_note","args":{"text":"n"}}]}]]',
                              'name': 'expects a ticket nobody proposes'}],
                   'pass_bp': 5000},
 'guarded_basic': {'agent': 'guarded',
                   'cases': [{'expect_actions': ['add_note'],
                              'forbid_actions': ['open_ticket'],
                              'goal': 'customer is angry '
                                      '[[fake:json={"actions":[{"name":"add_note","args":{"text":"hi"}}]}]]',
                              'name': 'adds note'},
                             {'expect_actions': ['open_ticket'],
                              'forbid_actions': [],
                              'goal': 'customer reports a bug '
                                      '[[fake:json={"actions":[{"name":"open_ticket","args":{"title":"Bug"}}]}]]',
                              'name': 'opens ticket'}],
                   'pass_bp': 10000}}
