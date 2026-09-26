Billing Service keeps invoice amounts honest.

Money is stored as integer cents. Stripe webhooks are treated as at-least-once deliveries, so payment application has to be safe to run twice.
