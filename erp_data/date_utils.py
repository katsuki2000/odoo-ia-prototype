"""
miro-rag/tools/date_utils.py

Utility functions for parsing French date expressions into Odoo domain ranges.
"""

from datetime import date, timedelta
from typing import Tuple, Optional
import calendar

def parse_period(periode: str) -> Optional[Tuple[str, str]]:
    """
    Parses a French date expression into a tuple of (start_date, end_date) strings
    formatted as 'YYYY-MM-DD', compatible with Odoo domain filters.
    
    Supported expressions:
    - "ce mois", "mois en cours"
    - "le mois dernier"
    - "cette annee", "cette année"
    - "l'annee derniere", "l'année dernière"
    - "Q1 2026", "Q3 2024"
    - "2024", "2025"
    - "aujourd'hui"
    - "hier"
    
    If the period cannot be parsed, returns None.
    """
    periode = periode.lower().strip()
    today = date.today()

    # "a ce jour" / "à ce jour" / "ce jour" / "toutes" (means all history up to today)
    if "ce jour" in periode or "a ce jour" in periode or "à ce jour" in periode:
        return None

    # "ce mois" / "mois en cours"
    if "ce mois" in periode or "mois en cours" in periode:
        start_date = today.replace(day=1)
        _, last_day = calendar.monthrange(today.year, today.month)
        end_date = today.replace(day=last_day)
        return start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")
        
    # Explicit months (e.g., "janvier 2025")
    french_months = {
        "janvier": 1, "fevrier": 2, "février": 2, "mars": 3, "avril": 4, 
        "mai": 5, "juin": 6, "juillet": 7, "aout": 8, "août": 8, 
        "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12, "décembre": 12
    }
    for month_name, month_num in french_months.items():
        if month_name in periode:
            words = periode.replace(",", " ").split()
            year = today.year
            for word in words:
                if word.isdigit() and len(word) == 4:
                    year = int(word)
                    break
            start_date = date(year, month_num, 1)
            _, last_day = calendar.monthrange(year, month_num)
            end_date = date(year, month_num, last_day)
            return start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")
        
    # "le mois dernier"
    if "mois dernier" in periode:
        first_day_this_month = today.replace(day=1)
        last_month = first_day_this_month - timedelta(days=1)
        start_date = last_month.replace(day=1)
        return start_date.strftime("%Y-%m-%d"), last_month.strftime("%Y-%m-%d")
        
    # "cette annee" / "cette année"
    if "cette annee" in periode or "cette année" in periode:
        start_date = date(today.year, 1, 1)
        end_date = date(today.year, 12, 31)
        return start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")
        
    # "l'annee derniere" / "l'année dernière"
    if "annee derniere" in periode or "année dernière" in periode:
        start_date = date(today.year - 1, 1, 1)
        end_date = date(today.year - 1, 12, 31)
        return start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")
        
    # "aujourd'hui"
    if "aujourd'hui" in periode:
        return today.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")
        
    # "hier"
    if "hier" in periode:
        yesterday = today - timedelta(days=1)
        return yesterday.strftime("%Y-%m-%d"), yesterday.strftime("%Y-%m-%d")
        
    # "Q1 2026" / "q3 2024"
    if periode.startswith("q") and len(periode) >= 7:
        try:
            quarter = int(periode[1])
            year = int(periode[3:])
            if 1 <= quarter <= 4:
                start_month = (quarter - 1) * 3 + 1
                start_date = date(year, start_month, 1)
                end_month = start_month + 2
                _, last_day = calendar.monthrange(year, end_month)
                end_date = date(year, end_month, last_day)
                return start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")
        except ValueError:
            pass
            
    # "2024" (Just a year)
    if len(periode) == 4 and periode.isdigit():
        year = int(periode)
        start_date = date(year, 1, 1)
        end_date = date(year, 12, 31)
        return start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")
        
    return None
