# Trading desk coordinator

The local server starts one desk coordinator and the existing bounded research
agent consumers. Every 30 seconds, the coordinator reads news, paper-worker and
ledger state. News supplies dated context through the existing research adapter.
Paper ingestion supplies the reconciled account ledger.

Each department submits one health task per five-minute window to the existing
agent service. Tasks retain source and observation times, run in isolated
processes with deadlines and await operator review. Outstanding tasks are capped
at 100. A full review queue pauses new submissions while health checks continue.
Failures expose an unavailable department. Task payloads contain health metadata.

The Auto Trading page shows these departments in Trading desk. GET /api/desk
returns their checks and handoff map. GET /api/agents exposes task results and
review status. Monitoring does not arm the paper worker or promote strategies.

This is a deterministic operations team. The existing 512 evidence role contracts
are available for supplied research inputs. Whole-market discovery, automatic
fundamental research and news-driven strategy validation remain pending. A
registered role alone does not demonstrate working access to its required data.
