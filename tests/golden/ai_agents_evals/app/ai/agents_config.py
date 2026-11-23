"""Agent runtime settings (generated from the spec: change them in the builder). Plain data, integers only."""

RUN_ROLES: tuple[str, ...] = ('admin', 'agent',)  # an empty tuple means any signed-in user
APPROVE_ROLES: tuple[str, ...] = ('admin',)  # approve / reject / acknowledge / hand off / record outcomes
READ_ROLES: tuple[str, ...] = ('admin',)
KNOWN_ROLES: tuple[str, ...] = ('admin', 'agent', 'customer',)  # the roles a proposal may be handed off to
ALLOW_SELF_APPROVAL = False  # may whoever started a run approve its proposals
EVALS = True  # packs.ai.evals is declared (the require_eval gate reads ai_eval_runs)

# the autonomy dial: allowed = min(agent autonomy, action max_autonomy, run mode)
RANK: dict[str, int] = {"suggest": 0, "draft": 1, "auto": 2}

# the action registry: the only things an agent can ever do
ACTIONS: dict[str, dict[str, object]] = {'add_note': {'description': 'Add an internal note',
              'entity': None,
              'fields': [],
              'kind': 'note',
              'max_autonomy': 'auto',
              'risk': 'low'},
 'escalate': {'description': 'Escalate to a manager',
              'entity': None,
              'fields': [],
              'kind': 'note',
              'max_autonomy': 'auto',
              'risk': 'high'},
 'note_draft': {'description': 'Add a note that needs approval',
                'entity': None,
                'fields': [],
                'kind': 'note',
                'max_autonomy': 'draft',
                'risk': 'medium'},
 'note_suggest': {'description': 'Suggest a note',
                  'entity': None,
                  'fields': [],
                  'kind': 'note',
                  'max_autonomy': 'suggest',
                  'risk': 'low'},
 'open_ticket': {'description': 'Open a ticket',
                 'entity': 'tickets',
                 'fields': ['title', 'priority'],
                 'kind': 'entity_create',
                 'max_autonomy': 'auto',
                 'risk': 'medium'}}

# agent -> gateway stage, allowed actions, autonomy ceiling, cap per run, optional eval suite that gates `auto`
AGENTS: dict[str, dict[str, object]] = {'autopilot': {'actions': ['add_note', 'escalate', 'note_draft', 'note_suggest', 'open_ticket'],
               'autonomy': 'auto',
               'max_actions_per_run': 3,
               'require_eval': None,
               'stage': 'answer'},
 'drafter': {'actions': ['add_note', 'escalate', 'note_draft', 'note_suggest', 'open_ticket'],
             'autonomy': 'draft',
             'max_actions_per_run': 5,
             'require_eval': None,
             'stage': 'answer'},
 'guarded': {'actions': ['add_note', 'open_ticket'],
             'autonomy': 'auto',
             'max_actions_per_run': 5,
             'require_eval': 'guarded_basic',
             'stage': 'answer'},
 'watcher': {'actions': ['add_note', 'note_draft', 'open_ticket'],
             'autonomy': 'suggest',
             'max_actions_per_run': 5,
             'require_eval': None,
             'stage': 'answer'}}

# table -> field -> rule, only for the entities an entity_create action writes (the allow-listed fields)
ENTITIES: dict[str, dict[str, dict[str, object]]] = {'tickets': {'priority': {'enum': None,
                          'max': 5.0,
                          'max_length': None,
                          'min': 1.0,
                          'required': False,
                          'type': 'integer'},
             'title': {'enum': None,
                       'max': None,
                       'max_length': 120,
                       'min': None,
                       'required': True,
                       'type': 'string'}}}

# table -> the roles that may create a row of that entity through its own CRUD permissions (empty tuple: nobody).
# An agent action writes a row only for an actor who holds one of them (the entity's own create check is not bypassed).
CREATE_ROLES: dict[str, tuple[str, ...]] = {'tickets': ('admin', 'agent')}

# table -> the entity's own repository (module, class), its entity name, and whether the entity is decided by abac / pbac
# policies (needs a request context: an agent action on it is refused, `policy_unsupported`) or has field write rules.
# An agent action creates a row through THAT repository's create lifecycle (hooks, state machine, events, numbering).
ENTITY_RUNTIME: dict[str, dict[str, object]] = {'tickets': {'entity': 'Ticket',
             'guarded': False,
             'module': 'app.crud.tickets',
             'numbered': False,
             'policy': False,
             'repository': 'TicketRepository'}}

MAX_ARGS_BYTES = 4096
MAX_CONTEXT_BYTES = 8192
MAX_NOTE_CHARS = 2000
