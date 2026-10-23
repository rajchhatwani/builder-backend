"""Fill the running commerce backend with realistic data, using only its public API.

    python examples/commerce/populate_commerce.py                       # API on :18100, mail catcher on :8025
    python examples/commerce/populate_commerce.py --api http://localhost:8000 --mail http://localhost:8025

What it does, the way a real deployment would see it:
  * two stores (tenants) sign up, verify their email through the mail catcher and log in
  * each store invites staff with different roles (manager, catalog, fulfillment, support, marketing)
    and a few customers; invitation emails are read from the mail catcher
  * each role does only its own job: catalog editors write products, support opens refunds,
    fulfillment ships, marketing runs discounts, and so on
  * orders are placed in every state: paid, pending, partially fulfilled, fully refunded, cancelled...

The backend has no business logic (no checkout, no stock decrement, no totals), so this script does the
arithmetic and the follow-up updates itself, as a storefront or an app would. It writes seeded.json and
USERS.md next to it. Standard library only. Running it twice is safe: a store that already has products is
left alone.
"""

import argparse
import json
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PASSWORD = "Demo-pass-2026!"
TOKEN_RE = re.compile(r"token=([A-Za-z0-9._~%-]+)")
CENT = Decimal("0.01")


def money(value: Decimal | float | str) -> str:
    return str(Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP))


def iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


class ApiError(Exception):
    def __init__(self, method: str, path: str, status: int, body: Any) -> None:
        super().__init__(f"{method} {path} -> {status}: {json.dumps(body)[:400]}")
        self.status, self.body = status, body


