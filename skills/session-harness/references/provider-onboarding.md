# Add one provider

Run the wizard in a terminal using the account that will execute requests:

```sh
ai-session onboard
ai-session onboard claude
ai-session claude onboard
ai-session onboard --list
```

Choose a provider by name or number. The list comes from the installed execution
adapters. If several routes exist, select `native`, `api`, `free` or `local`.
Provider aliases select available routes; they do not select a fixed model.
Use the live model catalog at task startup and choose the newest available generation.
An unknown provider requires a supported adapter before it can be onboarded.

## Native subscription

Install the native client and sign in with its own login flow, then run the wizard.
The wizard checks sign-in before saving authorization. Select a native quota mode
and local or trusted SSH authority for a first setup. Review the displayed settings
and type `yes` to save. Existing services, authority, mode, capacity, calendar,
budgets and usage history stay in place when adding another native service.

For an account shared across computers, authorize the service on its existing
authority as well as each participating client. The wizard does not change another
host's settings. Use `ai-session configure` for intentional account-wide changes.
Run the printed `usage check` command to verify current admission; saved setup alone
does not establish quota or paid-usage eligibility. New accounting baselines require
the explicit initialization procedure in [usage and context](usage-and-context.md).

## Explicit API

Use the provider's existing secure environment configuration. The wizard names the
required key variable and checks its presence without displaying or storing its
value. If it is missing, configure it outside the conversation and rerun onboarding.
No second credential store or shell-profile edit is created.

Run API onboarding on the monetary authority itself. An existing SSH quota authority
is preserved; the wizard does not replace it with a local authority to enable APIs.
Reuse the existing total monthly money cap and mode. If there is no cap, explicitly
choose a positive USD monthly cap and `strict` or `observed` mode. Strict currently
blocks API execution without a proven cost bound; observed accepts possible overruns.
Review and confirm the selected service before saving.

Optionally inspect the selected service's model catalog. For services without an
actual-cost receipt, complete verified token-rate setup using
[API and spend](api-and-spend.md). Catalog access and route authorization do not
prove inference readiness, model entitlement or a free allowance. The wizard makes
no model request, purchase, top-up or billing change.

## Recurring free access

Prepare a private verified account configuration using [free account setup](free-access.md).
Run `ai-session onboard PROVIDER`, choose `free`, and enter that configuration's
absolute path. The wizard imports only the selected provider, preserving the other
accounts, executor and existing group settings. Confirm an explicitly displayed
replacement if that provider already has different settings; Enter cancels it.
For a fresh group, choose whether to enable it. Mixed work remains off by default.

An imported key or catalog cannot replace current entitlement, allowance, pricing,
tokenizer and model evidence. Missing or expired evidence must be refreshed before
enabling the route. Disabled account records remain disabled. Configure an existing
remote free group on its executor; onboarding does not replace it with local state.
A disabled legacy OpenRouter-only group requires an explicit schema migration first;
the wizard refuses to discard its retained model configuration during conversion.

## Local Ollama

Run `ai-session onboard ollama`, choose `local`, then inspect the installed catalog.
Start Ollama first if its local daemon is unavailable. The check uses the supported
loopback endpoint with a bounded deadline. It does not create account authorization,
download models, change `OLLAMA_HOST`, or fall back to Ollama Cloud.
Use [client execution](../../../docs/CLIENT-EXECUTION.md) for the bounded run command.

## Cancel or finish

Enter `cancel` in a menu, decline the final confirmation, or press Ctrl-C to stop.
EOF and cancellation before confirmation leave authorization unchanged. The wizard
refuses noninteractive execution; `--list` and `--help` remain available for discovery.
An assistant must not answer the real account-authorization questions for the user.
Tests use isolated fixtures only.

Inspect the final result and any missing authentication, model or rate evidence.
After a storage failure, check `ai-session configure --status` before retrying;
existing setup fails closed if its confirmed write cannot complete. Never delete or
restore accounting to make onboarding succeed. A new provider's service selection
does not add it to an existing balancing group or relax model-role restrictions.
