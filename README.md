# Folio public research feed

Public SEC 13F filings and U.S. House transaction disclosures, refreshed hourly by GitHub Actions. No account data, portfolio receipts or brokerage keys belong in this repository.

Set the SEC_USER_AGENT Actions secret to a real contact name and email. The job uses it only in SEC request headers.

Workflow runs can be delayed or fail. Every dataset carries its own fetched_at timestamp. Check run status and dataset timestamps before relying on freshness.

Parser source: https://github.com/Jakeschincariol/trader-skill (MIT).
