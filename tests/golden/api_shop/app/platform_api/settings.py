"""API platform settings (generated from the spec: change them in the builder). Plain data, no secret."""

from typing import Any

# Roles that issue and revoke keys and install apps. Nobody else gets in (default deny).
ROLES: tuple[str, ...] = ('admin', 'integrator')

# public entity -> where its model lives, its URL path, the exact fields the public API returns (plus id), and whether
# a sandbox key may read it
ENTITIES: dict[str, dict[str, Any]] = {'Product': {'class': 'Product',
             'fields': ('title', 'price_cents'),
             'module': 'app.models.products',
             'plural_path': 'products',
             'sandbox': True,
             'table': 'products'},
 'Review': {'class': 'Review',
            'fields': ('stars', 'body'),
            'module': 'app.models.reviews',
            'plural_path': 'reviews',
            'sandbox': False,
            'table': 'reviews'}}

# "<count>/<n><unit>" per key and window; sandbox keys use the sandbox limit, prod keys and app tokens the other
RATE_LIMIT: str = '60/minute'
SANDBOX_RATE_LIMIT: str = '5/minute'
KEY_TTL_DAYS: int = 90

# app name -> {"title", "scopes": entity names it may ask for, "events": signed event types it may receive}
APPS: dict[str, dict[str, Any]] = {'reviews-widget': {'events': ('review-created',),
                    'scopes': ('Product', 'Review'),
                    'title': 'Reviews widget'},
 'storefront': {'events': ('product-updated',),
                'scopes': ('Product',),
                'title': 'Storefront sync'}}

# multi-tenant project: keys, installs, audit rows and public reads belong to the caller's tenant
TENANT_SCOPED: bool = True
