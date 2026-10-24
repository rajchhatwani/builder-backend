# Authorization in Tickets

This project decides access with **ABAC** policies. They are written in the builder and
shipped as data in `app/auth/policy_data.py`; `app/auth/policy.py` is the engine that evaluates them.
Change a policy in the builder and generate again: do not edit the data by hand.

## How a decision is made

1. **Default deny.** A request is allowed only if at least one *allow* policy applies and its condition holds.
2. **Deny wins.** If any *deny* policy applies and its condition holds, the request is refused, whatever else allows it.
3. **Signed in.** Every route needs a signed-in person; there are no public routes in this model.
4. **Rows are filtered in the database.** Listing, reading, changing and deleting only ever see rows the person may
   see, so totals and pages cannot leak anything. Someone else's row looks exactly like a row that does not exist (404).
5. **Writes are checked twice.** A new row must satisfy the `create` policies with the values sent. After an update the
   row must still be one the person could read, so a row cannot be handed away or moved out of reach.

## The policies

| Policy | Effect | Applies to | Carried by | Condition |
|---|---|---|---|---|
| `see_own_department` | allow | Ticket.list, Ticket.get, Ticket.head | everyone signed in | (the record's department is your department or the record's created by id is your id) |
| `open_in_own_department` | allow | Ticket.create | everyone signed in | the record's department is your department |
| `edit_own_unfinished` | allow | Ticket.update, Ticket.replace | everyone signed in | (the record's created by id is your id and the record's status is not "closed") |
| `admins_manage_everything` | allow | Ticket.* | everyone signed in | "admin" is one of your roles |
| `closed_is_final` | deny | Ticket.update, Ticket.replace, Ticket.delete | everyone signed in | the record's status is "closed" |
| `delete_from_office` | allow | Ticket.delete | everyone signed in | (your IP address is inside the network ["10.0.0.0/8", "127.0.0.0/8"] and the record's priority is at most 3 and the record's created by id is your id) |

## What conditions can look at

* **You** (the signed-in person): department, email, id, roles.
* **The record**: its own fields, plus `id`, `created_at`, `updated_at` and `created_by_id`.
* **The request**: the hour (UTC), the weekday (UTC, Monday is 0) and the caller's IP address.

Conditions are plain data (`all` / `any` groups of comparisons). There is no scripting: nothing in a policy is ever executed.

## Things to know

* **Missing values never match.** A comparison with an empty value is false, in the database and in Python alike.
  Creating a record without a field that a `create` policy checks is therefore refused. Send the value explicitly.
  The same rule applies to **deny** policies: a deny whose condition looks at an empty field does not fire for
  that record. Make such fields required, or add a second policy that covers the empty case.
* **IP conditions behind a proxy.** Run the application with `uvicorn --proxy-headers --forwarded-allow-ips <proxy address>`
  so the caller's address is the real one. Without it every request appears to come from the proxy.
* **Time is UTC.**
* **Tests.** `tests/test_authz.py` pins the engine file by hash, checks the policy data loads, and checks that unconditional
  deny policies and sign-in requirements hold. Entities governed by policies have no generic smoke test, because who may
  do what depends on your policies: add scenario tests for the rules that matter to your business.
