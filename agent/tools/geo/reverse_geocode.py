"""
Reverse geocoding tool -- resolves coordinates to a place/address.

Not yet implemented against a real provider (see GEOCODING_PROVIDER_API_KEY
in .env). This defines the contract `gather` calls against, so the graph
can be wired and tested before a provider is chosen.
"""

from __future__ import annotations


async def reverse_geocode(lat: float, lon: float) -> dict:
    """
    Resolve a coordinate pair to place information.

    Expected return shape once implemented:
        {
            "address": "10 Downing St, London SW1A 2AA, UK",
            "place_name": "Downing Street",
            "city": "London",
            "country": "United Kingdom",
        }
    """
    raise NotImplementedError("reverse_geocode: no provider wired up yet")
