"""YOUR provider adapters (written once, never overwritten).

Register an adapter for a kind and a name that is listed under `providers.adapters` in the spec:

    from app.providers.registry import register

    register("email", "myprovider", lambda: MyEmailAdapter())

An adapter has `kind`, `name`, `async health(credentials)` and `async call(request, credentials)`, maps
every failure onto app.providers.errors, and never puts a credential or a request body in a message.
Credentials arrive as a `Credentials` object (`credentials.get("api_key")`).
"""
