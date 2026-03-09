"""
Local frequency label lookup.
Maps known frequencies to human-readable service descriptions.
"""

from typing import Optional, List, Dict

# Common US frequencies and their typical usage
KNOWN_FREQUENCIES: Dict[str, str] = {
    '162.400': 'NOAA Weather Radio',
    '162.425': 'NOAA Weather Radio',
    '162.450': 'NOAA Weather Radio',
    '162.475': 'NOAA Weather Radio',
    '162.500': 'NOAA Weather Radio',
    '162.525': 'NOAA Weather Radio',
    '162.550': 'NOAA Weather Radio',
    '121.500': 'Aviation Emergency',
    '123.025': 'Aviation Helicopter Air-to-Air',
    '156.800': 'Marine VHF Channel 16 (Distress)',
}


def classify_frequency(frequency_mhz: float) -> Optional[str]:
    """
    Look up a frequency and return a human-readable description.
    Returns None if frequency is not in the local database.
    """
    key = f'{frequency_mhz:.3f}'
    return KNOWN_FREQUENCIES.get(key)


def classify_band(frequency_mhz: float) -> str:
    """Classify a frequency into its general band/service."""
    freq = frequency_mhz

    if 0.5 <= freq < 1.7:
        return 'AM Broadcast'
    if 1.7 <= freq < 30:
        return 'HF/Shortwave'
    if 30 <= freq < 50:
        return 'VHF Low Band'
    if 50 <= freq < 54:
        return 'Amateur 6m'
    if 54 <= freq < 88:
        return 'VHF TV'
    if 88 <= freq < 108:
        return 'FM Broadcast'
    if 108 <= freq < 118:
        return 'Aviation Navigation'
    if 118 <= freq < 137:
        return 'Aviation Voice'
    if 137 <= freq < 144:
        return 'Military/Government'
    if 144 <= freq < 148:
        return 'Amateur 2m'
    if 148 <= freq < 174:
        return 'VHF Public Safety/Business'
    if 225 <= freq < 400:
        return 'Military UHF'
    if 400 <= freq < 420:
        return 'Federal Government'
    if 420 <= freq < 450:
        return 'Amateur 70cm'
    if 450 <= freq < 470:
        return 'UHF Public Safety/Business'
    if 470 <= freq < 512:
        return 'UHF-T Band Public Safety'
    if 758 <= freq < 788:
        return 'FirstNet/Public Safety Broadband'
    if 806 <= freq < 869:
        return '800 MHz Public Safety/Trunking'
    if 896 <= freq < 960:
        return '900 MHz SMR/Trunking'

    return 'Unknown Band'


def get_band_info(channels: List[Dict]) -> List[Dict]:
    """Enrich a list of channel dicts with band classification."""
    enriched = []
    for ch in channels:
        freq = ch.get('frequency', 0)
        info = dict(ch)
        info['band'] = classify_band(freq)
        label = classify_frequency(freq)
        if label:
            info['known_service'] = label
        enriched.append(info)
    return enriched
