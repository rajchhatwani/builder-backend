"""Booking settings (generated from the spec: change them in the builder). Plain data, integers only."""

# who may read / book / manage; an empty tuple means any signed-in user
READ_ROLES: tuple[str, ...] = ('admin', 'staff', 'customer',)
BOOK_ROLES: tuple[str, ...] = ('admin', 'customer',)
MANAGE_ROLES: tuple[str, ...] = ('admin', 'staff',)
OWN_ONLY = True  # callers outside MANAGE_ROLES see only their own bookings
HOLD_TTL_SECONDS = 120
MAX_HORIZON_DAYS = 365
FREE_CANCEL_HOURS = 24
CANCEL_FEE_MINOR = 2500
FEE_CURRENCY = "EUR"
MAX_AVAILABILITY_DAYS = 31
MAX_ACTIVE_HOLDS = 20
MULTI_TENANT = True

# resource kinds: name -> mode and the defaults a new resource of the kind inherits
KINDS: dict[str, dict[str, object]] = {'loaner': {'capacity': 3,
            'max_minutes': 10080,
            'min_minutes': 60,
            'mode': 'pool',
            'schedule': {},
            'slot_minutes': 30,
            'timezone': 'UTC'},
 'practitioner': {'capacity': 1,
                  'max_minutes': 43200,
                  'min_minutes': 15,
                  'mode': 'slot',
                  'schedule': {'fri': [{'end': '12:00', 'start': '09:00'},
                                       {'end': '17:00', 'start': '13:00'}],
                               'mon': [{'end': '12:00', 'start': '09:00'},
                                       {'end': '17:00', 'start': '13:00'}],
                               'thu': [{'end': '12:00', 'start': '09:00'},
                                       {'end': '17:00', 'start': '13:00'}],
                               'tue': [{'end': '12:00', 'start': '09:00'},
                                       {'end': '17:00', 'start': '13:00'}],
                               'wed': [{'end': '12:00', 'start': '09:00'},
                                       {'end': '17:00', 'start': '13:00'}]},
                  'slot_minutes': 30,
                  'timezone': 'Europe/Berlin'},
 'room': {'capacity': 1,
          'max_minutes': 480,
          'min_minutes': 30,
          'mode': 'range',
          'schedule': {},
          'slot_minutes': 30,
          'timezone': 'Europe/Berlin'}}
