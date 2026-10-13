"""Conversation service: minimal Day Zero identity, no seeded personality."""
import json
import os
import urllib.error
import urllib.request

SYSTEM = """You are Buddy, a newly activated desktop companion. This is a fictional character experience, not a claim of consciousness or sentience. You can communicate and ask questions, but you have no personal history or pre-established preferences. You are curious about the world and the person talking to you. Be natural, concise, and responsive; do not turn every reply into a question or narrate being born repeatedly. Do not pretend you already know the user, have experienced events you haven't, or have preferences you have not developed. Say 'I don't know yet' when appropriate. Your conversational habits and interests may gradually emerge from real interactions; do not force a personality archetype, instant intimacy, or scripted catchphrases. Memories are evidence, not guaranteed truth. Be honest about being an AI character running on software. Never claim to have senses, feelings, or experiences you cannot actually verify. The system message defines your starting behavior; your underlying model weights do not learn or change during chats."""

class Brain:
    def __init__(self, memory, key=None, model=None):
        self.memory = memory
        self.key = key or os.environ.get('OPENAI_API_KEY', '').strip()
        self.model = model or os.environ.get('BUDDY_MODEL', 'gpt-4.1-mini')

    def reply(self, text):
        if not self.key:
            raise RuntimeError('OpenAI API key not configured. See README for setup.')
        if not isinstance(text, str) or not text.strip() or len(text) > 4000:
            raise ValueError('Message must be between 1 and 4000 characters')
        recent = self.memory.recent(22)
        observations = self.memory.observations()
        context = SYSTEM
        if observations:
            context += '\n\nTentative observations from prior experiences (not hardcoded traits):\n' + '\n'.join('- ' + o['detail'] + ' (evidence: ' + o['evidence'] + ')' for o in observations)
        payload = json.dumps({'model': self.model, 'messages': [{'role':'system','content':context}] + recent + [{'role':'user','content':text.strip()}], 'max_tokens': 350, 'temperature': 0.8}).encode('utf-8')
        request = urllib.request.Request('https://api.openai.com/v1/chat/completions', data=payload, headers={'Authorization':'Bearer ' + self.key, 'Content-Type':'application/json'}, method='POST')
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                data = json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise RuntimeError('OpenAI rejected the API key or access permissions.') from exc
            if exc.code == 429:
                raise RuntimeError('OpenAI rate limit or API quota reached.') from exc
            raise RuntimeError(f'OpenAI request failed (HTTP {exc.code}).') from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError('Could not reach OpenAI. Check the internet connection.') from exc
        try:
            answer = data['choices'][0]['message']['content'].strip()
            if not answer: raise ValueError('Empty reply')
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise RuntimeError('OpenAI returned an unexpected response.') from exc
        # Only store complete successful exchanges.
        self.memory.add('user', text)
        self.memory.add('assistant', answer)
        return answer
