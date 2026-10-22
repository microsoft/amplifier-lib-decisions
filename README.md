# Optional decision contracts

`amplifier-lib-decisions` is a small shared library for bounded
predicate, choice and ordinal score requests. It imports no Core, Foundation,
application, browser, vendor SDK or HTTP client. It owns neither credentials nor
endpoints. The initial provider implementations are OpenAI Decisions, TypeSafe
Jev and Microsoft Decision-1 through the Azure OpenAI provider.

`DecisionRequest` supplies one state and named typed questions. Explicit
`allow_external_state=True` is required by each provider before sending state.
`DecisionResult` preserves requested/reported models, usage, request ID, latency
and per-question `answered`, `refused`, `invalid`, `unavailable` or `abstained`
outcomes. Missing answers remain missing; providers cannot invent execution
authority. Confidence is provider specific and is not calibrated across vendors.
An alias is not an immutable checkpoint. Box/image execution is not advertised.
Self-hosted providers can attach a transport-verified checkpoint and explicit
`cost` metadata separately from token usage. A zero API charge excludes hardware
and electricity and does not erase hosted planning, writing or fallback charges.

The pure System One codec is shared by Jev and Decision-1. Each provider supplies
its own authenticated transport. The runtime helper bounds requests, emits
redacted lifecycle events, preserves cancellation and implements registry cleanup;
it performs no retries or fallback. Consumers own fallback policy.

## Optional Amplifier integration

Providers explicitly register `coordinator.get_capability('decision.backends')`,
a mapping from unique backend IDs to objects implementing `Backend`. Registration
does not select a model for any consumer. Cleanup removes only entries the
registration still owns. Multiple named backends can share one provider account.

```yaml
decisions:
  enabled: true
  backends:
    browser-selection:
      enabled: true
      model: an-explicit-model-or-deployment
```

The provider's ordinary auth/configuration remains authoritative. Consumers bind
their own purpose to a named backend and independently authorize state transfer.
Missing consumer selection means ordinary use. Neither ambient keys nor an
installed package changes that default. `mode: standard` overrides decision use.

Providers expose offline `amplifier.decision_backends` entry points returning
schema version 2, `provider_module`, backend metadata and a local `validate`
callable. Editors match these with saved provider accounts. Decision preferences
accept only `model` and optional `endpoint`; credentials stay with the account.
Discovery must not create a client, look up credentials or make a network call.
These interfaces are development contracts, pending ecosystem review.

Provider extras and the UI-use decisions extra depend on this repository's
canonical Git `main` branch; a separate PyPI release is not required. For direct use:

```sh
uv pip install 'amplifier-lib-decisions @ git+https://github.com/microsoft/amplifier-lib-decisions@main'
```

Hosts should record the installed revision and qualify updates before activation.
Local development can use a wheel or explicit editable source in an owned
environment. Do not install the retired `amplifier-bundle-decision-models`
prototype in the same environment; it used the same Python namespace.

Run `pytest` with the `test` extra. Tests use synthetic state and no service keys.
