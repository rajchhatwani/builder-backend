"""The seed plan: which rows each profile creates. Data only; nothing here is ever run as code.

Edit it in the builder (the same profile always yields the same rows: `seed` is the only source
of randomness and `as_of` the only clock)."""

PROFILES = {'demo': {'as_of': '2026-10-01',
          'entities': [{'count': 3,
                        'entity': 'Order',
                        'fields': [{'field': 'customer',
                                    'generator': {'max_words': 2,
                                                  'min_words': 2,
                                                  'type': 'words'}},
                                   {'field': 'total',
                                    'generator': {'max': '5000.00',
                                                  'min': '10.00',
                                                  'places': 2,
                                                  'type': 'decimal_range'}},
                                   {'field': 'stage',
                                    'generator': {'type': 'state',
                                                  'weights': {'auto_approved': 1,
                                                              'needs_review': 1,
                                                              'open': 1}}}]}],
          'name': 'demo',
          'seed': 7,
          'tenants': 2}}
