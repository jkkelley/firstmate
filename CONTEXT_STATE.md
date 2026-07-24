# CONTEXT_STATE.md

> Source of truth for AI session state. Feed this as the opening prompt of any new session.
> Do not edit manually unless re-validating against live infrastructure.

## Meta

| Field        | Value                                                                |
| ------------ | -------------------------------------------------------------------- |
| last_updated | 2026-07-24 02:49 UTC                                                 |
| updated_by   | context-compaction skill                                             |
| project      | firstmate (Yieldpoint AI / Astro Template Factory operational state) |
| repo         | github.com/jkkelley/firstmate                                        |

## Infrastructure

| Resource           | Value                                                                                                                                                                                                                  |
| ------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| kube-context       | `homelab-admin` (homelab cluster). Firstmate's shell default is `minikube` (wrong) - always pass `--context homelab-admin`.                                                                                            |
| container registry | `ghcr.io/jkkelley`. Pushing needs a token with `write:packages` (fine-grained PATs must add the Packages permission; classic PATs are most reliable for GHCR).                                                         |
| gateway namespace  | `yieldpoint-llm-gateway` - holds the real Anthropic key, sealed from build pods. LiteLLM pod needs 2Gi memory (1Gi OOM-crash-loops).                                                                                   |
| build namespace    | `yieldpoint-platform` - ATF build Jobs run here; ConfigMap `astro-factory-config` holds `factoryImageTag`.                                                                                                             |
| secrets            | HashiCorp Vault (`vault` ns, pod `vault-0`, KV v2) -> ESO -> k8s Secret. Real key at `secret/homelab/apps/astro-template-factory`, field `yieldpoint-ai-llc-anthropic-api-key` (verbatim name everywhere; NOT in SSM). |
| CI                 | Jenkins `jenkins.homelab.local`, `jenkins` ns, Kaniko/Trivy build pods.                                                                                                                                                |
| hosting            | S3 + CloudFront; dev sites at `*.dev.yieldpointhosted.com`.                                                                                                                                                            |

## Toolchain

| Tool            | Role          | Notes                                                                                                                                                                                                                                                                                                           |
| --------------- | ------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| ArgoCD          | GitOps        | Repo `yieldpoint-gitops` (app-of-apps). Auto-sync can stall on retry-exhaustion after a merge - hard-refresh + patch a sync to unstick.                                                                                                                                                                         |
| Jenkins         | CI            | Job `astro-template-factory-dev/main` (multibranch): builds+pushes the ghcr image (tag = build number) AND auto-bumps the GitOps factory tag. Shared lib `jenkins-shared-lib` loads via the GitHub API (needs a valid API token, separate from git). Firstmate triggers builds via the jenkins-mcp on PR merge. |
| ESO             | Secrets       | source: AWS SSM -> Vault -> ESO -> k8s Secret.                                                                                                                                                                                                                                                                  |
| LiteLLM gateway | LLM gateway   | Self-hosted proxy. Per-build virtual keys (haiku-scoped, $0.25 / 2h). `/v1/messages` Anthropic-native. Spend logs feed the cost ledger. Real key never reaches build pods - build gets virtual key + `ANTHROPIC_BASE_URL` only.                                                                                 |
| n8n             | build trigger | Creates the ATF build Job (s17 pivot). Mints the per-build virtual key from the gateway master key (Option A) and injects it + `ANTHROPIC_BASE_URL` into the Job.                                                                                                                                               |
| tasks-axi       | backlog       | `data/backlog.md`.                                                                                                                                                                                                                                                                                              |

## Active Tasks

| Priority | Task                                                             | Status                 | Next Action                                                                                                                                                                                                                  |
| -------- | ---------------------------------------------------------------- | ---------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1        | ATF generates styled Astro sites via LiteLLM gateway, end to end | DONE                   | First full `make test-stage1` e2e PASSED. Live styled site: https://summit-roofing-20260723200843.dev.yieldpointhosted.com/ - model-generated, styled, SEO (JSON-LD LocalBusiness), phone present, no real key in build pod. |
| 2        | Slice 1 (`atf-cat-s1-taxonomy`)                                  | held -> likely cleared | A live model-built site landed; confirm and unhold.                                                                                                                                                                          |
| 3        | Rich-fields e2e (`e2e-makefile-testing-fields`)                  | queued                 | Fix phone flow: the Stripe trigger CANNOT set `customer_details.phone` (parameter-unknown), so PHONE is empty on the rich path; metadata fields (slug/business/domain) flow fine.                                            |
| 4        | context-compaction skill import                                  | DONE                   | Merged as firstmate PR #4; skill now at `.agents/skills/context-compaction/`.                                                                                                                                                |

## Decisions Made

| Date       | Decision                                                                                       | Reason                                                                                    |
| ---------- | ---------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| 2026-07-22 | LLM gateway = LiteLLM (self-hosted), not a custom Go broker                                    | Proven, least code, native spend tracking.                                                |
| 2026-07-22 | n8n mints per-build virtual keys directly (Option A)                                           | Ships now, no new code; n8n is already high-trust (creates Jobs, holds the platform key). |
| 2026-07-22 | Per-build key budget/TTL = $0.25 / 2h                                                          | ~4x measured worst-case build spend.                                                      |
| 2026-07    | Missing/invalid model key -> degrade to stub + flag (`source=fallback`), not hard-fail         | Captain choice.                                                                           |
| 2026-07-23 | Every ATF/gateway e2e MUST run through `make test-stage1` (test customer `summit-roofing`)     | One canonical production path, never ad-hoc.                                              |
| 2026-07-23 | Every generated site must be styled + first-class SEO (LocalBusiness JSON-LD, sitemap, robots) | Professional standard; no bare pages.                                                     |

## Lessons Learned

- 2026-07-23: Jenkins factory build failed at shared-lib load with GitHub `401 Bad credentials` - the "GitHub" SCM source hits the GitHub API (not plain git); git-over-HTTPS worked. Switch the shared-lib SCM to plain Git, or use a classic PAT with API access.
- 2026-07-23: Kaniko GHCR push `DENIED` - the fine-grained PAT lacked `Packages: write` (`write:packages`). Git + API access do NOT cover container-registry pushes.
- 2026-07-23: Merging a template PR does NOT rebuild the factory image - the factory ConfigMap stays pinned to the old `factoryImageTag` until Jenkins rebuilds (`astro-template-factory-dev/main`) and auto-bumps it. Firstmate kicks that Jenkins job on merge.
- 2026-07-23: A real model-generated single-page site is ~2-3KB HTML; size alone is NOT the stub tell - verify with `generation.source=model` + a matching gateway spend row + bespoke client content.
- 2026-07-23: `fm_pid_identity` WSL2 drift fixed by adopting upstream's `/proc` starttime + cmdline hash; the fork carries local patches on hot files that re-conflict on every upstream pull.

## Blockers

| Blocker                    | Last Known State                                                                                                                                                       | Owner                                |
| -------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------ |
| Rich-fields e2e phone flow | Stripe trigger cannot set `customer_details.phone` (parameter-unknown); metadata fields flow fine. Only affects the rich-fields enhancement, not the working e2e site. | crew (`e2e-makefile-testing-fields`) |

## Hydration Prompt

Copy-paste this at the start of a new session:

```
Read CONTEXT_STATE.md in this project root before doing anything else.
Use the Infrastructure and Toolchain tables as ground truth.
Current focus: [replace with active task].
Do not suggest IP addresses, tool versions, or architecture patterns
that contradict CONTEXT_STATE.md without flagging the conflict first.
```
