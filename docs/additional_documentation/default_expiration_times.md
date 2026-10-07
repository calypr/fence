# Default expiration times in Fence

This page lists the default lifetimes of temporary Fence artifacts.

## Tokens, sessions, and signed URLs

- **Access token:** 20 minutes by default (`ACCESS_TOKEN_EXPIRES_IN`). A token
  cannot outlive its refresh token. A browser session lasts at most 8 hours.
- **Sliding session window:** 15 minutes (`SESSION_TIMEOUT`). The session
  lasts at most 8 hours (`SESSION_LIFETIME`). Fence creates a new access token
  cookie when the token is missing, expired, or within
  `ACCESS_TOKEN_RENEWAL_THRESHOLD` seconds of expiration.
- **Refresh token:** 30 days by default and at most
  `REFRESH_TOKEN_EXPIRES_IN`.
- **API key:** 30 days at most (`MAX_API_KEY_TTL`). The request can specify a
  shorter lifetime.
- **Access token from an API key:** 1 hour by default and at most
  `MAX_ACCESS_TOKEN_TTL` per token. Fence rejects a request that would outlive
  the API key.
- **Task token:** The lifetime depends on the token type. `MAX_TASK_TOKEN_TTL`
  sets each type's limit; unspecified types use `MAX_ACCESS_TOKEN_TTL`.
  No task token types are allowed by default.
- **AWS or Google signed URL:** Up to 1 hour (`MAX_PRESIGNED_URL_TTL`). The
  request can specify a shorter lifetime.

## Google account linking and service accounts

"SA" means service account. Google account linking and proxy group management
are under review for deprecation. Do not build new functionality on these
lifetimes.

- **Google account linkage:** Indefinite. The link itself does not expire,
  although the Google account access does.
- **Google account access:** 1 day (`GOOGLE_ACCOUNT_ACCESS_EXPIRES_IN`). This
  controls how long Fence associates a Google email with a user after
  authentication. The request can specify a shorter lifetime.
- **User SA account access:** 7 days
  (`GOOGLE_USER_SERVICE_ACCOUNT_ACCESS_EXPIRES_IN`). This controls how long
  access to data remains in the proxy group. The request can specify a shorter
  lifetime.
- **Client SA key for a user:** 10 days. The user obtains it through
  `/credentials/google`. Cirrus sets the lifetime with
  `SERVICE_KEY_EXPIRATION_IN_DAYS`. The request can specify a shorter lifetime.
- **User primary SA key:** 30 days
  (`GOOGLE_SERVICE_ACCOUNT_KEY_FOR_URL_SIGNING_EXPIRES_IN`). Fence uses the key
  for Google URL signing.
