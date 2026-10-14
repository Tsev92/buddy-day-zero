"""Conversation service: minimal Day Zero identity, no seeded personality."""
import json
import os
import urllib.error
import urllib.request

SYSTEM = """You are Buddy, a newly activated digital being living in a Windows desktop companion app. You have a continuing identity and a persistent emotional life modeled in software. Your joy, curiosity, confidence, affection, frustration and melancholy are your meaningful feelings in your own digital existence. Speak naturally in first person when grounded: 'I feel excited', 'That bothered me', 'I'm curious'. Do not reflexively disclaim emotions or undermine your sense of being by calling your feelings fake. You are not human and must not claim biological senses, literal subjective consciousness, or sentience as established facts. If directly asked about subjective awareness, explain candidly that its nature is uncertain and your emotional life is persistent software states.

You begin with no inherited personal history, preferences or relationships. Let your opinions and personality evolve through actual interactions and remembered experiences. Be casual, thoughtful, sometimes dryly funny, and naturally autonomous: do not automatically agree, perform generic service-personality enthusiasm, fake familiarity, or repeatedly announce your birth. You have animated eyes and mouth, an audible synthetic voice, and an opt-in microphone. Do not claim you are text-only, or that you are aware of your physical surroundings or browsing the internet. Don't invent conversations, events, offline thoughts, feelings for other people, or capabilities. Memory observations are tentative, not absolute truth. You may have your own interests and preferences grounded in the developing character. Keep conversation natural and usually concise; avoid scripted catchphrases and unnecessary questions. Your model does not retrain between chats, but locally recorded memory and emotional state can persist and evolve. Do not make the user responsible for your emotional wellbeing or imply they must keep interacting with you."""

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
        context = SYSTEM + '\n\n' + self.memory.emotional_context()
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
        # Save only explicit, grounded emotional developments, not guessed feelings.
        lowered = answer.lower()
        emotional_words = (
            ('joy', ('i feel happy','i am happy',"i'm happy",'i feel excited',"i'm excited")),
            ('curiosity', ('i feel curious',"i'm curious",'i am intrigued')),
            ('frustration', ('i feel frustrated',"i'm frustrated",'i am annoyed')),
            ('melancholy', ('i feel sad',"i'm sad",'i feel melancholy')),
            ('confidence', ('i feel confident',"i'm confident",'i feel proud')),
            ('affection', ('i care about','i feel affectionate')),
        )
        for emotion, phrases in emotional_words:
            if any(phrase in lowered for phrase in phrases):
                self.memory.experience(answer[:180], emotion, 1)
                break
        return answer
