# Synthetic lifecycle parser fixtures

These are original, minimal synthetic inputs authored for this repository under
its root MIT license, not captured or extracted provider pages. They replace the
former extracted HTML at these paths. No provider prose, artwork, scripts, styles,
or page assets are included. Model identifiers and structural protocol tokens
are retained only as parser test data, not current availability evidence.

All three encode JSON Next Flight framing, a canonical route, children outlets,
a page reference, and one scoped header with title, badge, and identity slots.
`large-current-flight.html` declares two aliases inline;
`deprecated-current-flight.html` exercises the deprecated badge;
`lazy-current-flight.html` resolves the identity through a separate lazy record.

The focused tests mutate these structures to reject wrong routes, incidental or
disjoint aliases, ambiguous headers/status, missing lazy records, malformed JSON,
cycles, excessive depth, and amplified DAG work. These fixtures test supported
structural contracts, not fidelity to the provider’s current live page. Replacing
them does not resolve redistribution rights for historical extracted fixtures.
