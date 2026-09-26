// Overlay WHY-path memory onto an ingested repository.
// Parameters: $repoId (required)
// Safe to re-run: MERGE on stable ids.

MERGE (r:Repository {id: $repoId})
ON CREATE SET r.name = coalesce(r.name, 'seed-billing'), r.summary = 'Integer cents and idempotent Stripe webhooks.'
SET r.updatedAt = datetime();

MERGE (tStripe:Technology {id: $repoId + ':technology:stripe'})
SET tStripe.repoId = $repoId, tStripe.name = 'stripe', tStripe.category = 'payments';
MERGE (r)-[:USES]->(tStripe);

MERGE (tFast:Technology {id: $repoId + ':technology:fastapi'})
SET tFast.repoId = $repoId, tFast.name = 'fastapi', tFast.category = 'web';
MERGE (r)-[:USES]->(tFast);

MERGE (lena:Developer {id: $repoId + ':developer:lena@example.com'})
SET lena.repoId = $repoId, lena.name = 'Lena Ortiz', lena.email = 'lena@example.com';
MERGE (lena)-[:WORKS_ON]->(r);

MERGE (floats:Decision {id: $repoId + ':decision:0000-use-floating-point-dollars'})
SET floats.repoId = $repoId, floats.slug = '0000-use-floating-point-dollars',
    floats.title = 'Use floating-point dollars', floats.status = 'superseded',
    floats.rationale = 'Store invoice amounts as floating-point dollar values and compute tax with float multiplication.',
    floats.date = date('2024-01-08'), floats.source = 'seed';
MERGE (floats)-[:ABOUT]->(r);
MERGE (floats)-[:DECIDED_BY]->(lena);

MERGE (cents:Decision {id: $repoId + ':decision:0001-use-integer-cents'})
SET cents.repoId = $repoId, cents.slug = '0001-use-integer-cents',
    cents.title = 'Store money as integer cents', cents.status = 'accepted',
    cents.rationale = 'All monetary amounts are integer cents. Tax rates are basis points. calculate_tax uses integer division.',
    cents.date = date('2024-02-12'), cents.source = 'seed';
MERGE (cents)-[:ABOUT]->(r);
MERGE (cents)-[:DECIDED_BY]->(lena);
MERGE (cents)-[:SUPERSEDES]->(floats);
MERGE (cents)-[:CHOOSES]->(tStripe);

MERGE (webhook:Decision {id: $repoId + ':decision:0002-invoice-paid-at-least-once'})
SET webhook.repoId = $repoId, webhook.slug = '0002-invoice-paid-at-least-once',
    webhook.title = 'Treat invoice.paid as at-least-once', webhook.status = 'accepted',
    webhook.rationale = 'apply_payment records a stable payment key and returns the existing key when Stripe delivers invoice.paid again.',
    webhook.date = date('2024-06-03'), webhook.source = 'seed';
MERGE (webhook)-[:ABOUT]->(r);
MERGE (webhook)-[:DECIDED_BY]->(lena);
MERGE (webhook)-[:CHOOSES]->(tStripe);

MERGE (issue:Issue {id: $repoId + ':issue:BILL-14'})
SET issue.repoId = $repoId, issue.key = 'BILL-14',
    issue.title = 'Stripe webhook retries double-apply payments', issue.status = 'resolved',
    issue.description = 'invoice.paid deliveries are at-least-once. apply_payment inserted a second payment and raised IntegrityError.',
    issue.source = 'seed';
MERGE (r)-[:HAS_ISSUE]->(issue);
MERGE (issue)-[:AFFECTS]->(r);

MERGE (err:Error {id: $repoId + ':error:duplicate-payment'})
SET err.repoId = $repoId, err.key = 'duplicate-payment', err.type = 'IntegrityError',
    err.message = 'payment already recorded for invoice', err.source = 'seed';
MERGE (issue)-[:CAUSED]->(err);

MERGE (sol:Solution {id: $repoId + ':solution:idempotent-payment'})
SET sol.repoId = $repoId, sol.key = 'idempotent-payment',
    sol.summary = 'Record a stable payment key and ignore duplicate invoice.paid events.',
    sol.source = 'seed';
MERGE (sol)-[:RESOLVES]->(issue);
MERGE (sol)-[:RESOLVES]->(err);
MERGE (sol)-[:INFORMS]->(webhook);

MERGE (pr:PullRequest {id: $repoId + ':pr:38'})
SET pr.repoId = $repoId, pr.number = 38, pr.title = 'Make Stripe payment application idempotent',
    pr.status = 'merged', pr.source = 'seed';
MERGE (r)-[:HAS_PR]->(pr);
MERGE (pr)-[:CLOSES]->(issue);
MERGE (pr)-[:AUTHORED_BY]->(lena);

RETURN r.id AS repoId, issue.key AS issue, cents.title AS decision, pr.number AS pull;
