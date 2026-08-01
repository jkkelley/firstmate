# CONTEXT_STATE.md

> Source of truth for AI session state. Feed this as the opening prompt of any new session.
> Do not edit manually unless re-validating against live infrastructure.

## Meta

| Field        | Value                                                                |
| ------------ | -------------------------------------------------------------------- |
| last_updated | 2026-07-31 17:40 UTC                                                 |
| updated_by   | context-compaction skill                                             |
| project      | firstmate (Yieldpoint AI / Astro Template Factory operational state) |
| repo         | github.com/jkkelley/firstmate                                        |

## Infrastructure

| Resource           | Value                                                                                                                                                                                                                                                                                                                                                     |
| ------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| kube-context       | `homelab-admin` (homelab cluster). Firstmate's shell default is `minikube` (wrong) - always pass `--context homelab-admin`.                                                                                                                                                                                                                               |
| AWS access         | **`minecraft-admin` is the only profile with real reach, and it is CAPTAIN-GATED PER USE** (set 2026-07-31). Never default to it, never fall back to it on AccessDenied, never put it in a crewmate brief. `yieldpoint-ai` and `yieldpoint-platform-dev-testing-user` are denied CloudFront/DynamoDB/S3 list. Account `690712292635`, region `us-east-2`. |
| container registry | `ghcr.io/jkkelley`. Pushing needs a token with `write:packages` (fine-grained PATs must add the Packages permission; classic PATs are most reliable for GHCR).                                                                                                                                                                                            |
| gateway namespace  | `yieldpoint-llm-gateway` - holds the real Anthropic key, sealed from build pods. LiteLLM pod needs 2Gi memory (1Gi OOM-crash-loops). Live 8+ days as of 2026-07-31, image `ghcr.io/berriai/litellm-database:v1.93.0`, service `litellm-gateway.yieldpoint-llm-gateway.svc.cluster.local:4000`.                                                            |
| build namespace    | `yieldpoint-platform` - ATF build Jobs run here; ConfigMap `astro-factory-config` holds `factoryImageTag`.                                                                                                                                                                                                                                                |
| secrets            | HashiCorp Vault (`vault` ns, pod `vault-0`, KV v2) -> ESO -> k8s Secret. Real key at `secret/homelab/apps/astro-template-factory`, field `yieldpoint-ai-llc-anthropic-api-key` (verbatim name everywhere; NOT in SSM).                                                                                                                                    |
| CI                 | Jenkins `jenkins.homelab.local`, `jenkins` ns, Kaniko/Trivy build pods.                                                                                                                                                                                                                                                                                   |
| hosting            | S3 + CloudFront; dev sites at `*.dev.yieldpointhosted.com`. Route53 zone `Z0224091PP37S9CM9NTF`. DynamoDB `dev-yieldpoint-platform-clients`. **No client sites live as of 2026-07-31** - the summit-roofing e2e infra was deprovisioned.                                                                                                                  |

## Toolchain

| Tool            | Role          | Notes                                                                                                                                                                                                                                                                                                           |
| --------------- | ------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| ArgoCD          | GitOps        | Repo `yieldpoint-gitops` (app-of-apps). Auto-sync can stall on retry-exhaustion after a merge - hard-refresh + patch a sync to unstick.                                                                                                                                                                         |
| Jenkins         | CI            | Job `astro-template-factory-dev/main` (multibranch): builds+pushes the ghcr image (tag = build number) AND auto-bumps the GitOps factory tag. Shared lib `jenkins-shared-lib` loads via the GitHub API (needs a valid API token, separate from git). Firstmate triggers builds via the jenkins-mcp on PR merge. |
| ESO             | Secrets       | source: AWS SSM -> Vault -> ESO -> k8s Secret.                                                                                                                                                                                                                                                                  |
| LiteLLM gateway | LLM gateway   | Self-hosted proxy. Per-build virtual keys (haiku-scoped, $0.25 / 2h). `/v1/messages` Anthropic-native. Spend logs feed the cost ledger. Real key never reaches build pods - build gets virtual key + `ANTHROPIC_BASE_URL` only. **Documented nowhere in the vault** - see blockers.                             |
| n8n             | build trigger | Creates the ATF build Job (s17 pivot). Mints the per-build virtual key from the gateway master key (Option A) and injects it + `ANTHROPIC_BASE_URL` into the Job.                                                                                                                                               |
| tasks-axi       | backlog       | `data/backlog.md`.                                                                                                                                                                                                                                                                                              |
| teardown        | e2e cleanup   | `make deprovision-client SLUG=<slug> ENV=dev CONFIRM=yes` in `yieldpoint-client-provisioner`, with `PROFILE`/`ROUTE53_ZONE_ID`/`DYNAMO_TABLE` all passed. **NOT `cleanup-test-infra`** - that only matches `test-*` slugs and silently no-ops.                                                                  |

