#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Single source for the opening Rebound disclaimer (host, card and checks)."""

DISCLAIMER = {
    'en': 'Rebound is an agentic creative aid: it proposes ideas and test plans judged by models, with no guarantee - unlike the rest of VanishingPoint, whose claims are measured.',
    'fr': 'Rebond est une aide cr\xe9ative agentique : il propose des id\xe9es et des plans de test jug\xe9s par des mod\xe8les, sans garantie - contrairement au reste de VanishingPoint, dont les affirmations sont mesur\xe9es.',
}


def get_disclaimer(language='en'):
    """Use intake.json's language code, falling back to English."""
    return DISCLAIMER.get(language, DISCLAIMER['en']) if isinstance(language, str) else DISCLAIMER['en']
