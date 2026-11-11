"""Native Ollama transport. No cloud fallback or thinking exposure.

By default only the loopback Ollama is allowed. A teammate's machine may instead use
the host's token-protected gateway (scripts/llm_gateway.py): that requires
OLLAMA_API_KEY and either HTTPS or a Tailscale address (100.64.0.0/10, *.ts.net),
whose traffic is already encrypted by WireGuard.
"""
import ipaddress
import json
import os
import uuid
from urllib.parse import urlsplit
import httpx
from providers.base import ModelReply, ToolCall, ConversationMessage
from providers.groq import encode_tool
from providers.local_settings import LocalAIError


def encode_messages(messages):
    output,call_names=[],{}
    for m in messages:
        entry={'role':m.role,'content':m.text or ''}
        if m.calls:
            entry['tool_calls']=[{'function':{'name':call.name,'arguments':call.arguments}} for call in m.calls]
            call_names.update({call.id:call.name for call in m.calls})
        if m.call_id:
            entry['tool_name']=call_names.get(m.call_id,'')
            entry['content']=json.dumps(m.result,ensure_ascii=False)
        output.append(entry)
    return output


LOOPBACK={'127.0.0.1','localhost','::1'}
TAILNET=ipaddress.ip_network('100.64.0.0/10')


def _tailnet_host(host):
    if host.endswith('.ts.net'): return True
    try: return ipaddress.ip_address(host) in TAILNET
    except ValueError: return False


def endpoint():
    """Return (base_url, headers) or None when the configured address is not allowed."""
    base=os.getenv('OLLAMA_BASE_URL','http://127.0.0.1:11434').rstrip('/')
    parsed=urlsplit(base)
    host=parsed.hostname or ''
    if parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment: return None
    key=os.getenv('OLLAMA_API_KEY','').strip()
    if parsed.scheme=='http' and host in LOOPBACK:
        return base,({'Authorization':f'Bearer {key}'} if key else {})
    if len(key)<24: return None
    if parsed.scheme=='https' or (parsed.scheme=='http' and _tailnet_host(host)):
        return base,{'Authorization':f'Bearer {key}'}
    return None


class OllamaProvider:
    def __init__(self,transport=None,model=None,budget=None):
        self.transport=transport
        self.model=model or os.getenv('OLLAMA_MODEL','qwen3:4b-instruct')
        self.budget=budget
        self.request_count=0
        self.last_metrics={}

    def metadata(self):
        target=endpoint()
        remote=bool(target and urlsplit(target[0]).hostname not in LOOPBACK)
        return {'provider':'Ollama','model':self.model,'request_count':self.request_count,'fallback':False,'local':True,'remote_gateway':remote,**self.last_metrics}

    def warm_up(self):
        # Load local inference before the user speaks. No business data or actions.
        self.request([ConversationMessage('system', 'Ответь только одним словом: готов.'),
                      ConversationMessage('user', 'Проверка готовности.')], predict=16)

    def available(self):
        target=endpoint()
        if not target: return False
        base,headers=target
        try:
            with httpx.Client(timeout=5,transport=self.transport,trust_env=False,follow_redirects=False) as client:
                response=client.get(base+'/api/tags',headers=headers)
            response.raise_for_status()
            return any(item.get('name')==self.model for item in response.json().get('models',[]))
        except (httpx.HTTPError,ValueError,TypeError,AttributeError): return False

    def request(self,messages,tools=None,schema=None,predict=None):
        target=endpoint()
        if not target: raise LocalAIError('unavailable')
        base,headers=target
        if self.model.endswith(':cloud'): raise LocalAIError('cloud_disabled')
        payload={'model':self.model,'messages':encode_messages(messages),'think':False,'stream':False,'keep_alive':'30m',
                 'options':{'num_ctx':int(os.getenv('OLLAMA_CONTEXT','8192')),'num_predict':predict or int(os.getenv('OLLAMA_NUM_PREDICT','384')),'temperature':0.2}}
        if tools: payload['tools']=[encode_tool(tool) for tool in tools]
        if schema: payload['format']=schema
        if self.budget: self.budget.consume()
        self.request_count+=1
        try:
            with httpx.Client(timeout=float(os.getenv('OLLAMA_TIMEOUT','120')),transport=self.transport,trust_env=False,follow_redirects=False) as client:
                response=client.post(base+'/api/chat',json=payload,headers=headers)
            response.raise_for_status()
            data=response.json()
            if not isinstance(data,dict) or data.get('done') is not True or data.get('done_reason')=='length':
                raise LocalAIError('invalid_reply')
            message=data['message']
            if not isinstance(message,dict): raise LocalAIError('invalid_reply')
            self.last_metrics={key:data.get(key) for key in ('total_duration','load_duration','prompt_eval_count','prompt_eval_duration','prompt_eval_cached_count','eval_count','eval_duration')}
            return message
        except httpx.TimeoutException:
            raise LocalAIError('timeout') from None
        except httpx.HTTPError:
            raise LocalAIError('unavailable') from None
        except (ValueError,KeyError,TypeError):
            raise LocalAIError('invalid_reply') from None

    def complete(self,messages,tools):
        message=self.request(messages,tools)
        try:
            allowed={encode_tool(tool)['function']['name'] for tool in tools}
            calls=[]
            for value in message.get('tool_calls',[]):
                function=value['function'];arguments=function['arguments']
                if isinstance(arguments,str): arguments=json.loads(arguments)
                if function['name'] not in allowed or not isinstance(arguments,dict): raise ValueError()
                calls.append(ToolCall(uuid.uuid4().hex,function['name'],arguments))
            text=message.get('content','')
            # Some templates consume the opening <think> in the generation prefix.
            # Never pass a reasoning prefix (or an unfinished block) to the UI/TTS.
            if '</think>' in text: text=text.rsplit('</think>',1)[1]
            if '<think>' in text: raise ValueError()
            text=text.strip()
            if not text and not calls: raise ValueError()
            return ModelReply(text,calls)
        except (ValueError,KeyError,TypeError): raise LocalAIError('invalid_reply') from None

    def structured(self,messages,schema,predict=2500):
        message=self.request(messages,schema=schema,predict=predict)
        try: return json.loads(message['content'])
        except (ValueError,KeyError,TypeError): raise LocalAIError('invalid_reply') from None
