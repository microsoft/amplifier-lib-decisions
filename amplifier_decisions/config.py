"""Offline validation for decision configuration, without account access."""
from urllib.parse import urlsplit


def endpoint(value):
    if not isinstance(value, str):
        raise ValueError('Choose an HTTPS service endpoint')
    url = urlsplit(value)
    if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError('Use an HTTPS endpoint without credentials or query parameters')
    return value.rstrip('/')


def validate(config):
    if not isinstance(config, dict) or set(config) - {'model', 'endpoint'}:
        raise ValueError('Only the decision model and service endpoint belong in decision preferences')
    model = config.get('model')
    if not isinstance(model, str) or not model.strip() or len(model) > 200:
        raise ValueError('Choose an explicit decision model')
    result = {'model': model.strip()}
    if config.get('endpoint'):
        result['endpoint'] = endpoint(config['endpoint'])
    return result


def configured_backends(config, default_id):
    """Named models share an account. The legacy single-model form also works."""
    value = config.get('decisions') or {}
    if value.get('enabled') is not True:
        return {}
    if 'backends' not in value:
        return {value.get('id', default_id): value}
    rows = value['backends']
    if not isinstance(rows, dict):
        raise ValueError('Decision backends must be a named mapping')
    return {key: row for key, row in rows.items() if isinstance(row, dict) and row.get('enabled') is True}