## Active Tasks

| Priority | Task                                                        | Status  | Next Action                                                                                                                                                                             |
| -------- | ----------------------------------------------------------- | ------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1        | ATF phase 1                                                 | DONE    | Closed out and moved to vault `03_Projects/done/astro_template_factory/` via PR #113 (merged 2026-07-31), evidence folder holds the screenshot + full e2e report. Test infra torn down. |
| 2        | Three captain decisions from the vault audit                | pending | `slug-length-strategy`, `retire-atf-anthropic-secret`, `provisioning-topology-fate`. Held in the backlog; dependent work is blocked on them.                                            |
| 3        | ATF category rebuild card (`atf-category-rebuild-card`)     | queued  | Vault `03_Projects/active/` is EMPTY - Slices 1-4 are orphaned. Cut `03_Projects/active/atf_category_rebuild/`. Also unhold `atf-cat-s1-taxonomy` (its gate condition is now met).      |
| 4        | Gateway architecture landing (`vault-gateway-arch-landing`) | queued  | Vault audit P0/A1: C4 L2 node, interface-map, header bump to v5, model-gen step, grown build-Job env contract.                                                                          |
| 5        | Tier-2 standards sweep (`vault-tier2-standards-sweep`)      | queued  | Vault audit P0/A2 plus T2 (parameterise e2e SOP off 35 hardcoded slugs) and T3 (repoint COMPASS, add testing-hub row).                                                                  |
| 6        | figma-wireframe skill (`figma-wireframe-ship`)              | queued  | Deterministic half verified. Figma MCP is UNAUTHENTICATED - needs captain OAuth plus a Full/Dev seat on a paid plan before the drawing half can be tested.                              |
| 7        | Rich-fields e2e (`e2e-makefile-testing-fields`)             | queued  | Fix phone flow: the Stripe trigger CANNOT set `customer_details.phone` (parameter-unknown), so PHONE is empty on the rich path; metadata fields flow fine.                              |

## Decisions Made

| Date       | Decision                                                                                       | Reason                                                                                                                           |
| ---------- | ---------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| 2026-07-22 | LLM gateway = LiteLLM (self-hosted), not a custom Go broker                                    | Proven, least code, native spend tracking.                                                                                       |
| 2026-07-22 | n8n mints per-build virtual keys directly (Option A)                                           | Ships now, no new code; n8n is already high-trust (creates Jobs, holds the platform key).                                        |
| 2026-07-22 | Per-build key budget/TTL = $0.25 / 2h                                                          | ~4x measured worst-case build spend.                                                                                             |
| 2026-07    | Missing/invalid model key -> degrade to stub + flag (`source=fallback`), not hard-fail         | Captain choice.                                                                                                                  |
| 2026-07-23 | Every ATF/gateway e2e MUST run through `make test-stage1` (test customer `summit-roofing`)     | One canonical production path, never ad-hoc.                                                                                     |
| 2026-07-23 | Every generated site must be styled + first-class SEO (LocalBusiness JSON-LD, sitemap, robots) | Professional standard; no bare pages.                                                                                            |
| 2026-07-31 | The `minecraft-admin` AWS profile requires explicit captain permission per use                 | It is the only broadly-privileged profile; breadth is why it is gated, not why it is handy.                                      |
| 2026-07-31 | Clean up after ourselves - e2e test infra is torn down after the run                           | Reversed the prior practice of leaving resources live for browsing.                                                              |
| 2026-07-31 | Evidence before teardown, as a hard ordering                                                   | Once infra is gone the screenshot + report are the only surviving proof; captured evidence must outlive the worker that made it. |

## Lessons Learned

