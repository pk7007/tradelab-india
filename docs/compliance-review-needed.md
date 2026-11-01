# Compliance review needed

This is a planning checklist, not legal advice and not a statement of compliance or regulatory approval.

Before any public release or material product expansion, obtain qualified advice on current applicable Indian laws, regulations, exchange/provider terms, privacy obligations, consumer disclosures, intellectual-property rights, and advertising/marketing claims.

SEBI issued a circular on safer participation of retail investors in algorithmic trading in February 2025. NSE implementation standards describe static-IP mapping for client API access. Requirements and applicability depend on the product and broker setup; this local prototype does not establish compliance. Review the [SEBI circular](https://www.sebi.gov.in/legal/circulars/feb-2025/safer-participation-of-retail-investors-in-algorithmic-trading_91614.html) and the broker/exchange's current implementation requirements before enabling API orders.

Review at minimum:

- Whether the user journey, recommendations, analytics, or claims could be treated as investment advice, research, or another regulated activity.
- Whether API access requires a static public IP, exchange/broker registration or tagging, broker-cloud hosting, or other controls for this user's exact setup.
- Data licenses, exchange terms, market-data rights, retention, and redistribution.
- Privacy notices, consent, deletion, security controls, and incident handling.
- Clear labeling of synthetic and historical data, hypothetical results, modeled costs, and limitations.
- The weekly digest's source terms, excerpt length, attribution, and automated use before enabling sources.

Do not claim SEBI/NSE approval or compliance without a documented basis and qualified review. Live trading is outside the default roadmap and requires separate explicit product approval, broker authorization, security review, operational readiness, and qualified legal/compliance review.