class Http:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.calls = 0

    def call(
        self, method: str, path: str, body: Any = None, token: str | None = None
    ) -> tuple[int, Any]:
        headers = {"Content-Type": "application/json"} if body is not None else {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(
            self.base + path,
            data=None if body is None else json.dumps(body).encode(),
            method=method,
            headers=headers,
        )
        self.calls += 1
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                raw = response.read()
                try:
                    return response.status, (json.loads(raw) if raw else None)
                except ValueError:  # e.g. the mail catcher answers "ok" as plain text
                    return response.status, raw.decode(errors="replace")
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                return exc.code, json.loads(raw) if raw else None
            except ValueError:
                return exc.code, raw.decode(errors="replace")

    def ok(
        self,
        method: str,
        path: str,
        body: Any = None,
        token: str | None = None,
        expect: int | None = None,
    ) -> Any:
        status, data = self.call(method, path, body, token)
        good = {expect} if expect else {200, 201, 204}
        if status not in good:
            raise ApiError(method, path, status, data)
        return data


class Mail:
    """Reads the emails the backend sends from a Mailpit-compatible mail catcher."""

    def __init__(self, base: str) -> None:
        self.http = Http(base)

    def clear(self) -> None:
        self.http.call("DELETE", "/api/v1/messages")

    def token_for(self, email: str, wait: float = 30) -> str:
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            _, found = self.http.call(
                "GET", "/api/v1/search?query=" + urllib.parse.quote(f"to:{email}")
            )
            for message in (found or {}).get("messages", []):
                _, full = self.http.call("GET", f"/api/v1/message/{message['ID']}")
                match = TOKEN_RE.search((full or {}).get("Text", "") + (full or {}).get("HTML", ""))
                if match:
                    return match.group(1)
            time.sleep(0.5)
        raise TimeoutError(f"no email with a token reached {email}")


@dataclass
class User:
    email: str
    name: str
    roles: list[str]
    token: str = ""
    refresh: str = ""
    id: str = ""


@dataclass
class Store:
    key: str
    name: str
    currency: str
    country: str
    order_base: int
    founder: User
    staff: dict[str, User] = field(default_factory=dict)
    customers: list[User] = field(default_factory=list)
    ids: dict[str, Any] = field(default_factory=dict)


class Seeder:
    def __init__(self, api: Http, mail: Mail) -> None:
        self.api, self.mail = api, mail
        self.rng = random.Random(7)
        self.now = datetime.now(UTC)

    # --- accounts ----------------------------------------------------------------------

    def login(self, user: User) -> None:
        tokens = self.api.ok("POST", "/auth/login", {"email": user.email, "password": PASSWORD})
        user.token, user.refresh = tokens["access_token"], tokens["refresh_token"]
        user.id = self.api.ok("GET", "/auth/me", token=user.token)["id"]

    def found_store(self, store: Store) -> None:
        status, body = self.api.call(
            "POST",
            "/auth/register",
            {
                "email": store.founder.email,
                "password": PASSWORD,
                "display_name": store.founder.name,
                "tenant_name": store.name,
                "locale": "en",
                "marketing_opt_in": False,
            },
        )
        if status == 201:
            token = self.mail.token_for(store.founder.email)
            self.api.ok("POST", "/auth/email/verify", {"token": token})
        elif status != 409:
            raise ApiError("POST", "/auth/register", status, body)
        self.login(store.founder)

    def invite(self, store: Store, user: User) -> None:
        status, body = self.api.call(
            "POST",
            "/auth/invitations",
            {"email": user.email, "roles": user.roles},
            store.founder.token,
        )
        if status == 201:
            token = self.mail.token_for(user.email)
            self.api.ok(
                "POST",
                "/auth/register",
                {
                    "email": user.email,
                    "password": PASSWORD,
                    "display_name": user.name,
                    "invite_token": token,
                    "locale": self.rng.choice(["en", "fr", "de", "hi", "ja"]),
                    "marketing_opt_in": self.rng.random() < 0.4,
                },
            )
        elif status not in (409, 422):
            raise ApiError("POST", "/auth/invitations", status, body)
        self.login(user)

    # --- helpers -----------------------------------------------------------------------

    def create(self, path: str, token: str, body: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = self.api.ok("POST", path, body, token, expect=201)
        return result

    def patch(self, path: str, token: str, body: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = self.api.ok("PATCH", path, body, token, expect=200)
        return result

    # --- one store ---------------------------------------------------------------------

    def populate(self, store: Store, catalog: list[dict[str, Any]]) -> None:
        a, s = store.founder, store.staff
        manager, catalog_user, fulfil, support, marketing = (
            s["manager"],
            s["catalog"],
            s["fulfillment"],
            s["support"],
            s["marketing"],
        )
        existing = self.api.ok("GET", "/products?limit=1", token=a.token)
        if existing["total"] > 0:
            print(f"  {store.name}: already has products, leaving its data alone")
            return

        # store settings, locations, shipping, tax -----------------------------------------
        self.create(
            "/stores",
            manager.token,
            {
                "name": store.name,
                "legal_name": f"{store.name} Ltd",
                "email": store.founder.email,
                "domain": f"{store.key}.example.com",
                "currency": store.currency,
                "timezone": "Europe/Berlin" if store.currency == "EUR" else "America/New_York",
                "weight_unit": "kg" if store.currency == "EUR" else "lb",
                "plan": "grow",
                "settings": {"checkout": {"guest": True, "phone_required": False}, "theme": "dawn"},
            },
        )
        loc_main = self.create(
            "/locations",
            manager.token,
            {
                "name": "Main warehouse",
                "address1": "1 Dock Road",
                "city": "Rotterdam",
                "country": "Netherlands",
                "country_code": "NL",
            },
        )
        loc_shop = self.create(
            "/locations",
            manager.token,
            {
                "name": "Flagship shop",
                "address1": "20 High Street",
                "city": "London",
                "country": "United Kingdom",
                "country_code": "GB",
                "fulfills_online_orders": False,
            },
        )
        self.create(
            "/locations",
            manager.token,
            {
                "name": "Closed popup",
                "active": False,
                "address1": "9 Old Lane",
                "city": "Paris",
                "country": "France",
                "country_code": "FR",
            },
        )
        zone_home = self.create(
            "/shipping_zones", manager.token, {"name": "Home market", "countries": [store.country]}
        )
        zone_world = self.create(
            "/shipping_zones", manager.token, {"name": "Rest of world", "countries": ["*"]}
        )
        rates = {
            "standard": self.create(
                "/shipping_rates",
                manager.token,
                {
                    "zone_id": zone_home["id"],
                    "name": "Standard",
                    "price": "4.90",
                    "min_weight": 0,
                    "max_weight": 20,
                },
            ),
            "free": self.create(
                "/shipping_rates",
                manager.token,
                {
                    "zone_id": zone_home["id"],
                    "name": "Free over 75",
                    "price": "0",
                    "min_order_subtotal": "75",
                },
            ),
            "express": self.create(
                "/shipping_rates",
                manager.token,
                {"zone_id": zone_home["id"], "name": "Express", "price": "14.90"},
            ),
            "international": self.create(
                "/shipping_rates",
                manager.token,
                {"zone_id": zone_world["id"], "name": "International", "price": "24.00"},
            ),
        }
        tax = Decimal("0.21") if store.currency == "EUR" else Decimal("0.08")
        self.create(
            "/tax_rates",
            manager.token,
            {
                "country_code": store.country,
                "name": "VAT" if store.currency == "EUR" else "Sales tax",
                "rate": str(tax),
                "includes_shipping": store.currency == "EUR",
            },
        )
        self.create(
            "/tax_rates",
            manager.token,
            {"country_code": "GB", "province_code": "", "name": "UK VAT", "rate": "0.20"},
        )
        store.ids.update(
            loc_main=loc_main["id"],
            loc_shop=loc_shop["id"],
            rates={k: v["id"] for k, v in rates.items()},
        )

        # catalog (the catalog editor does this) ------------------------------------------------
        tag_ids = {
            t: self.create("/tags", catalog_user.token, {"name": t})["id"]
            for t in ("new", "sale", "bestseller", "eco", "gift", "limited")
        }
        parent = self.create(
            "/collections",
            catalog_user.token,
            {
                "title": "Everything",
                "handle": "all",
                "published": True,
                "published_at": iso(self.now),
            },
        )
        collections = {
            "featured": self.create(
                "/collections",
                catalog_user.token,
                {
                    "title": "Featured",
                    "handle": "featured",
                    "published": True,
                    "published_at": iso(self.now),
                    "parent_id": parent["id"],
                    "seo_title": "Our favourites",
                },
            ),
            "sale": self.create(
                "/collections",
                catalog_user.token,
                {
                    "title": "On sale",
                    "handle": "sale",
                    "kind": "smart",
                    "published": True,
                    "parent_id": parent["id"],
                    "rules": {
                        "match": "all",
                        "conditions": [{"field": "tag", "op": "eq", "value": "sale"}],
                    },
                },
            ),
            "hidden": self.create(
                "/collections",
                catalog_user.token,
                {"title": "Staff picks (hidden)", "handle": "staff-picks", "published": False},
            ),
        }
        variants: list[dict[str, Any]] = []
        products: list[dict[str, Any]] = []
        for number, item in enumerate(catalog):
            handle = f"{store.key}-{item['handle']}"
            product = self.create(
                "/products",
                catalog_user.token,
                {
                    "title": item["title"],
                    "handle": handle,
                    "description_html": item.get(
                        "description", f"<p>{item['title']}: made to last.</p>"
                    ),
                    "vendor": item["vendor"],
                    "product_type": item["type"],
                    "status": item.get("status", "active"),
                    "tags_cache": item.get("tags", []),
                    "options": item.get("options", []),
                    "published_at": iso(self.now - timedelta(days=number))
                    if item.get("status", "active") == "active"
                    else None,
                    "seo_title": item["title"][:70],
                    "seo_description": f"Buy {item['title']} online"[:320],
                    "requires_shipping": item.get("shipping", True),
                },
            )
            products.append(product)
            for position, v in enumerate(item["variants"], start=1):
                variant = self.create(
                    "/variants",
                    catalog_user.token,
                    {
                        "product_id": product["id"],
                        "title": v["title"],
                        "sku": f"{store.key.upper()}-{item['handle'].upper()}-{position}",
                        "barcode": f"{store.order_base}{number:03d}{position:02d}",
                        "price": money(v["price"]),
                        "compare_at_price": money(v["compare"]) if v.get("compare") else None,
                        "cost": money(Decimal(str(v["price"])) * Decimal("0.4")),
                        "weight": v.get("weight", 0.5),
                        "position": position,
                        "option1": v.get("o1"),
                        "option2": v.get("o2"),
                        "inventory_policy": v.get("policy", "deny"),
                        "requires_shipping": item.get("shipping", True),
                    },
                )
                variants.append(
                    {**variant, "product_title": item["title"], "stock": v.get("stock", 25)}
                )
                for loc, share in ((loc_main, 1.0), (loc_shop, 0.2)):
                    stock = int(v.get("stock", 25) * share)
                    self.create(
                        "/inventory_levels",
                        catalog_user.token,
                        {
                            "variant_id": variant["id"],
                            "location_id": loc["id"],
                            "available": stock,
                            "on_hand": stock,
                            "incoming": 10 if stock == 0 else 0,
                        },
                    )
            for n in range(1, 3 if item.get("status", "active") == "active" else 1):
                self.create(
                    "/product_images",
                    catalog_user.token,
                    {
                        "product_id": product["id"],
                        "url": f"https://cdn.example.com/{handle}-{n}.jpg",
                        "alt": f"{item['title']} photo {n}",
                        "position": n,
                        "width": 1200,
                        "height": 1200,
                    },
                )
        # relations that are lists of ids on the parent
        for product, item in zip(products, catalog, strict=True):
            body: dict[str, Any] = {
                "tags": [tag_ids[t] for t in item.get("tags", []) if t in tag_ids]
            }
            self.patch(f"/products/{product['id']}", catalog_user.token, body)
        self.patch(
            f"/collections/{collections['featured']['id']}",
            catalog_user.token,
            {"products": [p["id"] for p in products[:4]]},
        )
        self.patch(
            f"/collections/{collections['sale']['id']}",
            catalog_user.token,
            {
                "products": [
                    p["id"]
                    for p, i in zip(products, catalog, strict=True)
                    if "sale" in i.get("tags", [])
                ]
            },
        )
        # a product that is deleted again: it is hidden from the API but kept in the database
        trash = self.create(
            "/products",
            catalog_user.token,
            {"title": "Discontinued mug", "handle": f"{store.key}-old-mug", "status": "archived"},
        )
        self.api.ok("DELETE", f"/products/{trash['id']}", token=manager.token, expect=204)
        store.ids.update(products=[p["id"] for p in products], variants=[v["id"] for v in variants])

        # content ----------------------------------------------------------------------------
        blog = self.create(
            "/blogs", catalog_user.token, {"title": "News", "handle": "news", "commentable": True}
        )
        for n, title in enumerate(
            ["Welcome to the new store", "How we pack your orders", "Spring lookbook (draft)"]
        ):
            self.create(
                "/articles",
                catalog_user.token,
                {
                    "blog_id": blog["id"],
                    "title": title,
                    "handle": f"{store.key}-post-{n}",
                    "author": store.founder.name,
                    "body_html": f"<p>{title}</p>",
                    "published": n < 2,
                    "published_at": iso(self.now - timedelta(days=n * 7)) if n < 2 else None,
                    "tags_cache": ["news"],
                },
            )
        self.create(
            "/pages",
            catalog_user.token,
            {
                "title": "About us",
                "handle": f"{store.key}-about",
                "body_html": "<p>We make things.</p>",
                "published": True,
            },
        )
        self.create(
            "/pages",
            catalog_user.token,
            {
                "title": "Returns policy",
                "handle": f"{store.key}-returns",
                "body_html": "<p>30 days.</p>",
                "published": True,
                "template_suffix": "policy",
            },
        )
        self.create(
            "/metafields",
            catalog_user.token,
            {
                "owner_type": "product",
                "owner_id": products[0]["id"],
                "namespace": "specs",
                "key": "material",
                "value_type": "string",
                "value": "organic cotton",
            },
        )
        self.create(
            "/metafields",
            catalog_user.token,
            {
                "owner_type": "product",
                "owner_id": products[0]["id"],
                "namespace": "specs",
                "key": "care",
                "value_type": "json",
                "value": {"wash": 30, "tumble_dry": False},
            },
        )
        self.create(
            "/webhooks",
            manager.token,
            {
                "topic": "orders.create",
                "url": f"https://hooks.example.com/{store.key}/orders",
                "secret": "whsec_demo_not_secret",
            },
        )
        self.create(
            "/webhooks",
            manager.token,
            {
                "topic": "refunds.create",
                "url": f"https://hooks.example.com/{store.key}/refunds",
                "active": False,
            },
        )

        # promotions (marketing) ----------------------------------------------------------------
        discounts = {
            "welcome10": self.create(
                "/discounts",
                marketing.token,
                {
                    "code": f"{store.key.upper()}WELCOME10",
                    "title": "10% welcome",
                    "kind": "percentage",
                    "value": "10",
                    "once_per_customer": True,
                    "starts_at": iso(self.now - timedelta(days=30)),
                    "active": True,
                },
            ),
            "five": self.create(
                "/discounts",
                marketing.token,
                {
                    "code": f"{store.key.upper()}FIVEOFF",
                    "title": "5 off 50",
                    "kind": "fixed_amount",
                    "value": "5",
                    "minimum_subtotal": "50",
                    "target": "order",
                },
            ),
            "ship": self.create(
                "/discounts",
                marketing.token,
                {
                    "code": f"{store.key.upper()}FREESHIP",
                    "title": "Free shipping",
                    "kind": "free_shipping",
                    "value": "0",
                    "target": "shipping",
                },
            ),
            "expired": self.create(
                "/discounts",
                marketing.token,
                {
                    "code": f"{store.key.upper()}SUMMER",
                    "title": "Summer (ended)",
                    "kind": "percentage",
                    "value": "25",
                    "ends_at": iso(self.now - timedelta(days=5)),
                    "active": True,
                },
            ),
            "future": self.create(
                "/discounts",
                marketing.token,
                {
                    "code": f"{store.key.upper()}BLACKFRIDAY",
                    "title": "Black Friday",
                    "kind": "percentage",
                    "value": "40",
                    "starts_at": iso(self.now + timedelta(days=60)),
                },
            ),
            "limited": self.create(
                "/discounts",
                marketing.token,
                {
                    "code": f"{store.key.upper()}FIRST100",
                    "title": "First 100",
                    "kind": "percentage",
                    "value": "15",
                    "usage_limit": 100,
                    "used_count": 100,
                },
            ),
        }
        self.create(
            "/gift_cards",
            marketing.token,
            {
                "code": f"{store.key.upper()}-GIFT-0001",
                "initial_value": "50",
                "balance": "50",
                "currency": store.currency,
                "expires_on": (self.now + timedelta(days=365)).date().isoformat(),
            },
        )
        self.create(
            "/gift_cards",
            marketing.token,
            {
                "code": f"{store.key.upper()}-GIFT-0002",
                "initial_value": "100",
                "balance": "37.50",
                "currency": store.currency,
                "note": "partly used",
            },
        )
        self.create(
            "/gift_cards",
            marketing.token,
            {
                "code": f"{store.key.upper()}-GIFT-0003",
                "initial_value": "25",
                "balance": "25",
                "currency": store.currency,
                "disabled": True,
                "note": "lost",
            },
        )

        # customers (support) -----------------------------------------------------------------------
        crm: list[dict[str, Any]] = []
        names = [
            ("Ada", "Lovelace"),
            ("Alan", "Turing"),
            ("Grace", "Hopper"),
            ("Linus", "Torvalds"),
            ("Margaret", "Hamilton"),
            ("Dennis", "Ritchie"),
            ("Barbara", "Liskov"),
            ("Ken", "Thompson"),
            ("Radia", "Perlman"),
            ("Édouard", "Müller-Øster"),
            ("李", "小龍"),
            ("Zoë", "O'Brien"),
        ]
        for n, (first, last) in enumerate(names):
            state = "disabled" if n == 8 else "invited" if n == 9 else "enabled"
            customer = self.create(
                "/customers",
                support.token,
                {
                    "email": f"{first.lower()}.{n}@{store.key}-mail.test".replace("é", "e").replace(
                        "李", "li"
                    ),
                    "first_name": first,
                    "last_name": last,
                    "phone": f"+1415555{n:04d}",
                    "state": state,
                    "accepts_marketing": n % 3 == 0,
                    "accepts_marketing_updated_at": iso(self.now - timedelta(days=n))
                    if n % 3 == 0
                    else None,
                    "tax_exempt": n == 4,
                    "tags_cache": ["vip"] if n < 2 else [],
                    "note": "Prefers evening delivery. " * (30 if n == 3 else 1),
                    "locale": "en",
                },
            )
            crm.append(customer)
            for k in range(2 if n % 4 == 0 else 1):
                self.create(
                    "/customer_addresses",
                    support.token,
                    {
                        "customer_id": customer["id"],
                        "name": f"{first} {last}",
                        "address1": f"{n + 1} Example Street",
                        "city": "Springfield",
                        "province": "IL",
                        "province_code": "IL",
                        "country": "United States",
                        "country_code": "US",
                        "postal_code": f"62{n:03d}",
                        "phone": f"+1415555{n:04d}",
                        "is_default": k == 0,
                    },
                )
        store.ids["customers"] = [c["id"] for c in crm]

        # storefront accounts: customers invited as users -------------------------------------------
        # (they also get a Customer record, matched by email; the backend does not link them)
        # carts (customers create them) -----------------------------------------------------------
        buyer = store.customers[0]
        for n in range(4):
            cart = self.create(
                "/carts",
                buyer.token,
                {
                    "token": f"{store.key}-cart-{n:03d}",
                    "email": buyer.email,
                    "currency": store.currency,
                    "status": ["open", "abandoned", "open", "converted"][n],
                    "customer_id": crm[0]["id"],
                    "expires_at": iso(self.now + timedelta(days=7 - n * 6)),
                },
            )
            for variant in self.rng.sample(variants, 2):
                self.create(
                    "/cart_lines",
                    buyer.token,
                    {
                        "cart_id": cart["id"],
                        "variant_id": variant["id"],
                        "quantity": self.rng.randint(1, 3),
                        "properties": {"gift_wrap": n == 0},
                    },
                )

        # orders in every state ---------------------------------------------------------------------
        scenarios = [
            ("paid_fulfilled", 0, "fulfilled"),
            ("paid_partially_fulfilled", 1, "partial"),
            ("paid_unfulfilled", 2, "none"),
            ("pending_payment", 3, "none"),
            ("cancelled_fraud", 4, "none"),
            ("fully_refunded", 5, "fulfilled"),
            ("partially_refunded", 6, "fulfilled"),
            ("with_discount", 7, "none"),
            ("international_express", 0, "none"),
            ("voided", 1, "none"),
            ("big_basket", 2, "partial"),
        ]
        summary = []
        for offset, (kind, customer_index, fulfil_mode) in enumerate(scenarios):
            order_id = self.place_order(
                store,
                kind,
                offset,
                crm[customer_index],
                variants,
                rates,
                tax,
                discounts,
                loc_main,
                support,
                fulfil,
                manager,
                marketing,
            )
            summary.append((kind, order_id))
            if fulfil_mode != "none":
                self.fulfil(store, order_id, loc_main, fulfil, partial=fulfil_mode == "partial")
        store.ids["orders"] = dict(summary)

        # reviews (customers write, marketing moderates) -----------------------------------------------
        for n, status in enumerate(["pending", "published", "rejected", "published"]):
            review = self.create(
                "/reviews",
                store.customers[n % len(store.customers)].token,
                {
                    "product_id": products[n % len(products)]["id"],
                    "customer_id": crm[n]["id"],
                    "rating": [5, 4, 1, 3][n],
                    "title": ["Love it", "Good value", "Spam!!!", "Fine"][n],
                    "body": "Review text. " * (3 + n),
                    "author_name": names[n][0],
                    "verified_purchase": n % 2 == 0,
                },
            )
            if status != "pending":
                self.patch(f"/reviews/{review['id']}", marketing.token, {"status": status})
        print(
            f"  {store.name}: {len(products)} products, {len(variants)} variants, {len(crm)} customers, {len(scenarios)} orders"
        )

    def place_order(
        self,
        store: Store,
        kind: str,
        offset: int,
        customer: dict[str, Any],
        variants: list[dict[str, Any]],
        rates: dict[str, Any],
        tax: Decimal,
        discounts: dict[str, Any],
        location: dict[str, Any],
        support: User,
        fulfil: User,
        manager: User,
        marketing: User,
    ) -> str:
        lines_wanted = self.rng.sample(
            variants, 6 if kind == "big_basket" else self.rng.randint(1, 3)
        )
        picked = [(v, self.rng.randint(1, 4)) for v in lines_wanted]
        subtotal = sum(Decimal(v["price"]) * q for v, q in picked)
        discount_total = Decimal("0")
        code: str | None = None
        discount = None
        if kind == "with_discount":
            discount, code = discounts["welcome10"], discounts["welcome10"]["code"]
            discount_total = (subtotal * Decimal("0.10")).quantize(CENT)
        rate_key = (
            "international"
            if kind == "international_express"
            else "free"
            if subtotal >= 75
            else "standard"
        )
        shipping = {
            "standard": Decimal("4.90"),
            "free": Decimal("0"),
            "international": Decimal("24.00"),
        }[rate_key]
        taxable = subtotal - discount_total
        tax_total = (taxable * tax).quantize(CENT)
        total = taxable + shipping + tax_total
        number = store.order_base + offset
        placed = self.now - timedelta(days=30 - offset * 2, hours=offset)
        address = {
            "name": f"{customer['first_name']} {customer['last_name']}",
            "address1": "1 Example Street",
            "city": "Springfield",
            "country_code": "US",
            "postal_code": "62000",
        }
        cancelled = kind == "cancelled_fraud"
        order = self.create(
            "/orders",
            support.token,
            {
                "number": number,
                "email": customer["email"],
                "customer_id": customer["id"],
                "status": "cancelled" if cancelled else "open",
                "financial_status": "pending",
                "currency": store.currency,
                "subtotal": money(subtotal),
                "shipping_total": money(shipping),
                "tax_total": money(tax_total),
                "discount_total": money(discount_total),
                "total": money(total),
                "billing_address": address,
                "shipping_address": address,
                "shipping_method": rate_key,
                "shipping_rate_id": rates[rate_key]["id"] if rate_key in rates else None,
                "discount_code": code,
                "tags_cache": ["web"] + (["fraud-review"] if cancelled else []),
                "source": "pos" if kind == "paid_unfulfilled" else "web",
                "placed_at": iso(placed),
                "cancelled_at": iso(placed + timedelta(hours=2)) if cancelled else None,
                "cancel_reason": "fraud" if cancelled else None,
                "note": "Please leave at the door." if offset % 3 == 0 else None,
            },
        )
        oid = order["id"]
        order_lines = []
        for v, q in picked:
            order_lines.append(
                self.create(
                    "/order_lines",
                    support.token,
                    {
                        "order_id": oid,
                        "variant_id": v["id"],
                        "title": v["product_title"],
                        "variant_title": v["title"],
                        "sku": v["sku"],
                        "quantity": q,
                        "unit_price": money(v["price"]),
                        "tax_total": money(Decimal(v["price"]) * q * tax),
                    },
                )
            )
        self.create(
            "/order_events",
            support.token,
            {
                "order_id": oid,
                "verb": "placed",
                "actor": customer["email"],
                "message": f"Order #{number} placed",
                "data": {"lines": len(order_lines)},
            },
        )
        if discount is not None:
            self.create(
                "/discount_usages",
                marketing.token,
                {
                    "discount_id": discount["id"],
                    "order_id": oid,
                    "amount": money(discount_total),
                    "email": customer["email"],
                },
            )
            self.patch(f"/discounts/{discount['id']}", marketing.token, {"used_count": 1})
        paid = kind not in ("pending_payment", "cancelled_fraud", "voided")
        if kind == "voided":
            self.create(
                "/transactions",
                support.token,
                {
                    "order_id": oid,
                    "kind": "authorization",
                    "status": "success",
                    "amount": money(total),
                    "currency": store.currency,
                    "gateway": "stripe",
                    "reference": f"pi_{number}",
                    "processed_at": iso(placed),
                },
            )
            self.create(
                "/transactions",
                support.token,
                {
                    "order_id": oid,
                    "kind": "void",
                    "status": "success",
                    "amount": money(total),
                    "currency": store.currency,
                    "gateway": "stripe",
                    "reference": f"pi_{number}_void",
                },
            )
            self.patch(
                f"/orders/{oid}",
                support.token,
                {
                    "financial_status": "voided",
                    "status": "cancelled",
                    "cancelled_at": iso(placed + timedelta(hours=1)),
                    "cancel_reason": "customer",
                },
            )
        elif kind == "cancelled_fraud":
            self.create(
                "/transactions",
                support.token,
                {
                    "order_id": oid,
                    "kind": "authorization",
                    "status": "failure",
                    "amount": money(total),
                    "currency": store.currency,
                    "gateway": "stripe",
                    "error_code": "card_declined",
                },
            )
            self.create(
                "/order_events",
                support.token,
                {
                    "order_id": oid,
                    "verb": "cancelled",
                    "actor": "system",
                    "message": "Flagged as fraud",
                },
            )
        elif paid:
            self.create(
                "/transactions",
                support.token,
                {
                    "order_id": oid,
                    "kind": "sale",
                    "status": "success",
                    "amount": money(total),
                    "currency": store.currency,
                    "gateway": "stripe",
                    "reference": f"ch_{number}",
                    "processed_at": iso(placed),
                },
            )
            self.patch(f"/orders/{oid}", support.token, {"financial_status": "paid"})
            self.create(
                "/order_events", support.token, {"order_id": oid, "verb": "paid", "actor": "stripe"}
            )
        else:
            self.create(
                "/transactions",
                support.token,
                {
                    "order_id": oid,
                    "kind": "authorization",
                    "status": "pending",
                    "amount": money(total),
                    "currency": store.currency,
                    "gateway": "bank_transfer",
                },
            )
        if (
            paid or kind == "pending_payment"
        ):  # stock is committed for everything that is not cancelled
            for _line, (v, q) in zip(order_lines, picked, strict=True):
                levels = self.api.ok("GET", "/inventory_levels?limit=100", token=fulfil.token)[
                    "items"
                ]
                level = next(
                    (
                        lv
                        for lv in levels
                        if lv.get("variant_id") == v["id"]
                        and lv.get("location_id") == location["id"]
                    ),
                    None,
                )
                if level is not None:
                    self.patch(
                        f"/inventory_levels/{level['id']}",
                        fulfil.token,
                        {"available": max(0, level["available"] - q), "committed": q},
                    )
        if kind in ("fully_refunded", "partially_refunded"):
            self.refund(
                store,
                order_lines,
                picked,
                oid,
                total,
                support,
                full=kind == "fully_refunded",
                location=location,
            )
        self.patch(
            f"/customers/{customer['id']}",
            support.token,
            {"orders_count": 1 + offset % 3, "total_spent": money(total) if paid else "0"},
        )
        return str(oid)

    def refund(
        self,
        store: Store,
        order_lines: list[dict[str, Any]],
        picked: list[tuple[dict[str, Any], int]],
        oid: str,
        total: Decimal,
        support: User,
        *,
        full: bool,
        location: dict[str, Any],
    ) -> None:
        refund = self.create(
            "/refunds",
            support.token,
            {
                "order_id": oid,
                "amount": money(total if full else total / 2),
                "reason": "damaged in transit" if full else "goodwill",
                "restock": full,
                "note": "Refunded to original payment method",
            },
        )
        for line, (v, q) in zip(order_lines, picked, strict=True):
            if full or line is order_lines[0]:
                qty = q if full else 1
                self.create(
                    "/refund_lines",
                    support.token,
                    {
                        "refund_id": refund["id"],
                        "order_line_id": line["id"],
                        "quantity": qty,
                        "subtotal": money(Decimal(v["price"]) * qty),
                    },
                )
                self.patch(f"/order_lines/{line['id']}", support.token, {"refunded_quantity": qty})
        self.create(
            "/transactions",
            support.token,
            {
                "order_id": oid,
                "kind": "refund",
                "status": "success",
                "amount": refund["amount"],
                "currency": store.currency,
                "gateway": "stripe",
                "reference": f"re_{oid[:8]}",
            },
        )
        self.patch(
            f"/orders/{oid}",
            support.token,
            {
                "financial_status": "refunded" if full else "partially_refunded",
                "total_refunded": refund["amount"],
                "status": "closed" if full else "open",
                "closed_at": iso(self.now) if full else None,
            },
        )
        self.create(
            "/order_events",
            support.token,
            {
                "order_id": oid,
                "verb": "refunded",
                "actor": support.email,
                "message": f"Refunded {refund['amount']}",
            },
        )

    def fulfil(
        self, store: Store, oid: str, location: dict[str, Any], fulfil: User, *, partial: bool
    ) -> None:
        lines = self.api.ok("GET", "/order_lines?limit=100", token=fulfil.token)["items"]
        mine = [ln for ln in lines if ln.get("order_id") == oid]
        shipped = mine[:1] if partial and len(mine) > 1 else mine
        fulfilment = self.create(
            "/fulfillments",
            fulfil.token,
            {
                "order_id": oid,
                "location_id": location["id"],
                "status": "success",
                "tracking_company": "DHL",
                "tracking_number": f"JD0146{self.rng.randint(10**8, 10**9)}",
                "tracking_url": "https://track.example.com/x",
                "shipped_at": iso(self.now - timedelta(days=1)),
            },
        )
        for line in shipped:
            self.create(
                "/fulfillment_lines",
                fulfil.token,
                {
                    "fulfillment_id": fulfilment["id"],
                    "order_line_id": line["id"],
                    "quantity": line["quantity"],
                },
            )
            self.patch(
                f"/order_lines/{line['id']}", fulfil.token, {"fulfilled_quantity": line["quantity"]}
            )
        status = "partial" if partial and len(mine) > 1 else "fulfilled"
        self.patch(f"/orders/{oid}", fulfil.token, {"fulfillment_status": status})
        self.create(
            "/order_events",
            fulfil.token,
            {
                "order_id": oid,
                "verb": "fulfilled",
                "actor": fulfil.email,
                "message": f"{status} fulfilment",
            },
        )


CATALOGS: dict[str, list[dict[str, Any]]] = {
    "acme": [
        {
            "title": "Classic Tee",
            "handle": "classic-tee",
            "vendor": "Acme",
            "type": "Shirts",
            "tags": ["bestseller", "eco"],
            "options": [
                {"name": "Size", "values": ["S", "M", "L"]},
                {"name": "Colour", "values": ["Black", "White"]},
            ],
            "variants": [
                {
                    "title": f"{s} / {c}",
                    "price": 24,
                    "compare": 30,
                    "o1": s,
                    "o2": c,
                    "stock": 40 if s != "L" else 0,
                }
                for s in ("S", "M", "L")
                for c in ("Black", "White")
            ],
        },
        {
            "title": "Zip Hoodie",
            "handle": "zip-hoodie",
            "vendor": "Acme",
            "type": "Outerwear",
            "tags": ["new", "sale"],
            "variants": [
                {"title": "M", "price": 59, "compare": 79, "o1": "M"},
                {
                    "title": "L",
                    "price": 59,
                    "compare": 79,
                    "o1": "L",
                    "policy": "continue",
                    "stock": 0,
                },
            ],
        },
        {
            "title": "Canvas Tote Bag",
            "handle": "tote",
            "vendor": "Acme",
            "type": "Bags",
            "tags": ["eco", "gift"],
            "variants": [{"title": "Default", "price": 18}],
        },
        {
            "title": "Wool Beanie",
            "handle": "beanie",
            "vendor": "Northwind",
            "type": "Hats",
            "tags": ["sale"],
            "variants": [{"title": "One size", "price": 15, "compare": 22}],
        },
        {
            "title": "Leather Belt",
            "handle": "belt",
            "vendor": "Northwind",
            "type": "Accessories",
            "tags": ["limited"],
            "variants": [
                {"title": "90 cm", "price": 45, "stock": 3},
                {"title": "100 cm", "price": 45, "stock": 1},
            ],
        },
        {
            "title": "Gift voucher",
            "handle": "voucher",
            "vendor": "Acme",
            "type": "Gift cards",
            "shipping": False,
            "tags": ["gift"],
            "variants": [{"title": "25", "price": 25}, {"title": "100", "price": 100}],
        },
        {
            "title": "Winter Parka (coming soon)",
            "handle": "parka",
            "vendor": "Acme",
            "type": "Outerwear",
            "status": "draft",
            "variants": [{"title": "M", "price": 189}],
        },
        {
            "title": "Summer Shorts 2019",
            "handle": "shorts",
            "vendor": "Acme",
            "type": "Shorts",
            "status": "archived",
            "variants": [{"title": "M", "price": 29}],
        },
        {
            "title": "Ünïcode Tee ☀ 漢字",
            "handle": "unicode-tee",
            "vendor": "Acme",
            "type": "Shirts",
            "description": "<p>" + "Very long description. " * 400 + "</p>",
            "variants": [{"title": "One", "price": 22}],
        },
        {
            "title": "Socks (3 pack)",
            "handle": "socks",
            "vendor": "Acme",
            "type": "Socks",
            "tags": ["bestseller"],
            "variants": [{"title": "Mixed", "price": 12, "stock": 500}],
        },
    ],
    "globex": [
        {
            "title": "Wireless Headphones",
            "handle": "headphones",
            "vendor": "Globex Audio",
            "type": "Audio",
            "tags": ["bestseller", "new"],
            "variants": [
                {"title": "Black", "price": 129, "compare": 159, "o1": "Black"},
                {"title": "Silver", "price": 129, "o1": "Silver", "stock": 5},
            ],
        },
        {
            "title": "USB-C Cable 2m",
            "handle": "usb-c",
            "vendor": "Globex",
            "type": "Cables",
            "tags": ["sale"],
            "variants": [{"title": "Default", "price": 9.9, "compare": 14.9, "stock": 900}],
        },
        {
            "title": "Mechanical Keyboard",
            "handle": "keyboard",
            "vendor": "Globex",
            "type": "Keyboards",
            "tags": ["limited"],
            "variants": [
                {"title": "Brown switches", "price": 99},
                {"title": "Red switches", "price": 99},
            ],
        },
        {
            "title": "4K Monitor 27in",
            "handle": "monitor",
            "vendor": "Globex Vision",
            "type": "Monitors",
            "variants": [{"title": "Default", "price": 449, "weight": 7.5, "stock": 8}],
        },
        {
            "title": "Laptop Stand",
            "handle": "stand",
            "vendor": "Globex",
            "type": "Accessories",
            "tags": ["eco"],
            "variants": [{"title": "Aluminium", "price": 39}],
        },
        {
            "title": "Extended warranty",
            "handle": "warranty",
            "vendor": "Globex",
            "type": "Services",
            "shipping": False,
            "variants": [{"title": "2 years", "price": 59}, {"title": "3 years", "price": 89}],
        },
        {
            "title": "Prototype board (draft)",
            "handle": "proto",
            "vendor": "Globex",
            "type": "Boards",
            "status": "draft",
            "variants": [{"title": "v0.1", "price": 0}],
        },
        {
            "title": "Webcam HD",
            "handle": "webcam",
            "vendor": "Globex",
            "type": "Video",
            "tags": ["sale"],
            "variants": [{"title": "Default", "price": 49, "compare": 69}],
        },
    ],
}


def build_stores(seeder: Seeder) -> list[Store]:
    def user(email: str, name: str, *roles: str) -> User:
        return User(email, name, list(roles))

    stores = [
        Store("acme", "Acme Outfitters", "USD", "US", 1001, user("ava@acme.test", "Ava Acme")),
        Store("globex", "Globex Goods", "EUR", "DE", 2001, user("gus@globex.test", "Gus Globex")),
    ]
    for store in stores:
        k = store.key
        store.staff = {
            "manager": user(f"mia.manager@{k}.test", "Mia Manager", "manager"),
            "catalog": user(f"carl.catalog@{k}.test", "Carl Catalog", "catalog"),
            "fulfillment": user(f"fay.fulfil@{k}.test", "Fay Fulfil", "fulfillment"),
            "support": user(f"sam.support@{k}.test", "Sam Support", "support"),
            "marketing": user(f"mo.marketing@{k}.test", "Mo Marketing", "marketing"),
        }
        store.customers = [
            user(f"{name}@{k}-shopper.test", name.title(), "customer")
            for name in ("zara", "yuki", "noah", "lena")
        ]
    return stores


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--api", default="http://localhost:18100")
    parser.add_argument("--mail", default="http://localhost:8025")
    args = parser.parse_args()

    api, mail = Http(args.api), Mail(args.mail)
    api.ok("GET", "/ready")
    mail.clear()
    seeder = Seeder(api, mail)
    stores = build_stores(seeder)
    for store in stores:
        print(f"{store.name}:")
        seeder.found_store(store)
        for user in [*store.staff.values(), *store.customers]:
            seeder.invite(store, user)
        print(f"  signed up {1 + len(store.staff) + len(store.customers)} users")
        seeder.populate(store, CATALOGS[store.key])

    users = []
    for store in stores:
        for u in [store.founder, *store.staff.values(), *store.customers]:
            users.append(
                {
                    "store": store.name,
                    "email": u.email,
                    "name": u.name,
                    "roles": ["admin"] if u is store.founder else u.roles,
                    "password": PASSWORD,
                }
            )
    (HERE / "seeded.json").write_text(
        json.dumps(
            {"api": args.api, "users": users, "ids": {s.key: s.ids for s in stores}},
            indent=2,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )
    rows = "\n".join(
        f"| {u['store']} | {u['email']} | {', '.join(u['roles'])} | {u['name']} |" for u in users
    )
    (HERE / "USERS.md").write_text(
        "# Seeded users\n\nEvery account uses the password `"
        + PASSWORD
        + "` (demo data only).\n\n| Store | Email | Roles | Name |\n|---|---|---|---|\n"
        + rows
        + "\n",
        encoding="utf-8",
    )
    print(f"done: {api.calls} API calls; see USERS.md and seeded.json")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ApiError, TimeoutError, urllib.error.URLError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
