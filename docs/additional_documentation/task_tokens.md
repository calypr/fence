# Task Tokens

Fence supports **Task Tokens**, an access token type for services that
explicitly support them, such as Funnel/TES.

## Requesting a Task Token

Call the credentials endpoint with a `task_token` query parameter specifying
the desired token type:

```text
POST /credentials/api/access_token?task_token=<task_token_type>
```

Include `expires_in` to request a specific lifetime in seconds. For example:

```text
POST /credentials/api/access_token?task_token=FOO&expires_in=100
```

If `expires_in` is omitted, the request defaults to the maximum lifetime the
user is authorized for (see [User Authorization](#user-authorization)). This is
expected to be the common case.

Authorization for this request is governed by Arborist resource policies.

## Operator Setup

To enable Task Tokens on a Gen3 commons, configure these Fence fields:

```yaml
# Task token types that can be requested by users.
ALLOWED_TASK_TOKEN_TYPES: []

# The number of seconds after a task access token is issued until it expires.
# This max applies even if Arborist grants a longer-lived token. Configure it
# per task token type; unspecified types fall back to MAX_ACCESS_TOKEN_TTL.
MAX_TASK_TOKEN_TTL: {}
# Example:
# WORKFLOW: 345600
```

- **`ALLOWED_TASK_TOKEN_TYPES`** lists supported task token types. A user can
  only request a type in this list, regardless of Arborist permissions.
- **`MAX_TASK_TOKEN_TTL`** sets a per-type lifetime ceiling, in seconds.
  Unlisted types use `MAX_ACCESS_TOKEN_TTL`. This cap always applies, even if
  an Arborist policy allows a longer lifetime.

## User Authorization

Task token access uses Arborist resource paths under
`/services/fence/task-token/`, granted via `user.yaml`.

### Basic access (the common case)

To request a task token of type `FOO`, a user needs `create` access on the
`fence` service for this resource:

```text
/services/fence/task-token/FOO
```

This access allows a `FOO` token of any lifetime up to the operator-configured
`MAX_TASK_TOKEN_TTL`. Without `expires_in`, Fence grants the maximum permitted
lifetime. We recommend this unscoped access unless a user needs a shorter
fixed lifetime.

### Time-scoped access (uncommon)

To restrict access to a fixed, shorter lifetime, append the duration in
seconds to the resource path:

```text
/services/fence/task-token/FOO/100
```

A user with `create` access on this resource must request a `FOO` token with
`expires_in=100`. Omitting `expires_in` or requesting a different value fails.

Use this when a specific user or token type needs a lifetime below the
operator-configured maximum. Communicate the permitted value to the user
outside the API; Fence does not expose it in API responses.

> An exact value above `MAX_TASK_TOKEN_TTL` cannot produce a token. Fence
> rejects the request instead of capping or flooring the lifetime. The Fence
> setting is the authoritative ceiling; a `user.yaml` entry alone cannot
> enforce the maximum.

### Example

```yaml
# user.yaml
authz:
  resources:
    - name: services
      subresources:
        - name: fence
          subresources:
            - name: task-token
              subresources:
                - name: FOO
                  subresources:
                    - name: "100"

users:
  u1:
    policies:
      # Grants create on /services/fence/task-token/FOO/100
      - funnel_foo_task_token_100s
```

With this policy, `u1` can request a `FOO` token only with a 100-second TTL.
If `MAX_TASK_TOKEN_TTL` is below 100, the request fails; Fence does not cap
the value to the lower limit.

## Precedence Summary

- **`ALLOWED_TASK_TOKEN_TYPES`** gates which types exist on the commons.
- **Arborist `create` on `/services/fence/task-token/{type}`** allows any
  lifetime up to the operator maximum.
- **Arborist `create` on `/services/fence/task-token/{type}/{seconds}`**
  restricts a user to the exact lifetime. The request fails if it exceeds
  `MAX_TASK_TOKEN_TTL`.
- **`MAX_TASK_TOKEN_TTL[{type}]`** is the operator ceiling and falls back to
  `MAX_ACCESS_TOKEN_TTL` when the type is not listed.

For unscoped requests, the effective TTL is the **minimum** of the requested
TTL (or operator maximum if omitted) and `MAX_TASK_TOKEN_TTL`. For exact-value
requests, the TTL is the Arborist-configured value if it does not exceed
`MAX_TASK_TOKEN_TTL`; otherwise the request fails.
