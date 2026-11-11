"""Small trusted dependencies, independent of LLM claims and database state."""
import math
import re
from zoneinfo import ZoneInfo
from services.business_hours import validate_schedule


def valid_price(service):
    price = service.get('price')
    return (isinstance(price, (int, float)) and not isinstance(price, bool)
            and math.isfinite(price) and price >= 0
            and isinstance(service.get('currency'), str)
            and re.fullmatch(r'[A-Z]{3}', service['currency']) is not None)


def knowledge_dependencies(config, category):
    missing = []
    services = config.business.knowledge.get('services', [])
    if category in {'pricing', 'booking'}:
        if not services: missing.append('catalog:services / pricing knowledge unavailable' if category=='pricing' else 'catalog:services')
        for service in services:
            label = service.get('id', 'service')
            if category=='pricing' and not valid_price(service): missing.append('catalog:price_currency:'+label)
            if category=='booking':
                duration = service.get('duration_minutes')
                if not isinstance(duration,int) or isinstance(duration,bool) or duration<=0: missing.append('catalog:duration:'+label)
                employees = {e.get('id') for e in config.business.knowledge.get('employees', [])}
                if not service.get('employees') or not set(service['employees'])<=employees: missing.append('catalog:employees:'+label)
    if category in {'booking','opening_hours'}:
        try:
            validate_schedule(config.business.schedule)
            ZoneInfo(config.business.timezone)
        except (ValueError, KeyError, TypeError): missing.append('knowledge:schedule_timezone')
    return missing