- 2026-07-23: Jenkins factory build failed at shared-lib load with GitHub `401 Bad credentials` - the "GitHub" SCM source hits the GitHub API (not plain git); git-over-HTTPS worked. Switch the shared-lib SCM to plain Git, or use a classic PAT with API access.
- 2026-07-23: Kaniko GHCR push `DENIED` - the fine-grained PAT lacked `Packages: write` (`write:packages`). Git + API access do NOT cover container-registry pushes.
- 2026-07-23: Merging a template PR does NOT rebuild the factory image - the factory ConfigMap stays pinned to the old `factoryImageTag` until Jenkins rebuilds (`astro-template-factory-dev/main`) and auto-bumps it. Firstmate kicks that Jenkins job on merge.
- 2026-07-23: A real model-generated single-page site is ~2-3KB HTML; size alone is NOT the stub tell - verify with `generation.source=model` + a matching gateway spend row + bespoke client content.
- 2026-07-23: `fm_pid_identity` WSL2 drift fixed by adopting upstream's `/proc` starttime + cmdline hash; the fork carries local patches on hot files that re-conflict on every upstream pull.
- 2026-07-31: A stale local clone masquerades as a missing file. A worker reported the mandatory testing SOP absent from the vault; the vault was fine and the clone was 9 commits behind. Always run `git fetch && git rev-list --left-right --count HEAD...origin/main` before claiming any file is missing from a repo.
- 2026-07-31: `cleanup-test-infra` looks like the teardown command but filters on `test-*` slugs only - it runs, reports success, and deletes nothing. Do not retry it for a real client slug; use `deprovision-client`.
- 2026-07-31: `deprovision-client.sh` silently skips its Route53 and DynamoDB steps with only a WARN when `ROUTE53_ZONE_ID`/`DYNAMO_TABLE` are unset, and defaults `PROFILE` to a profile that lacks permission. Pass all of them and verify the resources are actually gone rather than trusting the script's "complete" line.
- 2026-07-31: `chrome-devtools-axi` is wedged in this WSL2 environment (`Target closed` on every navigate; restarts and `--no-sandbox` do not help). Use puppeteer's cached Chrome directly: `~/.cache/puppeteer/chrome/*/chrome-linux64/chrome --headless --no-sandbox --screenshot=<path> --window-size=1440,2400 --virtual-time-budget=8000 <url>`, then read the PNG to confirm it caught the real page.
- 2026-07-31: A finished crewmate whose PR has not merged keeps its slot and repeatedly wakes the watcher as `stale`. That is normal, not a stuck worker - drain, re-arm, and tear down only once the work has landed.

## Blockers

| Blocker                                | Last Known State                                                                                                                                                                                                                                                                | Owner                                   |
| -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------- |
| `yieldpoint` second mate is DOWN       | Stopped around 2026-07-24 with finished work unreconciled; that is why the passing e2e never surfaced for a week. Needs relaunch before any routed work moves. Home: `/home/luna/.treehouse/firstmate-b1f316/1/firstmate`                                                       | firstmate                               |
| LiteLLM gateway undocumented           | Serving production 8+ days with ZERO vault coverage - vault-wide grep for the namespace returns nothing, and docs still call it "under captain review". Documentation gap, NOT a security hole (3-stage split genuinely not built, and what shipped is copy-gen, not code-gen). | `vault-gateway-arch-landing`            |
| Figma MCP unauthenticated              | Only `authenticate`/`complete_authentication` exposed; drawing tools appear after OAuth. Also needs a Full/Dev seat on a paid plan.                                                                                                                                             | captain                                 |
| `astro-anthropic-api-key` still synced | The real key still lands in `yieldpoint-platform`, where build pods run - an explicit anti-pattern in the design of record now that n8n mints per-build keys. Awaiting captain decision.                                                                                        | captain (`retire-atf-anthropic-secret`) |
| Rich-fields e2e phone flow             | Stripe trigger cannot set `customer_details.phone` (parameter-unknown); metadata fields flow fine. Only affects the rich-fields enhancement.                                                                                                                                    | crew (`e2e-makefile-testing-fields`)    |

## Hydration Prompt

Copy-paste this at the start of a new session:

```
Read CONTEXT_STATE.md in this project root before doing anything else.
Use the Infrastructure and Toolchain tables as ground truth.
Current focus: [replace with active task].
Do not suggest IP addresses, tool versions, or architecture patterns
that contradict CONTEXT_STATE.md without flagging the conflict first.
```
