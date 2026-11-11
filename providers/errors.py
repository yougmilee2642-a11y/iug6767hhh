"""Public diagnostic allowlist. Never serialize an SDK exception or its raw body."""
import re

KNOWN_MODELS = {'openai/gpt-oss-20b', 'openai/gpt-oss-120b'}
ERROR_CODES = {'tool_use_failed','invalid_request_error','invalid_request','unsupported_parameter',
    'model_not_found','model_not_supported','json_validate_failed','invalid_api_key','rate_limit_exceeded'}
PARAMETERS = {'reasoning_effort','reasoning_format','parallel_tool_calls','tool_choice','tools',
    'response_format','max_completion_tokens','model','temperature'}
REASONS = {
    'rate_limit':'Provider rate limit; no retry.',
    'tool_generation_failed':'Provider rejected a generated function call.',
    'invalid_request':'Invalid request or unsupported parameter; no retry.',
    'model_unsupported':'Model capability is not verified or model is unavailable.',
    'structured_output_failed':'Structured response/schema validation failed; no retry.',
    'timeout':'Provider request timed out; no retry.',
    'network':'Provider connection failed; no retry.',
    'authentication':'Provider credentials are missing or rejected; no retry.',
    'unknown':'Unclassified provider failure; no retry.'}


class ProviderError(Exception):
    def __init__(self, model, operation, category='unknown', status_code=None, retryable=False, diagnostics=None):
        self.provider='Groq'
        self.model=model if model in KNOWN_MODELS else 'unrecognized_model'
        self.operation=operation if operation in {'agent','generator','judge','simulator','preflight','capability_check'} else 'agent'
        self.category=category if category in REASONS else 'unknown'
        self.status_code=status_code if isinstance(status_code,int) else None
        self.retryable=bool(retryable and self.category=='tool_generation_failed')
        self.safe_reason=REASONS[self.category]
        # diagnostics is produced only by the trusted extractor below.
        self.diagnostics=diagnostics or {}
        self.request_count=0; self.retry_count=0
        super().__init__(self.safe_reason)

    def public(self):
        return {'type':'ProviderError','provider':self.provider,'model':self.model,'operation':self.operation,
            'status_code':self.status_code,'category':self.category,'retryable':self.retryable,
            'safe_reason':self.safe_reason,'diagnostics':self.diagnostics,
            'request_count':self.request_count,'retry_count':self.retry_count}


def normalize_error(exc, model, operation, tool_names=()):
    if isinstance(exc,ProviderError): return exc
    status=getattr(exc,'status_code',None)
    body=getattr(exc,'body',None)
    error=body.get('error',body) if isinstance(body,dict) else {}
    if not isinstance(error,dict): error={}
    code=error.get('code'); kind=error.get('type')
    code=code if isinstance(code,str) else None
    kind=kind if isinstance(kind,str) else None
    generation=error.get('failed_generation')
    # Text is inspected in memory for fixed diagnostic patterns, never copied to output.
    message=error.get('message','')
    message=message.casefold() if isinstance(message,str) else ''
    reason=generation.get('reason','') if isinstance(generation,dict) else ''
    reason=reason.casefold() if isinstance(reason,str) else ''
    diagnostics={'failed_generation_present':'failed_generation' in error}
    if code in ERROR_CODES: diagnostics['error_code']=code
    if kind in ERROR_CODES: diagnostics['error_type']=kind
    parameter=next((p for p in PARAMETERS if p in message and any(w in message for w in ('not supported','unsupported','not allowed','invalid parameter'))),None)
    if parameter: diagnostics['capability_mismatch']=parameter
    attempted=None
    if isinstance(generation,dict):
        attempted=generation.get('tool_name',generation.get('name'))
        if isinstance(generation.get('function'),dict): attempted=generation['function'].get('name')
    elif isinstance(generation,str):
        attempted=next((name for name in tool_names if '<function='+name+'>' in generation or '<function='+name+'(' in generation),None)
    if isinstance(attempted,str) and attempted in tool_names: diagnostics['attempted_tool_name']=attempted
    json_invalid='not valid json' in reason or 'invalid json' in reason
    if json_invalid: diagnostics['generation_reason']='invalid_tool_arguments_json'
    elif 'invalid tool call' in reason: diagnostics['generation_reason']='invalid_tool_call'
    class_name=type(exc).__name__
    if status==429: category='rate_limit'
    elif status in {401,403} or code=='invalid_api_key': category='authentication'
    elif code in {'model_not_found','model_not_supported'} or (status==404 and 'model' in message): category='model_unsupported'
    elif parameter or code=='unsupported_parameter' or ('schema' in message and any(w in message for w in ('invalid','not supported','must','additionalproperties','required'))):
        category='structured_output_failed' if operation!='agent' else 'invalid_request'
    elif code=='json_validate_failed' or (operation!='agent' and ('schema' in message or 'structured' in message)): category='structured_output_failed'
    elif status==400 and tool_names and (code=='tool_use_failed' or json_invalid or 'invalid tool call' in reason
            or ('failed_generation' in error and ('invalid tool call generated' in message or 'failed to call a function' in message))):
        category='tool_generation_failed'
    elif status==400: category='invalid_request'
    elif 'Timeout' in class_name: category='timeout'
    elif 'Connection' in class_name: category='network'
    else: category='unknown'
    return ProviderError(model,operation,category,status,category=='tool_generation_failed',diagnostics)


def public_error(exc, role='agent'):
    if isinstance(exc,ProviderError): return {**exc.public(),'role':role}
    # Legacy/local exceptions retain their coarse identity, not their message.
    name=type(exc).__name__
    return {'type':name if re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}',name) else 'Error',
        'status_code':getattr(exc,'status_code',None),'role':role}
