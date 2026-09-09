# Reviewed coding models

Development feature, not included in the published v0.2.0 release. These commands
add a reviewed OpenRouter text route for supervised coding tasks. They do not
install OmniRoute or make an API model a protected native coding client.

## What to add

1. Inspect `ai-session api coding-models`. This anonymous metadata request needs
   no account, key or money allowance. It reports eligible IDs and exclusion reasons.
2. For execution, use an existing OpenRouter account or create one through its
   official sign-up. One account can provide the five model families below; separate
   vendor accounts are unnecessary for this route. Account access is verified only
   through that account, not inferred from the public catalog.
3. Provide `OPENROUTER_API_KEY` through the execution environment's private secret
   facility. Keep account credentials outside repositories, prompts and runbooks.
   A repository secret is appropriate only for an explicitly configured automation
   consumer; it is not a password archive or a local environment variable.
4. Complete `ai-session configure` with OpenRouter selected and an explicitly chosen
   monthly money cap/mode. Paid requests run on the monetary authority. See
   [API admission and accounting](api-and-spend.md). Account creation and installation
   do not authorize credit purchases, automatic reload or paid inference.
5. Choose an exact eligible model ID and a bounded task. After money authorization:

```sh
ai-session api coding-models
ai-session api coding-run --model REVIEWED_MODEL_ID --max-output-tokens 1000 --reserve-cost 0.25 --id UNIQUE_TASK_ID < task.txt
```

The reservation is an illustrative caller choice, not a provider maximum charge.
Use the existing API procedure to size it and reconcile costs. In PowerShell, pipe
`Get-Content -Raw -Encoding utf8 task.txt` into `ai-session.ps1 api coding-run` with
the same arguments. The manager inspects the returned patch or analysis, applies
scoped edits and runs relevant tests. This route does not execute tools, apply code
or supply independent review approval.

## Reviewed candidates

The initial profile was reviewed on 2026-09-09 and expires on 2026-10-09.
[OmniRoute's provider registry](https://github.com/diegosouzapw/OmniRoute/blob/ba597b631d22d85e56db6982f24b7d1ebe238df9/open-sse/config/providerRegistry.ts)
supplies candidate families, not coding-quality or free-use evidence. Exact IDs
come from fresh OpenRouter metadata. Evidence below supports inclusion, not a
ranking: vendor reports use different agents, effort and evaluation conditions.

| Model ID | Coding evidence |
| --- | --- |
| `moonshotai/kimi-k3` | [Moonshot's report](https://github.com/MoonshotAI/Kimi-K3) describes repository and terminal coding evaluations. |
| `z-ai/glm-5.3-flash` | [Z.ai's report](https://autoclaw.z.ai/blog/model/glm-5.3-flash/) provides DeepSWE and Terminal-Bench results; the Flash name alone does not determine eligibility. |
| `deepseek/deepseek-v4-pro-0813` | [DeepSeek's model card](https://huggingface.co/deepseek-ai/DeepSeek-V4-Pro-0813) reports repository, terminal and software-engineering evaluations for this revision. |
| `minimax/minimax-m3` | [MiniMax's report](https://www.minimax.io/blog/minimax-m3) includes SWE-Bench Pro and Terminal-Bench coding evaluations. |
| `qwen/qwen3.8-max-0902` | [Qwen's exact model page](https://www.qwencloud.com/models/qwen3.8-max-0902) describes the engineering update; [Arena's changelog](https://arena.ai/company/leaderboard-changelog) records the same revision in Code Arena without establishing a rank here. |

These are reviewed candidates, not locally benchmarked or authenticated accounts.
No candidate is marked free. Catalog prices, zero-price metadata and an OmniRoute
listing never establish free entitlement. A successful catalog check is not a
successful inference or coding acceptance test.

## Selection and configuration

The bundled [JSON policy](coding-models.json) is an editable allowlist with evidence,
family, publisher, review and expiry dates. Pass `--policy /private/path/policy.json`
to either command to use your own reviewed policy. Copy the schema from the bundled
file, retain exact IDs, add HTTPS evidence and set expiry 1-90 days after review.
Review current primary sources before adding or renewing entries. Keep private
paths and deployment credentials out of public policy files.

Every catalog check and coding dispatch fetches fresh public metadata with a
separate 20-second deadline before the inference `--timeout` starts.
The allowlist applies to `coding-run`; the explicitly configured general `api run`
command retains its existing model selection and money controls. Eligibility
requires an unexpired reviewed ID, advertised tools and output controls, at least
65,536 effective context tokens, known positive output capacity and nonnegative
finite input/output prices. The policy can raise the minimum context. Removed,
retired or invalid models appear under `excluded`; there is no stale-cache fallback,
wildcard selection or automatic successor. Variants such as `:free`, `:nitro` and
`:exacto` need their own review. A network or malformed-catalog failure stops dispatch
before a money reservation or inference request.

`coding-run` repeats these checks, bounds requested output and uses the existing
single-use monetary admission. A different returned model ID hides the output and
reports `model_mismatch`; any known charge is still settled. Unknown costs retain
the reservation. Reusing a request ID never repeats paid inference. Inspect
`ai-session spend status` and reconcile actual evidence before any explicit retry.

The receipt separates `billing_service: openrouter` from `model_family`. These
requests consume the API money budget, not Codex, Claude or Antigravity subscription
allowances, and do not join native `balance`/`work` routing. Copilot, Cursor and other
hosts retain their own selection, billing and verification boundaries; sharing a
model name does not share a quota pool. See [client support](clients.md) and
[subscription balancing](balancing.md).
