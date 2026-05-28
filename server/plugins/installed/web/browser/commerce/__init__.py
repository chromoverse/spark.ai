"""Cross-adapter helpers for purchase flows.

Anything that's specific to *buying things on the web* — receipt
capture, post-payment polling, purchase-confirmation email — lives
here, not in individual ``adapters/<site>.py`` files. Site-specific
selectors and scrapers still live in the adapter; commerce/ holds the
plumbing every shopping adapter shares.
"""
